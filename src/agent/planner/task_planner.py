"""Task planner —— 结构化步骤与依赖（确定性，不调 LLM）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .dag import validate as _validate_dag


def normalize_steps(steps: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for index, raw in enumerate(steps or [], 1):
        if not isinstance(raw, dict):
            continue
        out.append({
            "id": str(raw.get("id") or f"S{index}"),
            "title": str(raw.get("title") or f"step {index}"),
            "status": str(raw.get("status") or "pending"),
            "depends_on": [str(d) for d in (raw.get("depends_on") or [])],
            "success": str(raw.get("success") or ""),
            "attempts": int(raw.get("attempts") or 0),
            "summary": str(raw.get("summary") or ""),
        })
    return out


def new_plan(goal: str, steps: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    normalized = normalize_steps(steps)
    if not normalized:
        normalized = [{"id": "S1", "title": goal, "status": "pending",
                       "depends_on": [], "success": "", "attempts": 0,
                       "summary": ""}]
    return {"goal": str(goal), "steps": normalized, "replans": [],
            "dag_issues": _validate_dag(normalized)}


def ready_steps(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    done = {s["id"] for s in plan.get("steps") or [] if s.get("status") == "done"}
    return [s for s in plan.get("steps") or []
            if s.get("status") == "pending"
            and all(d in done for d in s.get("depends_on") or [])]


def next_step(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    active = [s for s in plan.get("steps") or [] if s.get("status") == "active"]
    if active:
        return active[0]
    ready = ready_steps(plan)
    if not ready:
        return None
    ready[0]["status"] = "active"
    return ready[0]


def mark(plan: Dict[str, Any], step_id: str, status: str,
         summary: str = "") -> None:
    for step in plan.get("steps") or []:
        if step.get("id") != step_id:
            continue
        step["status"] = status
        step["summary"] = str(summary)
        if status == "active":
            step["attempts"] = int(step.get("attempts") or 0) + 1
        return


def render(plan: Dict[str, Any]) -> str:
    lines = [f"# PLAN: {plan.get('goal')}"]
    for step in plan.get("steps") or []:
        deps = ",".join(step.get("depends_on") or [])
        suffix = f" (after {deps})" if deps else ""
        lines.append(f"- {step.get('id')} [{step.get('status')}] "
                     f"{step.get('title')}{suffix}")
    return "\n".join(lines)


__all__ = ["new_plan", "normalize_steps", "ready_steps", "next_step",
           "mark", "render"]
