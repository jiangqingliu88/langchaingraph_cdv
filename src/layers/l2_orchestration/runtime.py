"""闭环流水线的**运行期设施** —— Runtime / 状态重建 / executor 调用包装。

运行时设施与 agent 图的边界
    Agent 拓扑已迁到 `src/agents/`（supervisor + 四个专家子图）；
    本模块只保留 Runtime / `_run_agent` / context 重建等平台设施。
    executor 节点包装在 `src/agents/runtime/nodes/`，路由在
    `src/agents/supervisor/routing.py`。

Runtime 为什么不进状态（这是这个模块存在的根本原因）
    状态进检查点、要能字节复现；而活连接 / agent 实例 / LLM 客户端不能序列化。
    所以状态里只放可复现的东西，运行期对象走
    `config["configurable"]["rt"]`，由 `n_init` 建、重入时由 `hydrate_runtime` 重建。

    **少了它们不是"退化"，是 AttributeError** —— 见 `hydrate_runtime` 的 docstring。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pathlib import Path
import json
import os
import subprocess
import time

import structlog

from src.layers.l2_orchestration.state import PipelineState
from src.layers.l3_decision.decision_engine import CoverageDrivenDecisionEngine

logger = structlog.get_logger()

# 递归上限：LangGraph 数的是 superstep 而不是轮次，一轮约 6-10 步。
_RECURSION_BASE = 20
_RECURSION_PER_ROUND = 12


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

        # ── Architecture 2.0 运行事实面（不可序列化，故不进状态）──
        #: 这次 run 的身份/执行环境（`src/core/runtime/run_context.py`）。
        self.ctx = None
        #: 执行事实日志（`docs/events.jsonl`）。
        self.event_store = None
        #: 产物索引（`artifacts/artifacts.json` + CAS）。
        self.artifacts = None
        #: EDA 进程生命周期（命令白名单 / 超时 / 进程树回收）。
        self.jobs = None
        #: 本轮决策的期望效果与基线快照（`n_record_decision` 写、
        #: `n_coverage` 读，用于 decision_eval_v1）。
        self._round_expected: Optional[Dict[str, Any]] = None
        self._round_prev_coverage: Optional[float] = None
        self._round_prev_failed: Optional[int] = None
        self._round_prev_compile_ok: Optional[bool] = None
        self._round_tp_snapshot: Dict[str, str] = {}

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
        from src.tools.integration.ide_tools.api import load_manual_nodes

        return load_manual_nodes()
    except Exception as exc:                       # pragma: no cover - 环境问题
        logger.warning(f"人工节点声明没读进来（按无声明处理）: {exc}")
        return []


#: 每个专家能看到的 ctx 白名单 —— 不是“信任 executor 自己只读 consumes”。
#: 这些键来自 `consumes` 声明 + executor 里真实的 `ctx.get(...)` 读取点；
#: 新增读取点必须同时加到对应角色，否则这里会把它裁掉（测试会红）。
_CTX_BASE = frozenset({
    "run_id", "output_root", "output_dir", "target", "max_rounds",
    "round_num", "iterations", "design_style", "sim_modes", "manual_gate",
    "bypass_design", "bypass_design_model", "phases",
})
_AGENT_CTX_KEYS: Dict[str, frozenset] = {
    "front": frozenset(),
    "design": frozenset({"spec"}),
    "model": frozenset({"spec", "design_arch", "agents"}),
    "verify": frozenset({"spec", "design_arch"}),
    "ops": frozenset({"env", "tests", "regression"}),
    "coverage": frozenset({"spec", "regression", "coverage"}),
    "debug": frozenset({"regression", "tests", "env", "debug",
                        "design_arch", "model", "spec", "coverage"}),
    "audit": frozenset({"regression", "coverage", "design_arch", "model",
                        "semantic_validations", "target"}),
}


def _rebuild_ctx(state: PipelineState, role: str = "") -> Dict[str, Any]:
    """把状态投影回 agent 期望的 ctx dict。

    这是**专家上下文隔离**的边界：`role` 给了就只保留该专家声明的键，
    不再把 coverage/debug/decision 等无关状态塞进每个 executor。`role=""`
    保留旧的全量投影（兼容直接调用 `_rebuild_ctx(state)` 的测试）。
    """
    d = state.model_dump()
    for k in ("pending_action", "last_action", "decision_log",
              "governance_outcome", "approval_outcome", "guardian_verdict",
              "human_escalation", "terminal_reason"):
        d.pop(k, None)
    if role:
        allowed = _CTX_BASE | _AGENT_CTX_KEYS.get(role, frozenset())
        d = {k: v for k, v in d.items() if k in allowed}
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

    task = {"ctx": _rebuild_ctx(state, role), "input": rt.spec_text,
            "output_dir": state.output_root,
            # 统一 RunContext 的**可序列化视图**：executor 不需要活对象，但应该
            # 能回答"我这次属于哪个 run / 父 run 是谁"。
            "run_id": state.run_id,
            "run_context": (rt.ctx.to_dict() if getattr(rt, "ctx", None) else {})}
    if params:
        task["params"] = params

    _eda = 1 if role in ("ops", "coverage") else 0
    try:
        # **LLM 出处埋点**：这里是整条链上**唯一同时看得见 `state` 与 `task`**
        # 的地方（`call_llm` 在下面四层，只有三个 str 参数）。把 label / 轮次 /
        # run 目录钉进 contextvar，`call_llm` 沿调用链读回来，审计就能答
        # "这一行 RTL 是哪一轮、哪个节点催出来的"。
        from src.layers.l2_orchestration.context.llm_origin import origin_scope

        with origin_scope(label, state.round_num, state.output_root):
            result = await agent.execute_task(task)
        # 失败时也保留 data（含 regression 的 failed 详情），供回归门控决策
        data = result.data if isinstance(result.data, dict) else {}
        score = data.get("score", 0)
        status = "passed" if result.success else "failed"
        # 熔断计的是**动作执行失败**（这一步真出错了），不是"结论不合意"。
        #
        # `audit` 是**报告者**：它 `success=False` 的意思是"这次不达标"
        #（NEEDS_FIX）—— 那恰恰是闭环**要**的输入，不是执行错误。把它计进熔断，
        # 等于闭环用自己的方向盘把自己掐停：实测 `audit` 连挂 3 轮 →
        # `GENERATE_DIRECTED_TEST` 熔断 → 升级人工 → 闭环停在 32.5%，
        # 而它本该继续迭代到 `max_rounds`。真正的执行失败是下面 `except` 那条。
        _countable = role != "audit"
        rt.governor.after_action(role, success=(result.success or not _countable),
                                 eda=_eda, tokens=_token_delta(rt))
        if not result.success:
            logger.warning(
                f"agent '{role}' 执行失败，已反馈驾驭层（熔断计数 +1）" if _countable
                else f"agent '{role}' 结论不合意（未达标）—— **不计熔断**："
                     f"这是闭环要的输入，不是执行失败")
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
    # Architecture 2.0：同一批文件进 ArtifactStore（所有 executor 都走这里，
    # 不再各自维护产物索引）。
    _register_artifacts(rt, role, data, state)

    entry = {"name": label, "status": status, "score": score,
             "time": round(time.time() - t0, 1)}
    if quality:
        entry["quality"] = quality
    _write_progress(state, entry)
    return data, entry


def _artifact_files(data: Dict[str, Any]) -> list:
    files = []
    for key in ("design_arch", "model", "tests", "rtl", "regression",
                "coverage", "env", "debug", "audit"):
        val = data.get(key) if isinstance(data, dict) else None
        if not isinstance(val, dict):
            continue
        for field in ("files", "written_files", "generated_files"):
            if isinstance(val.get(field), list):
                files.extend(val[field])
        artifacts = val.get("artifacts")
        if isinstance(artifacts, dict):
            for entry in artifacts.values():
                if isinstance(entry, dict) and entry.get("path"):
                    files.append(entry["path"])
    out, seen = [], set()
    for f in files:
        text = str(f)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out[:100]


def _register_artifacts(rt, role: str, data: Dict[str, Any], state) -> None:
    store = getattr(rt, "artifacts", None)
    if store is None:
        return
    for path in _artifact_files(data):
        try:
            store.register("executor_output", path, producer=role,
                           round=state.round_num)
        except Exception:                                  # noqa: BLE001 索引是增量
            continue


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

def init_run_core(rt: "Runtime", output_root, run_id: str = "") -> bool:
    """建 RunContext / EventStore / ArtifactStore / JobSupervisor。

    入口在 `run_closed_loop` / `_stream_run`（那里才知道最终 output_root 与
    run_id），断点重入时由 `hydrate_runtime` 兜底。**失败只 warning**：这些是
    证据/观测设施，缺了不该让整条流水线起不来；缺失会在 quality gate 的
    evidence 维度被看见。
    """
    try:
        from src.core.runtime import (
            ArtifactStore, EventStore, open_run_context, set_active_store,
        )
        from src.core.jobs import JobSupervisor

        desired_run_id = run_id or Path(output_root).name
        if (rt.ctx is not None
                and rt.ctx.output_root == Path(output_root)
                and rt.ctx.run_id == desired_run_id):
            if rt.event_store is not None:
                set_active_store(rt.event_store)
            return True
        ctx = open_run_context(output_root, run_id=run_id or None)
        ctx.paths.ensure()
        rt.ctx = ctx
        rt.event_store = EventStore(ctx.output_root, run_id=ctx.run_id)
        set_active_store(rt.event_store)
        rt.artifacts = ArtifactStore(ctx.output_root, run_id=ctx.run_id,
                                     event_store=rt.event_store)
        rt.jobs = JobSupervisor(run_dir=ctx.output_root, run_id=ctx.run_id,
                                event_store=rt.event_store,
                                artifact_store=rt.artifacts)
        # 回归框架的 LocalStrategy 用 module-global 拿到 supervisor（单进程串行）。
        try:
            from src.layers.l2_orchestration.regression_tools.regression_framework.execution.strategy \
                import set_job_supervisor
            set_job_supervisor(rt.jobs)
        except Exception as _e:                            # noqa: BLE001
            logger.debug(f"JobSupervisor 未绑定到回归框架: {_e}")
        return True
    except Exception as e:                                 # noqa: BLE001
        logger.warning(f"运行事实面初始化失败（证据链会缺事件/产物索引）: {e}")
        return False


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
    # 把 L5 的经验查询注进 L3 的引擎 —— **L3 不 import L5**（那是越级反向依赖），
    # 装配是 L2 的事。拿不到就传 None：引擎会跳过"经验增强"，规则照常跑
    # （决策本来就是规则先行，经验只做增强）。
    try:
        from src.layers.l5_evolution.growth import experience_provider
        _experience = experience_provider
    except Exception as e:
        logger.warning(f"经验查询不可用，决策将不带历史增强: {e}")
        _experience = None
    rt.engine = CoverageDrivenDecisionEngine(target=state.target,
                                             experience=_experience)

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
    # **把 case 库注进去**：回归结果要回写用例状态，而 `TestcaseRegistry` 在 L4
    # —— L1 不能反向 import 它（见 `InfrastructureManager.__init__` 的 docstring）。
    # 构造点在这里，所以由这里提供。拿不到就传 None，L1 会出一条 warning（不静默）。
    try:
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry
        _case_lib = TestcaseRegistry()
    except Exception as e:
        logger.warning(f"case 库不可用，回归结果不会回写用例状态: {e}")
        _case_lib = None
    rt.infra = InfrastructureManager(state.output_root, case_library=_case_lib)
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

    # Architecture 2.0：入口通常已经建过；重入路径（n_init 不再执行）靠这里兜底。
    if rt.ctx is None or rt.event_store is None or rt.artifacts is None:
        init_run_core(rt, state.output_root, state.run_id)


def recursion_limit(max_rounds: int) -> int:
    """LangGraph 数 superstep 而非轮次，一轮约 6-10 步，留足余量。"""
    return _RECURSION_BASE + _RECURSION_PER_ROUND * max(1, max_rounds)
