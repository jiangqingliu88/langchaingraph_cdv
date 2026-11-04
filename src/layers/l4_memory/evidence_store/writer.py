"""证据写入 —— 复用现有 append-only 账本（不新建平行事实系统）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from .kinds import FACT_CLASSES, PRODUCER_CLASSES


def annotate_fact(fact: Dict[str, Any], *, fact_class: str = "HYPOTHESIS",
                  producer_class: str = "agent", claim_ids: Iterable[str] = None,
                  actor: str = "") -> Dict[str, Any]:
    """给事实打证据类别；**不改变** subject/value/type。"""
    fact_class = str(fact_class or "HYPOTHESIS").upper()
    producer_class = str(producer_class or "agent").lower()
    if fact_class not in FACT_CLASSES:
        raise ValueError(f"未知 fact_class {fact_class!r}（允许 {FACT_CLASSES}）")
    if producer_class not in PRODUCER_CLASSES:
        raise ValueError(f"未知 producer_class {producer_class!r}")
    out = dict(fact)
    out.update({
        "fact_class": fact_class,
        "producer_class": producer_class,
        "claim_ids": [str(c) for c in (claim_ids or []) if str(c)],
        "actor": str(actor or ""),
    })
    return out


def append_evidence(root: str | Path, facts: List[Dict[str, Any]], *,
                    bundle_id: str, contract_hash: str = "",
                    run_id: str = "", tst_id: str = "", seed: Any = None,
                    actor: str = "") -> Dict[str, Any]:
    """`[{type, subject, value, ...}]` → FactBundle → 账本。"""
    from src.layers.l3_decision.contract import FactBundle, append_bundle

    bundle = FactBundle(
        bundle_id=bundle_id, run_id=str(run_id or ""), tst_id=str(tst_id or ""),
        seed=seed, contract_hash=str(contract_hash or ""), actor=str(actor or ""),
        facts=[annotate_fact(f, fact_class=f.get("fact_class", "HYPOTHESIS"),
                             producer_class=f.get("producer_class", "agent"),
                             claim_ids=f.get("claim_ids") or [],
                             actor=actor) for f in facts])
    return append_bundle(root, bundle)


__all__ = ["annotate_fact", "append_evidence"]
