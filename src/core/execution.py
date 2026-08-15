"""
Pipeline 执行服务 —— CLI 和 Web API 共享的验证流水线引擎

单例模式，管理 Agent 生命周期 + 流水线执行 + 运行状态追踪。
"""
from __future__ import annotations
import time, json, uuid, asyncio
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.core.output_config import make_output_root

from src.core.registry import AgentRegistry
from src.core.context import ContextStore
from src.tools.doc_tools.pipeline_docs import generate_phase_doc, update_flow_doc
from src.agents.design import DesignAgent
from src.agents.model import ModelAgent
from src.agents.verify import VerifyAgent
from src.agents.ops import OpsAgent
from src.agents.coverage import CoverageAgent
from src.agents.debug import DebugAgent
from src.agents.audit import AuditAgent
from config.settings import Settings

logger = structlog.get_logger()

# Pipeline 阶段定义（LEGACY 线性流水线，供 run_pipeline 使用）
# 这些旧角色（spec/rtl/uvm/test/assert/regress_cov/qa/report）是 11-Agent 体系残留，
# 新七 Agent 闭环（run_closed_loop）使用 design/model/verify/ops/coverage/debug/audit。
# 旧角色 → 新 Agent 映射：spec→design, rtl→design, uvm/test/assert→verify,
# regress_cov→ops+coverage, qa/report→audit。
# doc_only=True 的阶段仅生成文档，不执行 Agent
FULL_PHASES = [
    # 前端设计 (de/)
    ("spec",    "spec",          "spec",        False),
    ("design",  "design",         "design_arch", False),
    ("model",   "model",          "model",       False),
    ("rtl",     "rtl",            "rtl",         False),   # RTL 代码生成
    # 功能验证 (dv/)
    ("UVM",     "uvm",           "env",         False),
    ("test",    "test",          "tests",       False),
    ("assert",  "assert",        None,          False),
    ("regress_cov", "regress_cov", "regression", False),  # 编译仿真+覆盖率+gap分析+增补建议
    ("debug",   "debug",         None,          False),
    ("docs",    None,            None,          True),    # 并行: ifspec+rtlsign+vplan+tpoint+rtm (有实际coverage数据)
    ("qa",      "qa",            None,          False),
    ("report",  "report",        None,          False),
    ("vclose",  None,            None,          True),    # 验证收敛报告
]

QUICK_PHASES = [p for p in FULL_PHASES if p[0] in ("spec", "design", "model", "rtl", "UVM", "test", "docs")]

# ═══════════════════════════════════════════════════════════════
# 门禁机制 — 每个阶段的最低质量分数
# 低于门槛则管线 HALT，不允许降级通过
# ═══════════════════════════════════════════════════════════════
_PHASE_GATES = {
    # 前端设计 — 松门槛（LLM 生成，允许波动）
    "spec":    55,
    "design":  45,
    "model":   45,
    "rtl":     45,
    # 功能验证 — 严格门槛（关键质量节点）
    "UVM":     70,   # 静态检查不过 = 不能交付
    "test":    50,
    "assert":  30,
    "regress_cov": 50,  # 编译不过 = 后面的覆盖率全是空的
    "debug":   30,
    "qa":      50,
    "report":  40,
    # doc_only 阶段不设门禁
    "docs":    0,
    "vclose":  0,
}

# 通过 phase name 查找 FULL_PHASES 中的条目
def _phase(name):
    for p in FULL_PHASES:
        if p[0] == name:
            return p
    return None

# 工作流名称 → 可执行阶段列表映射
_WORKFLOW_PHASE_MAP = {
    "full_verification": FULL_PHASES,
    "quick_check":       QUICK_PHASES,
    "regression_only":   [
        _phase("regress_cov"),
        _phase("debug"),
        _phase("report"),
    ],
    "ppa_analysis":      [
        _phase("docs"),
        _phase("report"),
    ],
}

# ═══════════════════════════════════════════════════════════════
# 验证 Profile 预设（借鉴原型 --task-type）
# ═══════════════════════════════════════════════════════════════

VERIFY_PROFILES = {
    "quick": {
        "description": "快速质量检查：编译 + 冒烟 + QA 审查",
        "phases": ["design", "rtl", "UVM", "qa"],
        "approval_gates": ["design", "UVM"],
    },
    "standard": {
        "description": "标准验证流程：设计 + UVM + 测试 + 回归 + 报告",
        "phases": ["spec", "design", "model", "rtl", "UVM", "test",
                   "regress", "cover", "report"],
        "approval_gates": ["design", "UVM"],
    },
    "full": {
        "description": "完整签核流程：全部 Agent + 断言 + 调试 + 证据链",
        "phases": None,  # None = 走默认 FULL_PHASES
        "approval_gates": [],
    },
    "debug": {
        "description": "调试模式：只跑失败分析",
        "phases": ["debug"],
        "approval_gates": [],
    },
    "spec_only": {
        "description": "只做规格分析，输出结构化测试计划",
        "phases": ["spec"],
        "approval_gates": [],
    },
    "design_only": {
        "description": "只做设计：从 Spec 到 RTL",
        "phases": ["spec", "design", "model", "rtl"],
        "approval_gates": ["design", "rtl"],
    },
    # ── 增量更新模式 ──
    "spec_update": {
        "description": "Spec 变更：重新分析规格 → 更新验证计划 → 增量测试",
        "phases": ["spec", "design", "test", "docs"],
        "approval_gates": ["spec"],
    },
    "rtl_update": {
        "description": "RTL 变更：重新生成 RTL → UVM 编译检查 → 回归",
        "phases": ["rtl", "UVM", "regress_cov", "docs"],
        "approval_gates": ["rtl", "UVM"],
    },
    "uvm_update": {
        "description": "UVM Env 更新：重新生成环境 → 编译 → P0 回归",
        "phases": ["UVM", "test", "regress_cov", "qa"],
        "approval_gates": ["UVM"],
        "regress_dir": "uvm_regress",
    },
    "model_update": {
        "description": "参考模型更新：重新生成 C++ 模型 → 比对验证",
        "phases": ["model", "rtl", "regress_cov", "report"],
        "approval_gates": ["model"],
    },
    "regress_cov": {
        "description": "覆盖率回归：全量编译仿真 + 覆盖率收集 + gap 分析",
        "phases": ["UVM", "test", "regress_cov", "docs", "report"],
        "approval_gates": ["regress_cov"],
        "regression_mode": "cov",
    },
    "regress_xprop": {
        "description": "X-Propagation 回归：X 态传播检查 + 断言验证",
        "phases": ["UVM", "test", "assert", "regress_cov", "debug"],
        "approval_gates": ["regress_cov"],
        "regression_mode": "xprop",
    },
}


def resolve_phases_from_profile(profile: str) -> list:
    """从 profile 名称解析出阶段列表"""
    if profile not in VERIFY_PROFILES:
        raise ValueError(f"Unknown profile: {profile}. "
                         f"Available: {list(VERIFY_PROFILES.keys())}")
    config = VERIFY_PROFILES[profile]
    if config["phases"] is None:
        return FULL_PHASES
    # 将简写 phase 名映射到 FULL_PHASES 中的 tuple
    phase_map = {p[0]: p for p in FULL_PHASES}
    resolved = []
    for name in config["phases"]:
        if name in phase_map:
            resolved.append(phase_map[name])
    return resolved


def _writeback_produces(agent, result_data: Any, ctx: dict) -> None:
    """按 Agent 声明的 produces 契约写回共享上下文。"""
    key = getattr(agent, "produces", None)
    if not key or not isinstance(result_data, dict):
        return
    value = result_data.get(key)
    if not value:
        return
    source = getattr(agent, 'role', 'unknown')
    if hasattr(ctx, 'put'):
        ctx.put(key, value, source=source)
    else:
        ctx[key] = value


def _make_ctx_copy(ctx: ContextStore) -> ContextStore:
    """为并行执行创建隔离的 ctx 副本。"""
    new_ctx = ContextStore()
    for key, entry in ctx._data.items():
        val = entry.value
        new_ctx._data[key] = type(entry)(
            value=deepcopy(val) if isinstance(val, (dict, list)) else val,
            source=entry.source,
        )
        new_ctx._data[key].timestamp = entry.timestamp
        new_ctx._data[key].version = entry.version
    return new_ctx


def _build_task_input(agent, ctx, spec_text: str) -> str:
    """为单个 agent 构建字段级 task_input。"""
    consumes = getattr(agent, 'consumes', [])
    if not consumes:
        return spec_text
    if isinstance(consumes, dict):
        ctx_parts = {}
        for ck, fields in consumes.items():
            if hasattr(ctx, 'fetch'):
                val = ctx.fetch(ck, fields=fields)
            else:
                val = ctx.get(ck)
                if isinstance(val, dict) and fields:
                    val = {f: val[f] for f in fields if f in val}
            if val is not None:
                ctx_parts[ck] = val
        result = json.dumps(ctx_parts, ensure_ascii=False, default=str) if ctx_parts else spec_text
    else:
        ctx_parts = {k: ctx.get(k) for k in consumes if ctx.get(k) is not None}
        result = json.dumps(ctx_parts, ensure_ascii=False, default=str) if ctx_parts else spec_text

    # 反馈环路: 在 test 阶段注入 coverage gap 建议
    role = getattr(agent, 'role', '')
    if role == "test" and ctx.get("_supplement_cases"):
        gaps = ctx.get("_coverage_gaps", {})
        fb_round = ctx.get("_feedback_round", 1)
        supplement_input = json.dumps({
            "action": "supplement_cases",
            "feedback_round": fb_round,
            "coverage_gaps": gaps,
            "instruction": "Coverage target not met. Generate additional test cases to fill the gaps below.",
            "previous_input": json.loads(result) if result else {},
        }, ensure_ascii=False, default=str)
        return supplement_input

    return result


