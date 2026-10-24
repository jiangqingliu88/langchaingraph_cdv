"""
Tool Protocol — SignOffAI 统一工具接口 (Phase 1)

所有工具（内置 + 第三方 + 外部 CLI）必须实现的统一协议。
对标 Claude Code MCP 的 Tool 概念，但适配 EDA 验证场景。

设计原则:
  1. 自描述 (self-describing): ToolManifest 包含 LLM 所需的所有信息
  2. 可验证 (validatable): 输入/输出均有 JSON Schema，框架自动校
  3. 可隔离 (isolatable): 支持同进程/子进程/subprocess 三种执行模式
  4. 可审计 (auditable): 每次调用记录 timestamp/args/result/elapsed
  5. 可发现 (discoverable): 通过 PluginManager 自动扫描，无需硬编码注册

用法:
  from src.layers.l2_orchestration.communication.tool_protocol import ITool, ToolManifest, ExecutionContext, ToolResult

  class MyVcsTool(ITool):
      @property
      def manifest(self) -> ToolManifest:
          return ToolManifest(name="vcs_compile", version="1.0.0",
              description="Compile SystemVerilog with VCS",
              input_schema={...}, output_schema={...},
              risk_level=ToolRisk.SAFE)

      async def execute(self, args, context) -> ToolResult:
          ...
"""
from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable, Union
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════════

class ToolRisk(str, Enum):
    """工具风险等级 —— 全项目唯一来源（tool_system 的 RiskLevel/RISK_RULES 已并入此处）。"""
    SAFE = "safe"        # 只读/无副作用 — 自动通过
    WRITE = "write"      # 写磁盘/改配置 — 终端确认
    DANGER = "danger"    # 删除/提权/杀进程 — 直接拦截

    @property
    def approval_mode(self) -> str:
        return {"safe": "auto", "write": "console", "danger": "block"}[self.value]

    @property
    def description(self) -> str:
        return {
            "safe": "只读/无副作用 — 自动通过",
            "write": "写磁盘/改配置 — 需确认",
            "danger": "删除/提权/杀进程 — 直接拦截",
        }[self.value]

    @classmethod
    def parse(cls, value: Any) -> "ToolRisk":
        """把字符串/枚举归一化为 ToolRisk。

        未知取值 fail-closed 返回 DANGER（而非静默当作 safe 放行）——
        风险等级读不懂时应当拒绝执行。
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            return cls.DANGER


class ToolStatus(str, Enum):
    """工具生命周期状态"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"


class ExecutionMode(str, Enum):
    """工具执行模式"""
    INLINE = "inline"        # 同进程直接调用（默认，最快）
    SUBPROCESS = "subprocess"  # 子进程隔离（Python subprocess）
    CONTAINER = "container"  # 容器隔离（Docker/podman）


# ═══════════════════════════════════════════════════════════════
# 核心数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolExample:
    """工具调用示例 —— 给 LLM 做 few-shot learning"""
    description: str = ""              # 何时使用此示例
    args: Dict[str, Any] = field(default_factory=dict)
    expected_output: str = ""          # 预期输出的简要描述


