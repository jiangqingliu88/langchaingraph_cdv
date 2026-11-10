"""事件流 —— 每次状态迁移/LLM/工具/回填/压缩都落一行 JSONL。

同一份事件也是 UI 的实时流（`sink` 回调）与审计材料（磁盘上的 JSONL）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from ..zones import WorkspaceZones

EventSink = Callable[[Dict[str, Any]], None]


class EventLog:
    def __init__(self, zones: WorkspaceZones, session_id: str,
                 sink: Optional[EventSink] = None):
        self.path = zones.harness_dir / "sessions" / f"{session_id}.events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq = 0
        if self.path.is_file():
            try:
                with self.path.open(encoding="utf-8") as fh:
                    self.seq = sum(1 for _ in fh)
            except OSError:
                self.seq = 0
        self.sink = sink

    def emit(self, kind: str, **data: Any) -> Dict[str, Any]:
        self.seq += 1
        row = {"seq": self.seq,
               "ts": datetime.now(timezone.utc).isoformat(),
               "kind": kind, **data}
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if self.sink is not None:
            try:
                self.sink(row)
            except Exception:                     # noqa: BLE001 UI 回调不能拖垮循环
                pass
        return row
