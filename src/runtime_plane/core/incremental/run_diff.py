"""Run Diff —— 两次运行并排看：覆盖率、TP、回归、决策、归因、RTL。

已有的 `flow_tools.compare_runs` 面向用例级回归对比；这里补的是**验证智能**
维度（决策有效率、归因完整率、RTL 变化），并落一份 `docs/run_diff.json`。
不重跑、不碰进程，只对齐磁盘事实。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.runtime_plane.core.incremental.rtl_diff import diff_runs
from src.runtime_plane.core.metrics.engineering import collect


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coverage(root: Path) -> Dict[str, Any]:
    doc = _read_json(root / "sim" / "coverage" / "coverage_result.json")
    nested = doc.get("coverage") or {}
    report = _read_json(root / "report.json")
    return {
        "functional_pct": _num(doc.get("functional_pct") or nested.get("functional_pct")),
        "overall_pct": _num(doc.get("overall_pct") or nested.get("overall_pct")),
        "signed_off_coverage": _num(report.get("coverage")),
        "verdict": report.get("verdict", ""),
        "signoff_status": report.get("signoff_status", ""),
    }


def _tp(root: Path) -> Dict[str, Any]:
    doc = _read_json(root / "coverage" / "tp_matrix.json")
    counts = doc.get("counts") or {}
    return {"total": int(doc.get("total") or 0), **{k: int(v or 0) for k, v in counts.items()}}


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round(b - a, 2)


def compare_runs(baseline: str | Path, current: str | Path) -> Dict[str, Any]:
    base = Path(baseline)
    cur = Path(current)
    bm = collect(base)
    cm = collect(cur)
    bc = _coverage(base)
    cc = _coverage(cur)
    btp = _tp(base)
    ctp = _tp(cur)
    return {
        "schema": "run_diff_v1",
        "baseline": {"run_id": base.name, "coverage": bc, "tp": btp,
                     "regression": bm["regression"], "decision": bm["decision"],
                     "attribution": bm["attribution"]},
        "current": {"run_id": cur.name, "coverage": cc, "tp": ctp,
                    "regression": cm["regression"], "decision": cm["decision"],
                    "attribution": cm["attribution"]},
        "rtl": diff_runs(base, cur),
        "deltas": {
            "functional_pct": _delta(bc["functional_pct"], cc["functional_pct"]),
            "overall_pct": _delta(bc["overall_pct"], cc["overall_pct"]),
            "tp_hit": ctp.get("HIT", 0) - btp.get("HIT", 0),
            "tp_miss": ctp.get("MISS", 0) - btp.get("MISS", 0),
            "regression_seconds": _delta(bm["regression"]["total_seconds"],
                                         cm["regression"]["total_seconds"]),
            "decision_rate": _delta(bm["decision"]["effectiveness_rate"],
                                    cm["decision"]["effectiveness_rate"]),
            "attribution_rate": _delta(bm["attribution"]["attribution_rate"],
                                       cm["attribution"]["attribution_rate"]),
        },
    }


def write_run_diff(baseline: str | Path, current: str | Path) -> Dict[str, Any]:
    report = compare_runs(baseline, current)
    path = Path(current) / "docs" / "run_diff.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    report["path"] = str(path)
    return report
