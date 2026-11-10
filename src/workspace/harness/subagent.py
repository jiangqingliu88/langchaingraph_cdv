"""受限子 harness —— 同一个 staging、独立 session；不能再派子 agent。"""
from __future__ import annotations

from typing import Any, Dict


def run_subagent(parent, task: str, *, max_steps: int = 6) -> Dict[str, Any]:
    from .harness import Harness, HarnessConfig

    if not parent.config.allow_subagent:
        return {"ok": False, "error": "subagent 被禁用（当前 harness allow_subagent=False）"}
    child_config = HarnessConfig(
        max_steps=max(1, min(int(max_steps), parent.config.max_steps)),
        max_rounds=1,
        max_tool_errors=parent.config.max_tool_errors,
        max_tokens=parent.config.max_tokens,
        plan_first=False,
        require_plan_approval=False,
        require_exec_approval=parent.config.require_exec_approval,
        allow_subagent=False,
        emit_proposal=False,
        compaction=parent.config.compaction,
        event_sink=None,
    )
    child = Harness(parent.zones, config=child_config,
                    planner=parent.planner, tools=parent.sandbox)
    result = child.run(task)
    projection = child.session.projection()
    return {
        "ok": result.get("status") in ("proposal", "finished_no_proposal"),
        "session_id": projection["session_id"],
        "status": result.get("status"),
        "state": projection["state"],
        "changed_files": projection["changed_files"],
        "summary": (result.get("proposal", {}) or {}).get("open_questions", []),
    }
