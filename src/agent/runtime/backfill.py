"""结果回填 —— tool 结果既进消息（下一次 LLM 能看到），也进工作状态（Gate 能看到）。"""
from __future__ import annotations

import json
from typing import Any, Dict

from src.runtime.workspace_manager import WorkspaceZones
from src.runtime.session import Session


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
    session.append("tool", _payload(result), tool_call_id=call_id, name=tool,
                   args=args)
    working = session.working
    working["last_observation"] = str(result)[:500]
    _apply_working(tool, result, args, working)
    if zones.direct:
        # 直接模式只报**本会话工具改过的文件**；git 工作区可能本来就脏。
        changes = working.get("session_changes") or {}
        working["changed_files"] = [
            {"path": path, "action": action, "sha256": ""}
            for path, action in sorted(changes.items())]
    else:
        working["changed_files"] = zones.changed_files()
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


def _mark_change(tool: str, payload: Any, args: Dict[str, Any],
                 working: Dict[str, Any]) -> None:
    """记录本会话通过工具产生的文件变更（直接模式的 changed_files）。"""
    if tool not in ("write_file", "delete_file", "str_replace"):
        return
    if not isinstance(payload, dict):
        return
    path = str(payload.get("path") or args.get("path") or "")
    if not path:
        return
    action = ("delete" if tool == "delete_file"
              else "add" if payload.get("created") else "modify")
    changes = working.setdefault("session_changes", {})
    if action == "delete":
        if changes.get(path) == "add":
            changes.pop(path, None)              # 新建又删掉 = 净零
        else:
            changes[path] = "delete"
    elif changes.get(path) != "add":
        changes[path] = action


def _apply_basic(tool: str, payload: Any, args: Dict[str, Any],
                 working: Dict[str, Any]) -> None:
    _mark_change(tool, payload, args, working)
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
    elif tool == "run_stage" and isinstance(payload, dict):
        working.setdefault("runs", []).append({
            "role": payload.get("role", ""),
            "run_dir": payload.get("run_dir", ""),
            "ok": bool(payload.get("ok", payload.get("success"))),
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
