"""子 Agent 上下文 —— 只装它需要的局部信息，不灌主 Agent 的全量历史。"""
from __future__ import annotations

from typing import Any, Dict

from .contract import SubagentContract

_LIMITS = {"project": 4000, "task": 4000, "total": 14000}


def _clip(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]"


def build_subagent_task(contract: SubagentContract, *,
                        project_context: str = "",
                        task_memory: str = "",
                        recent: str = "") -> str:
    scope = contract.scope or {}
    lines = [
        f"# SUBAGENT TASK {contract.task_id}",
        f"agent_type: {contract.agent_type}",
        f"parent: {contract.parent_task_id or '(none)'}",
        "",
        "## OBJECTIVE",
        contract.objective,
        "",
        "## SCOPE",
        f"- read: {', '.join(scope.get('read') or []) or '(none)'}",
        f"- write: {', '.join(scope.get('write') or []) or '(none)'}",
        "",
        "## CONSTRAINTS",
        *[f"- {c}" for c in contract.constraints],
        "",
        "## DELIVERABLES",
        *[f"- {d}" for d in contract.deliverables],
        "",
        "## ACCEPTANCE",
        *[f"- {a}" for a in contract.acceptance],
    ]
    if project_context:
        lines += ["", "## PROJECT CONTEXT", _clip(project_context,
                                                  _LIMITS["project"])]
    if task_memory:
        lines += ["", "## TASK MEMORY", _clip(task_memory, _LIMITS["task"])]
    if recent:
        lines += ["", "## RECENT", _clip(recent, 2000)]
    lines += [
        "",
        "## RULES",
        "- 只做本 contract 范围内的任务，不扩大 scope。",
        "- 结论必须有文件/行号或工具证据；不确定就写进 unresolved。",
        "- 不要互相调用其它子 Agent；完成/阻塞后调用 finish。",
        "- 如允许写，在 workspace 下写 result.json / findings.json 等交付物。",
        "- COMPLETED 只表示执行结束，不代表主 Agent 已接受结论。",
    ]
    return "\n".join(lines)[:_LIMITS["total"]]


__all__ = ["build_subagent_task"]
