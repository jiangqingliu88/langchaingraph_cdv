"""Case 关联视图的对外门面 —— 构建 / 读盘 / 落盘（JSON + Markdown + HTML）。

    from src.ir_plane.decision.case_view import build_case_view
    data = build_case_view(run_dir)

产物默认落在 `<run>/coverage/case_view.{json,md,html}`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .builder import SCHEMA, build_case_view as _build
from .render import write_reports


def build_case_view(run_dir: str | Path) -> Dict[str, Any]:
    return _build(run_dir)


def load_case_view(run_dir: str | Path) -> Dict[str, Any]:
    """读已落盘的 `coverage/case_view.json`；没有就现建一份（不写盘）。"""
    od = Path(run_dir)
    path = od / "coverage" / "case_view.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        doc = {}
    return doc if doc.get("schema") == SCHEMA else build_case_view(od)


def write_case_view(run_dir: str | Path, *, out_prefix: str | Path = None,
                    formats: bool = True) -> Dict[str, Any]:
    """构建并落盘；`formats=True` 同时产 Markdown / HTML（评审可直接贴/挂）。"""
    od = Path(run_dir)
    data = build_case_view(od)
    prefix = Path(out_prefix) if out_prefix else od / "coverage" / "case_view"
    try:
        prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix.with_suffix(".json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if formats:
            data["_reports"] = write_reports(data, prefix)
    except OSError:
        pass
    return data
