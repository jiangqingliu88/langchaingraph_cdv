"""VPlan 源数据 → 内核认识的 IR。

映射原则：

- **TP ID 原样保留**（`TP_CMD_HS_001`），不另造一套 `TP-` 体系；下游只把
  `tp_id` 当不透明主键。
- **契约 ID 原样保留**（`C-*`）：写进 TP 的 `requirement` 与 Case IR 的
  `feats`，再由 sidecar `contract/plan_link.yaml` 保留矩阵状态。
- **不优化状态**：`planned` 仍是 `planned`，`assume` 仍是 `assume`；
  没有覆盖证据就不生成 `tp_matrix`，没有 EDA 就不写 `signoff_evidence`。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, List, Optional

from src.ir_plane.decision.case_ir import (
    checker_map, group_map, parse_declared, tst_id_of,
)
from .serialize import testpoints_yaml
from .source import TOPIC_CODES, VPlanProject, feature_paths
from .types import Execution, Realization, TestPoint

_STAGE_BY_PRIORITY = {"P0": "p0", "P1": "p1", "P2": "p2", "P3": "p3"}


def _split(value: Any) -> List[str]:
    text = str(value or "")
    for sep in ("|", ",", ";", " ", "+"):
        text = text.replace(sep, "\n")
    return [x.strip() for x in text.splitlines() if x.strip()]


def _topic_code(topic: str) -> str:
    code = TOPIC_CODES.get(topic)
    if code:
        return code
    ascii_part = "".join(ch for ch in topic if ch.isascii() and ch.isalnum())
    if ascii_part:
        return ascii_part.upper()
    return "T" + hashlib.sha256(topic.encode("utf-8")).hexdigest()[:6].upper()


def _stage(priority: str) -> str:
    return _STAGE_BY_PRIORITY.get(str(priority or "").strip().upper(), "p0")


def _case_index(project: VPlanProject) -> Dict[str, Dict[str, Any]]:
    return {str(c.get("case_id") or ""): c for c in project.cases
            if str(c.get("case_id") or "")}


def _contract_index(project: VPlanProject) -> Dict[str, Dict[str, Any]]:
    return project.contracts


def _pick(primary: str, fallback: str) -> str:
    return primary or fallback


def _one(value: str) -> List[str]:
    return [value] if value else []


def _realization(stimulus: str, row: Dict[str, Any]) -> Realization:
    """VPlan 行 → realization。

    默认仍是 `observe`：只给文字描述、没有绑定 agent 事务字段时，不能把
    “有文字”冒充成“能驱动”。但允许表里显式写
    `realization_kind` / `stimulus_field` / `realization_sequence`，
    让计划层与运行期模型可以对齐（不强制改现有 CSV 契约）。
    """
    kind = str(row.get("realization_kind") or "").strip().lower()
    field = str(row.get("stimulus_field") or "").strip()
    agent = str(row.get("realization_agent") or row.get("agent") or "").strip()
    sequence = str(row.get("realization_sequence") or "").strip()
    if kind in ("stimulus", "sequence", "observe", "backdoor") and (kind != "stimulus" or field):
        values = row.get("realization_values") or []
        if isinstance(values, str):
            values = [x.strip() for x in values.replace("|", ",").split(",")
                      if x.strip()]
        try:
            values = [int(v) for v in values]
        except (TypeError, ValueError):
            values = []
        return Realization(kind=kind, agent=agent, field=field,
                           sequence=sequence, values=values,
                           path=str(row.get("realization_path") or "").strip())
    if not stimulus:
        return Realization(kind="observe")
    return Realization(kind="observe",
                       extras={"vplan_stimulus": stimulus[:300]})


def _tp_notes(row: Dict[str, Any], feature_id: str,
              contract_id: str, stimulus: str,
              realization: Realization) -> List[str]:
    notes = [
        f"vplan_status={row.get('status') or 'planned'}",
        f"feature={feature_id}",
        f"spec_ref={row.get('spec_ref') or ''}",
    ]
    if contract_id:
        notes.append(f"contract={contract_id}")
    if realization.kind == "observe" and stimulus:
        notes.append("realization=observe（VPlan stimulus 未绑定事务字段）")
    elif realization.kind != "observe":
        notes.append(f"realization={realization.kind}")
    return notes


def _testpoint_from_row(row: Dict[str, Any], project: VPlanProject,
                        cases: Dict[str, Dict[str, Any]],
                        paths: Dict[str, str]) -> Optional[Dict[str, Any]]:
    tp_id = str(row.get("tp_id") or "").strip()
    if not tp_id:
        return None
    topic = str(row.get("topic") or "").strip()
    feature_id = str(row.get("feature_id") or "").strip()
    contract_id = str(row.get("contract_id") or "").strip()
    case_id = str(row.get("case_plan") or "").strip()
    case = cases.get(case_id) or {}
    test_name = str(case.get("test_name") or "").strip()
    priority = str(row.get("priority") or "").strip()
    stimulus = str(row.get("stimulus") or "").strip()
    realization = _realization(stimulus, row)
    tp = TestPoint(
        tp_id=tp_id,
        object=_pick(feature_id, project.dut),
        dimension=f"D_{_topic_code(topic)}",
        dimension_name=topic,
        value=str(row.get("test_point") or "").strip(),
        tree_path=paths.get(feature_id, ""),
        requirement=_pick(contract_id, str(row.get("spec_ref") or "").strip()),
        cover_id=contract_id,
        method=str(row.get("check_method") or "").strip(),
        checks=_split(row.get("check_method")),
        themes=_one(topic),
        priority=priority,
        realization=realization,
        execution=Execution(test=test_name, stage=_stage(priority)),
        case_id=case_id,
        case_ids=_one(case_id),
        tst_id=tst_id_of(test_name) if test_name else "",
        notes=_tp_notes(row, feature_id, contract_id, stimulus, realization),
    )
    return tp.to_dict()


def build_testpoints(project: VPlanProject) -> List[Dict[str, Any]]:
    """66 条 `planned` TP → `TestPoint.to_dict()` 形状。"""
    cases = _case_index(project)
    paths = feature_paths(project.features)
    out: List[Dict[str, Any]] = []
    for row in project.testpoints:
        tp = _testpoint_from_row(row, project, cases, paths)
        if tp is not None:
            out.append(tp)
    return out


def _group_by_case(testpoints: List[Dict[str, Any]]
                   ) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for tp in testpoints:
        case_ids = tp.get("case_ids") or (
            [tp["case_id"]] if tp.get("case_id") else [])
        for case_id in case_ids:
            out.setdefault(str(case_id), []).append(tp)
    return out


def _case_groups(covergroups: List[str], dimensions: List[str],
                 case_id: str, tp_ids: List[str]) -> List[Dict[str, Any]]:
    out = []
    for name in (covergroups or dimensions or [case_id]):
        out.append({
            "group": name,
            "cell": name,
            "required_layers": ["functional"],
            "tp_ids": tp_ids,
        })
    return out


def _case_checks(checks: List[str]):
    sva = [c for c in checks if c.lower().endswith("_sva") or "sva" in c.lower()]
    scb = [c for c in checks if c.lower().endswith("_scb") or "scb" in c.lower()]
    unmodeled = [c for c in checks if c not in sva and c not in scb]
    return sva, scb, unmodeled


def _highest_priority(members: List[Dict[str, Any]]) -> str:
    priority = ""
    for tp in members:
        p = str(tp.get("priority") or "")
        if p and (not priority or p < priority):
            priority = p
    return priority


def _case_from_row(row: Dict[str, Any],
                   members: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    case_id = str(row.get("case_id") or "").strip()
    if not case_id:
        return None
    tp_ids = [str(tp.get("tp_id") or "") for tp in members if tp.get("tp_id")]
    dimensions = sorted({str(tp.get("dimension") or "") for tp in members
                         if tp.get("dimension")})
    contract_refs = _split(row.get("contract_ids"))
    checks = _split(row.get("checks"))
    covergroups = _split(row.get("covergroups"))
    sva, scb, unmodeled = _case_checks(checks)
    groups = _case_groups(covergroups, dimensions, case_id, tp_ids)
    description = str(row.get("notes") or "").strip()
    batch = str(row.get("batch") or "").strip()
    case = {
        "id": case_id,
        "name": str(row.get("test_name") or case_id),
        "categories": [],
        # `feats` 在 Case IR 里就是需求/契约引用位；把 C-* 放这里，
        # 不新造字段，旧读者也不用改。
        "feats": contract_refs,
        "tests": [str(row.get("test_name") or "").strip()]
        if row.get("test_name") else [],
        "cells": sorted({g["cell"] for g in groups}),
        "dimensions": dimensions,
        "owner": str(row.get("owner") or "").strip(),
        "priority": _highest_priority(members),
        "tags": [batch] if batch else [],
        "test_intent": description,
        "test_count": len(tp_ids),
        "provenance": {
            "vplan_status": str(row.get("status") or "planned"),
            "batch": batch,
            "covergroups": covergroups,
            "checks": checks,
            # checker 类资产暂时没有 obligation 类型；如实列出，不冒充 SVA/SCB。
            "unmodeled_checks": unmodeled,
        },
        "groups": groups,
        "sva": [{"id": c, "cell": c, "required": True, "tp_ids": tp_ids}
                for c in sva],
        "scb": [{"id": c, "cell": c, "required": True, "checks": [c]}
                for c in scb],
        "constraints": [],
        "not_applicable": {},
        "waivers": [],
        "description": description,
        "source": "declared",
    }
    if not case["sva"]:
        case["not_applicable"]["sva"] = "VPlan case 未声明 SVA 资产（planned）"
    if not case["scb"]:
        case["not_applicable"]["scb"] = "VPlan case 未声明 SCB 资产（planned）"
    return case


def build_case_ir(project: VPlanProject,
                  testpoints: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """12 个 `planned` case → `case_ir_v1`（C-* 引用保在 `feats`）。"""
    tps = testpoints if testpoints is not None else build_testpoints(project)
    by_case = _group_by_case(tps)
    cases = []
    for row in project.cases:
        case = _case_from_row(row, by_case.get(str(row.get("case_id") or ""), []))
        if case is not None:
            cases.append(case)

    return {
        "schema": "case_ir_v1",
        "module": project.module,
        "source": "declared",
        "categories": [],
        "cases": cases,
        "notes": [
            f"由 VPlan 项目生成：{project.root}",
            f"spec_hash={project.spec_hash}",
            "契约状态保持 assume；case/TP 保持 planned，未产生运行证据",
        ],
    }


def build_contract_link(project: VPlanProject,
                        testpoints: Optional[List[Dict[str, Any]]] = None
                        ) -> Dict[str, Any]:
    """C-* ↔ TP ↔ case 的 sidecar（不改 CT/OBL，也不改契约哈希）。"""
    tps = testpoints if testpoints is not None else build_testpoints(project)
    rows: List[Dict[str, Any]] = []
    for cid in sorted(project.contracts):
        row = dict(project.contracts[cid])
        related = [tp for tp in tps if tp.get("cover_id") == cid
                   or tp.get("requirement") == cid]
        row["tp_ids"] = sorted({str(tp.get("tp_id") or "") for tp in related
                                if tp.get("tp_id")})
        row["case_ids"] = sorted({str(tp.get("case_id") or "") for tp in related
                                  if tp.get("case_id")})
        rows.append(row)
    return {
        "schema": "vplan_contract_link_v1",
        "project": str(project.root),
        "module": project.module,
        "dut": project.dut,
        "spec_hash": project.spec_hash,
        "status_counts": project.status_counts,
        "contracts": rows,
        "cases": [
            {"case_id": str(c.get("case_id") or ""),
             "contract_refs": _split(c.get("contract_ids")),
             "status": str(c.get("status") or "planned")}
            for c in project.cases
        ],
        "warnings": list(project.warnings),
    }


def build_payload(project: VPlanProject) -> Dict[str, Any]:
    """完整 IR payload（与 `vplan/runtime/plan.run_testpoints` 同形）。"""
    tps = build_testpoints(project)
    case_ir = build_case_ir(project, tps)
    by_kind = Counter(str(tp.get("realization", {}).get("kind") or "")
                      for tp in tps)
    by_stage = Counter(str((tp.get("execution") or {}).get("stage") or "")
                       for tp in tps)
    payload: Dict[str, Any] = {
        "count": len(tps),
        "by_kind": dict(sorted(by_kind.items())),
        "by_stage": dict(sorted(by_stage.items())),
        "observe_only": sum(1 for tp in tps if tp.get("observe_only")),
        "testpoints": tps,
        "case_ir": case_ir,
        "notes": [
            f"VPlan 项目：{project.root.name}（DUT={project.dut}）",
            f"契约 {len(project.contracts)} 条 / TP {len(tps)} 条 / "
            f"case {len(case_ir['cases'])} 条",
            f"契约状态：{project.status_counts}；TP 状态：{project.tp_status_counts}",
        ],
    }
    text = testpoints_yaml(payload)
    payload["testpoints_yaml"] = text
    doc = parse_declared(case_ir, module=project.module)
    payload["case_maps"] = {
        "group_map": group_map(doc),
        "checker_map": checker_map(doc),
    }
    canonical = json.dumps(case_ir, ensure_ascii=False, sort_keys=True)
    payload["case_ir_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()
    payload["methodology"] = {
        "schema": "vplan_methodology_v1",
        "framework": "vplan",
        "stage": "plan",
        "count": len(tps),
        "by_kind": payload["by_kind"],
        "by_stage": payload["by_stage"],
        "inputs": {
            "project": str(project.root),
            "spec": str(project.spec_path),
            "spec_hash": project.spec_hash,
            "contract_matrix": str(project.root / "data" / "contract_matrix"),
        },
        "artifacts": {
            "testpoints_yaml": {
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            },
        },
        "counts": {
            "contracts": len(project.contracts),
            "contracts_by_status": project.status_counts,
            "testpoints": len(tps),
            "cases": len(case_ir["cases"]),
        },
        "generated_by": "vplan.build@v1",
        "notes": list(project.warnings),
    }
    payload["contract_link"] = build_contract_link(project, tps)
    return payload
