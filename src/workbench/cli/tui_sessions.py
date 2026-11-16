"""TUI 会话索引 —— 与 2.0 手册一致落在 `chipstack_artifacts/tui/sessions/`。

这里只存**名字 → session_id / mode / workspace** 的索引；真正的对话检查点仍在
`runtime_plane.session`。两层分开：删掉索引不会丢 Harness 会话，删掉会话也
不会让索引文件变成假证据。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.runtime_plane.core.project_layout import ProjectLayout, safe_name


def sessions_dir(workspace: str | Path | None = None) -> Path:
    layout = ProjectLayout.discover(workspace)
    path = layout.artifact_root / "tui" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(name: str, workspace: str | Path | None = None) -> Path:
    return sessions_dir(workspace) / f"{safe_name(name, default='session')}.json"


def save(name: str, *, session_id: str, mode: str = "chat",
         workspace: str | Path | None = None, agent_mode: str = "") -> Path:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    target = _path(name, workspace)
    prior = load(name, workspace) or {}
    doc = {
        "schema": "tui_session_v1",
        "name": name,
        "session_id": session_id,
        "mode": mode,
        "agent_mode": agent_mode or prior.get("agent_mode") or "",
        "workspace": str(Path(workspace or Path.cwd()).resolve()),
        "created_at": prior.get("created_at") or now,
        "updated_at": now,
    }
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def load(name: str, workspace: str | Path | None = None) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(_path(name, workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def list_sessions(workspace: str | Path | None = None) -> list[Dict[str, Any]]:
    rows = []
    for path in sorted(sessions_dir(workspace).glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    return rows


__all__ = ["sessions_dir", "save", "load", "list_sessions"]