@dataclass
class ToolManifest:
    """工具自描述清单 —— 第三方工具接入的唯一契约"""
    name: str                          # 全局唯一名，建议命名空间: "vcs.compile", "questa.sim"
    version: str = "1.0.0"            # semver
    description: str = ""              # 给 LLM 看的，决定何时调用此工具（最关键字段）

    # Schema
    input_schema: Dict[str, Any] = field(default_factory=dict)   # JSON Schema (properties + required)
    output_schema: Dict[str, Any] = field(default_factory=dict)   # JSON Schema

    # 执行配置
    risk_level: ToolRisk = ToolRisk.SAFE
    execution_mode: ExecutionMode = ExecutionMode.INLINE
    timeout_s: float = 300.0
    retry_count: int = 0
    retry_delay_s: float = 1.0

    # 依赖声明
    requires_binaries: List[str] = field(default_factory=list)   # ["vcs", "verdi"]
    requires_python: str = ">=3.10"
    requires_packages: List[str] = field(default_factory=list)   # ["numpy>=1.21"]
    env_vars: Dict[str, str] = field(default_factory=dict)       # {"VCS_HOME": "/opt/synopsys/vcs"}

    # 元数据
    author: str = ""
    tags: List[str] = field(default_factory=list)               # ["simulation", "synopsys", "compile"]
    category: str = ""                                           # "simulation" | "lint" | "coverage" | "debug" | "util"
    status: ToolStatus = ToolStatus.ACTIVE
    homepage: str = ""
    license: str = ""

    # LLM 提示
    examples: List[ToolExample] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)               # LLM 使用提示

    def to_llm_function_spec(self) -> dict:
        """转为 OpenAI/LangChain function-calling 格式"""
        spec = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self._build_llm_description(),
                "parameters": self.input_schema if self.input_schema else {
                    "type": "object", "properties": {}, "required": [],
                },
            },
        }
        return spec

    def _build_llm_description(self) -> str:
        """构建 LLM 可读的描述，含 examples 和 tips"""
        parts = [self.description]
        if self.tips:
            parts.append("Tips: " + "; ".join(self.tips))
        if self.examples:
            parts.append("Examples:")
            for i, ex in enumerate(self.examples[:3], 1):
                parts.append(f"  {i}. {ex.description}: {json.dumps(ex.args)}")
        return "\n".join(parts)

    def validate(self) -> List[str]:
        """验证 manifest 完整性，返回问题列表"""
        issues = []
        if not self.name or not self.name.strip():
            issues.append("name is required")
        if not self.description:
            issues.append("description is empty (LLM won't know when to call this tool)")
        if not self.version:
            issues.append("version is required")
        if self.input_schema:
            props = self.input_schema.get("properties", {})
            required = self.input_schema.get("required", [])
            for r in required:
                if r not in props:
                    issues.append(f"required field '{r}' not in properties")
        return issues

    @property
    def hash(self) -> str:
        """manifest 内容哈希 —— 用于版本追踪"""
        sha = hashlib.sha256()
        sha.update(json.dumps({
            "name": self.name, "version": self.version,
            "input_schema": self.input_schema, "output_schema": self.output_schema,
        }, sort_keys=True, ensure_ascii=False).encode())
        return sha.hexdigest()[:16]


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_s: float = 0.0
    retry_attempt: int = 0
    manifest_hash: str = ""           # 执行时的工具版本 hash
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── 来源凭证（ADR-3）──
    # success 只是「执行者自述」。verified_by 回答的是「凭什么说它成功」：
    #   "eda"  —— 经真实 EDA（vlog/vsim）判定，铁律一要求的下游依据
    #   "llm"  —— LLM 自述成功，未经工具验证，不可作为签核依据
    #   "none" —— 纯确定性工具，本身无「外部验证」概念（如文件读写）
    # 没有这三个字段时，「LLM 猜的 success=True」与「vlog 验过的 success=True」
    # 在类型上完全不可区分——这是「可审计」最要命的一处缺口。
    verified_by: str = "none"
    evidence_ref: str = ""            # 证据位置：manifest / 日志 / ucdb 路径
    returncode: Optional[int] = None  # 子进程退出码（EDA 类工具）

    def to_json(self) -> str:
        """序列化为 JSON string —— LLM 可解析"""
        return json.dumps({
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "execution_time_s": self.execution_time_s,
            "verified_by": self.verified_by,
            **self.metadata,
        }, indent=2, ensure_ascii=False, default=str)

    def to_receipt(self) -> Dict[str, Any]:
        """回执行（落盘用）—— 比 to_json 多带凭证字段。"""
        return {
            "success": self.success,
            "error": self.error,
            "execution_time_s": self.execution_time_s,
            "manifest_hash": self.manifest_hash,
            "verified_by": self.verified_by,
            "evidence_ref": self.evidence_ref,
            "returncode": self.returncode,
        }

    @classmethod
    def ok(cls, data: Dict[str, Any] = None, **kwargs) -> ToolResult:
        return cls(success=True, data=data or {}, **kwargs)

    @classmethod
    def fail(cls, error: str, data: Dict[str, Any] = None, **kwargs) -> ToolResult:
        return cls(success=False, error=error, data=data or {}, **kwargs)


