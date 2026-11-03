"""Case View —— 应用服务 facade（CLI 与 Workbench 共用）。

这一层只做**编排**：读 run 目录里的生成物、必要时触发一次重建，然后把数据
原样交出去。它不解析业务语义 —— 语义在 tools 层（`humanview.case_ir` /
`case_associate_view` / `coverage_tools.{cell_matrix,evd}`）。

为什么要有这一层：ARCHITECTURE.md §1.3 声明了「CLI 与 Workbench 共用服务入口」。
Case View 是新增能力，**不新增绕过路径**：Workbench 经 `workbench/query` 读、
经这里写；CLI 也走这里，于是两边看到的永远是同一份生成物。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

ARTIFACTS = {
    "case_ir": "coverage/case_ir.json",
    "case_tp": "coverage/case_tp.json",
    "cell_matrix": "coverage/cell_matrix.json",
    "evd": "coverage/evd.json",
    "case_view": "coverage/case_view.json",
    "gates": "coverage/gates.json",
    "tp_matrix": "coverage/tp_matrix.json",
    "tp_cov_evidence": "coverage/tp_cov_evidence.json",
    "evidence_manifest": "coverage/evidence_manifest.json",
}


def _run_dir(path: str | Path) -> Path:
    p = Path(path)
    return p.parent if p.name == "coverage" else p


def _read(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def artifact(run_dir: str | Path, name: str) -> Dict[str, Any]:
    """读一份生成物（名字见 `ARTIFACTS`）。**只读**，缺失返回空 dict。"""
    rel = ARTIFACTS.get(name)
    return _read(_run_dir(run_dir) / rel) if rel else {}


def list_artifacts(run_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """每份生成物的存在性与 schema —— Workbench 的“产物清单”用。"""
    od = _run_dir(run_dir)
    out: Dict[str, Dict[str, Any]] = {}
    for name, rel in ARTIFACTS.items():
        path = od / rel
        doc = _read(path) if path.is_file() else {}
        out[name] = {"exists": path.is_file(), "schema": str(doc.get("schema") or ""),
                     "path": rel}
    return out


def case_view(run_dir: str | Path, *, rebuild: bool = False) -> Dict[str, Any]:
    """Case 证据视图（v2）。`rebuild=True` 时现建（不写盘）。"""
    od = _run_dir(run_dir)
    if not rebuild:
        doc = _read(od / ARTIFACTS["case_view"])
        if doc:
            return doc
    from src.tools.humanview.case_associate_view import build_case_view
    return build_case_view(od)


def case_gate(run_dir: str | Path, *, write: bool = True) -> Dict[str, Any]:
    """Case 门禁（blocker / warning / info）。"""
    from src.tools.humanview.case_associate_view.gates import (
        write_gates, validate_case_view,
    )
    od = _run_dir(run_dir)
    if write:
        return write_gates(od)
    return validate_case_view(case_view(od), artifact(od, "cell_matrix"),
                              artifact(od, "evd"), run=od.name)


def rebuild_evidence(run_dir: str | Path,
                     only: Optional[list] = None) -> Dict[str, Any]:
    """重跑派生物（模型改了、仿真没重跑时用）。"""
    from src.tools.checking.coverage_tools.evidence_pipeline import (
        run_evidence_pipeline)
    return run_evidence_pipeline(_run_dir(run_dir), only=only)


__all__ = [
    "ARTIFACTS", "artifact", "case_gate", "case_view", "list_artifacts",
    "rebuild_evidence",
]
