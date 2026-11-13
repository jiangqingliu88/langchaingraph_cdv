"""直接模式写入审计 —— 每次改/删记录前后 hash 与 diff。

不阻止写入（审批由 PermissionPolicy 负责），但保证事后可追溯、可回滚。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from ..zones import WorkspaceZones


def record_write(zones: WorkspaceZones, payload: Dict[str, Any],
                 action: str) -> None:
    if not zones.direct:
        return
    path = zones.harness_dir / "writes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "path": str(payload.get("path") or ""),
        "before_sha": str(payload.get("before_sha") or ""),
        "after_sha": str(payload.get("sha256") or ""),
        "diff": str(payload.get("diff") or "")[:8000],
    }
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


__all__ = ["record_write", "sha_text"]
