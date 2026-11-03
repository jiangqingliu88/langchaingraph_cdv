"""M0 影子模式 —— 新链路照跑，但**不改变任何现判定**。

做三件事：

1. 从 `coverage/case_ir.json` 适配出 `Contract v2`，编译出义务；
2. 把每条 `case_cov` 记录打成 `SimFactBundle`（一次执行 = 一包），追加进账本；
3. 用 `derive()` 重新推一遍，和现有 `case_cov` 的组状态 / SVA / SCB / case_status
   **逐条对账**，结果写 `status/shadow_report.json`。

停点条件（计划 M0）：**一致率 100%**；不一致必须能解释，不允许"差不多"。
这一阶段旧链路一行判定都不改 —— 新链路先证明自己能复现旧结论，才有资格接管。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .compiler import compile_obligations, obligation_id
from .contract_model import (
    CaseStatus, Contract, Fact, FactBundle, contract_from_case_ir, worst,
)
from .derive import case_statuses, derive
from .ledger import append_bundle, read_ledger, verify_chain

SCHEMA = "os_shadow_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _all_records(cov: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in sorted((cov / "case_cov").rglob("*.json")):
        if path.name.endswith(".cache"):
            continue
        rec = _read_json(path)
        if rec.get("task") or rec.get("case_id"):
            out.append(rec)
    return out


def _case_records(cov: Path) -> List[Dict[str, Any]]:
    return [r for r in _all_records(cov) if r.get("case_id")]


def _scb_status(summary: Dict[str, Any]) -> str:
    matched = summary.get("matched")
    if matched is None:
        return CaseStatus.NOT_APPLICABLE.value
    if int(summary.get("mismatched") or 0) > 0:
        return CaseStatus.MISSING.value
    return (CaseStatus.PROVEN.value if int(matched) > 0
            else CaseStatus.NOT_EXECUTED.value)


def _bin_facts(rec: Dict[str, Any], case: str, common: Dict[str, Any]) -> List[Fact]:
    """每个 **owned 仓** 一条事实（0 命中也要有 —— 否则"没打中"会消失）。"""
    out: List[Fact] = []
    for entry in rec.get("tp") or []:
        entry = entry or {}
        tp = str(entry.get("tp_id") or "")
        cp = str(entry.get("coverpoint") or "")
        hits = entry.get("hits") or {}
        for bin_name in entry.get("owned") or []:
            out.append(Fact(type="bin_hit", subject={
                "case": case, "tp": tp, "cp": cp, "bin": str(bin_name)},
                value={"hits": int(hits.get(bin_name) or 0)}, **common))
    return out


def _checker_facts(rec: Dict[str, Any], case: str,
                   common: Dict[str, Any]) -> List[Fact]:
    """SVA / SCB 的执行结果（含 env 聚合那一行）。"""
    out: List[Fact] = []
    summary = rec.get("scb_summary") or {}
    out.append(Fact(type="scb_result", subject={"case": case, "id": "aggregate"},
                    value={"status": _scb_status(summary),
                           "exec": int(summary.get("total") or 0),
                           "matched": summary.get("matched"),
                           "mismatched": summary.get("mismatched")}, **common))
    for item in rec.get("sva") or []:
        out.append(Fact(type="sva_result",
                        subject={"case": case, "id": str(item.get("id") or "")},
                        value={"status": str(item.get("status") or ""),
                               "fail": int(item.get("fail") or 0)}, **common))
    for item in rec.get("scb") or []:
        out.append(Fact(type="scb_result",
                        subject={"case": case, "id": str(item.get("id") or "")},
                        value={"status": str(item.get("status") or ""),
                               "exec": int(item.get("exec") or 0),
                               "matched": item.get("matched"),
                               "mismatched": item.get("mismatched")}, **common))
    return out


def _facts_of(rec: Dict[str, Any], contract: Contract) -> List[Fact]:
    """一条 case_cov 记录 → 原子事实（**完整**：缺的仓也要有 0 命中的事实）。"""
    case = str(rec.get("case_id") or "")
    common = {"contract_hash": contract.hash, "run_id": str(rec.get("run_id") or ""),
              "tst_id": str(rec.get("tst_id") or ""), "seed": rec.get("seed"),
              "producer": "coverage.collector@v3"}
    facts = _bin_facts(rec, case, common)
    facts.append(Fact(type="timing", subject={"case": case},
                      value={"ok": rec.get("timing_ok")}, **common))
    facts.extend(_checker_facts(rec, case, common))
    return facts


def build_bundle(rec: Dict[str, Any], contract: Contract) -> FactBundle:
    facts = _facts_of(rec, contract)
    bundle = FactBundle(bundle_id=f"B-{rec.get('tst_id') or rec.get('task')}",
                        run_id=str(rec.get("run_id") or ""),
                        tst_id=str(rec.get("tst_id") or ""),
                        seed=rec.get("seed"), contract_hash=contract.hash,
                        facts=facts)
    bundle.bundle_id = f"B-{bundle.digest()[:16]}"
    return bundle


def _group_results(case_spec, statuses: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for group in case_spec.groups:
        layers = [statuses.get(obligation_id("GROUP", case_spec.id,
                                             group.group, layer))
                  for layer in group.required_layers]
        out[group.group] = worst([s for s in layers if s])
    return out


def _compare(rec: Dict[str, Any], contract: Contract,
             statuses: Dict[str, str]) -> List[Dict[str, Any]]:
    case_spec = next(c for c in contract.cases if c.id == rec.get("case_id"))
    diffs: List[Dict[str, Any]] = []
    derived_groups = _group_results(case_spec, statuses)
    for item in rec.get("groups") or []:
        key = str(item.get("group") or "")
        want, got = str(item.get("result") or ""), derived_groups.get(key, "")
        if want != got:
            diffs.append({"check": "group", "case": case_spec.id, "group": key,
                          "expected": want, "derived": got})
    for item in rec.get("sva") or []:
        key = str(item.get("id") or "")
        want = str(item.get("status") or "")
        got = statuses.get(obligation_id("SVA", case_spec.id, key), "")
        if want != got:
            diffs.append({"check": "sva", "case": case_spec.id, "id": key,
                          "expected": want, "derived": got})
    for item in rec.get("scb") or []:
        key = str(item.get("id") or "")
        want = str(item.get("status") or "")
        got = statuses.get(obligation_id("SCB", case_spec.id, key), "")
        if want != got:
            diffs.append({"check": "scb", "case": case_spec.id, "id": key,
                          "expected": want, "derived": got})
    return diffs


def run_shadow(run_dir: str | Path, *, write: bool = True) -> Dict[str, Any]:
    """跑一次影子对账；`write=True` 时同时追加账本并落 `status/shadow_report.json`。"""
    root = Path(run_dir)
    cov = root / "coverage"
    case_ir = _read_json(cov / "case_ir.json")
    if not case_ir.get("cases"):
        return {"schema": SCHEMA, "available": False,
                "note": "没有 case_ir.json（先跑一轮 verify）"}
    contract = contract_from_case_ir(case_ir)
    obligations = compile_obligations(contract)
    by_case: Dict[str, list] = {}
    for obligation in obligations:
        by_case.setdefault(obligation.case, []).append(obligation)

    records = _case_records(cov)
    skipped = len([r for r in _all_records(cov) if not r.get("case_id")])
    bundles = facts = 0
    diffs: List[Dict[str, Any]] = []
    for rec in records:
        case = str(rec.get("case_id") or "")
        if case not in by_case:
            continue
        bundle = build_bundle(rec, contract)
        if write:
            append_bundle(root, bundle)
        bundles += 1
        facts += len(bundle.facts)
        facts_as_dicts = [f.model_dump(by_alias=True) for f in bundle.facts]
        statuses = derive(by_case[case], facts_as_dicts)
        diffs.extend(_compare(rec, contract, statuses))

    chain = verify_chain(root) if write else {"ok": True, "count": 0}
    report = {
        "schema": SCHEMA,
        "available": True,
        "contract_id": contract.id,
        "contract_hash": contract.hash,
        "obligations": len(obligations),
        "bundles": bundles,
        "bundles_skipped_no_case": skipped,
        "facts": facts,
        "ledger": {"path": "evidence/ledger.jsonl", "count": chain.get("count", 0),
                   "chain_ok": chain.get("ok"), "head": str(chain.get("head") or "")[:16]},
        "compare": {"checked": bundles, "mismatched": len(diffs), "diffs": diffs[:50]},
        "ok": not diffs,
        "scope": "case_level（组结果 / SVA / SCB / case_status）；"
                 "CELL 主色仍由 tp_cov_evidence 提供，M2 再接管",
    }
    if write:
        path = root / "status" / "shadow_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    return report


__all__ = ["SCHEMA", "build_bundle", "run_shadow"]
