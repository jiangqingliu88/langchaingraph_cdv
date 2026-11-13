"""Task DAG —— 依赖校验、并行层、下游失效。

Planner 维护依赖；Agent 只能提出任务，不能随意改全局依赖。
"""
from __future__ import annotations

from typing import Any, Dict, List, Set


def _ids(steps: List[Dict[str, Any]]) -> List[str]:
    return [str(s.get("id") or "") for s in steps]


def validate(steps: List[Dict[str, Any]]) -> List[str]:
    issues: List[str] = []
    ids = _ids(steps)
    if len(ids) != len(set(ids)):
        issues.append("步骤 id 重复")
    known = set(ids)
    for step in steps:
        for dep in step.get("depends_on") or []:
            if str(dep) not in known:
                issues.append(f"{step.get('id')} 依赖未知步骤 {dep}")
    # 环检测（DFS）
    graph = {str(s.get("id")): [str(d) for d in (s.get("depends_on") or [])]
             for s in steps}
    visiting: Set[str] = set()
    done: Set[str] = set()

    def _visit(node: str) -> bool:
        if node in visiting:
            return False
        if node in done:
            return True
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph and not _visit(dep):
                return False
        visiting.discard(node)
        done.add(node)
        return True

    for node in graph:
        if not _visit(node):
            issues.append(f"依赖成环：{node}")
            break
    return issues


def ready(steps: List[Dict[str, Any]]) -> List[str]:
    done = {str(s.get("id")) for s in steps if s.get("status") == "done"}
    return [str(s.get("id")) for s in steps
            if s.get("status") == "pending"
            and all(str(d) in done for d in (s.get("depends_on") or []))]


def layers(steps: List[Dict[str, Any]]) -> List[List[str]]:
    """拓扑分层：同一层可并行。"""
    remaining = {str(s.get("id")): set(str(d) for d in (s.get("depends_on") or []))
                 for s in steps}
    out: List[List[str]] = []
    done: Set[str] = set()
    while remaining:
        layer = [sid for sid, deps in remaining.items() if deps <= done]
        if not layer:
            break
        out.append(sorted(layer))
        done.update(layer)
        for sid in layer:
            remaining.pop(sid, None)
    return out


def downstream_of(steps: List[Dict[str, Any]], step_id: str) -> List[str]:
    """所有直接/间接依赖 step_id 的步骤（失败后需要重跑的下游）。"""
    children: Dict[str, List[str]] = {}
    for step in steps:
        for dep in step.get("depends_on") or []:
            children.setdefault(str(dep), []).append(str(step.get("id")))
    out: List[str] = []
    stack = list(children.get(str(step_id), []))
    seen: Set[str] = set()
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        out.append(node)
        stack.extend(children.get(node, []))
    return out


__all__ = ["validate", "ready", "layers", "downstream_of"]
