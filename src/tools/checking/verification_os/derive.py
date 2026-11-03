"""推导 —— L2 义务 × L3 事实 → 状态（纯函数，可重放）。

这是 v3 的"唯一判定实现"。约定：

  · **不读文件、不写文件**，只吃 `Contract + [Obligation] + [fact dict]`；
  · 同样的输入必然得到同样的输出（影子比对、跨机器复核都靠它）；
  · 状态词汇与现有 `case_cov` 一致（PROVEN / PARTIAL / MISSING /
    PENDING_BACKEND / NOT_APPLICABLE / NOT_EXECUTED），M0 才能逐条对账。

谓词语义（`compiler.LAYER_PREDICATES` 与之一一对应）：

    all_bins_hit  该组的 TP 名下**每个仓都命中** → PROVEN；部分 → PARTIAL；没有 → MISSING
    ok            时序检查通过 → PROVEN；超窗 → MISSING；没检查 → NOT_APPLICABLE
    matched       比对执行且不 mismatch → PROVEN；mismatch → MISSING；没有汇总 → NOT_APPLICABLE
    proven        路径证据 PROVEN；没有事实 → PENDING_BACKEND（后端未接）
    no_fail       断言执行且 0 违规 → PROVEN；有违规 → MISSING；没有事实 → MISSING
    executed      比对执行过（exec>0）→ PROVEN；未执行 → NOT_EXECUTED
"""
from __future__ import annotations

from typing import Any, Dict, List

from .contract_model import CaseStatus, Obligation, worst

S = CaseStatus


def _type_of(fact: Dict[str, Any]) -> str:
    """`FactType` 枚举或字符串都认 —— 账本读出来是字符串，内存对象是枚举。"""
    value = fact.get("type")
    return str(getattr(value, "value", value))


def _by_type(ledger: List[Dict[str, Any]], fact_type: str) -> List[Dict[str, Any]]:
    return [f for f in ledger if _type_of(f) == fact_type]


def _subject(fact: Dict[str, Any], key: str) -> Any:
    return (fact.get("subject") or {}).get(key)


def _value(fact: Dict[str, Any], key: str) -> Any:
    return (fact.get("value") or {}).get(key)


def _tp_bins(ledger: List[Dict[str, Any]], case: str,
             tp_ids: List[str]) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {tp: [] for tp in tp_ids}
    for fact in _by_type(ledger, "bin_hit"):
        if _subject(fact, "case") != case:
            continue
        tp = str(_subject(fact, "tp") or "")
        if tp in out:
            out[tp].append(int(_value(fact, "hits") or 0))
    return out


def _all_bins_hit(ledger: List[Dict[str, Any]], where: Dict[str, Any]) -> str:
    """**只对本次执行里出现过的 TP 判**（与 case_cov 的 per-record 口径一致）。

    契约里的 tp_ids 是整个组；但一次执行（一个 seed/一条 test）只覆盖其中
    一部分。要求"全组都中"会把每条记录的结论都压成 PARTIAL —— 那不是事实，
    是把"别的测试没跑"记到了这条头上。
    """
    case = str(where.get("case") or "")
    tp_ids = [str(t) for t in where.get("tp_ids") or []]
    bins = _tp_bins(ledger, case, tp_ids)
    present = {tp: values for tp, values in bins.items() if values}
    if not present:
        return S.MISSING.value
    if all(all(h > 0 for h in values) for values in present.values()):
        return S.PROVEN.value
    hits = [h for values in present.values() for h in values]
    return S.PARTIAL.value if any(h > 0 for h in hits) else S.MISSING.value


def _first(ledger: List[Dict[str, Any]], fact_type: str, case: str,
           **match: Any) -> Dict[str, Any] | None:
    for fact in _by_type(ledger, fact_type):
        if _subject(fact, "case") != case:
            continue
        if all(_subject(fact, k) == v for k, v in match.items()):
            return fact
    return None


def _timing(ledger: List[Dict[str, Any]], where: Dict[str, Any]) -> str:
    fact = _first(ledger, "timing", str(where.get("case") or ""))
    if fact is None:
        return S.NOT_APPLICABLE.value
    ok = _value(fact, "ok")
    if ok is True:
        return S.PROVEN.value
    return S.MISSING.value if ok is False else S.NOT_APPLICABLE.value


