"""Exact / Weak / Unknown 的正式语义。

    EXACT   逐用例覆盖率事实 + 完整身份关联（不是因果证明）
    WEAK    合并覆盖率 + 计划归因
    UNKNOWN 无法建立可信归因，不参与贡献计算
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

LEVELS = ("EXACT", "WEAK", "UNKNOWN")
_FULL_IDENTITY = ("run_id", "test_id", "seed", "rtl_hash",
                  "coverage_model_hash", "stimulus_plan_hash")


def classify_record(record: Dict[str, Any]) -> str:
    """一条归因记录 → EXACT / WEAK / UNKNOWN。"""
    if not isinstance(record, dict):
        return "UNKNOWN"
    level = str(record.get("attribution_level") or "").upper()
    if level in LEVELS:
        return level
    if record.get("hit_by"):
        # 逐用例事实：身份链完整才算 EXACT
        if all(record.get(k) not in (None, "") for k in _FULL_IDENTITY):
            return "EXACT"
        return "UNKNOWN"
    if record.get("attributed_by") or record.get("confidence") == "weak":
        return "WEAK"
    if record.get("confidence") == "exact":
        return "EXACT"
    return "UNKNOWN"


def from_attribution_doc(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """兼容现有 `coverage/attribution.json` 的 `bins` 形状。"""
    out: List[Dict[str, Any]] = []
    for item in (doc or {}).get("bins") or []:
        if not isinstance(item, dict):
            continue
        rec = dict(item)
        rec.setdefault("attribution_level", classify_record(rec))
        out.append(rec)
    return out


def rates(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """固定分母：EXACT/(EXACT+WEAK)；UNKNOWN 单列，不拿来美化 Exact Rate。"""
    rows = [r for r in records if isinstance(r, dict)]
    counts = {level: 0 for level in LEVELS}
    for row in rows:
        counts[classify_record(row)] = counts.get(classify_record(row), 0) + 1
    attributable = counts["EXACT"] + counts["WEAK"]
    total = len(rows)
    return {
        "total": total,
        "counts": counts,
        "exact_rate": round(counts["EXACT"] / attributable, 4)
                      if attributable else 0.0,
        "weak_rate": round(counts["WEAK"] / attributable, 4)
                     if attributable else 0.0,
        "unknown_rate": round(counts["UNKNOWN"] / total, 4) if total else 0.0,
        "identity_completeness": round(
            sum(1 for r in rows if all(r.get(k) not in (None, "")
                                       for k in _FULL_IDENTITY)) / total, 4)
            if total else 0.0,
    }


def quality_gate(result: Dict[str, Any], *, min_identity: float = 1.0,
                 max_unknown: float = 0.0) -> Dict[str, Any]:
    errors: List[str] = []
    if float(result.get("identity_completeness") or 0) < min_identity:
        errors.append("identity_completeness 低于目标 —— 身份链不完整")
    if float(result.get("unknown_rate") or 0) > max_unknown:
        errors.append("unknown_rate 超限 —— 有 Bin 无法可信归因")
    return {"ok": not errors, "errors": errors, "result": result}


__all__ = [
    "LEVELS", "classify_record", "from_attribution_doc", "quality_gate",
    "rates",
]
