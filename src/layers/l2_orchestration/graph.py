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
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from langgraph.errors import GraphInterrupt
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

        #: 人工节点声明（`config/ide/manual_nodes.yaml` → 节点 dict 列表）。
        #:
        #: 放在这里而不是 `hydrate_runtime`：它是**可序列化的纯数据**（不是活句柄），
        #: 而 `Runtime` 在正常启动与检查点重入时都会新建，所以 `__init__` 里读一次
        #: 就够。`hydrate_runtime` 的契约是"按状态重建**不可序列化**的对象"，
        #: 声明不属于那一类。
        #:
        #: 读失败 = 空列表（见 `load_manual_nodes`）。空声明**不是"没人要批"** ——
        #: `n_approval` 有 legacy 兜底，两个已知高危动作照样门控。
        self.manual_nodes: List[Dict[str, Any]] = _load_manual_nodes()


def _token_delta(rt) -> int:
    """自上次调用以来 LLM 消耗的 token 增量。

    `LLMTracerCallback.total_tokens_used` 是**全局累加器**（所有 LangChain 调用
    都记在它上面，见 context/llm_factory.py），而 `governor.after_action(tokens=)`
    要的是**这一步的消耗** —— 直接传累计值的话第一次调用就把预算打满。所以按
    增量传，游标存在 Runtime 上。

    这个增量以前从来没传过（三处 `after_action` 都只传 `eda=`），导致
    `budget.tokens_used` 恒为 0、token 预算永不触发 —— 「可治理」里的预算治理
    形同虚设。现在接上真实用量。
    """
    try:
        from src.layers.l2_orchestration.context.llm_factory import LLMTracerCallback
        now = LLMTracerCallback.total_tokens_used
    except Exception:
        return 0
    seen = getattr(rt, "_tokens_seen", 0)
    rt._tokens_seen = now
    return max(0, now - seen)


def _rt(config) -> Runtime:
    return config["configurable"]["rt"]


def _load_manual_nodes() -> List[Dict[str, Any]]:
    """读人工节点声明。读不到就空列表 —— **不抛**（见 `load_manual_nodes`）。"""
    try:
        from src.tools.ide_tools.api import load_manual_nodes

        return load_manual_nodes()
    except Exception as exc:                       # pragma: no cover - 环境问题
        logger.warning(f"人工节点声明没读进来（按无声明处理）: {exc}")
        return []


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
        rt.governor.after_action(role, success=result.success, eda=_eda,
                                 tokens=_token_delta(rt))
        if not result.success:
            logger.warning(f"agent '{role}' 执行失败，已反馈驾驭层（熔断计数 +1）")
    except Exception as e:
        logger.warning(f"{role} 执行失败: {e}")
        data, score, status = {}, 0, "error"
        rt.governor.after_action(role, success=False, eda=_eda,
                                 tokens=_token_delta(rt))

    # 确定性质量校验（QualityGuard）：结论进 phase → 落进证据链。
    # 默认 advisory（只记不改），理由与「为什么恒用 no_ask」见 _quality_check。
    data, quality = _quality_check(rt, role, data, state)

    # 审计证据链：记录该 agent 产出的文件（git diff + 理由）。
    # `_record_agent_files` 内部会把链增量刷盘 —— 崩在这一步之后的 run 也留得下证据。
    rt.service._record_agent_files(rt.file_audit, role, data, params)

    entry = {"name": label, "status": status, "score": score,
             "time": round(time.time() - t0, 1)}
    if quality:
        entry["quality"] = quality
    _write_progress(state, entry)
    return data, entry


