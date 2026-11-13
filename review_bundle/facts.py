"""Immutable Facts —— 压缩不能删的事实层。

只追加、不修改：用户要求、已批准决策、确定性检查结果、证据引用、阻塞项、
人工审批。上下文压缩可以丢解释性文字，但这些 fact 每轮都会重新注入（C2）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ...zones import WorkspaceZones

KINDS = {"requirement", "decision", "evidence", "blocker", "approval",
         "constraint"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FactStore:
    def __init__(self, zones: WorkspaceZones, task_id: str):
        self.path = zones.harness_dir / "task" / str(task_id) / "facts.jsonl"

    def _ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, text: str, *, ref: str = "",
               evidence: str = "", approved: bool = False) -> Dict[str, Any]:
        self._ensure()
        existing = self.list()
        row = {
            "id": f"F{len(existing) + 1:04d}",
            "kind": kind if kind in KINDS else "constraint",
            "text": str(text),
            "ref": str(ref),
            "evidence": str(evidence),
            "approved": bool(approved),
            "at": _now(),
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return row

    def list(self) -> List[Dict[str, Any]]:
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        rows: List[Dict[str, Any]] = []
        for line in text.splitlines():
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict) and doc.get("id"):
                rows.append(doc)
        return rows

    def ids(self) -> List[str]:
        return [str(row["id"]) for row in self.list()]

    def render(self, limit: int = 40) -> str:
        rows = self.list()[-limit:]
        if not rows:
            return ""
        lines = ["## IMMUTABLE FACTS (must survive compaction)"]
        for row in rows:
            extra = f" ref={row['ref']}" if row.get("ref") else ""
            lines.append(f"- {row['id']} [{row['kind']}] {row['text']}{extra}")
        return "\n".join(lines)


__all__ = ["FactStore", "KINDS"]