@dataclass
class ExecutionContext:
    """工具执行上下文 —— 隔离全局状态"""
    # 工作目录
    working_dir: str = "."
    output_dir: str = ""  # 空字符串 → 运行时由 make_output_root 生成

    # 项目信息
    project_name: str = ""
    run_id: str = ""
    session_id: str = ""

    # 环境变量（只读快照）
    env: Dict[str, str] = field(default_factory=dict)

    # 共享数据（带版本标记，immutable）
    spec: Optional[Dict[str, Any]] = None
    design: Optional[Dict[str, Any]] = None
    env_config: Optional[Dict[str, Any]] = None
    tests: Optional[Dict[str, Any]] = None
    coverage: Optional[Dict[str, Any]] = None
    regression: Optional[Dict[str, Any]] = None

    # 元数据
    tags: Dict[str, str] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        """生成只读快照"""
        return {
            "working_dir": self.working_dir,
            "output_dir": self.output_dir,
            "project_name": self.project_name,
            "run_id": self.run_id,
            "spec": self.spec,
            "design": self.design,
        }

    @classmethod
    def from_ctx(cls, ctx: Any, output_root: str | None = None) -> ExecutionContext:
        """从 ContextStore 或 dict 创建 ExecutionContext"""
        from src.layers.l1_infrastructure.output_config import make_output_root
        output_root = make_output_root(output_root)
        if ctx is None:
            return cls(output_dir=output_root)

        get = ctx.get if hasattr(ctx, "get") else (lambda k, d=None: ctx.get(k, d) if isinstance(ctx, dict) else d)

        return cls(
            working_dir=str(Path(output_root).resolve()),
            output_dir=str(Path(output_root).resolve()),
            run_id=get("run_id", "") or "",
            spec=get("spec", None),
            design=get("design_arch", get("design", None)),
            env_config=get("env", None),
            tests=get("tests", None),
            coverage=get("coverage", None),
            regression=get("regression", None),
        )


# ═══════════════════════════════════════════════════════════════
# ITool Protocol
# ═══════════════════════════════════════════════════════════════

def validate_by_schema(schema: Dict[str, Any], args: Dict[str, Any]) -> tuple:
    """按 manifest.input_schema 校验 args。返回 (pass, error_msg)。

    抽成模块级函数是因为 **Protocol 的默认实现不会被实现方继承** —— `ITool`
    上的 `validate_args_by_schema` 只是给显式 subclass 用的，几个 adapter 各自
    漏掉了它，`ToolHub.invoke` 又无条件调用，结果 28 个工具一调就 AttributeError。
    单一实现 + `_ensure_itool` 补默认值，这类问题才不会再冒出来。
    """
    if not schema:
        return True, ""
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for r in required:
        if r not in args:
            return False, f"Missing required field: '{r}'"
    for key, val in args.items():
        if key not in props:
            continue
        expected_type = props[key].get("type", "string")
        if expected_type == "string" and not isinstance(val, str):
            return False, f"Field '{key}' expected string, got {type(val).__name__}"
        if expected_type == "integer" and not isinstance(val, int):
            return False, f"Field '{key}' expected int, got {type(val).__name__}"
        if expected_type == "number" and not isinstance(val, (int, float)):
            return False, f"Field '{key}' expected number, got {type(val).__name__}"
        if "enum" in props[key] and val not in props[key]["enum"]:
            return False, f"Field '{key}'={val} not in {props[key]['enum']}"
    return True, ""


