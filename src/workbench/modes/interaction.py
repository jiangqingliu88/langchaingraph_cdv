"""三种前端的共享适配层：对话、可审查计划、确定性验证执行。

这里不实现另一个 Agent、分类器或执行引擎。实际 turn/resume 均由
agent_mode_service 复用。执行阶段必须显式选择 verify，绝不根据普通聊天
猜测应该修改什么文件、启动什么 EDA 进程。
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any

from src.workbench.api import agent_mode_service
from src.workbench.modes.agent_modes import AgentMode, get_mode


class InteractionMode(str, Enum):
    CHAT = "chat"
    PLAN = "plan"
    VERIFY = "verify"


AgentCaller = Callable[..., dict[str, Any]]
VerifyCaller = Callable[..., dict[str, Any]]


def _mode(value: InteractionMode | str) -> InteractionMode:
    if isinstance(value, InteractionMode):
        return value
    aliases = {
        "ask": "chat",
        "agent": "chat",
        "planning": "plan",
        "run": "verify",
        "execute": "verify",
        "engine": "verify",
    }
    try:
        return InteractionMode(aliases.get(str(value).lower(), str(value).lower()))
    except ValueError as exc:
        raise ValueError(f"未知交互模式：{value!r}；可用 chat/plan/verify") from exc


def _empty_result(mode: InteractionMode, session_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "invalid",
        "exit_code": 1,
        "error": "对话内容不能为空",
        "session_id": session_id or "",
        "interaction": {"mode": mode.value, "frontend": "cli"},
    }


def _agent_config(mode: InteractionMode, preset: AgentMode | None = None) -> dict[str, Any]:
    """交互方式 + 领域角色 → Harness 配置。两种来源都真实生效。"""
    config: dict[str, Any] = {"require_exec_approval": True}
    if preset is not None and preset.role_prompt:
        config["role_prompt"] = preset.role_prompt
    if mode == InteractionMode.PLAN:
        config.update({"plan_first": True, "require_plan_approval": True, "require_exec_approval": True})
    return config


def _decorate(
    result: dict[str, Any], mode: InteractionMode, frontend: str, preset: AgentMode | None = None
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError("Agent 执行结果必须是 dict，不能把未知对象包装成成功结果")
    body = dict(result)
    session = body.get("session") or {}
    body.setdefault(
        "session_id", body.get("session_id") or (session.get("session_id") if isinstance(session, dict) else "") or ""
    )
    body.setdefault("status", body.get("verdict") or body.get("status") or "unknown")
    body.setdefault("summary", body.get("reason") or body.get("summary") or "")
    body["interaction"] = {
        "mode": mode.value,
        "agent_mode": preset.id if preset is not None else "",
        "specialist": preset.specialist if preset is not None else "",
        "stages": list(preset.stages) if preset is not None else [],
        "frontend": frontend,
    }
    body["human_review_required"] = bool(
        body.get("pending") or body.get("status") in ("paused", "proposal") or mode == InteractionMode.PLAN
    )
    return body


def turn(
    prompt: str,
    *,
    mode: InteractionMode | str = InteractionMode.CHAT,
    agent_mode: str | None = None,
    workspace: str | None = None,
    session_id: str | None = None,
    frontend: str = "cli",
    agent_caller: AgentCaller | None = None,
    verifier_caller: VerifyCaller | None = None,
) -> dict[str, Any]:
    """处理一次交互；支持把实际 caller 注入用例，避免在测试中调用真实模型。

    `agent_mode` 是领域角色（agentic_chat / mental_model / formal / uvm …），
    与交互方式正交：GUI 选 9 种模式，后端仍只走 chat/plan/verify 三条真路径。
    """
    selected = _mode(mode)
    preset = get_mode(agent_mode) if agent_mode else None
    text = str(prompt or "").strip()
    if not text:
        result = _empty_result(selected, session_id)
        result["interaction"].update({"frontend": frontend, "agent_mode": preset.id if preset else ""})
        return result
    if selected == InteractionMode.VERIFY:
        from src.workbench.modes import router

        if verifier_caller is None:
            verifier_caller = router.run
        result = verifier_caller(text, mode="verify")
    else:
        caller = agent_caller or agent_mode_service.agent_turn
        config = _agent_config(selected, preset)
        current_session = str(session_id) if session_id else None
        result = caller(text, workspace=workspace, config=config, session_id=current_session)
    return _decorate(result, selected, frontend, preset)


def resume(
    session_id: str,
    *,
    workspace: str | None = None,
    approve: bool | None = None,
    answer: str = "",
    plan: str = "",
    frontend: str = "cli",
) -> dict[str, Any]:
    """继续既有 Agent/Harness 检查点。未提供的 resume 不允许调用。"""
    if not str(session_id or "").strip():
        raise ValueError("resume 需要已有 session_id")
    result = agent_mode_service.resume_turn(session_id, workspace=workspace, approve=approve, answer=answer, plan=plan)
    if isinstance(result.get("session"), dict):
        result["session"]["interaction_frontend"] = frontend
    return result


def pending_text(result: dict[str, Any]) -> str:
    pending = result.get("pending") or {}
    kind = str(pending.get("kind") or "")
    if kind == "approval":
        tool = pending.get("tool") or "待确认操作"
        reason = pending.get("reason") or "需要人工明确批准"
        return f"执行前审批：{tool} —— {reason}"
    if kind == "answer":
        return str(pending.get("question") or "需要补充信息")
    if kind == "plan":
        return "请审查候选计划；批准、修改后批准，或者拒绝"
    if result.get("status") == "proposal":
        return "产生的是候选提案，必须复核后才能当作验收证据"
    return ""


def model_configuration_label() -> str:
    """只读本地配置，报告缺失项；不连接模型、不读取或展示密钥内容。"""
    try:
        from config.settings import Settings

        config = Settings.get_instance().llm
        if not config.api_key:
            return "LLM_API_KEY 未设置：不能发起模型调用"
        return f"模型：{config.provider}/{config.model}（仅配置已读取，未测连通）"
    except Exception as exc:  # noqa: BLE001 配置读取不能拖垮整个桌面入口
        return f"模型配置读取失败：{type(exc).__name__}"


__all__ = ["InteractionMode", "model_configuration_label", "pending_text", "resume", "turn"]
