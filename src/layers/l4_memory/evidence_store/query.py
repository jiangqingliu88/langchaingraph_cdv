"""证据查询 —— 按 claim / fact_class / 类型聚合（只读）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from .kinds import PROVEN_FACT_CLASSES


def read_ledger(root: str | Path) -> List[Dict[str, Any]]:
    from src.tools.checking.verification_os import read_ledger as _read
    try:
        return _read(root)
    except Exception:                                  # noqa: BLE001 旁路
        return []


def fact_class_of(fact: Dict[str, Any]) -> str:
    return str(fact.get("fact_class") or "OBSERVED").upper()


def evidence_for_claims(ledger: Iterable[Dict[str, Any]]
                        ) -> Dict[str, List[Dict[str, Any]]]:
    """claim_id → 证据事实列表（只收参与判定的类别）。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for fact in ledger or []:
        if fact_class_of(fact) not in PROVEN_FACT_CLASSES:
            continue
        for cid in fact.get("claim_ids") or []:
            out.setdefault(str(cid), []).append(fact)
    return out


def counts(ledger: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    by_class: Dict[str, int] = {}
    by_producer: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    for fact in ledger or []:
        by_class[fact_class_of(fact)] = by_class.get(fact_class_of(fact), 0) + 1
        p = str(fact.get("producer_class") or "engine")
        by_producer[p] = by_producer.get(p, 0) + 1
        t = str(fact.get("type") or "")
        by_type[t] = by_type.get(t, 0) + 1
    return {"by_fact_class": by_class, "by_producer_class": by_producer,
            "by_type": by_type, "total": sum(by_class.values())}


__all__ = ["counts", "evidence_for_claims", "fact_class_of", "read_ledger"]