@runtime_checkable
class ITool(Protocol):
    """标准工具协议 —— 所有工具（内置/第三方/外部CLI）必须实现

    对标 Claude Code MCP Tool 概念:
      - manifest: 自描述清单（名字/版本/参数Schema/风险等级）
      - execute:  执行工具，接收 args + context，返回 ToolResult
      - check_health: 健康检查（二进制是否在 PATH 等）
      - validate_input: 业务级验证（超出 JSON Schema 的语义验证）

    最小实现（单文件工具）:
      class MyTool:
          @property
          def manifest(self): return ToolManifest(name="my_tool", ...)
          async def execute(self, args, ctx): return ToolResult.ok({...})
          async def check_health(self): return True
          async def validate_input(self, args): return []
    """

    @property
    @abstractmethod
    def manifest(self) -> ToolManifest:
        """返回工具自描述清单。框架在注册时调用一次并缓存。"""
        ...

    @abstractmethod
    async def execute(self, args: Dict[str, Any], context: ExecutionContext) -> ToolResult:
        """执行工具。

        Args:
          args: 已通过 manifest.input_schema 验证的参数
          context: 执行上下文（工作目录/项目信息/共享数据）

        Returns:
          ToolResult: 执行结果，data 应符合 manifest.output_schema
        """
        ...

    async def check_health(self) -> bool:
        """检查工具是否可用（二进制在 PATH、license 有效等）。

        默认返回 True。第三方工具应覆盖此方法做真实检查。
        """
        return True

    async def validate_input(self, args: Dict[str, Any]) -> List[str]:
        """业务级输入验证（超出 JSON Schema 的语义验证）。

        例如: 检查 filelist 文件是否存在、top_module 名称是否合法等。
        返回问题描述列表，空列表表示验证通过。
        """
        return []

    def validate_args_by_schema(self, args: Dict[str, Any]) -> tuple[bool, str]:
        """按 manifest.input_schema 验证 args。返回 (pass, error_msg)。"""
        return validate_by_schema(self.manifest.input_schema, args)


# ═══════════════════════════════════════════════════════════════
# ToolWrapper — 将 ITool 包装为 LangChain @tool
# ═══════════════════════════════════════════════════════════════

