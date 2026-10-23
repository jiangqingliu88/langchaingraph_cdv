"""纯函数节点 · 人工审批

高风险动作前停下来等人 —— checkpoint 模式下走 `interrupt()`，通道模式走阻塞 gate。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from langgraph.errors import GraphInterrupt

from src.layers.l2_orchestration.runtime import (
    Runtime, _rt,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


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
        # **`--approval auto` 必须赢过 interrupt 机制。**
        #
        # 原来这里只判 `rt.interrupt_mode`，于是打开检查点之后**每一个**高危动作
        # 都会停下来等人 —— 包括 CI 显式声明 `--approval auto`（无人值守）的那些。
        # 实测：`verify --checkpoint（默认开）--approval auto` 跑到
        # `FIX_FUNCTIONAL_bug` 就停住了，`auto` 等于没写。
        #
        # 判据用门控自己的 `requires_approval`（AUTO → False），而不是在这里
        # 再比一次 mode：**该不该问**是门控的事，这里只决定"问"用哪种机制。
        _must_ask = rt.approval_gate.requires_approval(action.action_type,
                                                       risk_level="high")
        if rt.interrupt_mode and _must_ask:
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
            #
            # 走到这里有两种情况：没检查点（通道模式，阻塞等答案），
            # 或者**门控说不用问**（`--approval auto`）—— 后者 `ask()` 内部
            # 直接返回 APPROVE，不会阻塞。
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


