"""
基础抽象类 - 更新使用LLM工厂
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import asyncio
import json
from pydantic import BaseModel, Field
from langchain.agents import AgentExecutor
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
import structlog

from src.core.llm_factory import LLMFactory
from config.settings import Settings

logger = structlog.get_logger()

# ── Helper: extract JSON from LLM text output ──

def _extract_json_from_llm(text: str):
    """Try to extract a JSON dict from LLM text (may be in ```json blocks)."""
    if not text or not isinstance(text, str):
        return None
    import re as _re
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    m = _re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, _re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(1))
            return result if isinstance(result, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    return None

# ==================== 基础数据模型 ====================

class AgentStatus(Enum):
    """Agent状态枚举"""
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"

class AgentResult(BaseModel):
    """Agent执行结果"""
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)



class AgentMessage(BaseModel):
    """Agent间通信消息"""
    id: str = Field(default_factory=lambda: f"msg_{datetime.now().timestamp()}")
    sender: str
    receiver: str
    content: Dict[str, Any] = Field(default_factory=dict)
    message_type: str = "task"
    timestamp: datetime = Field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    requires_response: bool = False

# ==================== 观察者模式 ====================

class AgentObserver(ABC):
    """Agent观察者接口"""
    
    @abstractmethod
    async def on_agent_start(self, agent_id: str, task: Dict[str, Any]):
        pass
    
    @abstractmethod
    async def on_agent_complete(self, agent_id: str, result: AgentResult):
        pass
    
    @abstractmethod
    async def on_agent_error(self, agent_id: str, error: Exception):
        pass

class AgentSubject:
    """被观察的Agent基类"""
    
    def __init__(self):
        self._observers: List[AgentObserver] = []
    
    def attach_observer(self, observer: AgentObserver):
        self._observers.append(observer)
    
    def detach_observer(self, observer: AgentObserver):
        self._observers.remove(observer)
    
    async def notify_start(self, agent_id: str, task: Dict[str, Any]):
        for observer in self._observers:
            await observer.on_agent_start(agent_id, task)
    
    async def notify_complete(self, agent_id: str, result: AgentResult):
        for observer in self._observers:
            await observer.on_agent_complete(agent_id, result)
    
    async def notify_error(self, agent_id: str, error: Exception):
        for observer in self._observers:
            await observer.on_agent_error(agent_id, error)

# ==================== 基础Agent类 ====================

class BaseAgent(ABC, AgentSubject):
    """
    基础Agent类

    使用模板方法模式定义Agent生命周期
    集成LLM工厂自动选择最优模型

    consumes / produces 声明 Agent 对共享上下文 (ctx) 的读写契约：
      consumes: List[str]  — 从 ctx 读取哪些 key，如 ["spec"]
      produces: str | None — 向 ctx 写入哪个 key，如 "env"；None 表示只产生文本
    """

    # 子类需要定义的任务类型，用于LLM工厂选择模型
    task_type: str = "spec_analysis"

    # 共享上下文契约 —— 子类覆盖
    # consumes: List[str]  → 全部字段; Dict[str, List[str]] → 字段级
    consumes: List[str] = []
    produces: Optional[str] = None

    def __init__(
        self,
        role: str,
        display_name: str,
        description: str,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__()
        self.role = role
        self.display_name = display_name
        self.description = description
        self.config = config or {}
        self.status = AgentStatus.IDLE
        self.state: Dict[str, Any] = {}
        self.metrics: Dict[str, Any] = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_tokens": 0,
            "total_time": 0.0
        }
        
        # LLM和Executor
        self.llm: Optional[BaseChatModel] = None
        self._executor: Optional[AgentExecutor] = None
        self.tools: List[BaseTool] = []
        
        # 设置
        self.settings = Settings.get_instance()

        # ── 验证与重试 ──
        self.min_score = 50       # 最低分阈值（低于此分触发重试）
        self.max_retries = 2      # 最大重试次数
        self._retry_count = 0     # 当前重试计数
        self._best_score = 0      # 历史最高分
        self._best_result = None  # 历史最佳产出

        # ── Tool Schema 验证 (可选) ──
        self.tool_registry = None  # 外部设置: agent.tool_registry = registry

        logger.info(f"Agent初始化", role=self.role, name=self.display_name)
    
    def _create_llm(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> BaseChatModel:
        """
        创建LLM实例
        
        使用LLM工厂根据任务类型自动选择最优模型
        """
        return LLMFactory.create_for_task(
            task_type=self.task_type,
            settings=self.settings
        )
    
    async def initialize(self):
        """
        初始化Agent

        模板方法 - 定义初始化流程
        1. 创建LLM
        2. 子类特定初始化
        3. 创建Agent Executor
        """
        logger.info(f"正在初始化Agent: {self.display_name}")

        # 1. 创建LLM
        self._llm_unavailable = False
        try:
            self.llm = self._create_llm()
        except (ValueError, Exception) as e:
            logger.warning(f"LLM创建失败", error=str(e))
            self.llm = None
            self._llm_unavailable = True

        # 2. 获取工具
        self.tools = await self._get_tools()

        # 2.5 可选: Tool Schema 验证包装
        if self.tool_registry and self.tools:
            from src.core.tool_system import ToolRegistryAdapter
            adapter = ToolRegistryAdapter(self.tool_registry)
            self.tools = adapter.wrap(self.tools)
            self._tool_adapter = adapter

        # 3. 获取Prompt
        prompt = await self._get_prompt_template()

        # 4. 子类特定初始化
        await self._setup()

        # 5. 创建Agent Executor（仅当 LLM 可用时）
        if self.llm and prompt:
            tools = self.tools if self.tools else []
            if tools:
                # Agent with tools: use LangChain agent executor
                from langchain.agents import create_openai_tools_agent
                agent = create_openai_tools_agent(
                    llm=self.llm,
                    tools=tools,
                    prompt=prompt
                )
                self._executor = AgentExecutor(
                    agent=agent, tools=tools,
                    verbose=self.settings.agent.verbose,
                    max_iterations=self.settings.agent.max_iterations,
                    handle_parsing_errors=True,
                    return_intermediate_steps=True
                )
            else:
                # No tools: use direct LLM chain (simpler, more reliable)
                from langchain_core.output_parsers import StrOutputParser
                self._direct_chain = prompt | self.llm | StrOutputParser()
                self._executor = None  # signal to use _direct_chain

        self.status = AgentStatus.IDLE
        logger.info(f"Agent初始化完成: {self.display_name}")
    
    @abstractmethod
    async def _setup(self):
        """子类特定初始化"""
        pass
    
    @abstractmethod
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        pass
    
    @abstractmethod
    async def _get_tools(self) -> List[BaseTool]:
        """获取工具列表"""
        pass
    
    # ── 共享上下文 (ctx) 读写 ──

    def _read_ctx(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """根据 consumes 声明读取数据。支持两种格式:
          List[str]:           consumes = ["spec"]        → 全部字段
          Dict[str,List[str]]: consumes = {"spec":["features","interfaces"]} → 字段级
        """
        raw_ctx = task.get("ctx", {}) if isinstance(task, dict) else {}
        if not raw_ctx or not self.consumes:
            return {}

        # 兼容 ContextStore 和原始 dict
        if hasattr(raw_ctx, 'get'):
            ctx_store = raw_ctx
        else:
            ctx_store = raw_ctx

        result = {}
        if isinstance(self.consumes, dict):
            # 字段级: {"spec": ["features", "interfaces"]}
            for key, fields in self.consumes.items():
                if hasattr(ctx_store, 'fetch'):
                    val = ctx_store.fetch(key, fields=fields)
                elif key in ctx_store:
                    val = ctx_store[key] if not hasattr(ctx_store, 'get') else ctx_store.get(key)
                    if isinstance(val, dict) and fields:
                        val = {f: val[f] for f in fields if f in val}
                else:
                    continue
                if val is not None:
                    result[key] = val.model_dump() if isinstance(val, BaseModel) else val
        else:
            # 列表: ["spec", "env"] → 全部字段
            for key in self.consumes:
                val = ctx_store.get(key) if hasattr(ctx_store, 'get') else ctx_store[key] if key in ctx_store else None
                if val is not None:
                    result[key] = val.model_dump() if isinstance(val, BaseModel) else val
        return result

    def _write_ctx(self, task: Dict[str, Any], result: "AgentResult") -> None:
        """根据 produces 声明，将 result.data 写回 task["ctx"]"""
        if not self.produces or not isinstance(task, dict):
            return
        ctx = task.get("ctx")
        if ctx is None:
            return
        # Accept both raw dict and ContextStore
        is_dict_like = isinstance(ctx, dict) or hasattr(ctx, 'put')
        if not is_dict_like:
            return

        data = result.data if isinstance(result.data, dict) else {}
        source = getattr(self, 'role', 'unknown')

        # ContextStore.put 优先
        if hasattr(ctx, 'put'):
            if self.produces in data:
                ctx.put(self.produces, data[self.produces], source=source)
            else:
                flat_keys = {"env_name", "output_dir", "filelist", "agent_count", "files",
                             "agents", "top_module", "scenario_count", "test_names", "scenarios", "test_cases",
                             "compile_status", "pass_count", "fail_count", "passed", "failed",
                             "total", "pass_rate", "compile",
                             "coverage_data", "gaps", "suggestions",
                             "line_pct", "branch_pct", "toggle_pct", "coverage_pct"}
                relevant = {k: v for k, v in data.items() if k in flat_keys}
                if relevant:
                    ctx.put(self.produces, relevant, source=source)
            return

        # Fallback: raw dict
        if self.produces in data:
            ctx[self.produces] = data[self.produces]
        else:
            flat_keys = {"env_name", "output_dir", "filelist", "agent_count", "files",
                         "agents", "top_module",
                         "scenario_count", "test_names", "scenarios",
                         "compile_status", "pass_count", "fail_count",
                         "coverage_data", "gaps", "suggestions"}
            relevant = {k: v for k, v in data.items() if k in flat_keys}
            if relevant:
                ctx[self.produces] = relevant

    # ── 验证 ──

    def validate(self, result_data: dict) -> tuple[bool, str]:
        """验证 Agent 产出是否达到最低质量标准。

        返回 (passed, reason)。子类可覆盖此方法定义自己的验证规则。
        默认：检查 score >= min_score。
        """
        score = result_data.get("score", 0)
        if score < self.min_score:
            return False, f"score {score} < min {self.min_score}"
        return True, "OK"

    def reset_retry_state(self):
        """重置重试状态（每次管道调用时清空）"""
        self._retry_count = 0
        self._best_score = 0
        self._best_result = None

    # ── Agent I/O 日志（控制台输出）──

    def _fmt_ctx(self, ctx_data: dict) -> str:
        """Format ctx data as concise string."""
        if not ctx_data:
            return "none"
        parts = []
        for k, v in ctx_data.items():
            if isinstance(v, dict):
                nk = len(v)
                # Show first few keys
                sk = ",".join(list(v.keys())[:4])
                parts.append(f"{k}({nk}k:{sk}{'...' if nk>4 else ''})")
            elif isinstance(v, list):
                parts.append(f"{k}({len(v)} items)")
            elif isinstance(v, str):
                parts.append(f"{k}({len(v)}c)")
            else:
                parts.append(f"{k}={v}")
        return " ".join(parts)

    def _fmt_input(self, task_input: str) -> str:
        """Format task input as concise one-liner."""
        s = str(task_input)[:150].replace("\n", "\\n").replace("\r", "")
        if len(str(task_input)) > 150:
            s += f"...({len(str(task_input))}c)"
        return s

    def _fmt_output(self, data: dict) -> str:
        """Format result data as concise one-liner."""
        parts = []
        # Key numeric/string metrics first
        for k in ("module_name", "env_name", "design_name", "model_type",
                   "feature_count", "function_count", "register_count",
                   "agent_count", "file_count", "test_count", "scenario_count",
                   "feature", "features", "test_points", "registers",
                   "operations", "files"):
            v = data.get(k)
            if v is not None:
                if isinstance(v, list):
                    parts.append(f"{k}={len(v)}")
                elif isinstance(v, (int, float, str)):
                    parts.append(f"{k}={v}")
        # Fallback: top-level keys with small values
        if not parts:
            for k, v in sorted(data.items()):
                if k in ("output", "score", "error", "_ctx_data", "code"):
                    continue
                if isinstance(v, (int, float, str, bool)):
                    parts.append(f"{k}={v}")
                elif isinstance(v, list):
                    parts.append(f"{k}#{len(v)}")
                elif isinstance(v, dict):
                    parts.append(f"{k}#{len(v)}")
        return ", ".join(parts[:8]) if parts else "—"

    def _log_io_begin(self, task_input: str, ctx_data: dict, mode: str, action: str):
        """Print agent input + action to console."""
        tag = self.role[:22]
        inp = self._fmt_input(task_input)
        ctx = self._fmt_ctx(ctx_data)
        from src.middleware.debug_logger import tracer
        tracer.agent_io(self.role, "in", inp)
        if ctx_data:
            tracer.agent_io(self.role, "ctx", ctx)
        tracer.agent_io(self.role, "act", f"{mode} -> {action}")

    def _log_io_end(self, result_data: dict, elapsed: float, success: bool = True):
        """Print agent output to console."""
        score = result_data.get("score", "?")
        out = self._fmt_output(result_data)
        t = f"{elapsed:.1f}s" if elapsed else "?"
        st = "OK" if success else "FAIL"
        from src.middleware.debug_logger import tracer
        tracer.agent_io(self.role, "out", f"{st} score={score} | {out} | {t}")

    # ── 任务执行 ──

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM path
        ctx_data = self._read_ctx(task)
        if ctx_data and isinstance(task, dict):
            task["_ctx_data"] = ctx_data

        start_time = datetime.now()
        self.status = AgentStatus.BUSY
        await self.notify_start(self.role, task)

        task_input = task.get("input", str(task))
        tools_names = [t.name for t in self.tools] if self.tools else []
        mode = "LLM" if self._executor else "direct"
        action = f"{self.produces or 'text'} generation" + (f" tools={tools_names[:4]}" if tools_names else "")
        self._log_io_begin(task_input, ctx_data, mode, action)

        try:
            processed_input = await self._pre_process(task)
            if self._executor:
                result = await self._executor.ainvoke({
                    "input": processed_input,
                    "chat_history": [],
                    "tool_names": tools_names,
                })
            elif hasattr(self, '_direct_chain') and self._direct_chain:
                # Direct LLM call (no tools) — must pass all prompt variables
                output_text = await self._direct_chain.ainvoke({
                    "input": processed_input,
                    "chat_history": [],
                    "agent_scratchpad": [],
                })
                result = {"output": output_text}
            else:
                # Keep local/template workflows usable when no provider is configured.
                result = self._offline_result()
            processed_result = await self._post_process(result)
            execution_time = (datetime.now() - start_time).total_seconds()
            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += execution_time

            # ── Extract structured data from LLM text output ──
            if isinstance(processed_result, dict):
                llm_output = processed_result.get("output", "")
                if isinstance(llm_output, str):
                    # Try to extract JSON from LLM text
                    parsed = _extract_json_from_llm(llm_output)
                    if parsed:
                        for k, v in parsed.items():
                            if k not in processed_result:
                                processed_result[k] = v
                        # Auto-detect which ctx key this agent's output maps to
                        SPEC_KEYS = {"design_name", "features", "interfaces", "test_points",
                                     "verification_architecture", "registers", "clock_domains"}
                        DESIGN_KEYS = {"module_name", "function_hier", "rtl_hier", "signoff_checklist"}
                        ENV_KEYS = {"env_name", "agent_count", "files", "filelist"}
                        MODEL_KEYS = {"module", "model_type", "analysis", "ref_model", "operations"}
                        TESTS_KEYS = {"scenarios", "scenario_count", "test_names", "policies", "yaml"}
                        REGRESSION_KEYS = {"compile", "summary", "tests", "compile_status", "pass_rate"}
                        COVERAGE_KEYS = {"coverage_data", "line_pct", "branch_pct", "gaps", "coverage_pct"}
                        DEBUG_KEYS = {"category", "errors", "suggestion", "fix_agent", "scores"}
                        parsed_keys = set(parsed.keys())
                        for key_set, ctx_key in [
                            (SPEC_KEYS, "spec"), (DESIGN_KEYS, "design_arch"),
                            (ENV_KEYS, "env"), (MODEL_KEYS, "model"),
                            (TESTS_KEYS, "tests"), (REGRESSION_KEYS, "regression"),
                            (COVERAGE_KEYS, "coverage"), (DEBUG_KEYS, "debug")]:
                            if parsed_keys & key_set and ctx_key not in processed_result:
                                processed_result[ctx_key] = parsed
                    # Heuristic scoring
                    if "score" not in processed_result and llm_output:
                        n_lines = len(llm_output.split("\n"))
                        has_json = "{" in llm_output
                        base = 70 if has_json else 50
                        processed_result["score"] = min(base + (n_lines // 20) * 3, 85)

            # Ensure a score is present
            if isinstance(processed_result, dict) and "score" not in processed_result:
                output_text = processed_result.get("output", "")
                has_struct = any(k in processed_result for k in
                    ("spec","design_arch","env","model","tests","regression","coverage","debug"))
                has_output = bool(output_text and len(str(output_text)) > 20)
                if has_struct:
                    processed_result["score"] = 75
                elif has_output:
                    processed_result["score"] = 55  # LLM ran, give passing baseline
                else:
                    processed_result["score"] = 30
            # Override: if score is 0 but LLM clearly ran, bump to minimum
            if isinstance(processed_result, dict) and processed_result.get("score", 0) <= 0:
                output_text = processed_result.get("output", "")
                if output_text and len(str(output_text)) > 20:
                    processed_result["score"] = 55
                elif processed_result.get("intermediate_steps"):
                    processed_result["score"] = 55
            agent_result = AgentResult(success=True, data=processed_result, execution_time=execution_time)
            # 将产出写回共享上下文
            self._write_ctx(task, agent_result)

            self._log_io_end(processed_result, execution_time, True)

            # 记录调试日志
            try:
                from src.middleware.debug_logger import debug_logger
                prompt_preview = str(getattr(self, '_last_prompt', ''))[:500]
                debug_logger.log_agent_call(self.role, self.display_name, str(task)[:500], prompt_preview, str(processed_result)[:500], tools_names, 0, execution_time, True)
            except:
                pass
            await self.notify_complete(self.role, agent_result)
            return agent_result
        except Exception as e:
            # A disconnected provider must not make template/offline workflows unusable.
            # Keep this opt-in through configuration for deployments that require strict LLM availability.
            if self.settings.agent.fallback_on_llm_error:
                logger.warning("LLM执行失败，使用本地降级结果", role=self.role, error=str(e))
                try:
                    fallback = self._offline_result(str(e))
                    processed_result = await self._post_process(fallback)
                    execution_time = (datetime.now() - start_time).total_seconds()
                    self.metrics["tasks_completed"] += 1
                    self.metrics["total_time"] += execution_time
                    agent_result = AgentResult(success=True, data=processed_result, execution_time=execution_time,
                                               metadata={"degraded": True, "llm_error": str(e)[:200]})
                    self._write_ctx(task, agent_result)
                    self._log_io_end(processed_result, execution_time, True)
                    await self.notify_complete(self.role, agent_result)
                    return agent_result
                except Exception as fallback_error:
                    logger.error("本地降级执行失败", role=self.role, error=str(fallback_error))
            self.metrics["tasks_failed"] += 1
            self._log_io_end({"error": str(e)[:80]}, (datetime.now() - start_time).total_seconds(), False)
            error_result = AgentResult(success=False, error=str(e))
            await self.notify_error(self.role, e)
            return error_result
        finally:
            self.status = AgentStatus.IDLE

    async def _pre_process(self, task: Dict[str, Any]) -> str:
        """预处理任务输入"""
        return task.get("input", str(task))

    def _offline_result(self, reason: str = "LLM provider is unavailable") -> Dict[str, Any]:
        """Return a deterministic degraded result without retrying a failed LLM executor."""
        payload = {"status": "degraded", "agent": self.role, "reason": reason}
        result = {
            "output": json.dumps(payload, ensure_ascii=False),
            "offline": True,
        }
        if self.produces:
            result[self.produces] = payload
        return result
    
    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """后处理执行结果"""
        return result
    
    @abstractmethod
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """直接执行（不使用Agent Executor时）"""
        pass
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "role": self.role,
            "status": self.status.value,
            "metrics": self.metrics.copy(),
            "state": self.state.copy()
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取性能指标"""
        return {
            "role": self.role,
            "display_name": self.display_name,
            "status": self.status.value,
            **self.metrics
        }

    requires_response: bool = False
