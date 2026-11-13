"""Run 视图的只读查询 —— 不 import Qt，不跑 EDA。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.runtime_plane.core.contracts.jsonl import read_jsonl


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def list_soc_runs(base: str | Path = ".") -> List[Dict[str, Any]]:
    """SoC run 列表（只读；底层复用 app service）。"""
    from src.workbench.api.soc_service import list_soc_runs as _impl
    return _impl(base)


def run_summary(run_root: str | Path) -> Dict[str, Any]:
    from src.workbench.api.soc_service import run_summary as _impl
    return _impl(run_root)


def read_events(run_root: str | Path,
                event_type: str = "") -> List[Dict[str, Any]]:
    rows = read_jsonl(Path(run_root) / "docs" / "events.jsonl")
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    return rows


def read_artifact_index(run_root: str | Path) -> Dict[str, Any]:
    return _read_json(Path(run_root) / "artifacts" / "artifacts.json")
