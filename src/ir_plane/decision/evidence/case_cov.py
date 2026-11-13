"""逐用例取证 —— **一条用例自己的 ucdb** 能证明哪些测试点。

实现细节在 `case_cov_impl.py`；本模块保留公共 API 与写盘。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.runtime_plane.tools.common.lib import case_meta

from .case_cov_impl import *  # noqa: F401,F403
from .case_cov_impl import (  # noqa: F401
    CASE_COV_SCHEMA, CASE_COV_CACHE_SCHEMA, CASE_TP_SCHEMA, REASON_TEXT,
    _by_case, _case_dirs, _counts, _entries_for, _evaluate_case, _index_tps,
    _load_case_contract, _owner_tps_for_case, _read_json, _read_tp_dicts,
    _select_case_dirs, _summarize_tp,
)


def case_cov_matrix(od: Path, *, max_cases: int = 0,
                    require_wave: bool = True, force: bool = False) -> dict:
    """逐用例解析回归目录 → 覆盖切片 + 用例 ↔ 测试点证据表。

    产物：

        coverage/case_cov/<stage>/<task>.json   一条用例一份
        coverage/case_tp.json                   用例 ↔ TP（正查/反查都行）

    没有 TP IR 时返回空（`_tp_matrix` 也这么做）：没有测试点就没有"签核谁"
    这个问题，不必去跑几百次 vcover。
    """
    od = Path(od)
    tps = _read_tp_dicts(od)
    if not tps:
        return {"schema": CASE_TP_SCHEMA, "cases": [], "by_tp": {}, "by_case": {},
                "counts": {"total": 0, "signed_off": 0, "unsigned": 0,
                           "behavior_pending": 0, "no_owner_case": 0},
                "signed_off_missing_wave": [], "evidence_sampled": False,
                "notes": ["没有 TP IR（coverage/testpoints.yaml）—— 不产逐用例证据"],
                "errors": [], "case_count": 0}

    tp_by_id, tp_by_test = _index_tps(tps)
    contract = _load_case_contract(od)
    # M2b：判定交给 derive —— 需要整份 case_ir（契约），不只是按 case 的索引
    case_ir_doc = _read_json(od / "coverage" / "case_ir.json")
    selected, sampled, notes = _select_case_dirs(
        _case_dirs(od), tp_by_id, tp_by_test, max_cases)

    cases: list = []
    errors: list = []
    for d in selected:
        meta = case_meta.read_task_meta(d)
        owner_tps, basis = _owner_tps_for_case(meta, tp_by_id, tp_by_test)
        if sampled and not owner_tps:
            continue
        rec = _evaluate_case(od, d, owner_tps, basis,
                             require_wave=require_wave, force=force,
                             contract=contract, case_ir=case_ir_doc)
        if rec.get("error"):
            errors.append(f"{rec['task']}: {rec.get('error_detail') or rec['error']}")
        cases.append(rec)

    # ── 汇总：每条测试点被哪些用例证明 ──
    by_tp = {str(tp.get("tp_id") or ""): _summarize_tp(
        tp, _entries_for(str(tp.get("tp_id") or ""), cases)) for tp in tps}
    unsigned = [{"tp_id": tid, "kind": v["kind"], "reasons": v["reasons"]}
                for tid, v in by_tp.items() if v["status"] == "UNSIGNED"]
    missing_wave = [{"tp_id": tid, "signed_off_by": v["signed_off_by"],
                     "owner_case": v["owner_case"]}
                    for tid, v in by_tp.items()
                    if v["signed_off"] and not v.get("wave_abs")]
    timing_warn = [{"tp_id": tid, "kind": v["kind"]}
                   for tid, v in by_tp.items()
                   if v.get("timing_ok") is False and v.get("kind") == "sequence"]
    result = {
        "schema": CASE_TP_SCHEMA, "run": od.name,
        "counts": _counts(by_tp, unsigned), "by_tp": by_tp,
        "by_case": _by_case(cases), "unsigned": unsigned,
        "signed_off_missing_wave": missing_wave,
        "timing_warn": timing_warn,
        "evidence_sampled": sampled, "case_count": len(cases),
        "notes": notes, "errors": errors[:50], "cases": cases,
    }
    _write_case_tp(od, result)
    return result


def _write_case_tp(od: Path, result: dict) -> None:
    """`coverage/case_tp.json` —— 用例 ↔ 测试点证据表（签核材料）。"""
    p = od / "coverage" / "case_tp.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in result.items() if k != "cases"}
        payload["case_count"] = len(result.get("cases") or [])
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8", newline="\n")
    except OSError:
        pass


def case_coverage_patch(case_index: dict) -> dict:
    """`run()` 用的摘要补丁：有逐用例证据才返回 `{"case_coverage": …}`。

    收成函数是为了让 `run` 少一个分支（架构复杂度预算把 `run` 钉在基线上）。
    """
    if not case_index.get("case_count"):
        return {}
    return {"case_coverage": {
        "case_count": case_index.get("case_count", 0),
        "counts": case_index.get("counts") or {},
        "evidence_sampled": bool(case_index.get("evidence_sampled")),
        "case_tp": "coverage/case_tp.json",
        "notes": list(case_index.get("notes") or []),
        "errors": list(case_index.get("errors") or [])[:10],
    }}
