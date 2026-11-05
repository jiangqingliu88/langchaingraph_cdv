"""现有 Case IR / TP IR → Unified Verification IR v3 的适配编译。

**不替换现有产物**：这里把已存在的 `case_ir.json`、`testpoints.yaml`、
behavior/config/resource 视图组织进五域 IR；`case_ir` 仍是 CASE/CCAT 的身份源，
IR 只是它的统一视图与编译入口。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .schema import IRIdentity, IRRelation, VerificationIR


def _as_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _case_ids_of(tp: Dict[str, Any]) -> List[str]:
    ids = [str(c) for c in (tp.get("case_ids") or []) if str(c)]
    if not ids and tp.get("case_id"):
        ids = [str(tp["case_id"])]
    return list(dict.fromkeys(ids))


def compile_from_case_ir(case_ir: Dict[str, Any], *,
                         testpoints: Optional[Iterable[Dict[str, Any]]] = None,
                         behaviors: Any = None,
                         configurations: Any = None,
                         resources: Any = None,
                         design_version: str = "",
                         model_version: str = "",
                         metadata: Optional[Dict[str, Any]] = None
                         ) -> VerificationIR:
    """Case IR（+ TP IR / 其它域）→ `verification_ir_v3`。"""
    cases = [c for c in (case_ir.get("cases") or []) if isinstance(c, dict)]
    tps = [t for t in (testpoints or []) if isinstance(t, dict)]

    dimensions: Dict[str, Dict[str, Any]] = {}
    groups: Dict[str, Dict[str, Any]] = {}
    sva: Dict[str, Dict[str, Any]] = {}
    scb: Dict[str, Dict[str, Any]] = {}
    v_cases: List[Dict[str, Any]] = []
    relations: List[IRRelation] = []
    rel_n = 0

    def rel(source: str, target: str, kind: str,
            evidence: Optional[str] = None) -> None:
        nonlocal rel_n
        if not source or not target:
            return
        rel_n += 1
        relations.append(IRRelation(
            relation_id=f"REL-{rel_n:05d}", source_id=source,
            target_id=target, relation_type=kind,
            evidence_requirement=evidence))

    for case in cases:
        cid = str(case.get("id") or "")
        if not cid:
            continue
        v_cases.append({
            "id": cid,
            "name": case.get("name", ""),
            "source": case.get("source", ""),
            "dimensions": [str(d) for d in (case.get("dimensions") or [])],
            "groups": list(case.get("groups") or []),
            "sva": list(case.get("sva") or []),
            "scb": list(case.get("scb") or []),
            "constraints": list(case.get("constraints") or []),
            "waivers": list(case.get("waivers") or []),
            "not_applicable": dict(case.get("not_applicable") or {}),
        })
        for dim in (case.get("dimensions") or []):
            dimensions.setdefault(str(dim), {"values": set(),
                                             "coverpoints": set()})
            rel(cid, str(dim), "constrained_by")
        for group in (case.get("groups") or []):
            if not isinstance(group, dict):
                continue
            gid = str(group.get("group") or "")
            if gid:
                groups[gid] = dict(group)
                rel(cid, gid, "realizes")
                for cp in (group.get("coverpoints") or []):
                    rel(gid, str(cp), "covered_by")
        for key, bucket in (("sva", sva), ("scb", scb)):
            for item in (case.get(key) or []):
                if not isinstance(item, dict):
                    continue
                iid = str(item.get("id") or "")
                if iid:
                    bucket[iid] = dict(item)
                    rel(cid, iid, "checked_by")
        for constraint in (case.get("constraints") or []):
            rel(cid, str(constraint), "constrained_by")

    v_tps: List[Dict[str, Any]] = []
    for tp in tps:
        tid = str(tp.get("tp_id") or "")
        if not tid:
            continue
        cids = _case_ids_of(tp)
        v_tps.append({
            "tp_id": tid,
            "case_id": cids[0] if cids else "",
            "case_ids": cids,
            "dimension": tp.get("dimension", ""),
            "field": tp.get("field", ""),
            "value": tp.get("value", ""),
            "coverpoint": tp.get("coverpoint", ""),
            "bin": tp.get("bin", ""),
            "groups": list(tp.get("groups") or []),
            "sva": list(tp.get("sva") or []),
            "scb": list(tp.get("scb") or []),
            "constraints": list(tp.get("constraints") or []),
            "requirement": tp.get("requirement", ""),
            "priority": tp.get("priority", ""),
        })
        for cid in cids:
            rel(tid, cid, "derived_from")
        dim = str(tp.get("dimension") or "")
        if dim:
            dimensions.setdefault(dim, {"values": set(),
                                        "coverpoints": set()})
            dimensions[dim]["values"].add(str(tp.get("value") or ""))
            if tp.get("coverpoint"):
                dimensions[dim]["coverpoints"].add(str(tp["coverpoint"]))
        for key, bucket in (("sva", sva), ("scb", scb)):
            for iid in (tp.get(key) or []):
                if str(iid):
                    rel(tid, str(iid), "checked_by")

    attr = {
        "dimensions": [
            {"key": key, "values": sorted(v["values"]),
             "coverpoints": sorted(v["coverpoints"])}
            for key, v in sorted(dimensions.items())
        ],
        "groups": [groups[k] for k in sorted(groups)],
    }
    verification = {
        "cases": v_cases,
        "testpoints": v_tps,
        "sva": [sva[k] for k in sorted(sva)],
        "scb": [scb[k] for k in sorted(scb)],
        "constraints": sorted({str(c) for case in v_cases
                               for c in case["constraints"] if str(c)}),
    }
    ir = VerificationIR(
        identity=IRIdentity(
            module_id=str(case_ir.get("module") or ""),
            design_version=str(design_version or ""),
            model_version=str(model_version or ""),
        ),
        attributes=attr,
        behaviors=dict(behaviors or {}),
        configurations=dict(configurations or {}),
        resources=dict(resources or {}),
        verification=verification,
        relations=relations,
        metadata=dict(metadata or {}),
    )
    return ir.seal()


__all__ = ["compile_from_case_ir"]
