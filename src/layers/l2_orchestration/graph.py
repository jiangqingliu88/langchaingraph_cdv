"""闭环流水线的 StateGraph 实现 —— 取代 run_closed_loop 的命令式控制流。

为什么要有这个文件
    原来是 626 行的单个 async 函数：阶段顺序靠语句顺序表达、动作分流靠 if/elif、
    循环靠 for-range、continue/break 混在语句中间。结果是「下一步做什么」无法
    单独测试，也无法回答「这条边为什么存在」。

    这里把同一套控制流显式成节点 + 条件边，行为保持等价。

两条设计约束（都是被真实故障逼出来的）
    1. 绝大多数边承载的是**控制**而非数据。原 ctx 在循环里只被读两次（都是 spec），
       真实数据流是 _run() 的返回值。所以图主要是「语句顺序的再编码」。
    2. **ctx 输入侧必须重建**。agent 读 task["ctx"]，若给空 dict，每个 agent 都会
       静默退化到启发式分支——不报错，只是行为悄悄变了。见 _rebuild_ctx()。

与 checkpointer 的关系
    状态里只放可字节复现的东西；活连接 / agent 实例 / LLM 客户端一律走
    Runtime（config["configurable"]["rt"]），由 init 节点重建。
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from langgraph.graph import END, START, StateGraph

from src.layers.l2_orchestration.state import PipelineState
from src.layers.l3_decision.decision_engine import (
    Action, CoverageDrivenDecisionEngine, Observation,
)

logger = structlog.get_logger()

# 递归上限：LangGraph 数的是 superstep 而不是轮次，一轮约 6-10 步。
_RECURSION_BASE = 20
_RECURSION_PER_ROUND = 12


# ═══════════════════════════════════════════════════════════════
# Runtime —— 不进状态的运行期对象
# ═══════════════════════════════════════════════════════════════

class Runtime:
    """节点需要、但不能进状态的东西。

    判据：序列化不可字节复现的一律留在这里。活 sqlite 连接、LLM 客户端、
    agent 实例、文件句柄放进去，checkpoint 就存不下来，--resume 也就无从谈起。
    """

    def __init__(self, service, spec_text: str, approval_gate=None,
                 interrupt_mode: bool = False):
        self.service = service
        self.spec_text = spec_text
        self.approval_gate = approval_gate
        #: True = 审批走 `interrupt()`：停下来落检查点，可以关掉进程过后来答。
        #: False = 审批走 `ApprovalGate` 的通道（终端问一句 / 界面弹框等待）。
        #: 由调用方按"这次运行有没有检查点"决定 —— 没有检查点就 interrupt 不了。
        self.interrupt_mode = interrupt_mode

        self.registry = service.registry
        self.engine: Optional[CoverageDrivenDecisionEngine] = None
        self.planner = None
        self.infra = None
        self.governor = None
        self.testcase_reg = None
        self.exclude_reg = None
        self.decision_reactor = None
        self.file_audit = None
        self.tool_auditor = None

        # 跨轮记忆（原本是局部变量 prev_coverage / last_action）
        self.prev_coverage: Optional[float] = None
        self.last_action = None
        # 跨 run 成长：L5 蒸馏出的动作权重（init 节点载入）
        self.distilled_weights: Dict[str, float] = {}


def _rt(config) -> Runtime:
    return config["configurable"]["rt"]


def _rebuild_ctx(state: PipelineState) -> Dict[str, Any]:
    """把状态投影回 agent 期望的 ctx dict。

    **图化最危险的一处**。agent 读 task["ctx"]（base.py 的 ctx_key 启发式、
    verify 读 spec 等）；如果这里给空 dict，agent 不会报错，只会静默走另一条
    分支。原 _run 传的是累积 ctx（所有 agent 写过的键都在），故这里做全量投影。

    刻意排除决策相关字段：它们不是 agent 的输入，混进去只会让 agent 看到
    自己不该看到的东西。
    """
    d = state.model_dump()
    for k in ("pending_action", "last_action", "decision_log",
              "governance_outcome", "approval_outcome", "guardian_verdict",
              "human_escalation", "terminal_reason"):
        d.pop(k, None)
    # output_root 用字符串，保持与既有 agent 一致
    d["output_dir"] = d.get("output_root", "")
    return d


def _as_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def _run_agent(rt: Runtime, state: PipelineState, role: str, label: str,
                     params: Dict[str, Any] = None) -> tuple:
    """执行单个 agent，返回 (data, phase_entry)。等价于原 _run 闭包。"""
    t0 = time.time()
    agent = rt.registry.get_agent_instance(role)
    if not agent:
        return {}, {"name": label, "status": "skipped", "score": 0}

    task = {"ctx": _rebuild_ctx(state), "input": rt.spec_text,
            "output_dir": state.output_root}
    if params:
        task["params"] = params

    _eda = 1 if role in ("ops", "coverage") else 0
    try:
        result = await agent.execute_task(task)
        # 失败时也保留 data（含 regression 的 failed 详情），供回归门控决策
        data = result.data if isinstance(result.data, dict) else {}
        score = data.get("score", 0)
        status = "passed" if result.success else "failed"
        rt.governor.after_action(role, success=result.success, eda=_eda)
        if not result.success:
            logger.warning(f"agent '{role}' 执行失败，已反馈驾驭层（熔断计数 +1）")
    except Exception as e:
        logger.warning(f"{role} 执行失败: {e}")
        data, score, status = {}, 0, "error"
        rt.governor.after_action(role, success=False, eda=_eda)

    # 审计证据链：记录该 agent 产出的文件（git diff + 理由）
    rt.service._record_agent_files(rt.file_audit, role, data, params)
    return data, {"name": label, "status": status, "score": score,
                  "time": round(time.time() - t0, 1)}


# ═══════════════════════════════════════════════════════════════
# 节点
# ═══════════════════════════════════════════════════════════════

def hydrate_runtime(rt: "Runtime", state: PipelineState) -> None:
    """按状态把 Runtime 里那些**不可序列化**的对象造出来。

    为什么是独立函数而不是留在 `n_init` 里：接上检查点之后，一次被中断的运行可以
    在**另一个进程**里续跑。那时 LangGraph 从检查点恢复，`n_init` **不会再执行**
    —— 而它建的那些东西（决策引擎、规划器、基础设施、治理器、两个注册表、
    审计链）后面每个节点都要用。少了它们不是"退化"，是 AttributeError。

    所以这里定义的是「Runtime 的构造契约」：给定 `state` 与 `rt.service`，
    运行期对象必须能被完整重建。`n_init` 调它，重入路径也调它 —— 一份实现，
    两处调用，不会漂移。
    """
    rt.engine = CoverageDrivenDecisionEngine(target=state.target)

    # 跨 run 成长（L5 蒸馏）：把已固化的动作权重读进本次 run。
    # 此前 DistillationOrchestrator.get_live_weights() 只有 CLI 展示会调用，
    # 主循环从不读取——蒸馏结果等于白学。
    try:
        from src.layers.l5_evolution.distillation import DistillationOrchestrator
        rt.distilled_weights = DistillationOrchestrator(state.output_root)\
            .get_live_weights() or {}
        if rt.distilled_weights:
            logger.info(f"载入 {len(rt.distilled_weights)} 条蒸馏动作权重（跨 run 成长生效）")
    except Exception as e:
        rt.distilled_weights = {}
        logger.warning(f"蒸馏权重载入失败（不影响闭环）: {e}")

    # Event Bus：KG 世界模型 + L3 决策 reactor
    try:
        from src.layers.l2_orchestration.communication.verification_events import (
            register_decision_reactor, register_verification_handlers)
        register_verification_handlers()
        _rl_path = str(Path.cwd() / ".signoffai" / "rl_policy.json")
        rt.decision_reactor = register_decision_reactor(
            target=state.target, rl_json_path=_rl_path,
            distilled_weights=rt.distilled_weights)
    except Exception:
        rt.decision_reactor = None

    from src.layers.l2_orchestration.planning import CoveragePlanner
    rt.planner = CoveragePlanner(target=state.target, start=0.0,
                                 max_rounds=state.max_rounds)

    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    rt.infra = InfrastructureManager(state.output_root)
    rt.infra.setup()

    from src.layers.l2_orchestration.governance.governor import Governor
    rt.governor = Governor(state.output_root)

    # 跨 run 共享的状态库（项目根 .signoffai/）
    from src.layers.l4_memory.testcase_registry import TestcaseRegistry
    rt.testcase_reg = TestcaseRegistry()
    from src.layers.l4_memory.exclude_registry import ExcludeRegistry
    rt.exclude_reg = ExcludeRegistry()

    # 工具回执落盘（ADR-3）：每条工具调用同时写 <output>/docs/tool_receipts.jsonl
    try:
        from src.layers.l2_orchestration.communication.tool_protocol import ToolAuditor
        rt.tool_auditor = ToolAuditor.with_receipts(state.output_root)
    except Exception:
        rt.tool_auditor = None

    # 独立文件审计链（局部实例：多模块并发时各模块证据链互不污染）
    try:
        from src.layers.l2_orchestration.evidence.file_audit import FileAuditTrail
        rt.file_audit = FileAuditTrail(str(state.output_root))
    except Exception:
        rt.file_audit = None


async def n_init(state: PipelineState, config) -> Dict[str, Any]:
    """重建所有运行期对象 —— 直接跑时的入口（重入时走 `hydrate_runtime`）。"""
    rt = _rt(config)
    hydrate_runtime(rt, state)
    return {"phases": [{"name": "planning", "status": "planned",
                        "target": state.target,
                        "milestones": rt.planner.milestones}]}


async def n_design(state: PipelineState, config) -> Dict[str, Any]:
    """design（或 bypass 模式下从 spec 直接解析）。"""
    rt = _rt(config)
    if state.bypass_design_model:
        logger.info("验证专注模式：bypass design/model，直接进入 verify（预置 RTL + 黄金模型）")
        spec, arch = {}, {}
        try:
            from src.tools.spec_tools.main import analyze_specification
            _raw = analyze_specification(rt.spec_text)
            spec = (json.loads(_raw)
                    if isinstance(_raw, str) and _raw.strip().startswith("{") else {})
            if not isinstance(spec, dict) or not spec.get("design_name"):
                spec = {"design_name": "dut"}
            _module = spec.get("design_name", "dut") or "dut"
            arch = {"module_name": _module,
                    "interfaces": spec.get("interfaces", []),
                    "registers": spec.get("registers", []),
                    "function_hier": {"children": []}}
            rt.testcase_reg.register_from_spec(spec, _module)
        except Exception as e:
            logger.warning(f"验证专注模式 spec 解析失败（回退最小 spec）: {e}")
            spec = {"design_name": "dut"}
            arch = {"module_name": "dut", "interfaces": [],
                    "registers": [], "function_hier": {"children": []}}
        return {"spec": spec, "design_arch": arch,
                "phases": [{"name": "design", "status": "skipped", "score": 0},
                           {"name": "model", "status": "skipped", "score": 0}]}

    data, phase = await _run_agent(rt, state, "design", "design")
    # 用例注册：design 之后 spec 就绪，用真实 design_name（而非硬编码 "dut"）
    try:
        _spec = data.get("spec", {})
        if isinstance(_spec, dict):
            rt.testcase_reg.register_from_spec(_spec, _spec.get("design_name", "dut") or "dut")
    except Exception:
        pass

    updates: Dict[str, Any] = {"phases": [phase]}
    # 沿用原语义：失败时保留旧值，不被 None 覆盖
    if isinstance(data.get("spec"), dict):
        updates["spec"] = data["spec"]
    if isinstance(data.get("design_arch"), dict):
        updates["design_arch"] = data["design_arch"]
    return updates


async def n_model(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    # bypass 模式下 design/model 的 phase 已在 n_design 追加，这里直接跳过
    if state.bypass_design_model:
        return {}
    data, phase = await _run_agent(rt, state, "model", "model",
                                   {"model_type": "systemverilog"})
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("model"), dict):
        updates["model"] = data["model"]
    return updates


async def n_verify(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    data, phase = await _run_agent(rt, state, "verify", "verify",
                                   {"design_style": state.design_style})
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("tests"), dict):
        updates["tests"] = data["tests"]
    return updates


async def n_env_arch_check(state: PipelineState, config) -> Dict[str, Any]:
    """env 架构验收：端口归属（静态）+ scoreboard 定向 case（仿真）。

    完全自包含（只读写磁盘），因此不需要状态输入。
    """
    output_root = Path(state.output_root)
    phase = {"name": "env_arch_check", "status": "skipped", "score": 0}
    try:
        from src.tools.uvm_tools.tool_check_env_arch.main import check_env_arch as _check
        from src.tools.lib.filelist import build_filelist_for_tb

        _fl = output_root / "inputs" / "filelists" / "filelist.f"
        if not _fl.exists():
            _env_name = "dut_env"
            for _p in sorted((output_root / "env").glob("*_pkg.sv")):
                _env_name = _p.name.replace("_pkg.sv", "")
                break
            _adir = output_root / "agents"
            _agents = [{"name": d.name} for d in _adir.iterdir() if d.is_dir()] \
                if _adir.exists() else []
            build_filelist_for_tb(output_root, _agents, _env_name, "filelist.f")

        _arch = await asyncio.to_thread(_check, str(output_root))
        _po = _arch.get("port_ownership", {}) or {}
        _sb = _arch.get("scoreboard", {}) or {}
        _status = _arch.get("status", "FAIL")
        _ok = _status == "PASS"
        phase = {
            "name": "env_arch_check",
            "status": "passed" if _ok else ("error" if _status == "EDA_MISSING" else "failed"),
            "score": 100 if _ok else 0,
            "port_ownership": _po.get("status"),
            "scoreboard": _sb.get("status"),
            "reason": (str(_po.get("message", "")) + " | " + str(_sb.get("message", "")))[:240],
        }
        if not _ok:
            logger.warning(f"env 架构验收未通过: {phase['reason']}")
    except Exception as e:
        phase = {"name": "env_arch_check", "status": "error", "score": 0,
                 "reason": str(e)[:160]}
        logger.warning(f"env 架构验收执行失败: {e}")
    return {"phases": [phase]}


async def n_round_bump(state: PipelineState, config) -> Dict[str, Any]:
    """循环闩锁 —— 这就是原来的 `for round_num in range(max_rounds)`。

    round_num / iterations 用 operator.add，所以返回 1 即自增。
    终止不靠递归上限，由各 router 显式检查轮次（见 _have_rounds_left）。
    """
    return {"round_num": 1, "iterations": 1}


async def n_ops(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    # round_num 经 round_bump 后即为 1 基轮次（原 for-range 是 0 基），故直接用
    data, phase = await _run_agent(rt, state, "ops", f"ops_r{state.round_num}",
                                   {"design_style": state.design_style})
    regression = data.get("regression", {}) if isinstance(data, dict) else {}

    # ── EDA 缺失检测（优先级最高：环境问题不是代码问题，终止闭环）──
    if isinstance(regression, dict) and regression.get("eda_missing"):
        _err = str(regression.get("error", ""))[:200]
        logger.error(f"EDA 工具缺失，终止闭环（安装 QuestaSim 并加入 PATH 后重试）: {_err}")
        return {"regression": regression, "regression_failed_count": 0,
                "eda_blocked": True, "interrupted": True,
                "terminal_reason": "eda_missing",
                "phases": [phase, {"name": "eda_check", "status": "failed",
                                   "reason": f"EDA 工具缺失: {_err}"}]}

    # ── 编译失败检测 ──
    compile_error = None
    if isinstance(regression, dict) and regression.get("compile") == "FAIL":
        try:
            from src.layers.l1_infrastructure.compile_healer import CompileErrorAnalyzer
            stderr = regression.get("stderr", regression.get("compile_errors", ""))
            cr = CompileErrorAnalyzer.analyze(str(stderr))
            compile_error = {"error_type": cr.error_type.value,
                             "message": cr.error_message,
                             "file": cr.error_file, "line": cr.error_line}
        except Exception as e:
            logger.warning(f"编译错误分析失败: {e}")

    failed = regression.get("failed", 0) if isinstance(regression, dict) else 0
    return {"regression": regression, "regression_failed_count": failed,
            "compile_error": compile_error, "phases": [phase]}


async def n_coverage(state: PipelineState, config) -> Dict[str, Any]:
    """coverage 阶段 —— 原循环里最大的一块（含 Exclude 调规 / 用例配比 / 归因校准）。"""
    rt = _rt(config)
    svc = rt.service
    data, phase = await _run_agent(rt, state, "coverage",
                                   f"coverage_r{state.round_num}",
                                   {"seed": state.seed, "round_num": state.round_num})

    coverage = data.get("coverage", {}) if isinstance(data, dict) else {}
    gaps = data.get("gaps", []) if isinstance(data, dict) else []
    final_coverage = state.final_coverage
    if isinstance(coverage, dict):
        final_coverage = _as_float(coverage.get("overall_pct",
                                                coverage.get("coverage_pct", 0)))

    # ── Exclude 四步闭环：自动发现 → 提议；已批准 → 有效覆盖率调规 ──
    coverage_map = data.get("coverage_map", {}) if isinstance(data, dict) else {}
    exclude_effect = {"excluded": 0, "effective_total": 0,
                      "effective_coverage": final_coverage}
    effective_coverage = final_coverage
    if isinstance(coverage_map, dict) and coverage_map.get("total"):
        calibration = data.get("calibration", {}) if isinstance(data, dict) else {}
        proposed = svc._discover_excludes(rt.exclude_reg, gaps, calibration)
        if proposed:
            logger.info(f"Exclude 自动发现 {proposed} 处结构性不可达覆盖点，已提议（待审批）")
        exclude_effect = rt.exclude_reg.effective_coverage_from_map(coverage_map)
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
        rt.testcase_reg.optimize_portfolio({"by_purpose": _by_purpose},
                                           state.round_num)
    except Exception:
        pass

    # ── 归因校准：上一轮决策动作的成效（delta 覆盖率为反馈信号）──
    if rt.last_action is not None and rt.prev_coverage is not None:
        try:
            from src.layers.l4_memory.coverage_experience import get_coverage_experience_store
            get_coverage_experience_store().record_round(
                state.round_num, rt.last_action[0], rt.last_action[1],
                rt.last_action[2], rt.prev_coverage, final_coverage, rt.last_action[3])
            rt.governor.after_action(rt.last_action[0],
                                     success=(final_coverage > rt.prev_coverage))
        except Exception as e:
            logger.warning(f"归因校准记录失败: {e}")
    rt.prev_coverage = final_coverage

    # ── Planning：进度对比里程碑 ──
    progress = rt.planner.check_progress(state.round_num, final_coverage)
    if not progress["on_track"]:
        logger.info(f"进度落后里程碑: {progress['coverage']}% vs 里程碑 "
                    f"{progress['milestone']}%（差距 {progress['gap']}%）")

    # ── 铁律 2：覆盖率数据库版本固化记录 + 原始证据（log/VCD）哈希 ──
    from src.layers.l1_infrastructure.infrastructure import sha256_file
    _log_path = data.get("log_path", "") if isinstance(data, dict) else ""
    _vcd_path = data.get("vcd_path", "") if isinstance(data, dict) else ""
    db_entry = {
        "round": state.round_num,
        "coverage_db": data.get("coverage_db", {}) if isinstance(data, dict) else {},
        "coverage_summary": data.get("coverage_summary", "") if isinstance(data, dict) else "",
        "coverage": final_coverage,
        "log_path": _log_path, "log_sha256": sha256_file(_log_path)[:16],
        "vcd_path": _vcd_path, "vcd_sha256": sha256_file(_vcd_path)[:16],
    }

    return {
        "coverage": coverage if isinstance(coverage, dict) else {},
        "gaps": gaps if isinstance(gaps, list) else [],
        "coverage_map": coverage_map if isinstance(coverage_map, dict) else {},
        "calibration": data.get("calibration", {}) if isinstance(data, dict) else {},
        "coverage_db": data.get("coverage_db", {}) if isinstance(data, dict) else {},
        "coverage_summary": data.get("coverage_summary", "") if isinstance(data, dict) else "",
        "log_path": _log_path, "vcd_path": _vcd_path,
        "functional_coverage": coverage.get("functional_pct", final_coverage)
        if isinstance(coverage, dict) else final_coverage,
        "final_coverage": final_coverage,
        "effective_coverage": effective_coverage,
        "exclude_effect": exclude_effect,
        "coverage_db_history": [db_entry],
        "phases": [phase],
    }


async def n_debug_functional(state: PipelineState, config) -> Dict[str, Any]:
    """功能回归失败 → 跳过 coverage，进 debug 修复。"""
    rt = _rt(config)
    logger.info(f"功能回归 {state.regression_failed_count} 失败 → 跳过 coverage，进入 debug 修复")
    data, phase = await _run_agent(rt, state, "debug", f"debug_r{state.round_num}")
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("debug"), dict):
        updates["debug"] = data["debug"]
    return updates


async def n_decide(state: PipelineState, config) -> Dict[str, Any]:
    """构造 Observation → 语义增强 → 决策（规则引擎 / DecisionReactor）。"""
    rt = _rt(config)
    failed = state.regression_failed_count

    # 功能回归失败 → failed_tests 非空 → 决策层走 REFACTOR_RTL
    _failed_tests = ([f"functional_regress_r{state.round_num}"]
                     if (failed and not state.compile_error) else [])
    obs = Observation(
        iteration_id=state.round_num - 1,
        coverage={"functional": state.effective_coverage},
        gaps=state.gaps,
        failed_tests=_failed_tests,
        coverage_history=state.coverage_history + [state.effective_coverage],
        compile_error=state.compile_error,
    )

    # 语义化：用 Verification Knowledge Graph 补 gap_paths（精准归因）
    try:
        from src.layers.l3_decision.decision_engine import enrich_observation
        _spec = state.spec
        if not _spec:
            _sp = Path(state.output_root) / "spec.json"
            if _sp.exists():
                _spec = json.loads(_sp.read_text(encoding="utf-8"))
        if _spec:
            obs = await enrich_observation(obs, _spec)
    except Exception:
        pass

    # 事件驱动决策：发 COVERAGE_UPDATED → DecisionReactor → 读结果
    if rt.decision_reactor is not None:
        try:
            from src.layers.l2_orchestration.communication.verification_events import (
                publish_observation)
            await publish_observation(obs)
            action = rt.decision_reactor.last_action or rt.engine.decide(obs)
        except Exception:
            action = rt.engine.decide(obs)
    else:
        action = rt.engine.decide(obs)

    return {"pending_action": action.to_dict(),
            "coverage_history": [state.final_coverage]}


async def n_governor(state: PipelineState, config) -> Dict[str, Any]:
    """驾驭层：熔断 / 预算 / 干预。override 时改写动作，其余交由 router 决定。"""
    rt = _rt(config)
    action = state.action()
    govern = rt.governor.before_action(action.action_type)
    if govern.allowed:
        return {"governance_outcome": "proceed"}

    if (govern.intervention
            and govern.intervention.get("cmd") == "override_action"
            and govern.intervention.get("action_type")):
        override = Action(action_type=govern.intervention["action_type"], params={},
                          priority="HIGH", reason=f"人工 override: {govern.reason}")
        rt.governor.intervention.clear()
        return {"pending_action": override.to_dict(), "governance_outcome": "override"}

    logger.warning(f"驾驭层拦截: {govern.reason}")
    decision = rt.service._escalate_to_human(govern.reason, action.action_type)
    return {"governance_outcome": decision,   # retry / abort / 其它
            "human_escalation": decision,
            "phases": [{"name": "governor", "status": "blocked",
                        "reason": govern.reason}]}


def r_governor(state: PipelineState) -> str:
    """熔断后：override/proceed 继续；retry 回下一轮（continue）；其余终止（break）。"""
    outcome = state.governance_outcome
    if outcome in ("proceed", "override"):
        return "proceed"
    if outcome == "retry":
        # 人工放行 → 复位熔断，等价于原来的 continue
        return "retry"
    return "abort"


async def n_governor_retry(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    try:
        rt.governor.breaker.reset((state.action() or Action("")).action_type)
    except Exception:
        pass
    return {}


def _interrupt_approval(rt, action):
    """停下来等人批 —— 返回一个 `ApprovalRecord`（与通道模式同形）。

    `interrupt()` 的第一次调用会**抛出** `GraphInterrupt`，由 LangGraph 接住并
    把当前状态写进检查点；恢复时同一个 `interrupt()` 调用会**返回**传进来的
    resume 值。所以这个函数在两条时间线上各跑一次，代码却只有一份。

    传进去的 payload 要**自包含**：恢复的人（可能是另一个进程、另一台机器）
    手上只有检查点，看不到内存里的任何东西。
    """
    from langgraph.types import interrupt
    from src.layers.l2_orchestration.governance.approval import (
        ApprovalDecision, ApprovalRecord,
    )

    token = f"ap-{len(rt.approval_gate.records) + 1}" if rt.approval_gate else "ap-1"
    answer = interrupt({
        "kind": "approval",
        "stage": action.action_type,
        "risk_level": "high",
        "reason": action.reason,
        "token": token,
    })

    # 恢复后 answer 是 `Command(resume=...)` 传进来的那个值。
    # 认不出来的答案一律按 SKIP —— 与超时同一条规矩：**没人明确说"批"就不放行**。
    try:
        decision = ApprovalDecision(str(answer).strip().lower())
    except (ValueError, TypeError):
        decision = ApprovalDecision.SKIP

    record = ApprovalRecord(stage=action.action_type, decision=decision,
                            reason=f"人工审批（检查点重入）: {decision.value}",
                            token=token)
    if rt.approval_gate is not None:
        rt.approval_gate.records.append(record)
        rt.approval_gate._notify_decision(record)      # noqa: SLF001
    return record


async def n_approval(state: PipelineState, config) -> Dict[str, Any]:
    """高风险动作（重构/改模型）前人工审批。"""
    rt = _rt(config)
    action = state.action()
    if not rt.approval_gate or action.action_type not in ("REFACTOR_RTL", "UPDATE_MODEL"):
        return {"approval_outcome": "proceed"}
    try:
        from src.layers.l2_orchestration.governance.approval import ApprovalDecision
        if rt.interrupt_mode:
            # 有检查点 → 走 interrupt()：本节点**抛出**，图把状态存进检查点然后
            # 结束这次 astream。等人来答（可能是另一个进程、另一天），
            # 恢复时 interrupt() 直接**返回**答案，从这里往下继续。
            # 这才叫"暂停"—— 而通道模式的"阻塞等答案"其实一直占着一个线程。
            record = _interrupt_approval(rt, action)
        else:
            # **取 .decision**：ask() 返回的是 ApprovalRecord。此前这里直接拿 record
            # 与枚举比较，dataclass 的 __eq__ 对非同类返回 NotImplemented → 恒为 False，
            # 于是拒绝/跳过两条分支是死代码，「用户拒绝」根本不生效。
            record = rt.approval_gate.ask(action.action_type, action.reason,
                                          risk_level="high")
        _d = record.decision
        if _d == ApprovalDecision.REJECT:
            logger.warning(f"人工审批拒绝: {action.action_type}")
            return {"approval_outcome": "reject",
                    "phases": [{"name": "approval", "status": "rejected",
                                "action": action.action_type,
                                "token": record.token}]}
        if _d in (ApprovalDecision.SKIP, ApprovalDecision.REVIEW):
            # SKIP 与 REVIEW 对闭环的效果相同：本次不执行该动作、继续迭代。
            # 区别只在审计语义——REVIEW 表示「待人工线下复核」。
            _st = "skipped" if _d == ApprovalDecision.SKIP else "review"
            return {"approval_outcome": "skip",
                    "phases": [{"name": "approval", "status": _st,
                                "action": action.action_type,
                                "token": record.token}]}
        return {"approval_outcome": "proceed",
                "phases": [{"name": "approval", "status": "passed",
                            "action": action.action_type,
                            "token": record.token}]}
    except Exception as e:
        # fail-closed：审批**故障**不是"没人反对"。原先是 proceed（全放行），
        # 那意味着治理一坏就静默失去作用 —— 与"可治理"的定位直接冲突。
        # 现在的语义是「问不出来就不做这个动作」，闭环继续但跳过它。
        logger.warning(f"审批检查失败，按跳过处理: {e}")
        return {"approval_outcome": "skip",
                "phases": [{"name": "approval", "status": "error",
                            "action": action.action_type,
                            "error": str(e)[:200]}]}


def r_approval(state: PipelineState) -> str:
    o = state.approval_outcome
    if o == "reject":
        return "reject"
    if o == "skip":
        return "skip"
    return "proceed"


async def n_record_decision(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    action = state.action()
    # 记住本轮动作，供下一轮记录成效
    _gr = [g.get("reason") for g in state.gaps
           if isinstance(g, dict) and g.get("reason")]
    _ud = [g.get("dimension") for g in state.gaps
           if isinstance(g, dict) and g.get("reason") == "unreachable" and g.get("dimension")]
    rt.last_action = (action.action_type, action.reason, _gr, _ud)

    return {"last_action": action.to_dict(),
            "phases": [{"name": "decision", "status": "decision",
                        "action": action.action_type, "reason": action.reason}]}


def r_action(state: PipelineState) -> str:
    """8 动作分流。未映射的动作显式报错——原来 if/elif 没有 else，
    未映射的 action_type 会静默重开一轮。"""
    at = (state.action() or Action("")).action_type
    allowed = {"CONVERGE", "COMPILE_RETRY", "REFACTOR_RTL", "UPDATE_MODEL",
               "GENERATE_DIRECTED_TEST", "RELAX_CONSTRAINT", "EXPAND_SEEDS"}
    if at not in allowed:
        raise ValueError(
            f"决策层返回了未映射的动作 {at!r}；decision_engine 的动作全集见 "
            "ACTION_HANDLERS，新增动作必须同时补 execution 的分支"
        )
    return at


async def n_apply_converge(state: PipelineState, config) -> Dict[str, Any]:
    """达标收敛：保存黄金基线 + 版本固化（git tag + 清单），然后离开循环。"""
    rt = _rt(config)
    action = state.action()
    phases = []
    _excl = state.exclude_effect.get("excluded", 0)
    _note = (f"（有效覆盖率 {state.effective_coverage}%，Exclude {_excl} 点）"
             if _excl else "")
    logger.info(f"闭环收敛: 覆盖率 {state.final_coverage}% ≥ {state.target}%{_note}")

    try:
        from src.layers.l1_infrastructure.golden_baseline import save_golden_baseline
        golden = save_golden_baseline(Path(state.output_root),
                                     {"functional": state.final_coverage}, state.target)
        if golden:
            logger.info(f"黄金基线已保存: {golden}")
            phases.append({"name": "golden_baseline", "status": "saved", "path": golden})
    except Exception as e:
        logger.warning(f"黄金基线保存失败: {e}")

    try:
        rt.infra.write_version_manifest({
            "final_coverage": state.final_coverage,
            "effective_coverage": state.effective_coverage,
            "exclude_effect": state.exclude_effect,
            "target": state.target, "iterations": state.iterations,
        })
        tag = f"signoff_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tr = rt.infra.git_tag(tag, f"coverage {state.final_coverage}%")
        if tr.get("tagged"):
            logger.info(f"版本已打 tag: {tag}")
            phases.append({"name": "git_tag", "status": "tagged", "tag": tag})
    except Exception as e:
        logger.warning(f"版本固化失败: {e}")

    return {"interrupted": True, "terminal_reason": "converged", "phases": phases}


async def n_apply_compile_retry(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    retries = state.compile_retries + 1
    ce = state.compile_error or {}
    phases: List[Dict[str, Any]] = []

    from src.layers.l1_infrastructure.compile_healer import (
        CompileErrorType, CompileResult, CompileSelfHealer)
    healer = CompileSelfHealer(state.output_root)
    err = CompileResult(
        success=False,
        error_type=CompileErrorType(ce.get("error_type", "unknown")),
        error_message=ce.get("message", ""),
        error_file=ce.get("file"), error_line=ce.get("line"),
    )
    heal = healer.heal(err)
    if heal["fixed"]:
        logger.info(f"编译自愈({retries}) 确定性修复: {heal['actions'][:2]}")
        # 修复成功=进展，复位熔断（否则连败 3 次会把自愈误判成失败熔断）
        try:
            rt.governor.breaker.reset("COMPILE_RETRY")
        except Exception:
            pass
    else:
        logger.info(f"确定性修复失败 → 交给 debug agent 修复 {ce.get('file','')}")
        _, phase = await _run_agent(rt, state, "debug", f"debug_compile_r{retries}",
                                    {"compile_error": ce})
        phases.append(phase)

    out: Dict[str, Any] = {"compile_retries": 1, "phases": phases}
    if retries >= 10:
        logger.error(f"编译失败 10 次仍未修复: {ce.get('message','')}")
        out.update({"interrupted": True, "terminal_reason": "compile_retry_exhausted"})
    return out


def r_after_compile_retry(state: PipelineState) -> str:
    if state.interrupted:
        return "abort"
    return _round_or_abort(state)


async def n_refactor_rtl(state: PipelineState, config) -> Dict[str, Any]:
    """回归守卫 → 改 design + 被动更新 model。"""
    rt = _rt(config)
    action = state.action()
    phases: List[Dict[str, Any]] = []

    try:
        from src.layers.l1_infrastructure.golden_baseline import GuardianAgent
        guardian = GuardianAgent(Path(state.output_root))
        check = await guardian.pre_refactor_check()
        if not check.get("allowed", False):
            logger.warning(f"回归守卫拒绝设计修改: {check.get('reason')}")
            return {"guardian_verdict": {"allowed": False, "reason": check.get("reason")},
                    "interrupted": True, "terminal_reason": "guardian_rejected",
                    "phases": [{"name": "guardian", "status": "rejected",
                                "reason": check.get("reason")}]}
    except Exception as e:
        logger.warning(f"回归守卫检查失败: {e}")

    _, p1 = await _run_agent(rt, state, "design", "design_fix", {"fix_agent": "rtl"})
    phases.append(p1)
    logger.info("设计重构 → 被动通知 model 更新（版本 +1）")
    _, p2 = await _run_agent(rt, state, "model", "model_update",
                             {"action": "update", "reason": action.reason})
    phases.append(p2)
    return {"guardian_verdict": {"allowed": True}, "phases": phases}


def r_after_guardian(state: PipelineState) -> str:
    if state.interrupted:
        return "abort"
    return _round_or_abort(state)


async def n_apply_update_model(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    action = state.action()
    logger.info(f"比对失败 → 主动更新 model: {action.reason}")
    _, phase = await _run_agent(rt, state, "model", "model_diagnose",
                                {"action": "update", "reason": action.reason})
    return {"phases": [phase]}


async def n_apply_directed_test(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    action = state.action()
    _, phase = await _run_agent(rt, state, "verify", "verify_supplement",
                                {"supplement": True,
                                 "gaps": (action.params or {}).get("gaps", [])})
    return {"phases": [phase]}


async def n_apply_relax(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    action = state.action()
    # 放宽约束：文本级修改 transaction 约束，下一轮重新编译仿真
    rt.service._relax_transaction_constraints(
        state.output_root, (action.params or {}).get("gaps", []))
    logger.info(f"放宽约束: {action.reason}")
    return {}


async def n_apply_expand_seeds(state: PipelineState, config) -> Dict[str, Any]:
    action = state.action()
    count = int((action.params or {}).get("count", 100))
    logger.info(f"扩种 → seed += {count}（覆盖率停滞，尝试新随机激励）")
    return {"seed": count}


def _round_or_abort(state: PipelineState) -> str:
    """还有下一轮就回 round_bump，否则去签核。

    **这一条最容易漏**：原来 `for range(max_rounds)` 隐式做了边界检查，
    图里必须显式写出来，否则会多跑一轮。
    """
    if state.round_num >= state.max_rounds:
        return "abort"
    return "next_round"


def r_coverage(state: PipelineState) -> str:
    """ops 之后的分流：EDA 缺失 / 编译失败 / 功能回归失败 / 正常收覆盖率。"""
    if state.eda_blocked:
        return "eda_missing"
    if state.regression_failed_count and not state.compile_error:
        return "functional_fail"
    if state.compile_error:
        return "compile_fail"
    return "run_coverage"


def r_after_converge(state: PipelineState) -> str:
    """收敛即离开循环去签核（原来 CONVERGE 分支末尾 break）。"""
    return "audit"


async def n_audit(state: PipelineState, config) -> Dict[str, Any]:
    """签核 audit —— 每条退出路径都要跑（包括 eda_blocked）。"""
    rt = _rt(config)
    data, phase = await _run_agent(rt, state, "audit", "audit")
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("audit"), dict):
        updates["audit"] = data["audit"]
    return updates


async def n_finalize(state: PipelineState, config) -> Dict[str, Any]:
    """证据链落盘 + manifest + 释放资源。"""
    rt = _rt(config)
    output_root = Path(state.output_root)

    # ── 文件级变更链（谁改了什么、为什么）──
    docs = output_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    file_chain_path = ""
    chain_valid, total_changes = False, 0
    if rt.file_audit is not None:
        try:
            chain = rt.file_audit.to_dict()
            chain_valid = rt.file_audit.verify()
            chain["chain_valid"] = chain_valid
            total_changes = chain.get("total_changes", 0)
            file_chain_path = str(docs / "file_change_chain.json")
            Path(file_chain_path).write_text(
                json.dumps(chain, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")
            # 回读磁盘复核：内存 verify() 等于「自己验自己」，尾部被裁发现不了
            from src.layers.l2_orchestration.evidence.file_audit import FileAuditTrail
            persisted = FileAuditTrail.verify_persisted(file_chain_path)
            if not persisted["valid"]:
                logger.warning(f"文件变更链落盘后复核未通过: {persisted['issues']}")
                chain_valid = False
        except Exception as e:
            logger.warning(f"文件变更链落盘失败: {e}")

    # ── 五层领域证据（L1 需求 / L2 设计 / L3 验证 / L4 执行 / L4.5 功能覆盖 / L5 签核）──
    # 落在 docs/evidence_chain.json —— CLI 的 _print_evidence_chain 读的就是这个结构，
    # 此前没有任何东西产出它，那段打印因此永远显示 0/0 与 NO。
    evidence_path = ""
    try:
        from src.layers.l2_orchestration.evidence.five_layer import FiveLayerEvidence
        ev = FiveLayerEvidence(output_root).build(
            spec=state.spec, design_arch=state.design_arch, tests=state.tests,
            regression=state.regression, coverage=state.coverage,
            final_coverage=state.final_coverage, target=state.target,
            exclude_effect=state.exclude_effect, phases=state.phases,
            evidence_chain_valid=chain_valid)
        evidence_path = str(docs / "evidence_chain.json")
        Path(evidence_path).write_text(
            json.dumps(ev, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
    except Exception as e:
        logger.warning(f"五层证据落盘失败: {e}")

    manifest_path = ""

    # ── Manifest：运行清单 ──
    try:
        docs = output_root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        from src.layers.l1_infrastructure.infrastructure import sha256_file
        rtl_hashes = {}
        rtl_dir = output_root / "rtl"
        if rtl_dir.exists():
            for sv in sorted(rtl_dir.glob("*.sv")):
                rtl_hashes[sv.name] = sha256_file(sv)[:16]

        manifest = {
            "architecture": "closed_loop_7agents",
            "target": state.target,
            "final_coverage": state.final_coverage,
            "effective_coverage": state.effective_coverage,
            "converged": state.effective_coverage >= state.target,
            "iterations": state.iterations,
            "phases": state.phases,
            "planning": {"target": rt.planner.target,
                         "milestones": rt.planner.milestones,
                         "convergence_forecast":
                             rt.planner.predict_convergence(state.coverage_history)},
            "testcase_portfolio": rt.testcase_reg.get_portfolio(),
            "testcase_stats": rt.testcase_reg.get_stats(),
            "exclude": {"stats": rt.exclude_reg.stats(),
                        "effect": state.exclude_effect,
                        "approved_points": sorted(rt.exclude_reg.get_excluded_points())},
            "rtl_hashes": rtl_hashes,
            "coverage_db_history": state.coverage_db_history,
            # 跨 run 成长：本次实际生效的蒸馏动作权重（可追溯「为什么这次这样决策」）
            "distilled_weights": rt.distilled_weights,
            "llm_audit": _collect_llm_audit(),
            "evidence": {"total_changes": total_changes,
                         "chain_valid": chain_valid,
                         "evidence_path": evidence_path,
                         "file_change_chain_path": file_chain_path},
        }
        manifest_path = str(docs / "manifest.json")
        Path(manifest_path).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
    except Exception as e:
        logger.warning(f"Manifest 落盘失败: {e}")

    # 汇总 Exclude 状态后释放 sqlite 连接（Windows 文件锁）
    exclude_stats = rt.exclude_reg.stats()
    try:
        rt.exclude_reg.close()
    except Exception:
        pass

    _passed = sum(1 for p in state.phases if p.get("status") == "passed")
    _name = Path(state.output_root).name
    _run_id = f"run_{_name.split('_')[-1] if '_' in _name else 'closed_loop'}"

    result = {
        "architecture": "closed_loop_7agents",
        "run_id": _run_id,
        "output_root": state.output_root,
        "phases": state.phases,
        "passed": _passed,
        "total": len(state.phases),
        "overall_score": round(state.effective_coverage, 1) if state.effective_coverage else 0,
        "final_coverage": state.final_coverage,
        "effective_coverage": state.effective_coverage,
        "converged": state.effective_coverage >= state.target,
        "eda_blocked": state.eda_blocked,
        "target": state.target,
        "iterations": state.iterations,
        "exclude": {"stats": exclude_stats, "effect": state.exclude_effect},
        "status": ("BLOCKED_EDA_MISSING" if state.eda_blocked
                   else ("CONVERGED" if state.effective_coverage >= state.target
                         else "COMPLETED")),
        "evidence": {"total_changes": total_changes, "chain_valid": chain_valid,
                     "evidence_path": evidence_path, "manifest_path": manifest_path,
                     "file_change_chain_path": file_chain_path},
    }
    return {"result": result}


# _collect_llm_audit 是 execution.py 的模块级函数；此处延迟引用避免循环 import
def _collect_llm_audit() -> Any:
    from src.layers.l2_orchestration.execution import _collect_llm_audit as _f
    return _f()


# ═══════════════════════════════════════════════════════════════
# 构图
# ═══════════════════════════════════════════════════════════════

#: 节点注册表 —— (节点名, 节点函数)。
#: 抽成模块级常量的理由：`stages.py` 要给每个节点配一份显示元数据（中文名 /
#: 分组 / 归属 agent），而「有哪些节点」必须只有一份。`tests/test_stages.py`
#: 断言两张表一一对应 —— 加了节点却忘了加元数据，那条测试会红。
NODE_FUNCS = (
    ("init", n_init), ("design", n_design), ("model", n_model), ("verify", n_verify),
    ("env_arch_check", n_env_arch_check), ("round_bump", n_round_bump),
    ("ops", n_ops), ("coverage", n_coverage), ("debug_functional", n_debug_functional),
    ("decide", n_decide), ("governor", n_governor),
    ("governor_retry", n_governor_retry), ("approval", n_approval),
    ("record_decision", n_record_decision),
    ("apply_converge", n_apply_converge),
    ("apply_compile_retry", n_apply_compile_retry),
    ("refactor_rtl", n_refactor_rtl), ("apply_update_model", n_apply_update_model),
    ("apply_directed_test", n_apply_directed_test), ("apply_relax", n_apply_relax),
    ("apply_expand_seeds", n_apply_expand_seeds),
    ("audit", n_audit), ("finalize", n_finalize),
)

NODE_NAMES = tuple(name for name, _ in NODE_FUNCS)


def build_closed_loop_graph(checkpointer=None, store=None):
    """构建七 Agent 闭环图。

    拓扑（与 run_closed_loop 的语句顺序一一对应）：
      init → design → model → verify → env_arch_check → round_bump
      round_bump → ops → {eda_missing→audit | compile_fail→decide
                          | functional_fail→debug→decide | run_coverage→coverage→decide}
      decide → governor → {proceed|override→approval → record → 动作分支}
                         {retry→round_bump} {abort→audit}
      各动作分支 → round_bump（或 converge/abort → audit）
      audit → finalize → END
    """
    g = StateGraph(PipelineState)

    for name, fn in NODE_FUNCS:
        g.add_node(name, fn)

    g.add_edge(START, "init")
    g.add_edge("init", "design")
    g.add_edge("design", "model")          # bypass 时 n_model 自行跳过
    g.add_edge("model", "verify")
    g.add_edge("verify", "env_arch_check")
    g.add_edge("env_arch_check", "round_bump")
    g.add_edge("round_bump", "ops")

    g.add_conditional_edges("ops", r_coverage, {
        "eda_missing": "audit",
        "compile_fail": "decide",
        "functional_fail": "debug_functional",
        "run_coverage": "coverage",
    })
    g.add_edge("debug_functional", "decide")
    g.add_edge("coverage", "decide")

    g.add_edge("decide", "governor")
    g.add_conditional_edges("governor", r_governor, {
        "proceed": "approval",
        "retry": "governor_retry",
        "abort": "audit",
    })
    g.add_edge("governor_retry", "round_bump")

    g.add_conditional_edges("approval", r_approval, {
        "proceed": "record_decision",
        "skip": "round_bump",
        "reject": "audit",
    })

    g.add_conditional_edges("record_decision", r_action, {
        "CONVERGE": "apply_converge",
        "COMPILE_RETRY": "apply_compile_retry",
        "REFACTOR_RTL": "refactor_rtl",
        "UPDATE_MODEL": "apply_update_model",
        "GENERATE_DIRECTED_TEST": "apply_directed_test",
        "RELAX_CONSTRAINT": "apply_relax",
        "EXPAND_SEEDS": "apply_expand_seeds",
    })

    g.add_conditional_edges("apply_converge", r_after_converge, {"audit": "audit"})
    g.add_conditional_edges("apply_compile_retry", r_after_compile_retry, {
        "next_round": "round_bump", "abort": "audit"})
    g.add_conditional_edges("refactor_rtl", r_after_guardian, {
        "next_round": "round_bump", "abort": "audit"})
    g.add_edge("apply_update_model", "round_bump")
    g.add_edge("apply_directed_test", "round_bump")
    g.add_edge("apply_relax", "round_bump")
    g.add_edge("apply_expand_seeds", "round_bump")

    g.add_edge("audit", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer, store=store)


def recursion_limit(max_rounds: int) -> int:
    """LangGraph 数 superstep 而非轮次，一轮约 6-10 步，留足余量。"""
    return _RECURSION_BASE + _RECURSION_PER_ROUND * max(1, max_rounds)
