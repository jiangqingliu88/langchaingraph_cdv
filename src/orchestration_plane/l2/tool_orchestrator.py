"""
Tool Orchestrator — 声明式工具编排 DSL (Phase 3)

支持:
  1. 声明式工具链定义（YAML/JSON）
  2. 顺序执行 + 条件分支 + 循环重试
  3. 数据传递（上游 output → 下游 input）
  4. 并行执行工具组
  5. 可视化执行图（DAG）
  6. 执行结果追踪

DSL 语法:
  pipeline:
    name: uvm_quality_check
    steps:
      - tool: check_static
        id: static
      - tool: check_compile
        id: compile
        depends_on: [static]
      - tool: check_loopback
        id: loopback
        depends_on: [compile]
      - tool: quality_report
        id: report
        depends_on: [static, compile, loopback]
        condition:
          field: compile.status
          op: eq
          value: PASS

用法:
  from src.orchestration_plane.l2.tool_orchestrator import ToolOrchestrator
  orch = ToolOrchestrator()
  result = await orch.run("uvm_quality_check", context=ctx)
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog
import yaml as _yaml

from src.orchestration_plane.l2.communication.tool_protocol import ITool, ToolResult, ExecutionContext, ToolManifest
from src.orchestration_plane.l2.communication.tool_hub import ToolHub
from src.orchestration_plane.l2.communication.tool_sandbox import ToolSandbox, SandboxPolicy

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# DSL 数据模型
# ═══════════════════════════════════════════════════════════════

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class ConditionOp(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    LT = "lt"
    IN = "in"
    CONTAINS = "contains"
    REGEX = "regex"


@dataclass
class StepCondition:
    """步骤执行条件"""
    field: str                      # 上游 step field 路径: "compile.status"
    op: ConditionOp = ConditionOp.EQ
    value: Any = None

    def evaluate(self, upstream_outputs: Dict[str, Dict[str, Any]]) -> bool:
        """评估条件: 上游某 step 的某 field 是否满足条件"""
        # Parse field path: "compile.status" → step_id="compile", key="status"
        parts = self.field.split(".", 1)
        if len(parts) != 2:
            return True
        step_id, key = parts
        data = upstream_outputs.get(step_id, {})
        actual = data.get(key)

        if self.op == ConditionOp.EQ:
            return actual == self.value
        elif self.op == ConditionOp.NEQ:
            return actual != self.value
        elif self.op == ConditionOp.GT:
            return float(actual or 0) > float(self.value)
        elif self.op == ConditionOp.LT:
            return float(actual or 0) < float(self.value)
        elif self.op == ConditionOp.IN:
            return actual in (self.value if isinstance(self.value, list) else [self.value])
        elif self.op == ConditionOp.CONTAINS:
            return str(self.value) in str(actual)
        elif self.op == ConditionOp.REGEX:
            import re
            return bool(re.search(str(self.value), str(actual)))
        return True


@dataclass
class PipelineStep:
    """编排流水线中的单个步骤"""
    tool: str                      # 工具名（在 ToolHub 中注册）
    id: str = ""                   # 步骤 ID（用于依赖引用），默认等于 tool
    depends_on: List[str] = field(default_factory=list)
    condition: Optional[StepCondition] = None
    args: Dict[str, Any] = field(default_factory=dict)
    args_from_upstream: Dict[str, str] = field(default_factory=dict)  # {param: "step_id.field"}
    retry_on_failure: int = 0
    timeout_s: float = 300.0
    description: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = self.tool


@dataclass
class PipelineDefinition:
    """声明式工具编排流水线"""
    name: str
    version: str = "1.0"
    description: str = ""
    steps: List[PipelineStep] = field(default_factory=list)
    on_error: str = "stop"         # stop | continue | rollback
    max_parallel: int = 4


@dataclass
class StepResult:
    """单步执行结果"""
    step_id: str
    tool_name: str
    status: StepStatus
    result: Optional[ToolResult] = None
    error: str = ""
    started_at: str = ""
    ended_at: str = ""
    elapsed_s: float = 0.0
    retries: int = 0


@dataclass
class PipelineResult:
    """流水线执行结果"""
    pipeline_name: str
    status: StepStatus
    steps: List[StepResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    total_time_s: float = 0.0
    started_at: str = ""
    ended_at: str = ""
    outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# 编排引擎
# ═══════════════════════════════════════════════════════════════

class ToolOrchestrator:
    """声明式工具编排引擎"""

    def __init__(self, hub: ToolHub = None, sandbox: ToolSandbox = None):
        self._hub = hub or ToolHub.get_instance()
        self._sandbox = sandbox or ToolSandbox(SandboxPolicy.standard())
        self._pipelines: Dict[str, PipelineDefinition] = {}

    # ═══════════════════════════════════════════════════════════
    # DSL 加载
    # ═══════════════════════════════════════════════════════════

    def load_pipeline_from_yaml(self, yaml_path: str) -> PipelineDefinition:
        """从 YAML 加载流水线定义"""
        content = Path(yaml_path).read_text(encoding="utf-8")
        data = _yaml.safe_load(content)
        return self._parse_pipeline(data)

    def load_pipeline_from_dict(self, data: Dict[str, Any]) -> PipelineDefinition:
        """从 dict 加载流水线定义"""
        return self._parse_pipeline(data)

    def register_pipeline(self, pipeline: PipelineDefinition) -> None:
        """注册流水线"""
        self._pipelines[pipeline.name] = pipeline
        logger.info(f"Pipeline registered: {pipeline.name} ({len(pipeline.steps)} steps)")

    def _parse_pipeline(self, data: Dict[str, Any]) -> PipelineDefinition:
        """解析流水线 DSL"""
        steps = []
        for s in data.get("steps", []):
            condition = None
            if "condition" in s:
                cond_data = s["condition"]
                condition = StepCondition(
                    field=cond_data.get("field", ""),
                    op=ConditionOp(cond_data.get("op", "eq")),
                    value=cond_data.get("value"),
                )
            step = PipelineStep(
                tool=s["tool"],
                id=s.get("id", s["tool"]),
                depends_on=s.get("depends_on", []),
                condition=condition,
                args=s.get("args", {}),
                args_from_upstream=s.get("args_from_upstream", {}),
                retry_on_failure=s.get("retry_on_failure", 0),
                timeout_s=s.get("timeout_s", 300.0),
                description=s.get("description", ""),
            )
            steps.append(step)

        return PipelineDefinition(
            name=data.get("name", "unnamed"),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            steps=steps,
            on_error=data.get("on_error", "stop"),
            max_parallel=data.get("max_parallel", 4),
        )

    # ═══════════════════════════════════════════════════════════
    # 执行
    # ═══════════════════════════════════════════════════════════

    async def run(self, pipeline_name: str,
                  context: ExecutionContext = None,
                  extra_args: Dict[str, Any] = None,
                  on_progress: Callable = None) -> PipelineResult:
        """执行流水线"""
        pipeline = self._pipelines.get(pipeline_name)
        if not pipeline:
            return PipelineResult(pipeline_name=pipeline_name, status=StepStatus.ERROR,
                                  steps=[], error=f"Pipeline '{pipeline_name}' not found")

        ctx = context or ExecutionContext()
        extra_args = extra_args or {}

        result = PipelineResult(
            pipeline_name=pipeline_name,
            status=StepStatus.RUNNING,
            started_at=datetime.now().isoformat(),
        )
        start_time = time.monotonic()

        # 拓扑排序
        step_order = self._topological_sort(pipeline.steps)
        step_outputs: Dict[str, Dict[str, Any]] = {}
        step_results: Dict[str, StepResult] = {}
        completed: Set[str] = set()

        # 按层级执行
        for level in step_order:
            # 并行执行同层级步骤
            tasks = []
            for step in level:
                tasks.append(self._execute_step(
                    step, pipeline, step_outputs, step_results, completed,
                    ctx, extra_args, on_progress,
                ))
            level_results = await asyncio.gather(*tasks, return_exceptions=True)

            for sr in level_results:
                if isinstance(sr, Exception):
                    logger.error(f"Step execution exception: {sr}")
                    continue
                if isinstance(sr, StepResult):
                    step_results[sr.step_id] = sr
                    if sr.status == StepStatus.PASSED and sr.result:
                        step_outputs[sr.step_id] = sr.result.data
                    completed.add(sr.step_id)

            # 错误处理
            failed_this_level = [sr for sr in step_results.values()
                                if sr.status in (StepStatus.FAILED, StepStatus.ERROR)]
            if failed_this_level and pipeline.on_error == "stop":
                # 跳过未执行的步骤
                for step in pipeline.steps:
                    if step.id not in completed:
                        step_results[step.id] = StepResult(
                            step_id=step.id, tool_name=step.tool,
                            status=StepStatus.SKIPPED,
                            error="Pipeline stopped due to upstream failure",
                        )
                break

        # 汇总
        result.steps = list(step_results.values())
        result.passed = sum(1 for s in result.steps if s.status == StepStatus.PASSED)
        result.failed = sum(1 for s in result.steps if s.status == StepStatus.FAILED)
        result.skipped = sum(1 for s in result.steps if s.status == StepStatus.SKIPPED)
        result.outputs = step_outputs
        result.total_time_s = round(time.monotonic() - start_time, 3)
        result.ended_at = datetime.now().isoformat()
        result.status = StepStatus.PASSED if result.failed == 0 else (
            StepStatus.FAILED if result.skipped == 0 else StepStatus.FAILED
        )

        return result

    async def _execute_step(self, step: PipelineStep, pipeline: PipelineDefinition,
                           outputs: Dict[str, Dict[str, Any]],
                           results: Dict[str, StepResult], completed: Set[str],
                           ctx: ExecutionContext, extra_args: Dict[str, Any],
                           on_progress: Callable = None) -> StepResult:
        """执行单个步骤"""
        # 检查依赖
        for dep in step.depends_on:
            if dep not in completed:
                return StepResult(
                    step_id=step.id, tool_name=step.tool,
                    status=StepStatus.SKIPPED,
                    error=f"Dependency '{dep}' not completed",
                )

        # 检查条件
        if step.condition:
            if not step.condition.evaluate(outputs):
                return StepResult(
                    step_id=step.id, tool_name=step.tool,
                    status=StepStatus.SKIPPED,
                    error=f"Condition not met: {step.condition.field} {step.condition.op.value} {step.condition.value}",
                )

        # 构建参数
        args = dict(step.args)
        args.update(extra_args.get(step.id, {}))
        for param, source in step.args_from_upstream.items():
            # source: "step_id.field"
            parts = source.split(".", 1)
            if len(parts) == 2:
                upstream_data = outputs.get(parts[0], {})
                if parts[1] in upstream_data:
                    args[param] = upstream_data[parts[1]]

        # 执行
        started = datetime.now().isoformat()
        t0 = time.monotonic()

        if on_progress:
            try:
                on_progress(step.id, "running", f"Running {step.tool}...")
            except Exception:
                pass

        tool = self._hub.get(step.tool)
        if not tool:
            return StepResult(
                step_id=step.id, tool_name=step.tool,
                status=StepStatus.ERROR, error=f"Tool '{step.tool}' not found",
                started_at=started,
            )

        # 带重试
        last_result = None
        for attempt in range(step.retry_on_failure + 1):
            try:
                result = await asyncio.wait_for(
                    self._hub.invoke(step.tool, args, ctx),
                    timeout=step.timeout_s,
                )
                if result.success:
                    if on_progress:
                        try:
                            on_progress(step.id, "passed", f"{step.tool} OK")
                        except Exception:
                            pass
                    return StepResult(
                        step_id=step.id, tool_name=step.tool,
                        status=StepStatus.PASSED, result=result,
                        started_at=started, ended_at=datetime.now().isoformat(),
                        elapsed_s=round(time.monotonic() - t0, 3),
                        retries=attempt,
                    )
                last_result = result
                if attempt < step.retry_on_failure:
                    logger.info(f"Retrying {step.tool} (attempt {attempt + 2}/{step.retry_on_failure + 1})")
                    await asyncio.sleep(1.0)

            except asyncio.TimeoutError:
                last_result = ToolResult.fail(f"Timeout after {step.timeout_s}s")
            except Exception as e:
                last_result = ToolResult.fail(str(e)[:500])

        if on_progress:
            try:
                on_progress(step.id, "failed", f"{step.tool} FAILED")
            except Exception:
                pass

        return StepResult(
            step_id=step.id, tool_name=step.tool,
            status=StepStatus.FAILED, result=last_result,
            error=last_result.error if last_result else "Unknown error",
            started_at=started, ended_at=datetime.now().isoformat(),
            elapsed_s=round(time.monotonic() - t0, 3),
            retries=step.retry_on_failure,
        )

    # ═══════════════════════════════════════════════════════════
    # 拓扑排序
    # ═══════════════════════════════════════════════════════════

    def _topological_sort(self, steps: List[PipelineStep]) -> List[List[PipelineStep]]:
        """将步骤按依赖拓扑排序为层级列表（同级可并行）"""
        step_map = {s.id: s for s in steps}
        in_degree = {s.id: 0 for s in steps}
        dependents = {s.id: [] for s in steps}

        for s in steps:
            for dep in s.depends_on:
                if dep in step_map:
                    in_degree[s.id] += 1
                    dependents[dep].append(s.id)

        levels = []
        remaining = set(s.id for s in steps)

        while remaining:
            # 找到当前入度为 0 的节点
            current = sorted([nid for nid in remaining if in_degree[nid] == 0],
                            key=lambda nid: steps.index(step_map[nid]))
            if not current:
                # 循环依赖检测
                cycle_nodes = remaining
                logger.error(f"Circular dependency detected: {cycle_nodes}")
                break

            level = [step_map[nid] for nid in current]
            levels.append(level)

            for nid in current:
                remaining.discard(nid)
                for dep_id in dependents[nid]:
                    in_degree[dep_id] -= 1

        return levels

    # ═══════════════════════════════════════════════════════════
    # 可视化
    # ═══════════════════════════════════════════════════════════

    def to_dot(self, pipeline_name: str) -> str:
        """生成 Graphviz DOT 格式的流水线图"""
        pipeline = self._pipelines.get(pipeline_name)
        if not pipeline:
            return ""

        lines = ["digraph {", '  rankdir=LR;', f'  label="{pipeline_name}";',
                 '  node [shape=box, style=rounded];', ""]

        for step in pipeline.steps:
            color = "black"
            tool = self._hub.get(step.tool)
            if tool:
                risk_colors = {"safe": "green", "write": "gold", "danger": "red"}
                color = risk_colors.get(tool.manifest.risk_level.value, "black")
            desc = step.description or step.tool
            lines.append(f'  {step.id} [label="{step.id}\\n{desc}", color={color}];')

        for step in pipeline.steps:
            for dep in step.depends_on:
                lines.append(f"  {dep} -> {step.id};")

        lines.append("}")
        return "\n".join(lines)

    def to_mermaid(self, pipeline_name: str) -> str:
        """生成 Mermaid 格式的流水线图"""
        pipeline = self._pipelines.get(pipeline_name)
        if not pipeline:
            return ""

        lines = ["```mermaid", "graph LR"]
        for step in pipeline.steps:
            desc = step.description or step.tool
            lines.append(f"  {step.id}[{desc}]")
        for step in pipeline.steps:
            for dep in step.depends_on:
                lines.append(f"  {dep} --> {step.id}")
        lines.append("```")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 内置流水线
# ═══════════════════════════════════════════════════════════════

BUILTIN_PIPELINES = {
    "uvm_quality_check": PipelineDefinition(
        name="uvm_quality_check",
        version="1.0",
        description="UVM 环境质量检查: 静态 → 编译 → 闭环 → 报告",
        steps=[
            PipelineStep(tool="check_static", id="static"),
            PipelineStep(tool="check_compile", id="compile", depends_on=["static"]),
            PipelineStep(tool="check_loopback", id="loopback", depends_on=["compile"]),
            PipelineStep(tool="quality_report", id="report",
                        depends_on=["static", "compile", "loopback"]),
        ],
    ),
    "code_generation": PipelineDefinition(
        name="code_generation",
        version="1.0",
        description="UVM 代码生成: 规格分析 → 渲染 → 写入",
        steps=[
            PipelineStep(tool="find_spec_yaml", id="parse"),
            PipelineStep(tool="jinja_render", id="render", depends_on=["parse"],
                        args_from_upstream={"output_dir": "parse.output_dir"}),
            PipelineStep(tool="write_file", id="write", depends_on=["render"],
                        args_from_upstream={"path_content": "render.file_list"}),
        ],
    ),
}
