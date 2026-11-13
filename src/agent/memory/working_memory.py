"""WorkingMemory —— 从 Session 投影出 C3（当前推理/操作/问题）。

不新增真源：所有字段都来自已经持久化的 `Session`；这里只做**稳定排序与摘要**，
保证每轮喂给 LLM 的工作上下文是同一形状。
"""
from __future__ import annotations

from typing import Any, Dict, List


def working_summary(session: Any) -> Dict[str, Any]:
    working = getattr(session, "working", {}) or {}
    evidence = working.get("evidence") or {}
    eda = working.get("eda") or {}
    subgoals = list(getattr(session, "subgoals", []) or [])
    return {
        "task": getattr(session, "task", ""),
        "state": getattr(session, "state", ""),
        "round": getattr(session, "round", 0),
        "plan": getattr(session, "plan", ""),
        "subgoals": [{"id": s.get("id"), "title": s.get("title"),
                      "status": s.get("status"),
                      "summary": str(s.get("summary") or "")[:300]}
                     for s in subgoals],
        "active_subgoal": getattr(session, "active_subgoal", ""),
        "open_questions": list(working.get("open_questions") or []),
        "todos": list(working.get("todos") or [])[-12:],
        "changed_files": list(working.get("changed_files") or [])[-20:],
        "commands": list(evidence.get("commands") or [])[-6:],
        "logs": list(evidence.get("logs") or [])[-6:],
        "eda": eda,
        "last_error": str(getattr(session, "last_error", "") or "")[:500],
        "subagents": list(working.get("subagents") or [])[-6:],
    }


def render_working(summary: Dict[str, Any]) -> str:
    lines = [
        "# WORKING CONTEXT",
        f"state: {summary.get('state')}  round: {summary.get('round')}",
    ]
    plan = str(summary.get("plan") or "")
    if plan:
        lines += ["", "## PLAN", plan[:1200]]
    subgoals: List[Dict[str, Any]] = summary.get("subgoals") or []
    if subgoals:
        lines += ["", "## SUBGOALS"]
        lines += [f"- {s['id']} {s['status']}: {s['title']}" for s in subgoals]
    if summary.get("open_questions"):
        lines += ["", "## OPEN QUESTIONS",
                  *[f"- {q}" for q in summary["open_questions"][:8]]]
    if summary.get("todos"):
        lines += ["", "## TODOS", *[f"- {t}" for t in summary["todos"]]]
    if summary.get("changed_files"):
        lines += ["", "## CHANGED FILES",
                  *[f"- {r.get('action', '?')} {r.get('path')}"
                    for r in summary["changed_files"]]]
    if summary.get("eda"):
        lines += ["", "## EDA", str(summary["eda"])[:1200]]
    if summary.get("last_error"):
        lines += ["", "## LAST ERROR", str(summary["last_error"])]
    if summary.get("subagents"):
        lines += ["", "## SUBAGENT RESULTS",
                  *[f"- {r.get('task')}: {r.get('status')}"
                    for r in summary["subagents"]]]
    return "\n".join(lines).strip() + "\n"


__all__ = ["working_summary", "render_working"]