def _scb_matched(ledger: List[Dict[str, Any]], where: Dict[str, Any]) -> str:
    case = str(where.get("case") or "")
    fact = _first(ledger, "scb_result", case, id="aggregate")
    if fact is None:
        return S.NOT_APPLICABLE.value
    matched = _value(fact, "matched")
    if matched is None:
        return S.NOT_APPLICABLE.value
    if int(_value(fact, "mismatched") or 0) > 0:
        return S.MISSING.value
    return S.PROVEN.value if int(matched) > 0 else S.MISSING.value


def _path(ledger: List[Dict[str, Any]], where: Dict[str, Any]) -> str:
    fact = _first(ledger, "path_result", str(where.get("case") or ""),
                  path=str(where.get("path") or ""))
    if fact is None:
        return S.PENDING_BACKEND.value
    return str(_value(fact, "status") or S.MISSING.value)


def _sva(ledger: List[Dict[str, Any]], where: Dict[str, Any]) -> str:
    fact = _first(ledger, "sva_result", str(where.get("case") or ""),
                  id=str(where.get("id") or ""))
    if fact is None:
        return S.MISSING.value
    return str(_value(fact, "status") or S.MISSING.value)


def _scb_executed(ledger: List[Dict[str, Any]], where: Dict[str, Any]) -> str:
    case = str(where.get("case") or "")
    sb_id = str(where.get("id") or "")
    fact = _first(ledger, "scb_result", case, id=sb_id)
    if fact is None:
        fact = _first(ledger, "scb_result", case, id="aggregate")
    if fact is None:
        return S.NOT_EXECUTED.value
    return str(_value(fact, "status") or S.NOT_EXECUTED.value)


_DISPATCH = {
    "all_bins_hit": _all_bins_hit,
    "ok": _timing,
    "matched": _scb_matched,
    "proven": _path,
    "no_fail": _sva,
    "executed": _scb_executed,
}


def evaluate(obligation: Obligation, ledger: List[Dict[str, Any]]) -> str:
    predicate = obligation.predicate
    fn = _DISPATCH.get(predicate.op)
    if fn is None:
        raise ValueError(f"未知算子: {predicate.op!r}（义务 {obligation.obligation_id}）")
    return fn(ledger, dict(predicate.where))


def derive(obligations: List[Obligation],
           ledger: List[Dict[str, Any]]) -> Dict[str, str]:
    """义务 → 状态。**唯一判定实现**：任何模块都不许再自己算。"""
    return {o.obligation_id: evaluate(o, ledger) for o in obligations}


def case_statuses(obligations: List[Obligation],
                  statuses: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """按 case 归并推导结果（给影子比对 / 视图用）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for obligation in obligations:
        slot = out.setdefault(obligation.case, {"groups": {}, "sva": {}, "scb": {}})
        subject = obligation.subject
        status = statuses.get(obligation.obligation_id, S.MISSING.value)
        if obligation.kind == "group_layer":
            layers = slot["groups"].setdefault(str(subject.get("group")), {})
            layers[str(subject.get("layer"))] = status
        elif obligation.kind == "sva":
            slot["sva"][str(subject.get("sva"))] = status
        elif obligation.kind == "scb":
            slot["scb"][str(subject.get("scb"))] = status
    for slot in out.values():
        # 与 `case_cov._case_status(groups, sva, scb)` 同口径：三集合一起判
        every = [v for group in slot["groups"].values() for v in group.values()]
        every += list(slot["sva"].values()) + list(slot["scb"].values())
        slot["case_status"] = _case_status(every)
    return out


def _case_status(statuses: List[str]) -> str:
    if not statuses:
        return ""
    verdict = worst(statuses)
    if verdict in ("PROVEN", "NOT_APPLICABLE"):
        return "VERIFIED"
    return "NOT_VERIFIED" if verdict == "MISSING" else "PARTIAL"


__all__ = ["case_statuses", "derive", "evaluate"]