class ToolWrapper:
    """将 ITool 实例包装为 LangChain BaseTool，统一两套体系。

    用法:
      my_tool = MyVcsTool()
      wrapper = ToolWrapper(my_tool, sandbox=None)
      lc_tool = wrapper.to_langchain_tool()

    LangChain Agent 调用 lc_tool 时:
      1. Schema validate (按 manifest.input_schema)
      2. Sandbox check (按 manifest.risk_level)
      3. execute(args, context) → ToolResult
      4. 返回 ToolResult.to_json()
    """

    def __init__(self, tool: ITool, sandbox=None, context: ExecutionContext = None):
        self._tool = tool
        self._sandbox = sandbox
        self._context = context or ExecutionContext()

    @property
    def tool(self) -> ITool:
        return self._tool

    def to_langchain_tool(self):
        """将 ITool 转为 LangChain BaseTool（保留原有 @tool 装饰器语义）"""
        # `langchain.tools` 在 1.x 只是指向 `langchain_core.tools` 的转发 shim
        # （它随 `langchain` 元包提供，而本仓并不需要那个元包）。直接引核心包。
        from langchain_core.tools import tool as lc_tool_decorator
        import functools
        import json as _json

        manifest = self._tool.manifest
        sandbox = self._sandbox
        tool_ref = self._tool

        @functools.wraps(lambda x: x)
        def _execute(input_str: str = "", **kwargs) -> str:
            """LangChain tool 执行入口"""
            import asyncio

            # 解析 args
            args = {}
            if input_str:
                try:
                    args = _json.loads(input_str) if isinstance(input_str, str) else input_str
                except (_json.JSONDecodeError, TypeError):
                    args = {}
            args.update(kwargs)

            # Schema 验证
            ok, err = tool_ref.validate_args_by_schema(args)
            if not ok:
                return ToolResult.fail(f"Schema validation: {err}").to_json()

            # Sandbox 检查
            if sandbox:
                try:
                    from src.layers.l2_orchestration.communication.tool_system import Tool as OldTool
                    dummy = OldTool(manifest.name, description=manifest.description,
                                    input_schema=manifest.input_schema,
                                    risk_level=manifest.risk_level.value)
                    ok, err = sandbox.check(dummy, args)
                    if not ok:
                        return ToolResult.fail(f"Sandbox blocked: {err}").to_json()
                except Exception:
                    pass

            # 执行
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, tool_ref.execute(args, self._context))
                        result = future.result(timeout=manifest.timeout_s)
                else:
                    result = asyncio.run(tool_ref.execute(args, self._context))
                return result.to_json()
            except Exception as e:
                return ToolResult.fail(str(e)[:500]).to_json()

        # 创建 LangChain tool
        lc_tool = lc_tool_decorator(manifest.name)(_execute)
        lc_tool.name = manifest.name
        lc_tool.description = manifest._build_llm_description()
        # 注入 args_schema 以支持 LangChain 结构化调用
        if manifest.input_schema:
            try:
                from pydantic import create_model, Field
                fields = {}
                props = manifest.input_schema.get("properties", {})
                required = manifest.input_schema.get("required", [])
                for pname, pdef in props.items():
                    ptype = str if pdef.get("type") == "string" else (
                        int if pdef.get("type") == "integer" else float if pdef.get("type") == "number" else str
                    )
                    default = ... if pname in required else None
                    desc = pdef.get("description", "")
                    fields[pname] = (ptype, Field(default, description=desc))
                if fields:
                    lc_tool.args_schema = create_model(f"{manifest.name}_args", **fields)
            except Exception:
                pass

        return lc_tool


# ═══════════════════════════════════════════════════════════════
# 内置工具基类
# ═══════════════════════════════════════════════════════════════

class BaseTool(ITool, ABC):
    """内置工具基类 —— 简化 ITool 实现。

    子类只需:
      1. 定义 manifest 属性
      2. 实现 execute() 方法
      3. 可选覆盖 check_health() / validate_input()
    """

    def __init__(self, context: ExecutionContext = None):
        self._context = context or ExecutionContext()
        self._call_count = 0
        self._total_time_s = 0.0
        self._last_error = None

    @property
    def context(self) -> ExecutionContext:
        return self._context

    @context.setter
    def context(self, ctx: ExecutionContext):
        self._context = ctx

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.name,
            "calls": self._call_count,
            "total_time_s": round(self._total_time_s, 3),
            "last_error": self._last_error,
        }

    async def execute(self, args: Dict[str, Any], context: ExecutionContext) -> ToolResult:
        """模板方法: 记录统计 + 调用 _execute_impl"""
        start = time.monotonic()
        self._call_count += 1
        try:
            result = await self._execute_impl(args, context)
            self._total_time_s += time.monotonic() - start
            result.execution_time_s = round(time.monotonic() - start, 3)
            result.manifest_hash = self.manifest.hash
            return result
        except Exception as e:
            self._last_error = str(e)[:500]
            self._total_time_s += time.monotonic() - start
            return ToolResult.fail(str(e)[:500], execution_time_s=round(time.monotonic() - start, 3))

    @abstractmethod
    async def _execute_impl(self, args: Dict[str, Any], context: ExecutionContext) -> ToolResult:
        """子类实现具体逻辑"""
        ...