class PipelineExecutionService:
    """流水线执行服务（单例）"""

    _instance: Optional[PipelineExecutionService] = None

    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = AgentRegistry.get_instance()
        self._initialized = False
        self._runs: Dict[str, dict] = {}  # run_id → {state, phases, results, ctx}

    @classmethod
    def get_instance(cls) -> PipelineExecutionService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Agent 生命周期 ──

    async def initialize_agents(self) -> None:
        """初始化所有 12 个 Agent（幂等）"""
        if self._initialized:
            return

        agents = [
            ("design",   DesignAgent()),
            ("model",    ModelAgent()),
            ("verify",   VerifyAgent()),
            ("ops",      OpsAgent()),
            ("coverage", CoverageAgent()),
            ("debug",    DebugAgent()),
            ("audit",    AuditAgent()),
        ]
        for role, agent in agents:
            await agent.initialize()
            self.registry.set_agent_instance(role, agent)

        self._initialized = True
        logger.info("All agents initialized via PipelineExecutionService")

    @property
    def initialized(self) -> bool:
        return self._initialized

    # ── 流水线执行 ──

    async def run_pipeline(
        self,
        spec_text: str,
        workflow: str = "full_verification",
        output_root: str | None = None,
        on_progress: callable = None,
        refine: bool = False,
        run_id: str | None = None,
        gate_enabled: bool = False,
        approval_gate = None,
        phase_timeout: int = 600,
        profile_name: str = "",
    ) -> dict:
        """[LEGACY 线性流水线] 执行验证流水线，返回 {run_id, phases, passed, total, ctx}

        新架构主路径是 run_closed_loop（七 Agent + 覆盖率驱动闭环）。
        本方法保留用于 vagent verify 的线性阶段（13 阶段 FULL_PHASES），
        支持阶段过滤/门禁/审批/profile，与闭环是两条并存路径。

        run_id 可由调用方预生成（Web API），或自动生成（CLI）。
        output_root 默认 None → 自动生成 output_{user}_{timestamp}。
        profile_name: 按 profile 过滤阶段（如 "spec_only" 只跑 spec）
        """
        output_root = make_output_root(output_root)
        if not self._initialized:
            await self.initialize_agents()

        if run_id is None:
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        phases = _WORKFLOW_PHASE_MAP.get(workflow, FULL_PHASES)

        # ── Profile 阶段过滤 ──
        if profile_name and profile_name in VERIFY_PROFILES:
            profile_phases = VERIFY_PROFILES[profile_name].get("phases")
            if profile_phases:
                phases = [p for p in phases if p[0] in profile_phases]

        # 初始化运行状态
        run_state = {
            "run_id": run_id,
            "workflow": workflow,
            "state": "running",
            "started_at": datetime.now().isoformat(),
            "current_phase": None,
            "phases": [],
            "ctx": ContextStore(),
        }
        # 初始化配置
        run_state["ctx"]["working_dir"] = str(Path(output_root).resolve())

        # ── 创建 docs 目录 ──
        docs_dir = Path(output_root) / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        # ── 持久化：创建运行记录 ──
        try:
            from src.database.repository import create_pipeline_run
            await create_pipeline_run(run_id, workflow, spec_text[:500], len(phases))
        except Exception:
            pass
        self._runs[run_id] = run_state

        ctx = run_state["ctx"]
        results = {}
        scores = {}  # per-agent scores

        # ── Harness: 快照 + 超时 + 中断恢复 ──
        from src.core.harness import Harness, HarnessTimeout, HarnessInterrupted
        _harness = Harness(output_root=str(output_root), base_timeout=phase_timeout)
        if run_state.get("resume_from"):
            _resume_info = _harness.resume_info()
            if _resume_info["can_resume"]:
                logger.info(f"Harness: resuming from phase '{_resume_info['last_phase']}'")
                run_state["resumed"] = True

        # ── 质量守护: 三层兜底 ──
        from src.core.quality_guard import QualityGuard, Verdict
        _guard = QualityGuard(approval_gate=approval_gate,
                              no_ask=(approval_gate is None or approval_gate.mode.value == "auto"))

        # ── 治理: Token 预算追踪 ──
        from src.core.llm_factory import LLMTracerCallback
        LLMTracerCallback.reset_budget()
        _token_budget = {"total_tokens": 0, "by_phase": {}, "limit": 200000,
                         "llm_calls": 0}

        # ── 审计: 阶段输入 hash 链 ──
        _input_hashes = {}
        import hashlib as _hashlib

        def _hash_ctx(key):
            val = ctx.get(key)
            if val is None:
                return ""
            return _hashlib.md5(json.dumps(val, sort_keys=True, default=str).encode()).hexdigest()[:8]

        # ── Log pipeline start ──
        try:
            from src.middleware.debug_logger import tracer
            tracer.pipeline_start(workflow, spec_text[:80], [p[0] for p in phases])
        except Exception: pass

        # ── 反馈环路: regress_cov → test (覆盖率不达标时回退补 case) ──
        _FEEDBACK_LOOP = {
            "trigger": "regress_cov",   # 哪个阶段触发回退
            "loop_to": "test",          # 回退到哪个阶段
            "max_rounds": 2,            # 最多几轮
        }
        _feedback_round = 0
        _phase_offsets = {p[0]: i for i, p in enumerate(phases)}  # phase name → index

        # ── 执行所有阶段 (test+assert 并行，其余保持依赖顺序) ──
        from src.core.step_executor import StepExecutor
        _PARALLEL_PAIRS = {("test", "assert")}
        _pi = 0
        while _pi < len(phases) and not run_state.get("halted"):
            p_tuple = phases[_pi]
            name, role, ctx_key = p_tuple[0], p_tuple[1], p_tuple[2]
            doc_only = p_tuple[3] if len(p_tuple) > 3 else False

            # ── 检测并行对 ──
            _next_tuple = phases[_pi + 1] if _pi + 1 < len(phases) else None
            _can_parallel = (
                _next_tuple is not None
                and not doc_only
                and not (_next_tuple[3] if len(_next_tuple) > 3 else False)
                and (name, _next_tuple[0]) in _PARALLEL_PAIRS
            )

            if _can_parallel:
                # ═══ 并行执行两个阶段 (独立 ctx 副本) ═══
                _next_name, _next_role = _next_tuple[0], _next_tuple[1]
                _agent_a = self.registry.get_agent_instance(role)
                _agent_b = self.registry.get_agent_instance(_next_role)

                if _agent_a and _agent_b:
                    _ctx_a = _make_ctx_copy(ctx)
                    _ctx_b = _make_ctx_copy(ctx)
                    _exec_a = StepExecutor(name, _agent_a, _ctx_a, output_root, on_progress)
                    _exec_b = StepExecutor(_next_name, _agent_b, _ctx_b, output_root, on_progress)
                    _input_a = _build_task_input(_agent_a, ctx, spec_text)
                    _input_b = _build_task_input(_agent_b, ctx, spec_text)

                    run_state["current_phase"] = f"{name}+{_next_name}"
                    _t0 = time.monotonic()
                    try:
                        from src.middleware.debug_logger import tracer
                        tracer.phase_start(f"{name}+{_next_name}",
                            f"{getattr(_agent_a,'display_name',role)}+{getattr(_agent_b,'display_name',_next_role)}")
                    except Exception: pass

                    _result_a, _result_b = await asyncio.gather(
                        _exec_a.execute(_input_a),
                        _exec_b.execute(_input_b),
                    )
                    _t1 = time.monotonic()
                    _p_time = round(_t1 - _t0, 1)

                    # 合并 produces 到主 ctx
                    for _ag, _res, _iso_ctx in [(_agent_a, _result_a, _ctx_a), (_agent_b, _result_b, _ctx_b)]:
                        _key = getattr(_ag, "produces", None)
                        if _key and _key in _iso_ctx._data:
                            ctx.put(_key, _iso_ctx[_key], source=getattr(_ag, 'role', 'unknown'))

                    # 记录两个阶段的结果
                    _halt_parallel = False
                    for _nm, _res in [(name, _result_a), (_next_name, _result_b)]:
                        results[_nm] = _res.status
                        scores[_nm] = _res.score
                        run_state["phases"].append({
                            "name": _nm, "status": _res.status, "time": _p_time,
                            "score": _res.score,
                            "input_hash": _input_hashes.get(_nm, ""),
                            "retries": _res.retries if _res.status != "skipped" else 0,
                            "started_at": datetime.fromtimestamp(_t0).isoformat(),
                            "ended_at": datetime.fromtimestamp(_t1).isoformat(),
                            "duration_ms": int((_t1 - _t0) * 1000),
                        })
                        try:
                            generate_phase_doc(_nm, ctx, str(docs_dir), run_state["phases"])
                        except Exception as _e:
                            logger.warning(f"Doc generation failed for phase {_nm}: {_e}")
                        try:
                            from src.middleware.debug_logger import tracer
                            tracer.phase_end(_nm, _res.status, _res.score, _p_time)
                        except Exception: pass

                        # 门禁检查 (--no-gate 时跳过)
                        _gate = _PHASE_GATES.get(_nm, 0)
                        if gate_enabled and _res.score < _gate and _nm not in ("docs", "vclose"):
                            _halt_msg = (
                                f"\n{'='*60}\n"
                                f"  GATE VIOLATION — Pipeline Halted\n"
                                f"  Phase: {_nm} | Score: {_res.score} | Threshold: {_gate}\n"
                                f"  Fix: re-run this phase or fix upstream inputs.\n"
                                f"{'='*60}\n"
                            )
                            print(_halt_msg)
                            logger.error("gate_violation", phase=_nm, score=_res.score, threshold=_gate)
                            run_state["halted"] = True
                            run_state["halt_phase"] = _nm
                            run_state["halt_reason"] = f"Phase '{_nm}' score {_res.score} < threshold {_gate}"
                            _halt_parallel = True
                            break

                    if _halt_parallel:
                        break
                    _pi += 2
                    continue
                _pi += 1
                continue

            # ═══ 单阶段串行执行 (原有逻辑) ═══
            if doc_only:
                if name == "docs":
                    # ═══ 并行生成 5 类文档 (ifspec/rtlsign/vplan/tpoint/rtm) ═══
                    _doc_types = ["ifspec", "rtlsign", "vplan", "tpoint", "rtm"]
                    _t0 = time.monotonic()
                    try:
                        from src.tools.doc_tools.pipeline_docs import generate_phase_doc
                        _tasks = [
                            asyncio.to_thread(generate_phase_doc, dt, ctx, str(docs_dir), run_state["phases"])
                            for dt in _doc_types
                        ]
                        await asyncio.gather(*_tasks)
                    except Exception as e:
                        logger.warning(f"Parallel doc generation failed: {e}")
                    _elapsed = round(time.monotonic() - _t0, 1)
                    run_state["phases"].append({
                        "name": name, "status": "passed", "time": _elapsed,
                        "score": 100, "retries": 0,
                        "docs_generated": _doc_types,
                    })
                else:
                    try:
                        from src.tools.doc_tools.pipeline_docs import generate_phase_doc
                        generate_phase_doc(name, ctx, str(docs_dir), run_state["phases"])
                    except Exception as e:
                        logger.warning(f"Doc generation failed for {name}: {e}")
                    run_state["phases"].append({
                        "name": name, "status": "passed", "time": 0,
                        "score": 100, "retries": 0,
                    })
                _pi += 1
                continue

            run_state["current_phase"] = name
            phase_started = time.monotonic()
            try:
                from src.middleware.debug_logger import tracer
                display = getattr(self.registry.get_agent_instance(role), 'display_name', role)
                tracer.phase_start(name, display)
            except Exception: pass

            agent = self.registry.get_agent_instance(role)
            if not agent:
                run_state["phases"].append({"name": name, "status": "skipped", "time": 0, "score": 0,
                                             "started_at": datetime.now().isoformat(), "ended_at": None, "duration_ms": 0})
                _pi += 1
                continue

            # ── 依赖检查 ──
            executor = StepExecutor(name, agent, ctx, output_root, on_progress)
            missing = executor.check_dependencies()
            if missing and role != "spec":
                print(f"\n  [PIPE] {name}: SKIPPED — missing={missing}  ctx_keys={list(ctx.keys())}")
                run_state["phases"].append({
                    "name": name, "status": "skipped", "time": 0, "score": 0,
                    "reason": f"missing inputs: {missing}",
                    "started_at": datetime.now().isoformat(), "ended_at": None, "duration_ms": 0,
                })
                _pi += 1
                continue

            # ── 审计: 记录输入 hash ──
            _consume_key = ""
            if agent.consumes:
                if isinstance(agent.consumes, list):
                    _consume_key = agent.consumes[0] if agent.consumes else ""
                elif isinstance(agent.consumes, dict):
                    _consume_key = next(iter(agent.consumes.keys()), "")
            _input_hash = _hash_ctx(_consume_key) if _consume_key else ""
            if _input_hash:
                _input_hashes[name] = _input_hash

            # ── 治理: 审批门控 (高风险阶段) ──
            _high_risk_phases = {"UVM", "regress_cov", "qa"}
            if approval_gate and name in _high_risk_phases:
                _summary = f"score≥{_PHASE_GATES.get(name,0)}, score={final_score}, hash={_input_hash}"
                _record = approval_gate.ask(name, _summary, risk_level="high")
                if _record.decision.value == "reject":
                    run_state["halted"] = True
                    run_state["halt_phase"] = name
                    run_state["halt_reason"] = f"用户审批拒绝 {name}"
                    break

            # ── Harness: 阶段前快照 ──
            _harness.snapshot(name, _pi, ctx, results, scores)

            # ── Harness: 中断检查 ──
            _interrupt = _harness.check_interrupt()
            if _interrupt == "abort":
                logger.warning(f"Harness: abort marker detected, stopping at {name}")
                run_state["halted"] = True
                run_state["halt_reason"] = "harness_abort_marker"
                break
            elif _interrupt == "pause":
                logger.info(f"Harness: pause marker detected at {name} — waiting for clear...")
                run_state["phases"].append({
                    "name": name, "status": "paused", "time": 0, "score": 0,
                    "reason": "human intervention — paused by .harness_pause marker"
                })

            # ── 字段级 task_input ──
            task_input = _build_task_input(agent, ctx, spec_text)

            # ── 使用 Harness 执行 (含超时 + 退避重试) ──
            try:
                step_result, attempt = await _harness.execute_with_retry(
                    executor.execute, task_input,
                    phase_name=name,
                    timeout=_harness.base_timeout,
                )
            except HarnessTimeout:
                final_status = "error"
                final_score = 0
                attempt = _harness.max_retries
                run_state["halted"] = True
                run_state["halt_reason"] = f"Phase '{name}' timed out"
                results[name] = final_status
                scores[name] = final_score
                break
            except HarnessInterrupted:
                final_status = "paused"
                final_score = 0
                results[name] = final_status
                scores[name] = final_score
                break
            final_status = step_result.status
            final_score = step_result.score

            # ── 三层兜底: 校验 → 回退 → 升级 ──
            _output_for_guard = ctx.get(ctx_key) if ctx_key else (step_result.ctx_diff if step_result.ctx_diff else {})
            _guarded, _guard_vr = _guard.guard(
                role, _output_for_guard if isinstance(_output_for_guard, dict) else {},
                ctx._data if hasattr(ctx, '_data') else (ctx if isinstance(ctx, dict) else {}),
                str(output_root)
            )
            if _guard_vr.verdict == Verdict.RETRY:
                final_status = "retrying"
                final_score = _guard_vr.score
            elif _guard_vr.verdict == Verdict.ABORT:
                run_state["halted"] = True
                run_state["halt_phase"] = name
                run_state["halt_reason"] = f"Quality guard abort: {_guard_vr.issues}"
                final_status = "error"
                final_score = _guard_vr.score
            elif _guard_vr.fallback_used:
                final_status = "degraded"
                final_score = _guard_vr.score
                # 用回退输出替换 ctx
                if ctx_key:
                    ctx.put(ctx_key, _guarded, source=f"{role}_fallback")

            results[name] = final_status
            scores[name] = final_score
            phase_ended = time.monotonic()
            phase_time = round(phase_ended - phase_started, 1)
            run_state["phases"].append({
                "name": name, "status": final_status, "time": phase_time,
                "score": final_score,
                "input_hash": _input_hashes.get(name, ""),
                "retries": attempt if final_status != "skipped" else 0,
                "started_at": datetime.fromtimestamp(phase_started).isoformat(),
                "ended_at": datetime.fromtimestamp(phase_ended).isoformat(),
                "duration_ms": int((phase_ended - phase_started) * 1000),
            })
            try:
                from src.middleware.debug_logger import tracer
                tracer.phase_end(name, final_status, final_score, phase_time)
            except Exception: pass

            # ── 门禁检查 (--no-gate 时跳过) ──
            gate = _PHASE_GATES.get(name, 0)
            if gate_enabled and final_score < gate and name not in ("docs", "vclose"):
                halt_msg = (
                    f"\n{'='*60}\n"
                    f"  GATE VIOLATION — Pipeline Halted\n"
                    f"  Phase: {name} | Score: {final_score} | Threshold: {gate}\n"
                    f"  Reason: quality below minimum, refusing to continue.\n"
                    f"  Fix: re-run this phase or fix upstream inputs.\n"
                    f"{'='*60}\n"
                )
                print(halt_msg)
                logger.error("gate_violation", phase=name, score=final_score, threshold=gate)
                run_state["halted"] = True
                run_state["halt_phase"] = name
                run_state["halt_reason"] = f"Phase '{name}' score {final_score} < threshold {gate}"
                break

            # ── 文本链阶段：存储输出数据 ──
            if ctx_key is None:
                for diff_key in step_result.ctx_diff:
                    if diff_key.startswith(f"_phase_"):
                        ctx[f"_phase_{name}"] = step_result.ctx_diff[diff_key]
                        break

            # ── 生成阶段 Markdown 文档 ──
            try:
                from src.tools.doc_tools.pipeline_docs import generate_phase_doc
                generate_phase_doc(name, ctx, str(docs_dir), run_state["phases"])
            except Exception as e:
                logger.warning(f"Doc generation failed for phase {name}: {e}")

            # ── ctx 清理 ──
            try:
                completed_roles = [p[1] for p in FULL_PHASES if p[0] in results]
                if hasattr(ctx, 'prune'):
                    ctx.prune(completed_roles)
            except Exception:
                pass

            # ── 决策层驱动: 覆盖率决策引擎决定下一步动作 ──
            if name == _FEEDBACK_LOOP["trigger"] and not run_state.get("halted"):
                _fb_should_loop = False
                _loop_to = None
                _action_reason = ""

                # 从 ctx 读取覆盖率数据
                coverage_data = ctx.get("coverage", {})
                reg_data = ctx.get("regression", {}) or {}
                debug_data = ctx.get("debug", {}) if isinstance(ctx.get("debug"), dict) else {}

                if isinstance(coverage_data, dict) and coverage_data:
                    overall = coverage_data.get("overall_pct", coverage_data.get("coverage_pct", 0))
                    if isinstance(overall, str):
                        try: overall = float(overall)
                        except ValueError: overall = 0

                    # 构造观测 → 决策引擎
                    try:
                        from src.core.decision_engine import CoverageDrivenDecisionEngine, Observation
                        _engine = CoverageDrivenDecisionEngine(target=95.0)
                        _obs = Observation(
                            iteration_id=_feedback_round,
                            coverage={"functional": overall, "overall_pct": overall},
                            uncovered_bins=gap_data.get("uncovered_bins", []) if isinstance(gap_data, dict) else [],
                            failed_tests=[t.get("name","") for t in reg_data.get("tests",[]) if t.get("status")=="FAIL"] if isinstance(reg_data, dict) else [],
                            dead_code_modules=[],
                            coverage_history=ctx.get("_coverage_history", []) + [overall],
                        )
                        _action = _engine.decide(_obs)
                        _action_reason = _action.reason
                        ctx["_coverage_history"] = _obs.coverage_history

                        # 动作 → 回退阶段映射
                        _action_to_phase = {
                            "GENERATE_DIRECTED_TEST": "test",
                            "EXPAND_SEEDS": "regress_cov",
                            "REFACTOR_RTL": "rtl",
                            "RETRY_ENV": "regress_cov",
                            "CONVERGE": None,  # 达标，不再回退
                        }
                        _loop_to = _action_to_phase.get(_action.action_type)
                        if _loop_to and _feedback_round < _FEEDBACK_LOOP["max_rounds"]:
                            _fb_should_loop = True
                            if _action.action_type == "REFACTOR_RTL":
                                ctx["_fix_request"] = {"fix_agent": "rtl", "suggestion": _action.reason}
                    except Exception as _de:
                        logger.warning(f"Decision engine failed: {_de}, fallback to simple coverage check")
                        if overall < 95 and _feedback_round < _FEEDBACK_LOOP["max_rounds"]:
                            _fb_should_loop = True
                            _loop_to = "test"

                if _fb_should_loop and _loop_to:
                    _feedback_round += 1
                    _loop_idx = _phase_offsets.get(_loop_to)

                    # 注入决策上下文
                    ctx["_feedback_round"] = _feedback_round
                    ctx["_coverage_gaps"] = gap_data
                    ctx["_supplement_cases"] = True
                    ctx["_decision_action"] = _action_reason

                    # 清理本轮产出，准备重跑
                    for _k in ["tests", "regression", "coverage"]:
                        if _k in results:
                            del results[_k]
                        if _k in scores:
                            del scores[_k]

                    logger.info(f"Decision engine: round {_feedback_round}/{_FEEDBACK_LOOP['max_rounds']}, "
                                f"action → '{_loop_to}': {_action_reason}",
                                coverage_pct=overall,
                                output_root=output_root)

                    run_state["phases"].append({
                        "name": "_decision",
                        "status": "looping",
                        "round": _feedback_round,
                        "loop_to": _loop_to,
                        "reason": _action_reason,
                    })

                    if _loop_idx is not None:
                        _pi = _loop_idx
                        continue

            _pi += 1

        passed = sum(1 for v in results.values() if v == "passed")
        degraded = sum(1 for v in results.values() if v == "degraded")
        failed = sum(1 for v in results.values() if v in ("failed", "error"))
        skipped = sum(1 for v in results.values() if v == "skipped")
        run_state["state"] = "completed" if passed + degraded == len(phases) else "completed_with_errors"
        run_state["passed"] = passed
        run_state["degraded"] = degraded
        run_state["failed"] = failed
        run_state["skipped"] = skipped
        run_state["completed_at"] = datetime.now().isoformat()
        run_state["passed"] = passed
        run_state["total"] = len(phases)

        # ── 反馈闭环：debug 分析 → 路由修复 → 精准重试 ──
        # 按 fix 类型只重跑受影响的智能体，不全量重跑
        MAX_FEEDBACK_LOOPS = 2
        iteration_count = 0
        for loop in range(MAX_FEEDBACK_LOOPS):
            iteration_count = loop + 1
            if on_progress:
                try: on_progress("ITER", "running", f"Feedback iteration {iteration_count}...")
                except Exception: pass
            debug_data = ctx.get("debug", {})
            if not isinstance(debug_data, dict) or debug_data.get("category") == "none":
                break

            fix_agent_role = debug_data.get("fix_agent", "")
            if not fix_agent_role:
                break

            role_to_phase = {
                "design": ("design", "design"),
                "uvm": ("UVM", "uvm"),
                "model": ("model", "model"),
                "spec": ("spec", "spec"),
                "rtl": ("rtl", "rtl"),
            }
            if fix_agent_role not in role_to_phase:
                break
            phase_name, agent_role = role_to_phase[fix_agent_role]

            agent = self.registry.get_agent_instance(agent_role)
            if not agent:
                break

            logger.info(f"[feedback loop {loop+1}] re-running {phase_name} to fix {fix_agent_role}")
            task = {"ctx": ctx,
                    "input": json.dumps({"fix": debug_data.get("suggestion", ""),
                                         "errors": debug_data.get("errors", [])[:3]},
                                        ensure_ascii=False),
                    "output_dir": output_root}
            try:
                r = await agent.execute_task(task)
                if r.success:
                    _writeback_produces(agent, r.data, ctx)

                    # ── 按 fix 类型决定重跑范围 ──
                    # 核心链 (始终重跑): regress + debug (验证修复效果)
                    # 扩展链: UVM + test (RTL/env 变更影响编译和测试)
                    # rtl 修复 → 重跑 UVM(重编译) + test(重生成) + regress
                    # env 修复 → 重跑 UVM + regress
                    _rerun_uvm = fix_agent_role in ("rtl", "uvm")
                    _rerun_test = fix_agent_role in ("spec", "design", "rtl")
                    _rerun_cover = False  # 覆盖率靠 regress 自动更新

                    # RTL/env 修复后重跑 UVM 重新编译
                    if _rerun_uvm:
                        uvm_agent = self.registry.get_agent_instance("uvm")
                        if uvm_agent:
                            ur = await uvm_agent.execute_task(
                                {"ctx": ctx,
                                 "input": json.dumps({"fix": True, "recompile": True}, ensure_ascii=False),
                                 "output_dir": output_root})
                            if ur.success:
                                _writeback_produces(uvm_agent, ur.data, ctx)

                    # Re-run regression_manager + debug_engineer (核心验证链)
                    reg_agent = self.registry.get_agent_instance("regress")
                    dbg_agent = self.registry.get_agent_instance("debug")
                    _regress_ok = False
                    if reg_agent:
                        rr = await reg_agent.execute_task(
                            {"ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if rr.success:
                            _writeback_produces(reg_agent, rr.data, ctx)
                            _regress_ok = True

                    if _regress_ok and dbg_agent:
                        dr = await dbg_agent.execute_task(
                            {"ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if dr.success:
                            _writeback_produces(dbg_agent, dr.data, ctx)

                    # 仅在 spec/design 变更时重跑 test
                    if _rerun_test:
                        test_agent = self.registry.get_agent_instance("test")
                        if test_agent:
                            tr = await test_agent.execute_task(
                                {"ctx": ctx,
                                 "input": json.dumps({"fix": True}, ensure_ascii=False),
                                 "output_dir": output_root})
                            if tr.success:
                                _writeback_produces(test_agent, tr.data, ctx)

                    logger.info(f"[feedback loop {loop+1}] fix applied, re-ran regress+debug"
                                + ("+test" if _rerun_test else ""))

                    # Re-check debug
                    new_debug = ctx.get("debug", {})
                    if isinstance(new_debug, dict) and new_debug.get("category") == "none":
                        logger.info(f"[feedback loop {loop+1}] all issues resolved!")
                        break
                else:
                    logger.warning(f"[feedback loop {loop+1}] fix agent {fix_agent_role} failed")
                    break
            except Exception as e:
                logger.error(f"[feedback loop {loop+1}] error: {e}")
                break

            # Re-check debug
            new_debug = ctx.get("debug", {})
            if isinstance(new_debug, dict) and new_debug.get("category") == "none":
                logger.info(f"[feedback loop {loop+1}] all issues resolved!")
                break

        # Recalculate passed
        passed = sum(1 for v in results.values() if v == "passed")
        run_state["passed"] = passed

        # 持久化：最终状态（含门禁 halt）
        if run_state.get("halted"):
            run_state["state"] = "halted_by_gate"
        elif passed == len(phases):
            run_state["state"] = "completed"
        else:
            run_state["state"] = "completed_with_errors"
        run_state["completed_at"] = datetime.now().isoformat()
        try:
            from src.database.repository import update_pipeline_run
            await update_pipeline_run(run_id,
                state=run_state["state"],
                phases_json=run_state["phases"],
                results=results,
                passed=passed,
                degraded=len(phases) - passed,
                total_time=sum(p.get("time", 0) for p in run_state["phases"]),
                completed_at=datetime.now(),
            )
        except Exception:
            pass  # DB 不可用时忽略

        # ── 聚合评分 ──
        active_agents = [p for p in run_state["phases"] if p["status"] != "skipped"]
        overall_score = int(sum(scores.get(p["name"], 0) for p in active_agents) / max(len(active_agents), 1))

        # ── Log pipeline end ──
        try:
            from src.middleware.debug_logger import tracer
            total_time = sum(p.get("time", 0) for p in run_state["phases"])
            tracer.pipeline_end(passed, len(phases), total_time, scores)
        except Exception: pass
        ctx["_scores"] = scores
        ctx["_overall_score"] = overall_score
        ctx["_iterations"] = iteration_count

        # ── 最终 flow.md 更新 ──
        try:
            update_flow_doc(run_state, ctx, str(docs_dir))
        except Exception as e:
            logger.warning(f"Final flow.md update failed: {e}")

        # ── 生成 Artifact Manifest (签核证据链) ──
        manifest_path = ""
        try:
            from src.core.manifest import ManifestBuilder
            from src.middleware.debug_logger import tracer
            session_id = getattr(tracer, 'session_id', run_id.replace('run_', ''))
            # 注入 run_type
            run_type = getattr(self, '_run_types', {}).get(run_id, 'traditional')
            ctx["_run_type"] = run_type
            builder = ManifestBuilder()
            manifest = builder.build(
                session_id=session_id,
                run_state={"run_id": run_id, "workflow": workflow,
                           "state": run_state["state"],
                           "started_at": run_state.get("started_at", ""),
                           "completed_at": run_state.get("completed_at", ""),
                           "passed": passed, "total": len(phases),
                           "ctx": ctx},
                phases=run_state["phases"],
                ctx=ctx,
                output_root=output_root,
            )
            manifest_json = builder.to_json(manifest)
            manifest_path = str(Path(output_root) / "docs" / "manifest.json")
            Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(manifest_path).write_text(manifest_json, encoding="utf-8")
            logger.info(f"Manifest saved: {manifest_path}")
        except Exception as e:
            logger.warning(f"Manifest generation failed: {e}")

        # ── 证据链收集 ──
        evidence_path = ""
        try:
            from src.core.evidence import collect_evidence
            chain = collect_evidence(run_id, output_root, ctx, run_state["phases"])
            evidence_json = json.dumps(chain.to_dict(), indent=2, ensure_ascii=False, default=str)
            evidence_path = str(Path(output_root) / "docs" / "evidence_chain.json")
            Path(evidence_path).parent.mkdir(parents=True, exist_ok=True)
            Path(evidence_path).write_text(evidence_json, encoding="utf-8")
            logger.info(f"Evidence chain saved: {evidence_path}")
        except Exception as e:
            logger.warning(f"Evidence collection failed: {e}")

        # ── 三层映射: 需求→模块→功能点→测试点 ──
        try:
            from src.core.design_mapper import DesignAgentMapper
            mapper = DesignAgentMapper()
            spec_data = ctx.get("spec", {}) if hasattr(ctx, 'get') else {}
            design_data = ctx.get("design_arch", {}) if hasattr(ctx, 'get') else {}

            # 从 spec + design 提取结构化数据
            spec_str = json.dumps(spec_data, default=str) if isinstance(spec_data, dict) else str(spec_data)
            design_str = json.dumps(design_data, default=str) if isinstance(design_data, dict) else str(design_data)
            combined_md = spec_str + "\n" + design_str

            modules = mapper.parse_md_modules(combined_md)
            # 从 spec 提取需求（VPlan 生成器，无 web 依赖）
            vp = None
            requirements = [{"id": r.id, "description": r.description}
                            for r in (vp.matrix.requirements.values() if vp and hasattr(vp, 'matrix') else [])]
            if not requirements and isinstance(spec_data, dict):
                features = spec_data.get("features", [])
                requirements = [{"id": f"REQ_AUTO_{i:03d}", "description": f.get("name", f.get("description", ""))}
                                for i, f in enumerate(features[:20])]

            mappings = mapper.match_req_to_features(requirements, modules)
            stored = await mapper.store(0, modules, mappings)
            logger.info(f"Design mapping stored: {stored}")
        except Exception as e:
            logger.warning(f"Design mapping failed: {e}")

        # ── 五大差异化引擎 ──
        try:
            from src.core.engines import VPlanGenerator, CoverageDrivenRegressor, DebugCopilot, RegressionTriage
            spec_str = json.dumps(ctx.get("spec", {}), default=str) if hasattr(ctx, 'get') else ""
            vplan_gen = VPlanGenerator(); vplan = vplan_gen.generate(spec_str)
            regressor = CoverageDrivenRegressor(ctx.get("coverage", {}) if hasattr(ctx, 'get') else {}, [{"name": tc.name, "level": tc.level} for tc in vplan.testcases]); smart_plan = regressor.select()
            copilot = DebugCopilot(); sim_logs = ""; [sim_logs := sim_logs + f.read_text(encoding="utf-8", errors="replace")[:50000] for f in Path(output_root).rglob("*.log") if f.exists()]; insights = copilot.analyze(sim_logs) if sim_logs else []
            triage = RegressionTriage(); failed_ps = [p for p in run_state["phases"] if p.get("status") in ("failed", "error")]; triage_result = triage.classify(failed_ps)
            engines = {"vplan":{"reqs":len(vplan.requirements),"cps":len(vplan.coverage_points),"tests":len(vplan.testcases),"risks":len(vplan.risk_items)},"smart_regression":{"selected":len(smart_plan.selected_tests),"skipped":len(smart_plan.skipped_tests),"time_saved_pct":smart_plan.time_saved_pct},"debug":{"insights":len(insights),"time_saved":copilot.time_saved_estimate(insights),"auto_fixable":sum(1 for i in insights if i.auto_fixable)},"triage":{"total":triage_result.total,"root_causes":triage_result.root_causes,"estimated_manual_time":triage_result.estimated_manual_time}}
            engines_path = str(Path(output_root) / "docs" / "engines.json"); Path(engines_path).parent.mkdir(parents=True, exist_ok=True); Path(engines_path).write_text(json.dumps(engines, indent=2, ensure_ascii=False, default=str), encoding="utf-8"); logger.info(f"Engines saved: {engines_path}")
        except Exception as e:
            logger.warning(f"Engines failed: {e}")

        # ── 收集 Token 用量 ──
        _token_budget["total_tokens"] = LLMTracerCallback.total_tokens_used
        _token_budget["llm_calls"] = LLMTracerCallback.call_count

        # ── 收集守护统计 ──
        _guard_report = _guard.report()

        # ── 治理摘要 ──
        _governance = {
            "approval_mode": approval_gate.mode.value if approval_gate else "auto",
            "approvals": approval_gate.summary() if approval_gate else {},
            "token_budget": _token_budget,
            "quality_guard": _guard_report,
            "harness": _harness.summary(),
            "input_hashes": _input_hashes,
            "gate_enabled": gate_enabled,
            "halted": run_state.get("halted", False),
            "halt_phase": run_state.get("halt_phase", ""),
            "halt_reason": run_state.get("halt_reason", ""),
        }
        run_state["governance"] = _governance
        run_state["output_root"] = str(output_root)
        run_state["overall_score"] = overall_score
        run_state["scores"] = scores

        return {
            "run_id": run_id,
            "workflow": workflow,
            "phases": run_state["phases"],
            "passed": passed,
            "total": len(phases),
            "scores": scores,
            "overall_score": overall_score,
            "governance": _governance,
            "ctx": ctx,
            "manifest_path": manifest_path,
            "evidence_path": evidence_path,
        }

    # ═══════════════════════════════════════════════════════════
    # 三层闭环架构: design → verify → regress → [decision] → report
    # ═══════════════════════════════════════════════════════════

    def _relax_transaction_constraints(self, output_root: str, gaps: list):
        """放宽约束：把被 constraint 型 gap 限制的信号约束放宽到全位宽范围。

        文本级修改 agents/*/*_transaction.sv 里的 `inside {[0:MAX]}` → 全范围，
        下一轮 coverage 重新编译仿真后，高位 toggle 不再是约束型缺口。
        """
        import re
        try:
            signals = {g.get("location", "").split("[")[0]
                       for g in gaps if isinstance(g, dict) and g.get("reason") == "constraint"}
            if not signals:
                return
            for tx_file in Path(output_root).glob("agents/*/*_transaction.sv"):
                text = tx_file.read_text(encoding="utf-8", errors="replace")
                widths = {}
                for m in re.finditer(r"rand\s+bit\s*\[(\d+):0\]\s+(\w+)\s*;", text):
                    widths[m.group(2)] = int(m.group(1)) + 1
                changed = False
                for sig in signals:
                    w = widths.get(sig)
                    if not w:
                        continue
                    full_max = (1 << w) - 1
                    pat = re.compile(r"(" + re.escape(sig) + r"\s+inside\s*\{\s*\[0:)\d+(\]\s*\})")
                    text, n = pat.subn(r"\g<1>" + str(full_max) + r"\g<2>", text)
                    if n > 0:
                        changed = True
                if changed:
                    tx_file.write_text(text, encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"放宽约束失败: {e}")

    @staticmethod
    def _escalate_to_human(reason: str, action_type: str) -> str:
        """升级人工：熔断/预算耗尽时，让人工决定 retry（复位熔断）/ abort（终止）。

        返回 "retry" 或 "abort"。
        """
        try:
            from src.core.quality_guard import EscalationConsole
            decision = EscalationConsole.ask(
                f"governor:{action_type}",
                [f"驾驭层拦截: {reason}"],
                {"action_type": action_type, "reason": reason},
            )
            # EscalationConsole 返回 retry/accept_fallback/skip/abort
            return decision if decision in ("retry", "abort") else "abort"
        except Exception:
            # 终端不可用（如 CI）→ 默认 abort（终止，人工后续介入）
            return "abort"

    def _record_agent_files(self, file_audit, role: str, data: dict, params: dict = None):
        """审计证据链：记录 Agent 产出的文件（git diff + 修改理由）。

        file_audit 作为参数传入（而非 self._file_audit），保证多模块流水并发时
        各模块证据链互不污染。
        """
        if file_audit is None:
            return
        # 从 data 里提取文件列表
        files = []
        reason = ""
        for key in ("design_arch", "model", "tests", "rtl", "regression"):
            if isinstance(data.get(key), dict):
                val = data[key]
                if isinstance(val.get("files"), list):
                    files.extend(val["files"])
                elif isinstance(val.get("written_files"), list):
                    files.extend(val["written_files"])
        # 参数里的 reason（如比对失败、死代码）
        if isinstance(params, dict):
            reason = params.get("reason", "")
        for fpath in files[:10]:  # 最多记录 10 个文件
            try:
                file_audit.record(str(fpath), reason or f"{role} 产出", role)
            except Exception:
                pass

    @staticmethod
    def _discover_excludes(exclude_reg, gaps: list, calibration: dict = None) -> int:
        """Exclude 四步闭环·第 1 步（自动发现）：结构性不可达覆盖点 → 提议放弃。

        归因分类（第 2 步）：coverage Agent 已在归因校准阶段把"多次 refactor 仍 0%"的
        unreachable 点筛入 `calibration.blacklisted_gaps`——这些点就是结构性死代码，
        直接提议 TYPE_UNREACHABLE。"规格不测/成本高"由工程师经 CLI 手动提议。
        返回本次提议数量。
        """
        try:
            from src.core.exclude_registry import TYPE_UNREACHABLE
            blacklisted = (calibration or {}).get("blacklisted_gaps", []) or []
            if not blacklisted:
                return 0
            existing = exclude_reg.get_all_points()
            proposed = 0
            for g in blacklisted:
                if not isinstance(g, dict):
                    continue
                dim = g.get("dimension", "")
                point = str(g.get("location") or g.get("signal") or dim or "unknown")
                if not point or point == "unknown" or point in existing:
                    continue
                exclude_reg.propose_exclude(
                    point,
                    reason=f"结构性死代码：{dim} 多次重构后覆盖率仍为 0%",
                    exclude_type=TYPE_UNREACHABLE,
                    evidence=f"unreachable 黑名单命中（dimension={dim}）",
                )
                existing.add(point)
                proposed += 1
            return proposed
        except Exception as e:
            logger.warning(f"Exclude 自动发现失败: {e}")
            return 0

    async def run_closed_loop(self, spec_text: str, output_root: str = "output",
                              target: Optional[float] = None, max_rounds: int = 5,
                              design_style: str = "baseline",
                              approval_gate=None) -> dict:
        """七 Agent 闭环：design → model → verify → ops → coverage → [decision] → audit。

        决策层驱动迭代（5 动作），覆盖率达标收敛。
        target: 覆盖率目标（None=从统一配置 Settings.verification.coverage_target 读，默认 95）。
        design_style: 设计风格（baseline/pipeline/low_power），驱动策略包加载。
        approval_gate: 审批门控（None=自动；传入则高风险动作前审批）。
        """
        # 解析输出目录一次（幂等），避免每个 Agent 各自追加时间戳 → 目录不一致
        output_root = make_output_root(output_root)
        # 统一覆盖率目标来源（消除散落硬编码 95）
        if target is None:
            from src.core.planning import get_coverage_target
            target = get_coverage_target()
        from src.core.decision_engine import CoverageDrivenDecisionEngine, Observation
        # 初始化审计证据链（独立实例 + 局部变量：多模块流水并发时各模块证据链互不污染）
        file_audit = None
        try:
            from src.core.file_audit import FileAuditTrail
            file_audit = FileAuditTrail(str(output_root))
        except Exception:
            pass

        if not self._initialized:
            await self.initialize_agents()

        ctx = {}
        phases = []
        coverage_history = []
        engine = CoverageDrivenDecisionEngine(target=target)

        # ── Planning 阶段：长周期任务规划（目标分解 + 里程碑 + 收敛预测）──
        from src.core.planning import CoveragePlanner
        planner = CoveragePlanner(target=target, start=0.0, max_rounds=max_rounds)
        phases.append({"name": "planning", "status": "planned",
                       "target": target, "milestones": planner.milestones})

        # ── L1 基础设施层：统一管理文件系统 / Git 仓库 / 覆盖率数据库 ──
        from src.core.infrastructure import InfrastructureManager
        infra = InfrastructureManager(output_root)
        infra.setup()

        # ── 驾驭层：统一预算 + 熔断 + 细粒度干预 + 决策可干预 ──
        from src.core.governor import Governor
        governor = Governor(output_root)

        # ── 用例状态库：场景分解 + 比例动态优化（数据驱动的用例管理）──
        # 跨 run 共享（用例 effectiveness / portfolio 权重跨 run 累积），放项目根 .signoffai/
        from src.core.testcase_registry import TestcaseRegistry
        testcase_reg = TestcaseRegistry()

        # ── Exclude 状态库：允许放弃（四步闭环：发现→归因→审计→调规）──
        # 跨 run 共享（审计哈希链跨 run 连续），放项目根 .signoffai/
        from src.core.exclude_registry import ExcludeRegistry
        exclude_reg = ExcludeRegistry()

        async def _run(role, label, params=None):
            """执行单个真实 Agent（execute_task）。"""
            t0 = __import__('time').time()
            agent = self.registry.get_agent_instance(role)
            if not agent:
                phases.append({"name": label, "status": "skipped", "score": 0})
                return {}
            task = {"ctx": ctx, "input": spec_text, "output_dir": output_root}
            if params:
                task["params"] = params
            try:
                result = await agent.execute_task(task)
                # 失败时也保留 data（含 regression 的 failed 详情），供回归门控决策
                data = result.data if isinstance(result.data, dict) else {}
                score = data.get("score", 0)
                status = "passed" if result.success else "failed"
                # 驾驭层：agent 执行成败反馈给 Governor（agent 级熔断，连续失败 → 升级人工）
                governor.after_action(role, success=result.success,
                                      eda=(1 if role in ("ops", "coverage") else 0))
                if not result.success:
                    logger.warning(f"agent '{role}' 执行失败，已反馈驾驭层（熔断计数 +1）")
            except Exception as e:
                logger.warning(f"{role} 执行失败: {e}")
                data, score, status = {}, 0, "error"
                governor.after_action(role, success=False,
                                      eda=(1 if role in ("ops", "coverage") else 0))
            ctx.update(data)
            phases.append({"name": label, "status": status, "score": score,
                           "time": round(__import__('time').time() - t0, 1)})

            # ── 审计证据链: 记录该 Agent 产出的文件（git diff + 理由）──
            self._record_agent_files(file_audit, role, data, params)
            return data

        # ── 顺序: design → model → verify ──
        await _run("design", "design")
        # 用例注册：design 之后 ctx["spec"] 就绪，用真实 design_name（而非硬编码 "dut"）
        try:
            _spec = ctx.get("spec", {}) if isinstance(ctx, dict) else {}
            if isinstance(_spec, dict):
                _module = _spec.get("design_name", "dut") or "dut"
                testcase_reg.register_from_spec(_spec, _module)
        except Exception:
            pass
        # SystemVerilog 参考模型（与 DUT 接口对齐，接入 env 做逐拍 compare）
        await _run("model", "model", {"model_type": "systemverilog"})
        await _run("verify", "verify", {"design_style": design_style})

        # ── 闭环: ops → coverage → [decision] ──
        final_coverage = 0.0
        effective_coverage = 0.0          # Exclude 调规后的有效覆盖率（决策层按此判断）
        exclude_effect = {}               # 每轮有效覆盖率明细（excluded/effective_total/...）
        compile_retries = 0
        iterations = 0
        seed = 0  # 随机种子（EXPAND_SEEDS 时递增，扩种 → 覆盖率变化）
        coverage_db_history = []  # 铁律 2：每轮覆盖率数据库版本固化记录
        prev_coverage = None       # 归因校准: 上一轮覆盖率
        last_action = None         # 归因校准: (action_type, reason, gap_reasons, unreachable_dims)
        for round_num in range(max_rounds):
            iterations += 1
            regress_data = await _run("ops", f"ops_r{round_num+1}", {"design_style": design_style})

            # 统一从 data["regression"] 取回归数据（ops 返回 {"regression": {...}}）
            regression = regress_data.get("regression", {}) \
                if isinstance(regress_data, dict) else {}

            # ── 编译失败检测（优先级最高，编译不过后面全废）──
            compile_error = None
            if isinstance(regression, dict) and regression.get("compile") == "FAIL":
                try:
                    from src.core.compile_healer import CompileErrorAnalyzer
                    # 分析编译错误
                    stderr = regression.get("stderr", regression.get("compile_errors", ""))
                    cr = CompileErrorAnalyzer.analyze(str(stderr))
                    compile_error = {
                        "error_type": cr.error_type.value,
                        "message": cr.error_message,
                        "file": cr.error_file,
                        "line": cr.error_line,
                    }
                except Exception as e:
                    logger.warning(f"编译错误分析失败: {e}")

            # ── 回归门控：功能回归（不收集覆盖率）全部 pass 才进入 coverage ──
            # 决策：功能不正确（回归有失败）→ 收集覆盖率无意义，跳过 coverage 进 debug 修复
            failed = regression.get("failed", 0) if isinstance(regression, dict) else 0
            _cov_params = {"seed": seed, "round_num": round_num + 1}
            if failed and not compile_error:
                logger.info(f"功能回归 {failed} 失败 → 跳过 coverage，进入 debug 修复")
                cov_data = {}
                await _run("debug", f"debug_r{round_num+1}")
            else:
                cov_data = await _run("coverage", f"coverage_r{round_num+1}", _cov_params)

            coverage = cov_data.get("coverage", {}) if isinstance(cov_data, dict) else {}
            gaps = cov_data.get("gaps", []) if isinstance(cov_data, dict) else []
            if isinstance(coverage, dict):
                final_coverage = coverage.get("overall_pct", coverage.get("coverage_pct", 0))
                if isinstance(final_coverage, str):
                    try: final_coverage = float(final_coverage)
                    except: final_coverage = 0.0
            # ── Exclude 四步闭环：自动发现 → 提议；已批准 → 有效覆盖率调规 ──
            coverage_map = cov_data.get("coverage_map", {}) if isinstance(cov_data, dict) else {}
            exclude_effect = {"excluded": 0, "effective_total": 0,
                              "effective_coverage": final_coverage}
            effective_coverage = final_coverage
            if isinstance(coverage_map, dict) and coverage_map.get("total"):
                calibration = cov_data.get("calibration", {}) if isinstance(cov_data, dict) else {}
                proposed = self._discover_excludes(exclude_reg, gaps, calibration)
                if proposed:
                    logger.info(f"Exclude 自动发现 {proposed} 处结构性不可达覆盖点，已提议（待审批）")
                exclude_effect = exclude_reg.effective_coverage_from_map(coverage_map)
                effective_coverage = exclude_effect.get("effective_coverage", final_coverage)
                if exclude_effect.get("excluded"):
                    logger.info(f"Exclude 调规：{exclude_effect['excluded']} 点已放弃，"
                                f"有效覆盖率 {effective_coverage}%（原始 {exclude_effect['raw_coverage']}%）")
            # ── 用例比例动态优化：覆盖率反馈 → 调 purpose 权重 → 影响下一轮优先级 ──
            try:
                _by_purpose = {
                    "functional": {"coverage": coverage.get("functional_pct", final_coverage),
                                   "sim_time": 0},
                    "protocol": {"coverage": coverage.get("branch_pct", 0), "sim_time": 0},
                    "corner": {"coverage": coverage.get("toggle_pct", 0), "sim_time": 0},
                }
                testcase_reg.optimize_portfolio({"by_purpose": _by_purpose}, round_num + 1)
            except Exception:
                pass
            # ── 归因校准: 上一轮决策动作的成效（delta 覆盖率为反馈信号）──
            if last_action is not None and prev_coverage is not None:
                try:
                    from src.core.coverage_experience import get_coverage_experience_store
                    get_coverage_experience_store().record_round(
                        round_num + 1, last_action[0], last_action[1], last_action[2],
                        prev_coverage, final_coverage, last_action[3])
                    # 驾驭层：动作成效反馈到熔断器（覆盖率提升=成功，停滞=失败）
                    governor.after_action(last_action[0], success=(final_coverage > prev_coverage))
                except Exception as _e:
                    logger.warning(f"归因校准记录失败: {_e}")
            prev_coverage = final_coverage

            # ── Planning：进度对比里程碑 + 收敛预测 ──
            progress = planner.check_progress(round_num + 1, final_coverage)
            forecast = planner.predict_convergence(coverage_history)
            if not progress["on_track"]:
                logger.info(f"进度落后里程碑: {progress['coverage']}% vs 里程碑 {progress['milestone']}%"
                            f"（差距 {progress['gap']}%）")

            # 铁律 2：记录本轮覆盖率数据库（ucdb 哈希）+ 降采样汇总文件路径
            # 原始证据（仿真 log + VCD 波形）也记录进证据链（供人工检查 + 签核追溯）
            import hashlib as _hashlib
            _log_path = cov_data.get("log_path", "") if isinstance(cov_data, dict) else ""
            _vcd_path = cov_data.get("vcd_path", "") if isinstance(cov_data, dict) else ""
            def _file_sha(p):
                try:
                    return _hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] if p and Path(p).exists() else ""
                except Exception:
                    return ""
            coverage_db_history.append({
                "round": round_num + 1,
                "coverage_db": cov_data.get("coverage_db", {}) if isinstance(cov_data, dict) else {},
                "coverage_summary": cov_data.get("coverage_summary", "") if isinstance(cov_data, dict) else "",
                "coverage": final_coverage,
                "log_path": _log_path,
                "log_sha256": _file_sha(_log_path),
                "vcd_path": _vcd_path,
                "vcd_sha256": _file_sha(_vcd_path),
            })
            # 覆盖率数据库归档已由 L1 统一完成（CoverageCollectTool → infra.collect_coverage），
            # 此处不再手动 archive，避免与子进程归档重复。

            # 决策：按"有效覆盖率"判断（已批准的 Exclude 点从分母剔除，不再追不可达死代码）
            # 功能回归失败 → failed_tests 非空 → 决策层走 RETRY_ENV（环境自愈/重试），而非盲目补覆盖率
            _failed_tests = [f"functional_regress_r{round_num+1}"] if (failed and not compile_error) else []
            obs = Observation(
                iteration_id=round_num,
                coverage={"functional": effective_coverage},
                gaps=gaps,
                failed_tests=_failed_tests,
                coverage_history=coverage_history + [effective_coverage],
                compile_error=compile_error,
            )
            coverage_history.append(final_coverage)
            action = engine.decide(obs)

            # ── 驾驭层：熔断 / 预算 / 干预 / 决策可干预 ──
            govern = governor.before_action(action.action_type)
            if not govern.allowed:
                if (govern.intervention
                        and govern.intervention.get("cmd") == "override_action"
                        and govern.intervention.get("action_type")):
                    # 人工 override：接管决策，强制指定动作
                    from src.core.decision_engine import Action
                    action = Action(
                        action_type=govern.intervention["action_type"],
                        params={}, priority="HIGH",
                        reason=f"人工 override: {govern.reason}")
                    governor.intervention.clear()
                else:
                    # 熔断 / 预算耗尽 → 升级人工（人机协作，而非直接终止）
                    phases.append({"name": "governor", "status": "blocked",
                                   "reason": govern.reason})
                    logger.warning(f"驾驭层拦截: {govern.reason}")
                    decision = self._escalate_to_human(govern.reason, action.action_type)
                    if decision == "retry":
                        governor.breaker.reset(action.action_type)  # 人工放行，复位熔断
                        continue
                    else:
                        break  # abort / skip → 终止闭环

            # ── 审批门控：高风险动作（重构/改模型）前人工审批 ──
            if approval_gate and action.action_type in ("REFACTOR_RTL", "UPDATE_MODEL"):
                try:
                    from src.core.approval import ApprovalDecision
                    _decision = approval_gate.ask(action.action_type, action.reason,
                                                  risk_level="high")
                    if _decision == ApprovalDecision.REJECT:
                        phases.append({"name": "approval", "status": "rejected",
                                       "action": action.action_type})
                        logger.warning(f"人工审批拒绝: {action.action_type}")
                        break
                    elif _decision == ApprovalDecision.SKIP:
                        phases.append({"name": "approval", "status": "skipped",
                                       "action": action.action_type})
                        continue
                except Exception as e:
                    logger.warning(f"审批检查失败: {e}")

            phases.append({"name": "decision", "status": "decision",
                           "action": action.action_type, "reason": action.reason})

            # ── 归因校准: 记住本轮动作（供下一轮记录成效）──
            _gap_reasons = [g.get("reason") for g in gaps
                            if isinstance(g, dict) and g.get("reason")]
            _unreachable_dims = [g.get("dimension") for g in gaps
                                 if isinstance(g, dict) and g.get("reason") == "unreachable"
                                 and g.get("dimension")]
            last_action = (action.action_type, action.reason, _gap_reasons, _unreachable_dims)

            if action.action_type == "CONVERGE":
                _excl_note = (f"（有效覆盖率 {effective_coverage}%，Exclude {exclude_effect.get('excluded', 0)} 点）"
                              if exclude_effect.get("excluded") else "")
                logger.info(f"闭环收敛: 覆盖率 {final_coverage}% ≥ {target}%{_excl_note}")
                # 覆盖率首次达标 → 保存黄金基线（golden.tar.gz）
                try:
                    from src.core.golden_baseline import save_golden_baseline
                    golden_path = save_golden_baseline(
                        Path(output_root), {"functional": final_coverage}, target)
                    if golden_path:
                        logger.info(f"黄金基线已保存: {golden_path}")
                        phases.append({"name": "golden_baseline", "status": "saved",
                                       "path": golden_path})
                except Exception as e:
                    logger.warning(f"黄金基线保存失败: {e}")
                # 基础设施：版本固化（git tag + 版本清单）
                try:
                    infra.write_version_manifest({
                        "final_coverage": final_coverage,
                        "effective_coverage": effective_coverage,
                        "exclude_effect": exclude_effect,
                        "target": target,
                        "iterations": iterations,
                    })
                    tag_name = f"signoff_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    tag_result = infra.git_tag(tag_name, f"coverage {final_coverage}%")
                    if tag_result.get("tagged"):
                        logger.info(f"版本已打 tag: {tag_name}")
                        phases.append({"name": "git_tag", "status": "tagged",
                                       "tag": tag_name})
                except Exception as e:
                    logger.warning(f"版本固化失败: {e}")
                break
            elif action.action_type == "COMPILE_RETRY":
                # 编译失败自愈
                compile_retries += 1
                from src.core.compile_healer import CompileSelfHealer
                healer = CompileSelfHealer(str(output_root))
                from src.core.compile_healer import CompileResult, CompileErrorType
                err = CompileResult(
                    success=False,
                    error_type=CompileErrorType(compile_error.get("error_type", "unknown")),
                    error_message=compile_error.get("message", ""),
                    error_file=compile_error.get("file"),
                    error_line=compile_error.get("line"),
                )
                heal = healer.heal(err)
                logger.info(f"编译自愈({compile_retries}): {'已修复' if heal['fixed'] else '需重试'} - {heal['actions'][:2]}")
                if compile_retries >= 3:
                    logger.error(f"编译失败 3 次仍未修复: {compile_error.get('message','')}")
                    break
            elif action.action_type == "REFACTOR_RTL":
                # 回归守卫：改设计前强制跑 golden 用例集，<100% 拒绝本次修改
                try:
                    from src.core.golden_baseline import GuardianAgent
                    guardian = GuardianAgent(Path(output_root))
                    check = await guardian.pre_refactor_check()
                    if not check.get("allowed", False):
                        logger.warning(f"回归守卫拒绝设计修改: {check.get('reason')}")
                        phases.append({"name": "guardian", "status": "rejected",
                                       "reason": check.get("reason")})
                        break  # 破坏性变更被守卫拦截，终止闭环
                except Exception as e:
                    logger.warning(f"回归守卫检查失败: {e}")
                # 被动触发: 设计重构 → 改 design + 自动更新 model
                await _run("design", "design_fix", {"fix_agent": "rtl"})
                logger.info("设计重构 → 被动通知 model 更新（版本 +1）")
                await _run("model", "model_update", {"action": "update",
                                                     "reason": action.reason})
            elif action.action_type == "UPDATE_MODEL":
                # 主动触发: 比对失败 → 更新参考模型
                logger.info(f"比对失败 → 主动更新 model: {action.reason}")
                await _run("model", "model_diagnose", {"action": "update",
                                                       "reason": action.reason})
            elif action.action_type == "GENERATE_DIRECTED_TEST":
                # 按 gap 生成定向激励（不再是空骨架）
                await _run("verify", "verify_supplement",
                           {"supplement": True, "gaps": action.params.get("gaps", [])})
            elif action.action_type == "RELAX_CONSTRAINT":
                # 放宽约束：文本级修改 transaction 约束，下一轮重新编译仿真
                self._relax_transaction_constraints(output_root, action.params.get("gaps", []))
                logger.info(f"放宽约束: {action.reason}")
            elif action.action_type == "EXPAND_SEEDS":
                # 扩种：递增随机种子，下一轮 coverage 用新种子 → 覆盖率变化
                seed += int(action.params.get("count", 100)) if isinstance(action.params, dict) else 100
                logger.info(f"扩种 → seed={seed}（覆盖率停滞，尝试新随机激励）")

        # ── 签核 ──
        await _run("audit", "audit")

        # ── 审计证据链: 落盘 + 完整性校验 ──
        evidence_path = ""
        manifest_path = ""
        chain_valid = False
        total_changes = 0
        if file_audit is not None:
            try:
                chain = file_audit.to_dict()
                chain["chain_valid"] = file_audit.verify()
                chain_valid = chain["chain_valid"]
                total_changes = chain.get("total_changes", 0)
                docs_dir = Path(output_root) / "docs"
                docs_dir.mkdir(parents=True, exist_ok=True)
                evidence_path = str(docs_dir / "evidence_chain.json")
                Path(evidence_path).write_text(
                    json.dumps(chain, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
            except Exception as e:
                logger.warning(f"证据链落盘失败: {e}")

        # ── Manifest: 运行清单（输入/输出/决策/证据摘要 + 覆盖率版本固化）──
        try:
            docs_dir = Path(output_root) / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            # 铁律 2：RTL 代码哈希（连同覆盖率数据库一起固化版本）
            import hashlib
            rtl_hashes = {}
            rtl_dir = Path(output_root) / "rtl"
            if rtl_dir.exists():
                for sv in sorted(rtl_dir.glob("*.sv")):
                    rtl_hashes[sv.name] = hashlib.sha256(
                        sv.read_bytes()).hexdigest()[:16]
            manifest = {
                "architecture": "closed_loop_7agents",
                "target": target,
                "final_coverage": final_coverage,
                "effective_coverage": effective_coverage,
                "converged": effective_coverage >= target,
                "iterations": iterations,
                "phases": phases,
                "planning": {
                    "target": planner.target,
                    "milestones": planner.milestones,
                    "convergence_forecast": planner.predict_convergence(coverage_history),
                },
                "testcase_portfolio": testcase_reg.get_portfolio(),
                "testcase_stats": testcase_reg.get_stats(),
                "exclude": {
                    "stats": exclude_reg.stats(),
                    "effect": exclude_effect,
                    "approved_points": sorted(exclude_reg.get_excluded_points()),
                },
                "rtl_hashes": rtl_hashes,
                "coverage_db_history": coverage_db_history,
                "evidence": {
                    "total_changes": total_changes,
                    "chain_valid": chain_valid,
                    "evidence_path": evidence_path,
                },
            }
            manifest_path = str(docs_dir / "manifest.json")
            Path(manifest_path).write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")
        except Exception as e:
            logger.warning(f"Manifest 落盘失败: {e}")

        # 汇总 Exclude 状态后释放 sqlite 连接（Windows 文件锁：跨 run 持久数据读完及时 close）
        exclude_stats = exclude_reg.stats()
        try:
            exclude_reg.close()
        except Exception:
            pass

        return {
            "architecture": "closed_loop_7agents",
            "output_root": str(output_root),
            "phases": phases,
            "final_coverage": final_coverage,
            "effective_coverage": effective_coverage,
            "converged": effective_coverage >= target,
            "target": target,
            "iterations": iterations,
            "exclude": {"stats": exclude_stats, "effect": exclude_effect},
            "status": "CONVERGED" if effective_coverage >= target else "COMPLETED",
            "evidence": {
                "total_changes": total_changes,
                "chain_valid": chain_valid,
                "evidence_path": evidence_path,
                "manifest_path": manifest_path,
            },
        }

    async def run_multi_module(self, module_specs: List[dict], output_root: str = "output",
                               target: Optional[float] = None, max_rounds: int = 5,
                               design_style: str = "baseline", max_concurrency: int = 4,
                               approval_gate=None) -> List[dict]:
        """多模块软件流水：并发跑多个闭环，EDA 等待期间互相推进（不阻塞）。

        与"多 DUT"的区别：这里的"多模块"是多个验证任务/规格的流水并行——
        模块 A 在 EDA 编译仿真（to_thread 线程里）时，模块 B 的 LLM 生成
        （design/model/verify）在事件循环里继续推进，不空转、不完全阻塞。

        module_specs: [{"name", "spec_file"|"spec_text", "target"?, "max_rounds"?, "design_style"?}, ...]
        每个模块独立 output_root/<name> + 独立证据链（FileAuditTrail 实例隔离，见 run_closed_loop）。

        返回与输入同序的结果列表（单个模块异常以 Exception 形式留在结果里）。
        """
        from src.core.pipeline_scheduler import PipelineScheduler
        from src.core.output_config import make_output_root

        # 先确保 agent 初始化（避免多任务并发时重复初始化竞态）
        if not self._initialized:
            await self.initialize_agents()

        base_root = make_output_root(output_root)
        sched = PipelineScheduler(max_concurrency=max_concurrency)

        def _make_task(m: dict, idx: int):
            name = (m.get("name") or f"module_{idx + 1}").replace("/", "_").replace("\\", "_")
            spec = m.get("spec_text", "")
            if not spec and m.get("spec_file"):
                try:
                    spec = Path(m["spec_file"]).read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    spec = ""
                    logger.warning(f"模块 {name} spec 读取失败: {e}")
            # 每个模块独立带时间戳子目录（make_output_root 幂等，互不冲突）
            sub_root = make_output_root(str(Path(base_root) / name))

            async def _run():
                return await self.run_closed_loop(
                    spec_text=spec, output_root=sub_root,
                    target=m.get("target", target),
                    max_rounds=m.get("max_rounds", max_rounds),
                    design_style=m.get("design_style", design_style),
                    approval_gate=approval_gate,
                )
            return _run

        tasks = [_make_task(m, i) for i, m in enumerate(module_specs)]
        return await sched.waterfall(tasks)

    # ── 运行状态查询 ──

    def get_run_status(self, run_id: str) -> Optional[dict]:
        """获取运行状态（供 SSE 轮询 / 前端查询）。优先内存，其次 DB。"""
        run = self._runs.get(run_id)
        if not run:
            return None
        return {
            "run_id": run["run_id"],
            "state": run["state"],
            "current_phase": run["current_phase"],
            "phases": run["phases"],
            "passed": run.get("passed", 0),
            "total": run.get("total", 0),
            "overall_score": run.get("overall_score", 0),
            "scores": run.get("scores", {}),
            "governance": run.get("governance", {}),
            "output_root": run.get("output_root", ""),
            "started_at": run.get("started_at", ""),
            "completed_at": run.get("completed_at", ""),
        }

    def list_runs(self) -> List[dict]:
        """列出所有运行"""
        return [
            {"run_id": r["run_id"], "workflow": r["workflow"],
             "state": r["state"], "started_at": r["started_at"]}
            for r in self._runs.values()
        ]

    # ── 单 Agent 执行 ──

    async def run_single_agent(
        self, role: str, input_text: str
    ) -> dict:
        """执行单个 Agent，返回 {success, output, error}"""
        if not self._initialized:
            await self.initialize_agents()

        agent = self.registry.get_agent_instance(role)
        if not agent:
            return {"success": False, "error": f"Agent not found: {role}"}

        task = {"ctx": {}, "input": input_text}
        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "output": r.data.get("output", "") if r.data else "",
            "error": r.error,
        }

    # ── 测试用例生成 ──

    async def generate_testcases(
        self, spec_text: str, output_dir: str = "output/testcases"
    ) -> dict:
        """运行 test_engineer Agent 生成测试用例"""
        if not self._initialized:
            await self.initialize_agents()

        ctx = {
            "spec": {"test_points": []},
            "env": {"env_name": "dut_env"},
        }

        agent = self.registry.get_agent_instance("test")
        if not agent:
            return {"success": False, "error": "test_engineer not found"}

        task = {
            "ctx": ctx,
            "input": json.dumps({
                "test_points": [],
                "env": ctx["env"],
            }),
            "output_dir": output_dir,
        }

        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "tests": r.data.get("tests", {}),
            "output": r.data.get("output", ""),
            "error": r.error,
        }
