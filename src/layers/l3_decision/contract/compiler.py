"""契约编译器 —— L1 Contract → L2 Obligations（纯函数，确定性）。

一条义务 = "必须被清偿的一个证明"：

    group_layer  (case, group, layer)  该组的某层证据
    sva          (case, sva id)        断言被执行且不报错
    scb          (case, scb id)        比对被执行且不 mismatch

`obligation_id` **确定性生成**（契约不变 → id 不变），这是增量验证的地基：
worklist 靠它去重、账本靠它对账。

编译期就拒绝坏规则：`Predicate.fact_type` 不在 `FACT_TYPES` 里直接抛错
（"规则只允许引用已声明的事实类型"—— 计划里的那条硬约束）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .contract_model import (
    Contract, GroupSpec, Obligation, Predicate,
)

_ID_BAD = re.compile(r"[^A-Za-z0-9_.\-]+")

#: 证据层 → 判据（事实类型 + 算子）。新增一层必须同时在这里登记。
LAYER_PREDICATES: Dict[str, Dict[str, Any]] = {
    "functional": {"fact_type": "bin_hit", "op": "all_bins_hit"},
    "timing": {"fact_type": "timing", "op": "ok"},
    "data": {"fact_type": "scb_result", "op": "matched"},
    "path": {"fact_type": "path_result", "op": "proven"},
}


def _slug(text: Any) -> str:
    out = _ID_BAD.sub("_", str(text or "").strip()).strip("_")
    return out.upper() or "X"


def obligation_id(kind: str, case: str, *parts: Any) -> str:
    body = "-".join([_slug(case)] + [_slug(p) for p in parts if p])
    return f"OBL-{kind.upper()}-{body}"


def _group_obligation(contract: Contract, case_id: str,
                      group: GroupSpec, layer: str) -> Obligation:
    rule = LAYER_PREDICATES[layer]
    where: Dict[str, Any] = {"case": case_id, "group": group.group}
    if layer == "functional":
        where["tp_ids"] = list(group.tp_ids)
    elif layer == "path":
        where["path"] = group.cell
    return Obligation(
        obligation_id=obligation_id("GROUP", case_id, group.group, layer),
        contract_id=contract.id, kind="group_layer", case=case_id,
        subject={"group": group.group, "layer": layer, "cell": group.cell},
        predicate=Predicate(fact_type=rule["fact_type"], op=rule["op"],
                            where=where),
    )


def compile_obligations(contract: Contract) -> List[Obligation]:
    """`Contract` → 全部义务（按 case 排序，id 稳定）。"""
    out: List[Obligation] = []
    for case in contract.cases:
        for group in case.groups:
            for layer in group.required_layers:
                if layer not in LAYER_PREDICATES:
                    raise ValueError(
                        f"证据层 {layer!r} 没有登记判据（见 LAYER_PREDICATES）")
                out.append(_group_obligation(contract, case.id, group, layer))
        for sva in case.sva:
            out.append(Obligation(
                obligation_id=obligation_id("SVA", case.id, sva.id),
                contract_id=contract.id, kind="sva", case=case.id,
                subject={"sva": sva.id, "cell": sva.cell},
                predicate=Predicate(fact_type="sva_result", op="no_fail",
                                    where={"case": case.id, "id": sva.id}),
                required=bool(sva.required),
            ))
        for scb in case.scb:
            out.append(Obligation(
                obligation_id=obligation_id("SCB", case.id, scb.id),
                contract_id=contract.id, kind="scb", case=case.id,
                subject={"scb": scb.id, "cell": scb.cell},
                predicate=Predicate(fact_type="scb_result", op="executed",
                                    where={"case": case.id, "id": scb.id,
                                           "evidence": scb.evidence}),
                required=bool(scb.required),
            ))
    return sorted(out, key=lambda o: o.obligation_id)


__all__ = ["LAYER_PREDICATES", "compile_obligations", "obligation_id"]