# ═══════════════════════════════════════════════════════════════
# 工具调用审计
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolCallRecord:
    """单次工具调用审计记录"""
    tool_name: str
    tool_version: str
    args_summary: str                  # 参数摘要（截断）
    success: bool
    error: str = ""
    execution_time_s: float = 0.0
    timestamp: str = ""
    run_id: str = ""
    manifest_hash: str = ""
    sandbox_decision: str = "auto"
    #: 来源凭证 —— 与 `ToolResult` 同一口径。
    #: 回执里没有它，"EDA 验过"与"LLM 自述"在审计侧就分不开了。
    verified_by: str = "none"          # eda | llm | none
    evidence_ref: str = ""
    returncode: Optional[int] = None


class ToolAuditor:
    """工具调用审计器 — 记录所有工具调用，支持查询和统计。

    receipt_path 非空时，每条记录同时 append 到该 JSONL 文件（append-only）。
    原来只有内存，进程退出即失——架构图声称的 tool_receipts 因此一直落不了地。
    """

    def __init__(self, max_records: int = 10000, receipt_path: str = ""):
        self._records: List[ToolCallRecord] = []
        self._max_records = max_records
        self._stats: Dict[str, Dict[str, Any]] = {}  # tool_name → {calls, failures, total_time}
        self._receipt_path = receipt_path
        if receipt_path:
            p = Path(receipt_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            # 每次 run 覆盖上一轮，避免 JSONL 无限增长；同一 run 内为 append
            p.write_text("", encoding="utf-8")

    @classmethod
    def with_receipts(cls, output_root: str, max_records: int = 10000) -> "ToolAuditor":
        """把回执落到 <output_root>/docs/tool_receipts.jsonl（与证据链同目录）。"""
        return cls(max_records=max_records,
                   receipt_path=str(Path(output_root) / "docs" / "tool_receipts.jsonl"))

    def record(self, record: ToolCallRecord) -> None:
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

        # Update stats
        if record.tool_name not in self._stats:
            self._stats[record.tool_name] = {"calls": 0, "failures": 0, "total_time_s": 0.0}
        s = self._stats[record.tool_name]
        s["calls"] += 1
        if not record.success:
            s["failures"] += 1
        s["total_time_s"] += record.execution_time_s

        self._append_receipt(record)

    def _append_receipt(self, record: ToolCallRecord) -> None:
        """落盘一条回执。写失败不应阻断工具执行，故吞掉异常。"""
        if not self._receipt_path:
            return
        try:
            with open(self._receipt_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "tool": record.tool_name, "version": record.tool_version,
                    "args": record.args_summary, "success": record.success,
                    "error": record.error, "time_s": record.execution_time_s,
                    "timestamp": record.timestamp, "run_id": record.run_id,
                    "manifest_hash": getattr(record, "manifest_hash", ""),
                    "sandbox_decision": getattr(record, "sandbox_decision", ""),
                    # 来源凭证：签核侧只认 `eda`（见 ToolResult 的 ADR-3）。
                    "verified_by": getattr(record, "verified_by", "none"),
                    "evidence_ref": getattr(record, "evidence_ref", ""),
                    "returncode": getattr(record, "returncode", None),
                }, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    def query(self, tool_name: str = None, success: bool = None, limit: int = 50) -> List[ToolCallRecord]:
        records = self._records
        if tool_name:
            records = [r for r in records if r.tool_name == tool_name]
        if success is not None:
            records = [r for r in records if r.success == success]
        return records[-limit:]

    def get_stats(self, tool_name: str = None) -> Dict[str, Any]:
        if tool_name:
            return self._stats.get(tool_name, {"calls": 0, "failures": 0, "total_time_s": 0.0})
        return dict(self._stats)

    def to_jsonl(self) -> str:
        """导出为 JSONL"""
        import json
        lines = []
        for r in self._records:
            lines.append(json.dumps({
                "tool": r.tool_name, "version": r.tool_version,
                "args": r.args_summary, "success": r.success, "error": r.error,
                "time": r.execution_time_s, "timestamp": r.timestamp, "run_id": r.run_id,
            }, ensure_ascii=False))
        return "\n".join(lines)
