"""VPlan 产物摘要 —— 给工作台 / CLI 读的只读投影。

两个入口：

    project_summary(project_root)  项目侧：需求/feature/契约/TP/case 与状态
    run_artifacts(run_dir)         运行侧：TP IR、覆盖率计划、契约、sv 资产、回归

不写盘、不重跑生成器；读不到就如实留空（`exists: false`），不编数字。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .source import VPlanError, load_project


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def project_summary(project_root: str | Path) -> Dict[str, Any]:
    """VPlan 项目（或 run 的 `inputs/vplan/`）→ 计数与状态。"""
    root = Path(project_root)
    if (root / "inputs" / "vplan" / "data").is_dir():
        root = root / "inputs" / "vplan"
    try:
        proj = load_project(root)
    except VPlanError as exc:
        return {"error": str(exc), "project": str(root)}
    return {
        "project": str(proj.root),
        "module": proj.module,
        "dut": proj.dut,
        "spec_hash": proj.spec_hash,
        "requirements": len(proj.requirements),
        "features": len(proj.features),
        "topics": len(proj.topics),
        "contracts": len(proj.contracts),
        "contracts_by_status": dict(proj.status_counts),
        "testpoints": len(proj.testpoints),
        "testpoints_by_status": dict(proj.tp_status_counts),
        "cases": len(proj.cases),
        "cases_by_status": dict(proj.case_status_counts),
        "warnings": list(proj.warnings),
        "status": "PLAN_ONLY",
        "signable": False,
    }


def run_artifacts(run_dir: str | Path) -> Dict[str, Any]:
    """一次 run 的 VPlan 执行产物（只读）。"""
    root = Path(run_dir)
    tp_doc = _read_json(root / "coverage" / "testpoints.json")
    plan = _read_yaml(root / "coverage" / "coverage_plan.yaml")
    manifest = _read_json(root / "contract" / "contract_manifest.json")
    vplan_map = _read_json(root / "contract" / "vplan_map.json")
    regression = _read_json(root / "regression_stages.json")
    signoff = _read_json(root / "signoff_evidence.json")

    sv_rows: List[Dict[str, str]] = []
    registry = root / "sv" / "asset_registry.csv"
    if registry.is_file():
        with registry.open(encoding="utf-8-sig", newline="") as fh:
            sv_rows = [dict(r) for r in csv.DictReader(fh)]

    inputs = root / "inputs" / "vplan"
    artifacts = []
    for label, rel in (
            ("VPlan 输入", "inputs/vplan/data/execution_meta.csv"),
            ("测试点 IR", "coverage/testpoints.json"),
            ("覆盖率计划", "coverage/coverage_plan.yaml"),
            ("契约清单", "contract/contract_manifest.json"),
            ("dplan ↔ VPlan 映射", "contract/dplan_map.json"),
            ("C-* → 环境契约映射", "contract/vplan_map.json"),
            ("sv 资产登记", "sv/asset_registry.csv"),
            ("UVM 环境架构（VPlan 契约）", "sv/uvm_arch.yaml"),
            ("分级回归", "regression_stages.json")):
        path = root / rel
        artifacts.append({"label": label, "path": rel,
                          "exists": path.is_file(),
                          "size": path.stat().st_size if path.is_file() else 0})

    return {
        "run_id": root.name,
        "run_dir": str(root),
        "project": str(inputs) if inputs.is_dir() else "",
        "testpoints": int(tp_doc.get("count") or 0),
        "testpoints_by_kind": tp_doc.get("by_kind") or {},
        "batches": len(plan.get("batches") or []),
        "coverpoints": int((plan.get("summary") or {}).get(
            "coverpoint_count") or 0),
        "contract_id": str(manifest.get("contract_id") or ""),
        "contract_hash": str(manifest.get("contract_hash") or ""),
        "obligations": int(manifest.get("obligations") or 0),
        "cases": int(manifest.get("cases") or 0),
        "mapped_contracts": len((vplan_map.get("contracts") or {})),
        "sv_assets": len(sv_rows),
        "regression": str(regression.get("status") or ""),
        "signoff": str(signoff.get("status") or ""),
        "artifacts": artifacts,
    }


__all__ = ["project_summary", "run_artifacts"]
