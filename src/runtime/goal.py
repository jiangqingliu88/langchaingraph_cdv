"""Goal + rounds —— 一次任务是一个 goal；一轮失败（比如证据不全）进入下一轮。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_goal(task: str, max_rounds: int = 2) -> Dict[str, Any]:
    return {"objective": task, "status": "active", "max_rounds": int(max_rounds),
            "current_round": 1, "rounds": [],
            "created_at": _now(), "updated_at": _now()}


def start_round(goal: Dict[str, Any], feedback: str = "") -> Dict[str, Any]:
    rounds: List[Dict[str, Any]] = goal.setdefault("rounds", [])
    index = len(rounds) + 1
    goal["current_round"] = index
    goal["status"] = "active"
    row = {"index": index, "state": "running", "feedback": feedback,
           "steps": 0, "started_at": _now(), "ended_at": "",
           "summary": ""}
    rounds.append(row)
    goal["updated_at"] = _now()
    return row


def current_round(goal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rounds = goal.get("rounds") or []
    return rounds[-1] if rounds else None


def finish_round(goal: Dict[str, Any], state: str, summary: str = "") -> None:
    row = current_round(goal)
    if row is None:
        return
    row.update({"state": state, "summary": summary, "ended_at": _now()})
    goal["updated_at"] = _now()


def finish_goal(goal: Dict[str, Any], status: str, summary: str = "") -> None:
    goal["status"] = status
    goal["summary"] = summary
    goal["updated_at"] = _now()


def can_retry(goal: Dict[str, Any]) -> bool:
    return len(goal.get("rounds") or []) < int(goal.get("max_rounds") or 1)


def goal_line(goal: Dict[str, Any]) -> str:
    return (f"goal={goal.get('status')} round={goal.get('current_round')}"
            f"/{goal.get('max_rounds')}")
