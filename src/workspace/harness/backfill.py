"""结果回填 —— tool 结果既进消息（下一次 LLM 能看到），也进工作状态（Gate 能看到）。"""
from __future__ import annotations

import json
from typing import Any, Dict

from ..zones import WorkspaceZones
from .session import Session


def record_assistant(session: Session, decision: Dict[str, Any], call_id: str) -> Dict[str, Any]:
    tool = str(decision.get("tool") or "")
    args = decision.get("args") or {}
    message = session.append(
        "assistant", str(decision.get("thought") or ""),
        tool_calls=[{
            "id": call_id, "type": "function",
            "function": {"name": tool,
                         "arguments": json.dumps(args, ensure_ascii=False,
                                                 default=str)},
        }])
    if decision.get("plan"):
        message["plan"] = str(decision["plan"])
    return message


def _payload(result: Any, limit: int = 8_000) -> Any:
    if not isinstance(result, dict):
        return str(result)[:limit]
    text = json.dumps(result, ensure_ascii=False, default=str)
    return result if len(text) <= limit else {
        "truncated": True, "chars": len(text), "head": text[:limit]}


def record_result(session: Session, call_id: str, tool: str,
                  result: Any, zones: WorkspaceZones,
                  args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    args = args or {}
    session.append("tool", _payload(result), tool_call_id=call_id, name=tool)
    working = session.working
    working["changed_files"] = zones.changed_files()
    working["last_observation"] = str(result)[:500]
    _apply_working(tool, result, args, working)
    return {"message_count": len(session.messages),
            "changed_files": len(working["changed_files"])}


def _apply_working(tool: str, result: Any, args: Dict[str, Any],
                   working: Dict[str, Any]) -> None:
    payload = result.get("result") if isinstance(result, dict) else None
    if tool in ("run_verify", "collect_evidence") and isinstance(payload, dict):
        evidence = payload.get("evidence") if tool == "run_verify" else payload
        _set_eda(working, evidence or {}, payload)
    elif tool == "compare_evidence" and isinstance(payload, dict):
        working.setdefault("eda", {})["comparison"] = payload
    else:
        _apply_basic(tool, payload, args, working)


def _apply_basic(tool: str, payload: Any, args: Dict[str, Any],
                 working: Dict[str, Any]) -> None:
    if tool == "run_shell" and isinstance(payload, dict):
        evidence = working.setdefault("evidence", {"commands": [], "logs": []})
        evidence.setdefault("commands", []).append({
            "cmd": str(payload.get("command")),
            "exit_code": int(payload.get("exit_code", 1)),
            "log": str(payload.get("log") or ""),
        })
        if payload.get("log"):
            evidence.setdefault("logs", []).append(str(payload["log"]))
    elif tool == "read_file" and isinstance(payload, str):
        working.setdefault("reads", {})[str(args.get("path") or "")] = len(payload)
    elif tool == "todo_write":
        todos = args.get("todos")
        if isinstance(todos, list):
            working["todos"] = todos
    elif tool == "propose":
        questions = args.get("open_questions") or []
        if isinstance(questions, list):
            existing = list(working.get("open_questions") or [])
            working["open_questions"] = list(dict.fromkeys(
                existing + [str(q) for q in questions]))
    else:
        _apply_record(tool, payload, args, working)


def _apply_record(tool: str, payload: Any, args: Dict[str, Any],
                  working: Dict[str, Any]) -> None:
    """列表型工作状态：子 agent / 后台任务 / 证据导出。"""
    if tool == "spawn_subagent" and isinstance(payload, dict):
        working.setdefault("subagents", []).append({
            "task": str(args.get("task") or ""),
            "session_id": payload.get("session_id", ""),
            "status": payload.get("status", ""),
        })
    elif tool == "job_start" and isinstance(payload, dict):
        working.setdefault("jobs", []).append({
            "job_id": payload.get("job_id", ""),
            "log": payload.get("log", ""),
        })
    elif tool == "export_evidence" and isinstance(payload, dict):
        _add_export(working, payload)


def _set_eda(working: Dict[str, Any], evidence: Dict[str, Any],
             payload: Dict[str, Any]) -> None:
    eda = working.setdefault("eda", {})
    if not eda.get("before"):
        eda["before"] = evidence
    eda["after"] = evidence
    eda["target"] = evidence.get("target") or eda.get("target", 0)
    eda["run_dir"] = evidence.get("run_dir") or payload.get("run_dir", "")
    if payload.get("log"):
        eda["log"] = payload["log"]
    if payload.get("exit_code") is not None:
        eda["exit_code"] = payload["exit_code"]
    eda["functional_met"] = bool(evidence.get("functional_met"))
    if isinstance(payload.get("export"), dict):
        _add_export(working, payload["export"])


def _add_export(working: Dict[str, Any], payload: Dict[str, Any]) -> None:
    row = {"zip_path": payload.get("zip_path", ""),
           "sha256": payload.get("sha256", ""),
           "files": payload.get("files", 0),
           "complete": bool(payload.get("complete")),
           "ok": bool(payload.get("ok"))}
    working.setdefault("exports", []).append(row)
