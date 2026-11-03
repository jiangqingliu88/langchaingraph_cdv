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
        out[tid] = {"test": str(execution.get("test") or ""),
                    "stage": str(execution.get("stage") or ""),
                    "seeds": seeds, "case_id": str(tp.get("case_id") or "")}
    return out


def _declared_tests(run_dir: Path) -> set:
    doc = _read_yaml(run_dir / "inputs" / "yaml" / "regression.yaml")
    return {str(t.get("name") or "") for t in (doc.get("tests") or [])
            if isinstance(t, dict)}


def _current_ledger(run_dir: Path, current: str) -> List[Dict[str, Any]]:
    """只留当前契约的事实（run 级事实 `contract_hash` 为空，照用）。"""
    return [f for f in read_ledger(run_dir)
            if str(f.get("contract_hash") or "") in ("", current)]


def _tps_of(obligation, tp_index: Dict[str, Dict[str, Any]]) -> List[str]:
    if obligation.kind == "group_layer":
        return [str(t) for t in (obligation.predicate.where.get("tp_ids") or [])]
    return [tid for tid, info in tp_index.items()
            if info.get("case_id") == obligation.case]


def build_worklist(run_dir: str | Path) -> Dict[str, Any]:
    """未清偿义务 → 需要重跑的回归 test 清单（只读）。"""
    root = Path(run_dir)
    check = check_contract(root)
    if not check.get("ok"):
        return {"schema": SCHEMA, "available": False,
                "reason": check.get("reason"), "note": "没有契约 → 跑全量"}
    contract = load_contract(root)
    if contract is None:
        return {"schema": SCHEMA, "available": False,
                "reason": "contract_unreadable", "note": "没有契约 → 跑全量"}
    declared = _declared_tests(root)
    if not declared:
        return {"schema": SCHEMA, "available": False,
                "reason": "regression_yaml_missing", "note": "没有回归清单 → 跑全量"}

    obligations = compile_obligations(contract)
    statuses = derive(obligations, _current_ledger(root, contract_hash(root)))
    tp_index = _tp_index(root)

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

    tests = sorted(items)
    return {
        "schema": SCHEMA,
        "available": True,
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
    }


def write_worklist(run_dir: str | Path) -> Dict[str, Any]:
    data = build_worklist(run_dir)
    path = Path(run_dir) / "status" / "worklist.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass
    return data


__all__ = ["SCHEMA", "build_worklist", "regression_test_name", "write_worklist"]
