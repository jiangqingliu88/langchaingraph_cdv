"""executor 节点 · 修复

后段：编译重试 / RTL 重构 / 更新模型 / 生成定向测试 —— 失败后的四条修复路。
"""
from __future__ import annotations

from typing import Any, Dict, List

from pathlib import Path
import json

import structlog

from src.layers.l2_orchestration.runtime import (
    _rt, _run_agent,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


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


async def n_refactor_rtl(state: PipelineState, config) -> Dict[str, Any]:
    """回归守卫 → 改 design + 被动更新 model。"""
    rt = _rt(config)
    action = state.action()
    phases: List[Dict[str, Any]] = []

    try:
        from src.layers.l1_infrastructure.golden_baseline import GuardianAgent
        # **把 runner 注进去**：跑 golden 用例集走的是工具子进程那条通路，
        # 而它属于本层。`GuardianAgent` 在 L1，不能反向 import 这里 ——
        # 所以由我们提供（见它 `__init__` 的 docstring）。不传的话守卫会
        # 因为"验证不了"而拒绝放行（那比默默跳过守卫安全）。
        from src.layers.l2_orchestration.communication.tool_subprocess import (
            run_tool_in_subprocess,
        )
        guardian = GuardianAgent(Path(state.output_root),
                                 run_tool=run_tool_in_subprocess)
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
        from src.tools.checking.debug_tools.main import fingerprint_error
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


