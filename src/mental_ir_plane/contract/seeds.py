"""种子索引（P6）—— **哪个 seed 清偿了哪些义务**。

为什么需要：签核证据必须可复现。`signed_off_by = task@seed` 已经回答了
"这条 TP 由哪次执行证明"，但反过来"第 4001 颗种子到底证了哪几条义务"
只能靠人翻 `case_cov`。索引把这件事变成一张表：

    status/seed_index.json
      seeds[]       每一 (tst, seed) 一条：清偿了哪些义务、还剩哪些
      by_seed{}     按 seed 汇总：这一颗种子一共清偿了几条（去重）

口径与 `derive()` 完全一致：**取当前契约的事实**（旧契约的按 stale 过滤），
按 (tst, seed) 分组后重新推导 —— 不另算一套规则。

边界：只有带 CSE 身份的执行才有义务（批次级 test 没有 case），所以这张表
覆盖的是**用例证据**；批次用例的合并覆盖率仍由 `tp_shadow` 对账。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .build import check_contract, contract_hash, load_contract
from .compiler import compile_obligations
from .derive import derive
from .ledger import read_ledger

SCHEMA = "os_seed_index_v1"
_DONE = ("PROVEN", "NOT_APPLICABLE")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _f_type(fact: Dict[str, Any]) -> str:
    value = fact.get("type")
    return str(getattr(value, "value", value))


def _group_facts(ledger: List[Dict[str, Any]],
                 current: str) -> Dict[tuple, List[Dict[str, Any]]]:
    """按 `(tst, seed)` 分组；只要当前契约、且带 case 身份的事实。"""
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for fact in ledger:
        if str(fact.get("contract_hash") or "") not in ("", current):
            continue
        if _f_type(fact) == "tp_attr":
            continue
        if not str((fact.get("subject") or {}).get("case") or ""):
            continue
        key = (str(fact.get("tst_id") or ""), fact.get("seed"))
        groups.setdefault(key, []).append(fact)
    return groups


def build_seed_index(run_dir: str | Path) -> Dict[str, Any]:
    """当前契约的事实按 (tst, seed) 分组 → 每组的义务清偿情况。"""
    root = Path(run_dir)
    check = check_contract(root)
    if not check.get("ok"):
        return {"schema": SCHEMA, "available": False, "reason": check.get("reason")}
    contract = load_contract(root)
    if contract is None:
        return {"schema": SCHEMA, "available": False,
                "reason": "contract_unreadable"}
    current = contract_hash(root)
    obligations = compile_obligations(contract)
    by_case: Dict[str, list] = {}
    for obligation in obligations:
        by_case.setdefault(obligation.case, []).append(obligation)

    groups = _group_facts(read_ledger(root), current)

    rows: List[Dict[str, Any]] = []
    by_seed: Dict[str, Dict[str, Any]] = {}
    for (tst, seed), facts in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        case = str((facts[0].get("subject") or {}).get("case") or "")
        obligations_of_case = by_case.get(case) or []
        statuses = derive(obligations_of_case, facts)
        discharged = sorted(k for k, s in statuses.items() if s in _DONE)
        remaining = sorted(k for k, s in statuses.items() if s not in _DONE)
        rows.append({"seed": seed, "tst_id": tst, "case": case,
                     "total": len(statuses), "discharged": discharged,
                     "remaining": remaining})
        slot = by_seed.setdefault(str(seed), {"seed": seed, "discharged": [],
                                             "runs": 0})
        slot["runs"] += 1
        for oid in discharged:
            if oid not in slot["discharged"]:
                slot["discharged"].append(oid)

    for slot in by_seed.values():
        slot["discharged"].sort()
        slot["count"] = len(slot["discharged"])
    return {
        "schema": SCHEMA,
        "available": True,
        "run": root.name,
        "contract_id": contract.id,
        "contract_hash": current,
        "seeds": rows,
        "by_seed": {k: by_seed[k] for k in sorted(by_seed)},
        "counts": {"runs": len(rows), "seeds": len(by_seed),
                   "discharged_total": sum(len(r["discharged"]) for r in rows)},
    }


def write_seed_index(run_dir: str | Path) -> Dict[str, Any]:
    data = build_seed_index(run_dir)
    from src.runtime_plane.core.runtime.atomic import atomic_write_json

    path = Path(run_dir) / "status" / "seed_index.json"
    try:
        atomic_write_json(path, data)
    except OSError:
        pass
    return data


__all__ = ["SCHEMA", "build_seed_index", "write_seed_index"]
