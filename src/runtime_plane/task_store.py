"""TaskStore —— 当前任务的持久化状态。

目录（`.signoffai/task/<task_id>/`）：

    goal.md               最终目标 / 验收标准
    plan.json             步骤与依赖
    todo.json             当前待办
    decisions.json        关键决策（为什么这么选）
    assumptions.json      假设与待确认项
    blockers.json         阻塞项（交还人工）
    task_memory.md        滚动摘要（给下一轮 LLM 的 C2/C3）
    completion_report.md  结束时的结果报告

这些文件是**跨进程恢复**的真源：会话 JSON 保存聊天，TaskStore 保存“任务现在
处于什么状态、为什么”。两者独立，任何一方丢失都能从另一方重建。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.runtime_plane.core.runtime.atomic import atomic_write_json, atomic_write_text

from .workspace_manager import WorkspaceZones
from .facts import FactStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, zones: WorkspaceZones, task_id: str):
        self.root = zones.harness_dir / "task" / str(task_id)
        self.facts = FactStore(zones, task_id)

    def ensure(self) -> "TaskStore":
        self.root.mkdir(parents=True, exist_ok=True)
        return self

    # ── 读写 ──────────────────────────────────────────────────────────────

    def _json_path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def read_json(self, name: str, default: Any) -> Any:
        try:
            doc = json.loads(self._json_path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        return doc

    def write_json(self, name: str, value: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._json_path(name), value)

    def write_text(self, name: str, value: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.root / f"{name}.md", value)

    def _bump(self) -> int:
        meta = self.read_json("meta", {})
        version = int(meta.get("version") or 0) + 1
        meta["version"] = version
        meta["updated_at"] = _now()
        self.write_json("meta", meta)
        return version

    def append_event(self, kind: str, **data: Any) -> None:
        """Task 级事件日志（事件事实源；snapshot 是可恢复投影）。"""
        self.root.mkdir(parents=True, exist_ok=True)
        row = {"event_id": f"E{time.time_ns()}",
               "ts": _now(), "kind": kind, **data}
        with (self.root / "events.jsonl").open("a", encoding="utf-8",
                                               newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _args_hash(args: Any) -> str:
        text = json.dumps(args or {}, sort_keys=True, ensure_ascii=False,
                          default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _append_invocation(self, row: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "invocations.jsonl").open(
                "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def begin_invocation(self, tool: str, args: Any, *,
                         side_effect: bool = False) -> str:
        """工具调用前落 RUNNING；崩溃后这里会留下未完成记录。"""
        inv_id = f"I{uuid.uuid4().hex[:10]}"
        self._append_invocation({
            "invocation_id": inv_id, "tool": str(tool),
            "args_hash": self._args_hash(args),
            "status": "RUNNING", "side_effect": bool(side_effect),
            "started_at": _now(),
        })
        return inv_id

    def finish_invocation(self, inv_id: str, status: str, *,
                          result_hash: str = "", error: str = "") -> None:
        self._append_invocation({
            "invocation_id": inv_id, "status": str(status),
            "result_hash": str(result_hash), "error": str(error)[:500],
            "finished_at": _now(),
        })

    def invocations(self) -> List[Dict[str, Any]]:
        path = self.root / "invocations.jsonl"
        latest: Dict[str, Dict[str, Any]] = {}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            inv = str(row.get("invocation_id") or "")
            if not inv:
                continue
            merged = dict(latest.get(inv) or {})
            merged.update(row)
            latest[inv] = merged
        return sorted(latest.values(), key=lambda r: str(r.get("started_at") or ""))

    def pending_invocations(self) -> List[Dict[str, Any]]:
        return [r for r in self.invocations() if r.get("status") == "RUNNING"]

    def last_invocation(self, tool: str, args_hash: str) -> Dict[str, Any]:
        for row in reversed(self.invocations()):
            if row.get("tool") == tool and row.get("args_hash") == args_hash:
                return row
        return {}

    def recover_invocations(self) -> List[Dict[str, Any]]:
        """进程重启时把 RUNNING 标成 UNKNOWN（副作用未知）。"""
        pending = self.pending_invocations()
        for row in pending:
            self.finish_invocation(
                str(row.get("invocation_id")), "UNKNOWN",
                error="process recovery: prior invocation did not finish")
        if pending:
            self.append_event("invocation.recover",
                              count=len(pending),
                              tools=[r.get("tool") for r in pending])
        return pending

    # ── 目标 / 计划 / 待办 ────────────────────────────────────────────────

    def add_fact(self, kind: str, text: str, **kwargs: Any) -> Dict[str, Any]:
        for row in self.facts.list():
            if row.get("kind") == kind and row.get("text") == str(text):
                return row
        row = self.facts.append(kind, str(text), **kwargs)
        self._bump()
        self.append_event("fact.add", fact_id=row["id"], fact_kind=kind)
        return row

    def set_goal(self, goal: str, acceptance: List[str] | None = None) -> None:
        self.write_text("goal", f"# GOAL\n\n{goal}\n\n## ACCEPTANCE\n\n"
                                + "\n".join(f"- {a}" for a in (acceptance or [])))
        meta = self.read_json("meta", {})
        meta.update({"goal": goal, "acceptance": acceptance or []})
        self.write_json("meta", meta)
        self.add_fact("requirement", goal, approved=True)
        self._bump()
        self.append_event("goal.set", goal=goal)

    def goal(self) -> Dict[str, Any]:
        return self.read_json("meta", {})

    def set_plan(self, steps: List[Dict[str, Any]]) -> None:
        self.write_json("plan", {"steps": steps, "updated_at": _now()})
        self._bump()
        self.append_event("plan.set", steps=[s.get("id") for s in steps])

    def plan(self) -> List[Dict[str, Any]]:
        return list(self.read_json("plan", {}).get("steps") or [])

    def set_todos(self, todos: List[Any]) -> None:
        self.write_json("todo", {"todos": todos, "updated_at": _now()})
        self._bump()
        self.append_event("todo.set", count=len(todos))

    def todos(self) -> List[Any]:
        return list(self.read_json("todo", {}).get("todos") or [])

    # ── 决策 / 假设 / 阻塞 ────────────────────────────────────────────────

    def add_decision(self, decision: str, *, reason: str = "",
                     evidence: str = "", status: str = "ACCEPTED") -> None:
        rows = list(self.read_json("decisions", []))
        row = {"id": f"D{len(rows) + 1:03d}", "decision": decision,
               "reason": reason, "evidence": evidence, "status": status,
               "at": _now()}
        rows.append(row)
        self.write_json("decisions", rows)
        self.add_fact("decision", decision, ref=row["id"], evidence=evidence,
                      approved=status == "ACCEPTED")
        self._bump()
        self.append_event("decision.add", decision_id=row["id"],
                          status=status)

    def decisions(self) -> List[Dict[str, Any]]:
        return list(self.read_json("decisions", []))

    def add_assumption(self, text: str) -> None:
        rows = list(self.read_json("assumptions", []))
        rows.append({"text": text, "at": _now()})
        self.write_json("assumptions", rows)

    def assumptions(self) -> List[Dict[str, Any]]:
        return list(self.read_json("assumptions", []))

    def add_blocker(self, text: str) -> None:
        rows = list(self.read_json("blockers", []))
        rows.append({"text": text, "at": _now()})
        self.write_json("blockers", rows)
        self.add_fact("blocker", text)
        self._bump()
        self.append_event("blocker.add", text=text)

    def blockers(self) -> List[Dict[str, Any]]:
        return list(self.read_json("blockers", []))

    # ── 项目 / 子任务结果 ─────────────────────────────────────────────────

    def write_project_context(self, text: str) -> None:
        self.write_text("project_context", text)

    def project_context(self) -> str:
        path = self.root / "project_context.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def add_subagent_result(self, result: Dict[str, Any]) -> None:
        rows = list(self.read_json("subagents", []))
        rows.append({"task_id": result.get("task_id", ""),
                     "status": result.get("status", ""),
                     "summary": str(result.get("summary") or "")[:2000],
                     "artifacts": list(result.get("artifacts") or []),
                     "unresolved": list(result.get("unresolved") or []),
                     "at": _now()})
        self.write_json("subagents", rows)
        self.add_fact("evidence",
                      f"subagent {result.get('task_id')}: {result.get('summary', '')[:200]}",
                      ref=str(result.get("task_id") or ""))
        self._bump()
        self.append_event("subagent.result", task_id=result.get("task_id"),
                          status=result.get("status"))

    def subagent_results(self) -> List[Dict[str, Any]]:
        return list(self.read_json("subagents", []))

    # ── 渲染 ──────────────────────────────────────────────────────────────

    def render_memory(self) -> str:
        """C2/C3 的确定性摘要（不调 LLM，不丢状态）。"""
        meta = self.goal()
        steps = self.plan()
        done = [s for s in steps if s.get("status") == "done"]
        active = [s for s in steps if s.get("status") in ("active", "pending")]
        lines = [
            "# TASK MEMORY", "",
            "## GOAL", str(meta.get("goal") or "(none)"), "",
            "## COMPLETED",
            *(f"- {s.get('id')}: {s.get('title')}" for s in done),
            "",
            "## CURRENT / NEXT",
            *(f"- {s.get('id')}: {s.get('title')} [{s.get('status')}]"
              for s in active[:8]),
            "",
            "## DECISIONS",
            *(f"- {d.get('id')}: {d.get('decision')} ({d.get('status')})"
              for d in self.decisions()[-8:]),
            "",
            "## BLOCKERS",
            *(f"- {b.get('text')}" for b in self.blockers()[-8:]),
            "",
            "## SUBAGENT RESULTS",
            *(f"- {r.get('task_id')}: {r.get('status')} {r.get('summary', '')[:160]}"
              for r in self.subagent_results()[-6:]),
            "",
            self.facts.render(),
        ]
        return "\n".join(lines).strip() + "\n"

    def write_completion(self, status: str, summary: str,
                         evidence: Dict[str, Any] | None = None) -> None:
        body = [
            "# COMPLETION REPORT", "",
            f"status: {status}", "", summary, "",
            "## EVIDENCE", json.dumps(evidence or {}, ensure_ascii=False, indent=2),
        ]
        self.write_text("completion_report", "\n".join(body))
        self.write_json("completion", {"status": status, "summary": summary,
                                       "evidence": evidence or {},
                                       "at": _now()})

    def consistency(self) -> List[str]:
        """恢复前的一致性检查：坏 JSON、重复/悬空步骤、空版本。"""
        from ..planner.dag import validate as validate_dag

        issues: List[str] = []
        for name in ("meta", "plan", "todo", "decisions", "blockers",
                     "subagents"):
            path = self._json_path(name)
            if not path.is_file():
                continue
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                issues.append(f"{name}.json 读不出：{exc}")
        if not self.facts.path.is_file() and self.goal().get("goal"):
            issues.append("facts.jsonl 缺失（需求/决策未落到不可丢失层）")
        if int(self.goal().get("version") or 0) <= 0:
            issues.append("TaskStore version 为空（写入未记账）")
        issues.extend(validate_dag(self.plan()))
        return issues

    def snapshot(self) -> Dict[str, Any]:
        return {
            "task_id": self.root.name,
            "goal": self.goal(),
            "plan": self.plan(),
            "todos": self.todos(),
            "decisions": self.decisions(),
            "assumptions": self.assumptions(),
            "blockers": self.blockers(),
            "subagents": self.subagent_results(),
            "facts": self.facts.list(),
            "version": int(self.goal().get("version") or 0),
            "memory": self.render_memory(),
        }


__all__ = ["TaskStore"]
