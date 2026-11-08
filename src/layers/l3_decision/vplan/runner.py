"""把 VPlan 项目写成一次**只规划**的 run。

产出与正常 `verify` 相同的 IR 位置（`coverage/testpoints.*`、
`coverage/case_ir.json`、`contract/*`），但没有 EDA 证据、没有
`signoff_evidence/`、也没有 `report.json`。因此它**不可签核** —— 这是
有意的：规划层不能冒充执行层。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.core.runtime.atomic import atomic_write_json, atomic_write_text

from .build import build_payload
from .source import VPlanProject


def _write_yaml(path: Path, doc: Any) -> None:
    atomic_write_text(path, yaml.safe_dump(doc, allow_unicode=True,
                                           sort_keys=False))


def _counts(project: VPlanProject, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "requirements": len(project.requirements),
        "features": len(project.features),
        "topics": len(project.topics),
        "contracts": len(project.contracts),
        "contracts_by_status": project.status_counts,
        "testpoints": len(payload.get("testpoints") or []),
        "testpoints_by_status": project.tp_status_counts,
        "cases": len(project.cases),
        "cases_by_status": project.case_status_counts,
    }


def write_plan_only_run(project: VPlanProject, output_dir: str | Path, *,
                        run_id: Optional[str] = None) -> Dict[str, Any]:
    """生成规划产物；返回摘要（路径、计数、显式的不可签核状态）。"""
    out = Path(output_dir)
    cov = out / "coverage"
    docs = out / "docs"
    contract_dir = out / "contract"
    for d in (cov, docs, contract_dir):
        d.mkdir(parents=True, exist_ok=True)

    payload = build_payload(project)
    counts = _counts(project, payload)

    # ── 与正常 verify 同位置的核心 IR ──
    atomic_write_text(cov / "testpoints.yaml", payload["testpoints_yaml"])
    atomic_write_json(cov / "testpoints.json", payload)
    atomic_write_json(cov / "case_ir.json", payload["case_ir"])
    for key, name in (("group_map", "case_group_map.json"),
                      ("checker_map", "case_checker_map.json")):
        doc = (payload.get("case_maps") or {}).get(key)
        if doc:
            atomic_write_json(cov / name, doc)
    atomic_write_json(cov / "methodology.json", payload["methodology"])

    # ── 契约构建物（CT/OBL 仍由现有编译器生成；C-* 在 sidecar 里）──
    contract_manifest: Dict[str, Any] = {}
    try:
        from src.layers.l3_decision.contract import write_contract

        contract_manifest = write_contract(
            out, payload["case_ir"], module=project.module)
    except Exception as exc:                       # noqa: BLE001
        contract_manifest = {"error": str(exc)}
    _write_yaml(contract_dir / "plan_link.yaml", payload["contract_link"])

    # ── spec.json：给现有 front/verify 读模块名与需求 ──
    spec_doc = {
        "design_name": project.module,
        "vplan": {
            "project_root": str(project.root),
            "dut": project.dut,
            "spec": str(project.spec_path),
            "spec_hash": project.spec_hash,
            "status": "PLANNED",
        },
        "features": [
            {
                "id": row.get("feature_id"),
                "name": row.get("description") or row.get("feature_id"),
                "level": row.get("feature_level"),
                "parent": row.get("parent_feature_id"),
            }
            for row in project.features
        ],
        "requirements": project.requirements,
        "interfaces": [],
        "registers": [],
        "interrupts": [],
    }
    atomic_write_json(out / "spec.json", spec_doc)

    # ── 运行索引：明确标成 PLANNED，避免被当成一次执行 run ──
    execution = {
        "status": "PLAN_ONLY",
        "reason": "只生成规划/契约 IR；未运行 UVM/EDA，未产生证据",
        "signable": False,
    }
    manifest = {
        "schema": "vplan_plan_manifest_v1",
        "run_id": run_id or out.name,
        "module": project.module,
        "origin": "vplan",
        "status": "PLANNED",
        "final_coverage": 0,
        "target": None,
        "converged": False,
        "iterations": 0,
        "phases": [{"id": "vplan", "status": "PLANNED", "executor": "vplan"}],
        "evidence": {"chain_valid": False},
        "vplan": {
            "project_root": str(project.root),
            "spec_hash": project.spec_hash,
            "counts": counts,
        },
        "execution": execution,
    }
    atomic_write_json(docs / "manifest.json", manifest)
    atomic_write_json(docs / "vplan_source.json", {
        "schema": "vplan_source_v1",
        "project_root": str(project.root),
        "module": project.module,
        "dut": project.dut,
        "spec": str(project.spec_path),
        "spec_hash": project.spec_hash,
        "spec_meta": project.spec_meta,
        "counts": counts,
        "warnings": list(project.warnings),
        "contracts": [
            {
                "contract_id": row.get("contract_id"),
                "status": row.get("status"),
                "owner": row.get("owner"),
                "p_level": row.get("p_level"),
                "check_method": row.get("check_method"),
                "check_artifact": row.get("check_artifact"),
            }
            for row in payload["contract_link"]["contracts"]
        ],
    })

    try:
        materialize_project_inputs(project, out)
    except Exception:                                # noqa: BLE001 输入复制不拦产物
        pass

    return {
        "run": str(out),
        "run_id": run_id or out.name,
        "origin": "vplan",
        "module": project.module,
        "dut": project.dut,
        "spec_hash": project.spec_hash,
        "counts": counts,
        "execution": execution,
        "artifacts": {
            "testpoints_yaml": str(cov / "testpoints.yaml"),
            "testpoints_json": str(cov / "testpoints.json"),
            "case_ir": str(cov / "case_ir.json"),
            "methodology": str(cov / "methodology.json"),
            "contract_manifest": str(contract_dir / "contract_manifest.json"),
            "plan_link": str(contract_dir / "plan_link.yaml"),
            "manifest": str(docs / "manifest.json"),
        },
        "contract_manifest": contract_manifest,
        "warnings": list(project.warnings),
    }


def materialize_project_inputs(project: VPlanProject,
                               run_dir: str | Path) -> Dict[str, Any]:
    """把 VPlan 项目的**契约结构**复制到 `<run>/inputs/vplan/`。

    让一次 run 自包含：spec 抽取表、契约矩阵、case、schemas、生成物说明、
    执行资产都在 inputs/vplan 下。

    执行期只读 `inputs/vplan/`；运行期模型在内存中由 CSV 投影。
    """
    import shutil

    from src.layers.l1_infrastructure.layout import vplan_inputs_dir

    root = Path(run_dir)
    dest = vplan_inputs_dir(root)
    dest.mkdir(parents=True, exist_ok=True)
    copies = (
        ("docs/specs", "docs/specs"),
        ("docs/verification", "docs/verification"),
        ("docs/contract", "docs/contract"),
        ("docs/appendix", "docs/appendix"),
        ("data", "data"),
        ("cases", "cases"),
        ("schemas", "schemas"),
        ("scripts", "scripts"),
        ("util_comp.yaml", "util_comp.yaml"),
        ("signoff_policy.yaml", "signoff_policy.yaml"),
        ("README.md", "README.md"),
        ("VERSION", "VERSION"),
    )
    copied = []
    for src_rel, dst_rel in copies:
        src = project.root / src_rel
        if not src.exists():
            continue
        target = dest / dst_rel
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        copied.append(src_rel)

    (dest / "README.md").write_text(
        "# inputs/vplan — 本次 run 的 VPlan 契约结构\n\n"
        f"来源项目：`{project.root}`\n\n"
        "包含 spec 抽取表、契约矩阵、cases、schemas、`data/*.csv` 执行资产与\n"
        "生成物说明。运行期结构由 CSV 在内存中组装。\n",
        encoding="utf-8")
    return {"path": str(dest), "copied": copied}
