"""M4 —— **义务驱动的执行清单**：只重跑还没清偿的那几条。

输入全部是只读的：契约（义务）、账本（事实）、`testpoints.yaml`（TP →
test/stage/seed）、`regression.yaml`（真实存在的回归 test 名）。

输出：

    {"open": 12, "tests": ["tp_x", …], "regex": "^(tp_x|tp_y)$",
     "items": [{test, stage, seeds, tp_ids, obligations}], "skipped_no_test": [...]}

关键纪律：

  · **算不出来就跑全量**（契约缺失 / regression.yaml 缺失 → `available: false`）；
  · 义务到 TP 的映射只走契约里的 `tp_ids` 与 TP 的 `case_id`，不从名字猜；
  · 映射不到回归 test 的（观测型组没有独立用例）进 `skipped_no_test`，
    **不静默丢**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .build import check_contract, contract_hash, load_contract
from .compiler import compile_obligations
from .derive import derive
from .ledger import read_ledger

SCHEMA = "os_worklist_v1"
_DONE = ("PROVEN", "NOT_APPLICABLE")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def regression_test_name(tp_id: str) -> str:
    """TP → 回归 test 名（与 `regression_gen` 同一口径：`tp_<slug>`）。"""
    slug = re.sub(r"[^a-z0-9]+", "_", str(tp_id or "tp").lower()).strip("_")
    if slug.startswith("tp_"):
        slug = slug[len("tp_"):]
    return f"tp_{slug}"


def _tp_index(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    doc = _read_yaml(run_dir / "coverage" / "testpoints.yaml")
    out: Dict[str, Dict[str, Any]] = {}
    for tp in doc.get("testpoints") or []:
        if not isinstance(tp, dict):
            continue
        tid = str(tp.get("tp_id") or "")
        if not tid:
            continue
        execution = tp.get("execution") or {}
        seeds = [int(s) for s in execution.get("seeds") or [] if str(s).isdigit()]
        case_ids = [str(c) for c in (tp.get("case_ids") or []) if str(c)]
        if not case_ids and tp.get("case_id"):
            case_ids = [str(tp["case_id"])]
        out[tid] = {"test": str(execution.get("test") or ""),
                    "stage": str(execution.get("stage") or ""),
                    "seeds": seeds, "case_id": str(tp.get("case_id") or ""),
                    "case_ids": case_ids}
    return out


def _declared_tests(run_dir: Path) -> set:
    doc = _read_yaml(run_dir / "inputs" / "yaml" / "regression.yaml")
    return {str(t.get("name") or "") for t in (doc.get("tests") or [])
            if isinstance(t, dict)}


def _current_ledger(run_dir: Path, current: str) -> List[Dict[str, Any]]:
    """只留当前契约的事实（run 级事实 `contract_hash` 为空，照用）。"""
    return [f for f in read_ledger(run_dir)
            if str(f.get("contract_hash") or "") in ("", current)]


def _load_coverage_holes(run_dir: Path) -> Dict[str, Any]:
    """覆盖缺口（优先读产物；没有就现算 —— 只读，不落盘）。"""
    doc = _read_json(run_dir / "coverage" / "coverage_holes.json")
    if doc:
        return doc
    try:
        from src.layers.l3_decision.evidence.coverage_holes import (
            build_coverage_holes,
        )
        return build_coverage_holes(run_dir)
    except Exception:                              # noqa: BLE001 旁路
        return {}


#: 这些缺口可以直接翻译成"再跑哪条 test"。
_RERUN_ACTIONS = ("stimulus_gap", "signoff_gap")


def _coverage_suggestions(holes: Dict[str, Any], declared: set,
                          tp_index: Dict[str, Dict[str, Any]]
                          ) -> tuple:
    """`coverage_holes` → `[{test, seeds, tp_ids, action}]`（可重跑的建议）。

    `model_drift` 不产生重跑建议（那是生成/命名问题），`backend_pending`
    也不产生（后端没接，跑了也没用）—— 它们留在 `coverage_holes.json` 里。
    """
    out: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for hole in holes.get("holes") or []:
        if not isinstance(hole, dict):
            continue
        action = str(hole.get("action") or "")
        if action not in _RERUN_ACTIONS:
            continue
        tid = str(hole.get("tp_id") or "")
        test = regression_test_name(tid)
        if test not in declared:
            skipped.append({"tp_id": tid, "action": action,
                            "reason": "no_regression_test", "test": test})
            continue
        info = tp_index.get(tid) or {}
        seeds = list(dict.fromkeys(
            [int(s) for s in (hole.get("seeds") or []) if str(s).isdigit()]
            + [int(s) for s in (info.get("seeds") or []) if str(s).isdigit()]))
        out.append({
            "test": test,
            "stage": info.get("stage") or str(hole.get("stage") or ""),
            "seeds": seeds,
            "tp_ids": [tid] if tid else [],
            "action": action,
            "dimension": hole.get("dimension", ""),
            "bin": hole.get("bin", ""),
            "requirement": hole.get("requirement", ""),
        })
    return out, skipped


def _merge_suggestions(items: Dict[str, Dict[str, Any]],
                       suggestions: List[Dict[str, Any]]) -> None:
    """覆盖缺口建议并入 `items`：同一 test 只出现一次，seeds/tp_ids 取并集。"""
    for suggestion in suggestions:
        slot = items.setdefault(suggestion["test"], {
            "test": suggestion["test"], "stage": suggestion["stage"],
            "seeds": list(suggestion["seeds"]), "tp_ids": [], "obligations": [],
            "coverage_holes": []})
        slot["seeds"] = sorted(set(slot.get("seeds") or [])
                               | set(suggestion["seeds"]))
        for tid in suggestion["tp_ids"]:
            if tid not in slot["tp_ids"]:
                slot["tp_ids"].append(tid)
        slot.setdefault("coverage_holes", []).append({
            "tp_id": suggestion["tp_ids"][0] if suggestion["tp_ids"] else "",
            "action": suggestion["action"],
            "dimension": suggestion["dimension"],
            "bin": suggestion["bin"],
            "requirement": suggestion["requirement"]})


def _tps_of(obligation, tp_index: Dict[str, Dict[str, Any]]) -> List[str]:
    if obligation.kind == "group_layer":
        return [str(t) for t in (obligation.predicate.where.get("tp_ids") or [])]
    return [tid for tid, info in tp_index.items()
            if obligation.case in (info.get("case_ids")
                                   or [info.get("case_id")])]


def _impact_summary(run_dir: Path) -> Dict[str, Any]:
    """RTL 变更影响（`incremental/plan.json`）—— 用于**最小重跑**排序。"""
    doc = _read_json(run_dir / "incremental" / "plan.json")
    if not doc:
        return {"available": False, "reason": "没有 incremental/plan.json"}
    confidence = str(doc.get("confidence") or "")
    return {
        "available": True,
        "confidence": confidence,
        "selected_tests": list(doc.get("selected_tests") or []),
        "changed_files": list((doc.get("changed") or {}).get("changed") or []),
        "reason": str(doc.get("reason") or ""),
        # 只有非保守结论才允许拿来"缩小范围"；其余仍按全量。
        "reliable": confidence not in ("", "conservative_all", "unknown_file"),
    }


def build_worklist(run_dir: str | Path) -> Dict[str, Any]:
    """未清偿义务 → 需要重跑的回归 test 清单（只读）。"""
    root = Path(run_dir)
    holes = _load_coverage_holes(root)
    hole_summary = {"available": bool(holes.get("available")),
                    "counts": holes.get("counts") or {}}
    impact = _impact_summary(root)
    check = check_contract(root)
    if not check.get("ok"):
        return {"schema": SCHEMA, "available": False,
                "reason": check.get("reason"), "note": "没有契约 → 跑全量",
                "coverage_holes": hole_summary, "impact": impact}
    contract = load_contract(root)
    if contract is None:
        return {"schema": SCHEMA, "available": False,
                "reason": "contract_unreadable", "note": "没有契约 → 跑全量",
                "coverage_holes": hole_summary, "impact": impact}
    declared = _declared_tests(root)
    if not declared:
        return {"schema": SCHEMA, "available": False,
                "reason": "regression_yaml_missing", "note": "没有回归清单 → 跑全量",
                "coverage_holes": hole_summary, "impact": impact}

    obligations = compile_obligations(contract)
    current_facts = _current_ledger(root, contract_hash(root))
    statuses = derive(obligations, current_facts)
    tp_index = _tp_index(root)
    suggestions, hole_skipped = _coverage_suggestions(holes, declared, tp_index)
    selected = set(impact.get("selected_tests") or [])
    for suggestion in suggestions:
        suggestion["in_impact"] = (
            (not impact.get("reliable")) or suggestion["test"] in selected)

    items: Dict[str, Dict[str, Any]] = {}
    skipped: List[Dict[str, Any]] = []
    open_ids: List[str] = []
    for obligation in obligations:
        status = statuses.get(obligation.obligation_id)
        if status in _DONE:
            continue
        open_ids.append(obligation.obligation_id)
        tps = _tps_of(obligation, tp_index)
        if not tps:
            skipped.append({"obligation": obligation.obligation_id,
                            "reason": "no_tp_mapping"})
            continue
        for tid in tps:
            info = tp_index.get(tid) or {}
            test = regression_test_name(tid)
            if test not in declared:
                if not any(s.get("obligation") == obligation.obligation_id
                           for s in skipped):
                    skipped.append({"obligation": obligation.obligation_id,
                                    "reason": "no_regression_test", "tp_id": tid})
                continue
            slot = items.setdefault(test, {
                "test": test, "stage": info.get("stage"),
                "seeds": info.get("seeds") or [], "tp_ids": [], "obligations": []})
            if tid not in slot["tp_ids"]:
                slot["tp_ids"].append(tid)
            if obligation.obligation_id not in slot["obligations"]:
                slot["obligations"].append(obligation.obligation_id)

    # 覆盖缺口 → 重跑建议（与义务清单合并；同一 test 只出现一次）
    _merge_suggestions(items, suggestions)

    tests = sorted(items)
    return {
        "schema": SCHEMA,
        "available": True,
        # **有没有历史证据**：一次全新 run 的账本是空的，此时"全部未清偿"只是
        # 因为还没跑过，worklist 不能当执行计划用（它会漏掉批次用例）。
        # 自动启用 worklist 的调用方必须看这个标志。
        "prior_evidence": bool(current_facts),
        "ledger_facts": len(current_facts),
        "contract_id": contract.id,
        "contract_hash": contract_hash(root),
        "obligations": len(obligations),
        "open": len(open_ids),
        "items": [items[t] for t in tests],
        "tests": tests,
        "count": len(tests),
        # **必须允许种子/批次后缀**：`tests` 过滤是对**目录名**做 `re.search`
        # （`tp_x_seed_3001` / `tp_x_run_2_seed_3001`），锚死 `$` 会把它们全筛掉，
        # 分级回归随即报"没有任何用例匹配 tag"。
        "regex": ("^(" + "|".join(re.escape(t) for t in tests) + ")"
                  r"(?:_run_\d+)?(?:_seed_\d+)?$") if tests else "",
        "skipped_no_test": skipped[:50],
        # **覆盖缺口 → 下一轮建议**（CDV 闭环）。与义务清单合并进 `items`，
        # 但单独列一份，调用方可以只取建议而不跑义务清单。
        "coverage_holes": {
            **hole_summary,
            "suggested": suggestions,
            "suggested_count": len(suggestions),
            "skipped": hole_skipped[:50],
        },
        # **变更影响**：只有 `reliable=True` 时才能用来缩小重跑范围；
        # `in_impact` 标在每条建议上，调用方可以只跑 impacted。
        "impact": impact,
        "impact_suggested": [s for s in suggestions if s.get("in_impact")],
    }


def write_worklist(run_dir: str | Path) -> Dict[str, Any]:
    data = build_worklist(run_dir)
    from src.core.runtime.atomic import atomic_write_json

    path = Path(run_dir) / "status" / "worklist.json"
    try:
        atomic_write_json(path, data)
    except OSError:
        pass
    return data


__all__ = ["SCHEMA", "build_worklist", "regression_test_name", "write_worklist"]
