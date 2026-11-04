"""状态权威对账 —— **视图展示的绿黄红** vs `case_cov` 里的 derive 判定。

## 为什么需要

状态只该由 `verification_os.derive()` 产出；`case_view` / `cell_matrix` /
GUI 只做**展示映射**。但历史上视图各自从原始日志重算一遍，改一处就会和签核
结论分叉（"cell_matrix 绿、case_view 红"）。

这份对账把"分叉"从感觉变成数字：

    case_cov（derive 判定）  ──期望色──┐
                                       ├─→ status/authority_diff.json
    case_view（展示层）      ──实际色──┘

口径：只有**有契约**的记录参与（批次级 test / 旧目录没有 CASE，走 legacy
展示，不属于对账范围）。差异为 0 是"单一判定"的验收读数。

TP 级已有 `status/tp_shadow.json`（推导 vs `tp_matrix`），这里把它汇总进来，
不再另算一套。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .status_vocab import NA, worst

SCHEMA = "authority_diff_v1"
REL_PATH = "status/authority_diff.json"

_LAYERS = ("coverage", "sva", "scoreboard", "path")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _records(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted((run_dir / "coverage" / "case_cov").rglob("*.json")):
        rec = _read_json(path)
        task = str(rec.get("task") or "")
        if task:
            out[task] = rec
    return out


def _expected_layers(rec: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """从 `case_cov` 的 derive 判定算期望展示色（独立于 view 的实现）。"""
    groups = [g for g in rec.get("groups") or [] if isinstance(g, dict)]
    if not groups:
        return None
    sva = [s.get("status") for s in rec.get("sva") or [] if isinstance(s, dict)]
    scb = [s.get("status") for s in rec.get("scb") or [] if isinstance(s, dict)]
    path = [(g.get("path") or {}).get("status") for g in groups]
    real_path = [s for s in path if s and s != "NOT_APPLICABLE"]
    return {
        "coverage": worst([g.get("result") for g in groups]),
        "sva": worst(sva) if sva else NA,
        "scoreboard": worst(scb) if scb else NA,
        "path": worst(real_path) if real_path else NA,
    }


def _view_layers(case: Dict[str, Any]) -> Dict[str, str]:
    return {key: str((case.get(key) or {}).get("status") or NA)
            for key in _LAYERS}


def build_authority_diff(run_dir: str | Path) -> Dict[str, Any]:
    root = Path(run_dir)
    view = _read_json(root / "coverage" / "case_view.json")
    records = _records(root)
    diffs: List[Dict[str, Any]] = []
    checked = 0
    for case in view.get("cases") or []:
        if not isinstance(case, dict):
            continue
        rec = records.get(str(case.get("task") or ""))
        expected = _expected_layers(rec or {})
        if expected is None:
            continue                      # legacy/批次：没有契约，不参与对账
        checked += 1
        actual = _view_layers(case)
        for layer in _LAYERS:
            if expected[layer] != actual[layer]:
                diffs.append({"task": case.get("task"),
                              "case_id": case.get("case_id"),
                              "layer": layer,
                              "expected": expected[layer],
                              "actual": actual[layer]})
    tp = _read_json(root / "status" / "tp_shadow.json")
    report = {
        "schema": SCHEMA,
        "run": root.name,
        "case_view": {"checked": checked, "mismatched": len(diffs),
                      "diffs": diffs[:100]},
        "tp_shadow": {"available": bool(tp.get("available")),
                      "tps": tp.get("tps", 0),
                      "mismatched": tp.get("mismatched", 0)},
        "ok": not diffs,
        "note": ("差异为 0 = 视图状态与 case_cov 的 derive 判定一致；"
                 "有差异时先修视图的重算逻辑，不要让两份报表各说各的"),
    }
    return report


def write_authority_diff(run_dir: str | Path) -> Dict[str, Any]:
    root = Path(run_dir)
    report = build_authority_diff(root)
    from src.core.runtime.atomic import atomic_write_json

    path = root / REL_PATH
    try:
        atomic_write_json(path, report)
    except OSError:
        pass
    return report


__all__ = ["REL_PATH", "SCHEMA", "build_authority_diff", "write_authority_diff"]
