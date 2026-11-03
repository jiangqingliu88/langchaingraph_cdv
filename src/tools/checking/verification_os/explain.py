"""`vagent why` —— **一条义务为什么是这个状态**（M5 的核心命令）。

回答三件事：

    1. 这条义务要什么：谓词（事实类型 / 算子 / 定位条件）
    2. 现在是什么：用账本事实现推一遍（与 `derive()` 同一实现）
    3. 还差什么：缺哪种事实、该由哪条 test × seed 提供（从 TP IR 反查）

只读：不重新采集、不改账本。它把"红灯"从"看 5 个 JSON 猜"变成一条命令。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .build import check_contract, contract_hash, load_contract
from .compiler import compile_obligations
from .derive import derive
from .ledger import read_ledger


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _f_type(fact: Dict[str, Any]) -> str:
    value = fact.get("type")
    return str(getattr(value, "value", value))


def _matching_facts(ledger: List[Dict[str, Any]], obligation,
                    contract_hash_: str) -> List[Dict[str, Any]]:
    """与这条义务相关的事实（同类型 + 同 case；run 级事实也算进来）。"""
    out = []
    predicate = obligation.predicate
    case = str(predicate.where.get("case") or "")
    for fact in ledger:
        if _f_type(fact) != predicate.fact_type.value:
            continue
        owner = str((fact.get("contract_hash") or ""))
        if owner and owner != contract_hash_:
            continue                       # 旧契约的事实（stale）不参与
        subject = fact.get("subject") or {}
        if case and subject.get("case") not in (case, ""):
            continue
        out.append(fact)
    return out


def _suggest_tests(run_dir: Path, obligation) -> List[Dict[str, Any]]:
    """缺证据时：该跑哪条 test / 哪个 seed（从 TP IR 反查）。"""
    try:
        import yaml

        doc = yaml.safe_load((run_dir / "coverage" / "testpoints.yaml")
                             .read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError):
        return []
    tp_ids = set((obligation.predicate.where or {}).get("tp_ids") or [])
    out: List[Dict[str, Any]] = []
    for tp in (doc.get("testpoints") if isinstance(doc, dict) else None) or []:
        if not isinstance(tp, dict) or str(tp.get("case_id") or "") != obligation.case:
            continue
        if tp_ids and str(tp.get("tp_id") or "") not in tp_ids:
            continue
        execution = tp.get("execution") or {}
        seeds = [int(s) for s in execution.get("seeds") or [] if str(s).isdigit()]
        out.append({"tp_id": tp.get("tp_id"), "test": execution.get("test"),
                    "stage": execution.get("stage"),
                    "seeds": seeds[:3]})
    return out[:5]


def explain(run_dir: str | Path, obligation_id: str) -> Dict[str, Any]:
    """一条义务的取证链（contract → 谓词 → 事实 → 状态 → 还差什么）。"""
    root = Path(run_dir)
    check = check_contract(root)
    if not check.get("ok"):
        return {"available": False, "reason": check.get("reason"),
                "obligation_id": obligation_id}
    contract = load_contract(root)
    if contract is None:
        return {"available": False, "reason": "contract_unreadable",
                "obligation_id": obligation_id}
    obligations = compile_obligations(contract)
    obligation = next((o for o in obligations
                       if o.obligation_id == obligation_id), None)
    if obligation is None:
        return {"available": False, "reason": "obligation_not_found",
                "obligation_id": obligation_id,
                "hint": "用 `vagent contract show` 看义务清单"}

    current = contract_hash(root)
    ledger = read_ledger(root)
    status = derive([obligation], ledger)[obligation.obligation_id]
    facts = _matching_facts(ledger, obligation, current)
    out: Dict[str, Any] = {
        "available": True,
        "obligation_id": obligation.obligation_id,
        "contract_id": contract.id,
        "contract_hash": current,
        "kind": obligation.kind,
        "case": obligation.case,
        "subject": dict(obligation.subject),
        "predicate": {"fact_type": obligation.predicate.fact_type.value,
                      "op": obligation.predicate.op,
                      "where": dict(obligation.predicate.where)},
        "status": status,
        "facts": [{"type": _f_type(f), "subject": f.get("subject"),
                   "value": f.get("value"), "tst_id": f.get("tst_id"),
                   "seed": f.get("seed")} for f in facts[:20]],
        "facts_total": len(facts),
    }
    if status != "PROVEN":
        out["missing"] = {
            "fact_type": obligation.predicate.fact_type.value,
            "where": dict(obligation.predicate.where),
            "suggested_runs": _suggest_tests(root, obligation),
        }
    return out


def status_summary(run_dir: str | Path) -> Dict[str, Any]:
    """一次 run 的 OS 视图：契约 / 账本 / 两级影子对账。"""
    root = Path(run_dir)
    check = check_contract(root)
    case_shadow = _read_json(root / "status" / "shadow_report.json")
    tp_shadow = _read_json(root / "status" / "tp_shadow.json")
    ledger = read_ledger(root)
    return {
        "run": root.name,
        "contract": check,
        "ledger": {"facts": len(ledger),
                   "head": str(ledger[-1].get("hash") or "")[:16] if ledger else ""},
        "case_shadow": {"ok": case_shadow.get("ok"),
                        "mismatched": (case_shadow.get("compare") or {}).get("mismatched"),
                        "stale_facts": case_shadow.get("stale_facts")},
        "tp_shadow": {"ok": tp_shadow.get("ok"),
                      "mismatched": tp_shadow.get("mismatched"),
                      "tps": tp_shadow.get("tps")},
    }


__all__ = ["explain", "status_summary"]
