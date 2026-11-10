"""main/ 的只读视图 —— 只暴露读、列、指纹；没有写方法。"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from ..zones import WorkspaceZones


class MainView:
    def __init__(self, zones: WorkspaceZones):
        self._zones = zones

    @property
    def root(self) -> Path:
        return self._zones.main

    def read(self, rel: str) -> str:
        return self._zones.read(rel, zone="main")

    def path(self, rel: str) -> Path:
        return self._zones.main_path(rel, must_exist=True)

    def list(self, limit: int = 500) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rows.append({"path": path.relative_to(self.root).as_posix(),
                         "size": str(path.stat().st_size)})
            if len(rows) >= limit:
                break
        return rows

    def fingerprint(self) -> str:
        return self._zones.fingerprint("main")
