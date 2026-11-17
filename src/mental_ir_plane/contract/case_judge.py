"""M2b —— case 级判定交给 `derive()`：采集端只给**原始事实**。

从一个"执行切片"能拿到的最原始的东西出发：

    bins       (tp, cp, bin) → 命中次数（0 命中也要给）
    sva        (id) → 是否被求值过 + 违规次数
    scb        (id) → exec / matched / mismatched
    timing     → 检查过没有 / 超没超窗

`judge_case()` 把它们变成事实，编译该 case 的义务，跑 `derive()`，输出：
组各层状态 / SVA / SCB / case_status —— 与 `case_cov` 现有字段一一对应。

为什么不让 case_cov 自己判：那是"五份投影各算各的"的来源。采集端只负责
**看见什么就记什么**，判据只能有一处。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .compiler import compile_obligations
from .contract_model import Contract, Fact, contract_from_case_ir, worst
from .derive import case_statuses, derive


def _fact(type_: str, subject: Dict[str, Any], value: Dict[str, Any],
          contract_hash: str = "") -> Dict[str, Any]:
    return Fact(type=type_, contract_hash=str(contract_hash or ""),
                subject=subject, value=value).model_dump(by_alias=True)


def build_raw_facts(case_id: str, *, bins: List[Dict[str, Any]] = None,
                    sva: List[Dict[str, Any]] = None,
                    scb: List[Dict[str, Any]] = None,
                    timing_ok: Optional[bool] = None,
                    contract_hash: str = "") -> List[Dict[str, Any]]:
    """原始事实 → 事实列表（不含任何判定）。

    `contract_hash` 是**证据所属的契约版本**；空串表示 legacy（不比较）。
    """
    facts: List[Dict[str, Any]] = []
    for item in bins or []:
        facts.append(_fact("bin_hit", {
            "case": case_id, "tp": str(item.get("tp") or ""),
            "cp": str(item.get("cp") or ""), "bin": str(item.get("bin") or "")},
            {"hits": int(item.get("hits") or 0)}, contract_hash))
    for item in sva or []:
        facts.append(_fact("sva_result", {
            "case": case_id, "id": str(item.get("id") or "")},
            {"present": bool(item.get("present")),
             "fail": None if item.get("fail") is None else int(item.get("fail") or 0)},
            contract_hash))
    for item in scb or []:
        facts.append(_fact("scb_result", {
            "case": case_id, "id": str(item.get("id") or "")},
            {"exec": int(item.get("exec") or 0),
             "matched": item.get("matched"), "mismatched": item.get("mismatched")},
            contract_hash))
    facts.append(_fact("timing", {"case": case_id}, {"ok": timing_ok},
                       contract_hash))
    return facts


def judge_case(case_ir: Dict[str, Any], case_id: str,
               facts: List[Dict[str, Any]], *,
               expected_contract_hash: str = "") -> Optional[Dict[str, Any]]:
    """该 case 的义务状态（没有契约/没有义务 → None，调用方保留旧判定）。

    `expected_contract_hash` 是**当前契约构建物**的哈希（manifest）。
    事实带了哈希且与它不一致 → 拒绝判定（deny-first），不静默计入。
    """
    if not case_ir.get("cases") or not case_id:
        return None
    contract: Contract = contract_from_case_ir(case_ir)
    expected = str(expected_contract_hash or contract.hash)
    foreign = {str(f.get("contract_hash") or "") for f in facts
               if f.get("contract_hash")}
    foreign.discard(expected)
    if foreign:
        raise ValueError(
            f"事实契约哈希 {sorted(h[:12] for h in foreign)} 与当前契约 "
            f"{expected[:12]}… 不一致 —— 拒绝用它判定 CASE {case_id}")
    obligations = [o for o in compile_obligations(contract) if o.case == case_id]
    if not obligations:
        return None
    statuses = derive(obligations, facts)
    slot = case_statuses(obligations, statuses)[case_id]
    groups = {group: {"layers": layers,
                      "result": worst([s for s in layers.values() if s])}
              for group, layers in slot["groups"].items()}
    return {"statuses": statuses, "groups": groups, "sva": slot["sva"],
            "scb": slot["scb"], "case_status": slot["case_status"]}


__all__ = ["build_raw_facts", "judge_case"]