def _git_head(start: Path = None) -> str:
    """当前代码的提交号，用于签核包回溯「这份结果是哪版代码跑出来的」。

    取不到就返回空串 —— 签核包里少一个字段，不该打断 finalize。
    """
    try:
        r = subprocess.run(["git", "-C", str(start or Path.cwd()), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _write_progress(state: PipelineState, entry: Dict[str, Any]) -> None:
    """把「跑到哪一步了」增量写到 `<output>/docs/progress.json`。

    `evidence_chain.json` / `manifest.json` 都是 `n_finalize` 才生成的**总结**，
    中途失败的 run 一份都没有（实测 `output_...152822` 的 docs/ 下只有一份
    0 行的 tool_receipts.jsonl）。失败时最需要知道的就是"走到了哪、哪一步炸的"，
    所以这里每跑完一个 agent 就刷一次，代价是一个小文件。

    故意不写成证据链格式：它不是签核依据，只是**运行进度**，不该被误当成证据。
    """
    try:
        payload = {
            "run_id": state.run_id,
            "round_num": state.round_num,
            "phases": list(state.phases) + [entry],
            "pending_action": (state.pending_action.get("action_type")
                               if isinstance(state.pending_action, dict) else None),
            "final_coverage": state.final_coverage,
        }
        out = Path(state.output_root) / "docs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "progress.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
    except Exception as e:
        logger.debug(f"progress.json 写入失败（不影响流程）: {e}")


# ═══════════════════════════════════════════════════════════════
# 质量校验（QualityGuard 接线）
# ═══════════════════════════════════════════════════════════════

def _quality_check(rt, role: str, data: dict, state) -> tuple:
    """对 agent 产出跑 `QualityGuard` 的确定性校验，返回 (data, 摘要)。

    摘要进 phase entry → 落进 `progress.json` / manifest / 证据链，所以
    「这个 agent 的产出没过哪几条确定性校验」是**可审计的**，而不只是打条日志。

    两个必须说清的设计点：

    1. **恒用 `no_ask=True`。** `QualityGuard` 的 Layer 3 在 `no_ask=False` 时会调
       `EscalationConsole.ask()` —— **交互等终端输入**。闭环可能跑在无头环境
       （CI / 后台 / 工具子进程），`no_ask=False` 会把整个跑挂在那里等输入。
       恒用 `no_ask=True`：到第 3 层就是「接受当前产出 + 降分标记」，不阻塞。
       （人工升级另有通路：governor 预算/熔断耗尽时的 `_escalate_to_human`。）

    2. **默认 advisory（只记不改）。** Layer 2 会用规则/模板**替换掉 agent 的产出**
       —— 那是行为变更，不该在没人要求时静默生效。默认只记校验结论；
       设 `SIGNOFFAI_QUALITY_GUARD=enforce` 才让它接管 data，`=off` 完全关闭。
    """
    mode = os.environ.get("SIGNOFFAI_QUALITY_GUARD", "advisory").strip().lower()
    if mode == "off" or not isinstance(data, dict) or not data:
        return data, {}

    try:
        from src.layers.l2_orchestration.governance.quality_guard import (
            PIPELINE_ROLE_MAP, QualityGuard, run_validator)

        if role not in PIPELINE_ROLE_MAP:
            # 该角色没有确定性校验规则 —— 如实返回空摘要，不假装校验过
            return data, {}

        if mode == "enforce":
            # 三层兜底：Layer 2 可能用规则/模板**替换产出**，故只在 enforce 下走
            if getattr(rt, "quality_guard", None) is None:
                rt.quality_guard = QualityGuard(approval_gate=rt.approval_gate,
                                                no_ask=True)
            checked, vr = rt.quality_guard.guard(
                role, data, {"spec": rt.spec_text}, state.output_root)
        else:
            # advisory：只跑 Layer 1，拿**未经改写**的原始判定。
            # 走 guard() 的话 Layer 3 会把 verdict 强改成 PASS 并降分，
            # 记录里就只剩一个 pass，看不出它其实没过哪几条检查。
            vr = run_validator(role, data, state.output_root)
            checked = data
            if vr is None:
                return data, {}

        verdict = getattr(getattr(vr, "verdict", None), "value", str(vr.verdict))
        summary = {
            "validator": PIPELINE_ROLE_MAP.get(role),
            "verdict": verdict,
            "score": getattr(vr, "score", None),
            "issues": list(getattr(vr, "issues", None) or [])[:5],
            "fallback_used": bool(getattr(vr, "fallback_used", False)),
            "mode": mode,
        }
        if verdict != "pass":
            logger.warning(f"agent '{role}' 质量校验 {verdict}: {summary['issues'][:2]}")

        if mode == "enforce" and summary["fallback_used"]:
            # 只有回退真的产出了替换内容时才接管（Layer 2 命中的情况）
            return checked, summary
        return data, summary
    except Exception as e:
        # 校验本身出问题不该打断闭环 —— 它是「多一道确定性检查」，不是主流程
        logger.warning(f"质量校验执行失败（跳过）: {e}")
        return data, {}


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
        # **必须装进 hub**：这个 auditor 才是带落盘路径的那个，但之前建完就挂在
        # rt 上没人用；ToolHub 自己一直用构造时的纯内存 `ToolAuditor()`。
        # 结果 `docs/tool_receipts.jsonl` 被建出来却永远是 0 行 —— 工具审计在
        # 证据包里等于不存在。
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        ToolHub.get_instance().set_auditor(rt.tool_auditor)
    except Exception as _e:
        logger.warning(f"工具回执审计器安装失败（工具调用将不留回执）: {_e}")
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
        from src.tools.lib.filelist import build_filelist_for_tb, derive_env_name

        _fl = output_root / "inputs" / "filelists" / "filelist.f"
        if not _fl.exists():
            # 环境名推导有讲究，别在这里手写"取第一个 *_pkg.sv"（那个写法会把
            # 子包 `_parameters_pkg` 当环境包）—— 见 `derive_env_name` 的说明。
            _env_name = derive_env_name(output_root)
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


def _have_rounds_left(state: PipelineState) -> bool:
    """轮次预算还有没有。

    `n_round_bump` 的 docstring 一直写着"终止靠 router 显式检查轮次（见
    _have_rounds_left）"，但这个函数**从来不存在** —— 于是 `max_rounds` 只被拿去
    算 `recursion_limit`（`_RECURSION_BASE + 12/轮`），没有任何一处真的用它收口。
    后果：覆盖率不达标时闭环一直转，直到 `GraphRecursionError: Recursion limit of
    32 reached`。界面上「冒烟（1 轮）」名副其实地跑了 4 轮，然后以一句框架报错收场。

    `round_num` 在这里已经是**自增之后**的值（router 读到的是本轮更新过的状态），
    所以 `round_num <= max_rounds` 的意思是"这一轮是预算内的，可以跑"。
    """
    return state.round_num <= max(1, state.max_rounds)


def r_after_round_bump(state: PipelineState) -> str:
    """轮次预算的唯一把关点。

    `round_bump` 是**所有回边的汇合处**：governor_retry / approval-skip /
    apply_compile_retry / guardian / update_model / directed_test / relax /
    expand_seeds 全都回到这里，再从它进 `ops`。所以预算只在这里查一次就够 ——
    不必在八条回边上各写一遍（写八遍就是八份真相，漏一处就是又一轮失控）。

    预算用尽走 `audit`（与 governor 的 abort 同一条出口）：**如实签核**，
    结果里的 `converged` 由 `effective_coverage >= target` 推出来，所以"轮次用尽
    但没达标"会如实记成未收敛，而不是假装通过。
    """
    if _have_rounds_left(state):
        return "next_round"
    logger.info(f"轮次预算用尽（已跑 {state.round_num - 1} 轮 / 上限 {state.max_rounds}），"
                f"退出闭环进入签核：覆盖率 {state.final_coverage}% / 目标 {state.target}%")
    return "give_up"


async def n_ops(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    # round_num 经 round_bump 后即为 1 基轮次（原 for-range 是 0 基），故直接用
    # `sim_modes` 与 `design_style` 同位：都是"这次运行怎么跑"的输入，不是全局开关。
    data, phase = await _run_agent(rt, state, "ops", f"ops_r{state.round_num}",
                                   {"design_style": state.design_style,
                                    "sim_modes": list(state.sim_modes or [])})
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
    # **挂死/看门狗超时不算功能失败**：那是 bench/激励侧的事。算进去的后果是决策引擎
    # 按 REFACTOR_RTL 去改 RTL —— 实测真跑了一轮 `design_fix`，改的是没坏的代码。
    # `functional_failed` 由 L1 归类后给出（见 `_HANG_RE`）；没有这个键就退回旧口径。
    harness = regression.get("harness_failures") or [] if isinstance(regression, dict) else []
    if isinstance(regression, dict) and "functional_failed" in regression:
        decision_failed = int(regression.get("functional_failed", 0) or 0)
    else:
        decision_failed = failed
    if harness:
        phase["harness_failures"] = harness[:5]
        # ── C：挂死也要有**归因**，不能只留一串日志文本 ──
        # 取指纹（规范化后 MD5）+ 归类，走 debug_tools 的纯函数工具。
        # **只归类、不改 RTL** —— 这是"挂死不该引着改设计"与"挂死也得看得懂"
        # 之间的分界：debug 的判断力用上了，它那条改 RTL 的路没走。
        phase["harness_triage"] = _triage_harness(harness)
        # **定案 → 规则草案**：这类挂死反复出现、有指纹，却没有任何规则在拦它 ——
        # 正是最该长出一条规则的地方。只起草，不自动生效（见 rule_draft 的说明）。
        try:
            from src.layers.l4_memory.rule_draft import (drafts_from_triage,
                                                        write_drafts)

            _n = write_drafts(Path(state.output_root),
                              drafts_from_triage(phase["harness_triage"],
                                                 Path(state.output_root).name))
            if _n:
                phase["rule_drafts"] = _n
                logger.info(f"起草 {_n} 条规则草案 → docs/rule_drafts.md（等人拍板）")
        except Exception as _e:                        # noqa: BLE001 起草是旁路
            logger.debug(f"规则起草跳过: {_e}")
        # ── B：把"为什么没进 debug"写进 phase ──
        # 不然界面上只有一行日志，人会问"debug agent 怎么没触发"（真被问过）。
        if not decision_failed and not compile_error:
            phase["debug_skipped_reason"] = (
                f"{len(harness)} 个失败全是 bench 侧（挂死/看门狗超时）—— "
                f"debug 只修 DUT 功能错，不改 bench；已按指纹归类，见 harness_triage")
        phase["reason"] = (str(phase.get("reason", "")) +
                           f" | {len(harness)} 个 test 挂死/看门狗超时（bench 侧，"
                           f"不计入功能失败）")[:400]
        logger.warning(f"ops：{len(harness)} 个 test 挂死/看门狗超时，"
                       f"不计入功能失败、不触发 RTL 重构：{harness[:3]}")
    return {"regression": regression, "regression_failed_count": decision_failed,
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
                                     success=(final_coverage > rt.prev_coverage),
                                     tokens=_token_delta(rt))
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


def _approval_artifacts(state: PipelineState) -> List[Dict[str, Any]]:
    """这次审批要人看的产物 —— **紧凑**清单。

    为什么带产物：在此之前审批框上只有一句 `action.reason`（"功能覆盖 62%"），
    人根本不知道自己在批准**什么文件**。而卡住运行的恰恰是这些中间 YAML ——
    实测一次 `bench.yaml` 的 schema 不符让整次运行挂在 verify。

    为什么是裁剪过的：完整清单带 sha256 与逐条诊断，会把 checkpoint（`interrupt`
    的 payload 会进检查点）和运行日志撑肥。界面要的是"哪几份有问题、几处"，
    详情它自己会去 `flow.artifacts` 读。
    """
    try:
        from src.tools.flow_tools.api import run_artifacts

        report = run_artifacts(str(state.output_root))
        if not isinstance(report, dict) or report.get("error"):
            return []
        return [{"path": a.get("path", ""), "group": a.get("group", ""),
                 "exists": bool(a.get("exists")),
                 "errors": int(a.get("errors") or 0),
                 "warnings": int(a.get("warnings") or 0)}
                for a in report.get("artifacts") or []]
    except Exception as exc:                       # pragma: no cover - 环境问题
        logger.warning(f"审批产物清单取不到（照常审批）: {exc}")
        return []


def _interrupt_approval(rt, action, *, summary: str = "",
                        artifacts: Optional[List[Dict[str, Any]]] = None):
    """停下来等人批 —— 返回一个 `ApprovalRecord`（与通道模式同形）。

    `interrupt()` 的第一次调用会**抛出** `GraphInterrupt`，由 LangGraph 接住并
    把当前状态写进检查点；恢复时同一个 `interrupt()` 调用会**返回**传进来的
    resume 值。所以这个函数在两条时间线上各跑一次，代码却只有一份。

    传进去的 payload 要**自包含**：恢复的人（可能是另一个进程、另一台机器）
    手上只有检查点，看不到内存里的任何东西。

    `summary` / `artifacts` 是给**人**看的：判什么、看哪几份文件。界面的检查点
    分支读的就是这个 dict（经 journal 的 `run.interrupted`）—— 所以产物必须加在
    这里，只加在 `ApprovalRequest` 上界面是看不到的（那条路只有通道模式走）。
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
        "summary": summary or action.reason,
        "reason": action.reason,
        "token": token,
        "artifacts": list(artifacts or []),
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


#: 已知的高危动作 —— **声明缺失时的兜底**。
#:
#: 这两个动作从 graph 化之前就要求人工审批（改 RTL、改参考模型都会让已有的
#: 签核证据失效）。声明文件是**主源**，这里是安全网：文件丢了、写坏了、
#: 或者压根没人写，这两个动作照样得有人批 —— 治理不能因为一份配置文件不在
#: 就静默失效。
#:
#: 刻意**只保这两个**：兜底名单越长，它就越是"第二份真相"。新增的高危动作
#: 一律走声明，不在这个元组里登记。
#: 兜底的高危动作（声明文件读不到时用）。**新旧名字都列** —— 声明里可能写的是
#: 老名字 `REFACTOR_RTL`，而决策层现在产的是 `FIX_FUNCTIONAL_bug` 之类。
_LEGACY_HIGH_RISK_ACTIONS = ("REFACTOR_RTL", "UPDATE_MODEL",
                             "FIX_FUNCTIONAL_bug", "FIX_PROTOCOL_bug",
                             "FIX_RESET_bug", "FIX_CDC_bug",
                             "FIX_DEADCODE_bug", "FIX_MODEL_bug")


def _matching_manual_node(rt: Runtime, after: str,
                          action_type: str) -> Optional[Dict[str, Any]]:
    """在声明里找"挂在 `after` 阶段之后、且只针对 `action_type`"的那一条。

    两条匹配规则，都是刻意的：
      · `after` 必须对上 —— 声明挂错阶段的节点不该在这里生效；
      · `action` 必须**写且等于**当前动作。声明里没写 `action` 的是"这个阶段的
        通用停靠点"（那是后续增量要接的东西），本增量只认动作级声明，不把它
        当成"所有动作都要批"—— 那会把每一次迭代都变成等人。
    """
    for node in getattr(rt, "manual_nodes", []) or []:
        if node.get("after") != after:
            continue
        if node.get("action") and node.get("action") == action_type:
            return node
    return None


async def n_approval(state: PipelineState, config) -> Dict[str, Any]:
    """高风险动作前的人工审批 —— **触发条件读声明**（`config/ide/manual_nodes.yaml`）。

    在此之前这里是一行硬编码：`action_type not in ("REFACTOR_RTL", "UPDATE_MODEL")`。
    声明文件有 schema、有编辑界面、有测试，闭环却从不读它 —— 于是"人工节点"
    一直只是文档。现在它是主源，硬编码退化成兜底（见 `_LEGACY_HIGH_RISK_ACTIONS`）。

    本增量只把**触发**改成读声明，不新增闸门点：声明仍只能挂在 `decide` 这类
    既有位置上，且必须写明 `action`。"在某个阶段之后无条件停一下"（产物闸门）
    是后续增量，那需要相应的条件路由。
    """
    rt = _rt(config)
    action = state.action()
    if not rt.approval_gate:
        return {"approval_outcome": "proceed"}

    node = _matching_manual_node(rt, "decide", action.action_type)
    if node is None and action.action_type not in _LEGACY_HIGH_RISK_ACTIONS:
        return {"approval_outcome": "proceed"}

    # 声明在 → 用它的提示语与超时默认；不在 → 这两个动作的原始行为
    summary = (node or {}).get("prompt") or action.reason
    artifacts = _approval_artifacts(state)
    try:
        from src.layers.l2_orchestration.governance.approval import ApprovalDecision
        if rt.interrupt_mode:
            # 有检查点 → 走 interrupt()：本节点**抛出**，图把状态存进检查点然后
            # 结束这次 astream。等人来答（可能是另一个进程、另一天），
            # 恢复时 interrupt() 直接**返回**答案，从这里往下继续。
            # 这才叫"暂停"—— 而通道模式的"阻塞等答案"其实一直占着一个线程。
            record = _interrupt_approval(rt, action, summary=summary,
                                         artifacts=artifacts)
        else:
            # **取 .decision**：ask() 返回的是 ApprovalRecord。此前这里直接拿 record
            # 与枚举比较，dataclass 的 __eq__ 对非同类返回 NotImplemented → 恒为 False，
            # 于是拒绝/跳过两条分支是死代码，「用户拒绝」根本不生效。
            record = rt.approval_gate.ask(action.action_type, summary,
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
    except GraphInterrupt:
        # **`GraphInterrupt` 必须先于下面那条 `except Exception` 重抛。**
        #
        # 它是 `Exception` 的子类，而下面那条是 catch-all —— 不重抛的话，
        # `interrupt()` 抛出的"停下来等人"会被当成"审批故障"降级成 skip：
        # 图继续往下跑、人根本没被问到，而日志里只留一句 warning。
        #
        # 实测过：真图上这条审批**从来没停过**。`tests/test_checkpoint.py` 用的是
        # 自己的假审批节点（没有这层 try），所以一直是绿的 —— 机制被验过，
        # 真节点没有。**"暂停"不是"失败"，别把它降级掉。**
        raise
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
    """动作分流。未映射的动作显式报错——原来 if/elif 没有 else，
    未映射的 action_type 会静默重开一轮。

    **先归一**（`canonical_action`）：老名字（`REFACTOR_RTL` / `COMPILE_RETRY` /
    `UPDATE_MODEL`）映射到 `FIX_*_bug` 的分类名 —— RL 策略文件和历史轨迹里存的是
    老名字，直接比会判成"未映射"。
    """
    from src.layers.l3_decision.decision_engine import canonical_action

    at = canonical_action((state.action() or Action("")).action_type)
    allowed = {"CONVERGE", "FIX_COMPILE_bug", "FIX_MODEL_bug", "FIX_FUNCTIONAL_bug",
               "FIX_PROTOCOL_bug", "FIX_RESET_bug", "FIX_CDC_bug", "FIX_DEADCODE_bug",
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

    # ── 改 RTL 是**事务**：改前快照 → 改后按影响面重跑 → 破坏了就回滚 ──
    # 理由是"改一个 bug 可能把已经好的功能改坏"，而原来改完没有任何比对：
    # 守卫要的黄金基线只在收敛时才存（这个闭环从没收敛过 → 每次都被放行）。
    from src.layers.l1_infrastructure.refactor_guard import RefactorGuard
    from src.layers.l3_decision.decision_engine import verification_plan

    # 根因 → 验证计划：跑多少、还该补什么验证、要不要人看（见 `VERIFICATION_PLANS`）
    plan = verification_plan(action.action_type)
    guard = RefactorGuard(Path(state.output_root), design_name=_design_name(state))
    snap = guard.snapshot()

    _, p1 = await _run_agent(rt, state, "design", "design_fix", {"fix_agent": "rtl"})
    phases.append(p1)

    # 改完立刻验证：**改动前通过的用例，改动后必须仍然通过**
    guard_result = guard.verify(snap, plan=plan)
    grade = {"name": "refactor_guard",
             "root_cause": action.action_type,
             "plan": {k: plan[k] for k in ("scope", "tags", "extra", "needs_human")},
             "fix_kind": guard_result.get("fix_kind", "")}
    if guard_result.get("regressed"):
        restored = guard.rollback(snap)
        grade.update({
            "status": "rolled_back",
            "reason": (f"改动使 {len(guard_result['regressed'])} 个原本通过的用例失败，"
                       f"已回滚 RTL（恢复 {len(restored)} 个文件）"),
            "regressed": guard_result["regressed"][:10],
            "restored": restored[:10],
        })
        logger.warning(f"改 RTL 破坏了既有功能，已回滚：{guard_result['regressed'][:5]}")
    else:
        grade["status"] = "kept"
        grade["reason"] = (guard_result.get("error")
                           or f"{guard_result['scope']['why']}；"
                              f"原本通过的 {len(guard_result.get('watched') or [])} 个用例仍然通过")
    grade["scope"] = guard_result.get("scope", {})
    grade["watched"] = len(guard_result.get("watched") or [])
    if plan.get("needs_human"):
        # 机器给不出可信结论的那几类（CDC 同步器对不对、死代码是不是真不可达）
        # —— 如实挂起一个待人工确认，不假装验证过了
        grade["needs_human"] = plan["why"]
        logger.warning(f"这次改动的验证需要人工确认：{plan['why']}")
    phases.append(grade)

    logger.info("设计重构 → 被动通知 model 更新（版本 +1）")
    _, p2 = await _run_agent(rt, state, "model", "model_update",
                             {"action": "update", "reason": action.reason})
    phases.append(p2)
    return {"guardian_verdict": {"allowed": True}, "phases": phases}


def _triage_harness(harness: List[str]) -> List[Dict[str, Any]]:
    """给挂死的 test 取指纹 + 归类（**只归类，不改 RTL**）。

    挂死以前只是一串 `"build_x/test_y: # UVM_ERROR ..."` 文本 —— 看得见，但
    归不了类：同一个原因挂 5 条和 5 个不同原因挂 1 条长得一样。这里走 debug 的
    纯函数工具（`debug.fingerprint_error`：规范化去掉行号/地址后取 MD5）把它们
    聚成"几条不同的挂法"。

    失败**不影响主流程**：归类是锦上添花，取不到就返回空的指纹（不编）。

    **直接调那个纯函数，不走 `call_tool`** —— `debug.fingerprint_error` **没有
    在 ToolHub 上登记**（它只在 GUI 的桥目录里），走 `call_tool` 永远拿不到。
    这里是给挂死加一条归因注记，不是一次受治理的工具动作，直接调不算绕开治理。
    """
    out = []
    try:
        from src.tools.debug_tools.main import fingerprint_error
    except Exception:                                 # noqa: BLE001
        return out
    for entry in harness[:10]:
        text = str(entry)
        item: Dict[str, Any] = {"test": text.split(":")[0][-60:], "note": text[-120:]}
        try:
            payload = fingerprint_error(error_text=text)
            if isinstance(payload, str):
                import json as _json
                payload = _json.loads(payload)
            if isinstance(payload, dict):
                item.update({k: payload[k] for k in ("fingerprint", "category", "matched")
                             if payload.get(k)})
        except Exception as e:                        # noqa: BLE001
            item["note"] = f"{item['note']}（归类失败: {str(e)[:60]}）"
        out.append(item)
    return out


def _design_name(state: PipelineState) -> str:
    """这次运行的设计名（顶层 RTL 文件名）—— 判"动的是不是顶层"要用。

    两个来源都试：spec 里直接写的 `design_name`，以及 `design_arch` 里的
    `module_name`（model agent 用的是后者）。都读不到就返回空 —— `scope()`
    会因此退回全量（认不出就多跑，不漏跑）。
    """
    spec = getattr(state, "spec", None)
    if isinstance(spec, dict):
        if spec.get("design_name"):
            return str(spec["design_name"])
        arch = spec.get("design_arch")
        if isinstance(arch, dict) and arch.get("module_name"):
            return str(arch["module_name"])
    return ""


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
            # 产出时刻 + 代码版本。**这两条本来写在每个生成文件的头注释里**，
            # 但那会让产物不可复现（同一输入两次跑，内容哈希对不上，见
            # gen_uvm.reproducible_now 的说明）。它们属于「这次 run 的元数据」，
            # 该记在 manifest 里 —— 每个产物文件没有独立的时间戳，整份签核包
            # 共用一个。
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "git_head": _git_head(output_root),
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
        # 预算实况：token 预算刚接上真实用量，把数字暴露出来，
        # 否则「预算耗尽」拦截时没人知道到底用了多少、该把阈值调到哪。
        "budget": (rt.governor.budget.status() if rt.governor else {}),
    }
    if rt.governor:
        _b = rt.governor.budget
        logger.info(f"预算: tokens {_b.tokens_used}/{_b.token_budget} · "
                    f"eda {_b.eda_calls}/{_b.eda_budget} · "
                    f"time {_b.time_used_s:.0f}s/{_b.time_budget_s:.0f}s")
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
    # round_bump 是所有回边的汇合点 —— 轮次预算在这里收口（见 r_after_round_bump）
    g.add_conditional_edges("round_bump", r_after_round_bump, {
        "next_round": "ops",
        "give_up": "audit",
    })

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
        "FIX_COMPILE_bug": "apply_compile_retry",
        # 改 RTL 的三类走同一个节点（都要过回归守卫 + 重跑比对）
        "FIX_FUNCTIONAL_bug": "refactor_rtl",
        "FIX_PROTOCOL_bug": "refactor_rtl",
        "FIX_RESET_bug": "refactor_rtl",
        "FIX_CDC_bug": "refactor_rtl",
        "FIX_DEADCODE_bug": "refactor_rtl",
        "FIX_MODEL_bug": "apply_update_model",
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
