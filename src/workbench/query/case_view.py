"""Case View 只读查询 —— 页面只渲染生成物，不重算、不写盘。

与 `src/workbench/ARCHITECTURE.md` 的冻结契约一致：本层**不 import Qt**，
也不 import `src.tools.*`（页面经 `bridge/catalog.py` 的工具拿数据，或直接
读 run 目录里已经落盘的 JSON）。写操作走 `src.interfaces.api.case_view_service`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

#: 生成物相对路径 —— 与 `case_view_service.ARTIFACTS` 同一份名字。
FILES = {
    "case_ir": "coverage/case_ir.json",
    "cell_matrix": "coverage/cell_matrix.json",
    "evd": "coverage/evd.json",
    "case_view": "coverage/case_view.json",
    "gates": "coverage/gates.json",
    "evidence_manifest": "coverage/evidence_manifest.json",
}


def _read(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def read_case_view(run_dir: str | Path) -> Dict[str, Any]:
    return _read(Path(run_dir) / FILES["case_view"])


def read_cell_matrix(run_dir: str | Path) -> Dict[str, Any]:
    return _read(Path(run_dir) / FILES["cell_matrix"])


def read_evd(run_dir: str | Path) -> Dict[str, Any]:
    return _read(Path(run_dir) / FILES["evd"])


def read_case_gates(run_dir: str | Path) -> Dict[str, Any]:
    doc = _read(Path(run_dir) / FILES["gates"])
    if not doc:
        return {}
    return {
        "verdict": doc.get("verdict", ""),
        "counts": doc.get("counts") or {},
        "blockers": list(doc.get("blockers") or [])[:20],
        "warnings": list(doc.get("warnings") or [])[:20],
        "infos": list(doc.get("infos") or [])[:20],
    }


def list_case_artifacts(run_dir: str | Path) -> List[Dict[str, Any]]:
    """每份 Case 生成物在不在 —— 页面顶部“产物清单”用。"""
    root = Path(run_dir)
    out: List[Dict[str, Any]] = []
    for name, rel in FILES.items():
        path = root / rel
        doc = _read(path) if path.is_file() else {}
        out.append({"name": name, "path": rel, "exists": path.is_file(),
                    "schema": str(doc.get("schema") or "")})
    return out


__all__ = [
    "FILES", "list_case_artifacts", "read_case_gates", "read_case_view",
    "read_cell_matrix", "read_evd",
]
