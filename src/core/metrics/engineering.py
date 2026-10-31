"""四个工程指标（`engineering_metrics_v1`）。

1. 回归总耗时（秒）与相对基线的下降比例；
2. 增量回归相对全量回归的预计节省（来自 `incremental/plan.json`）；
3. Coverage Bin → Test/Seed 的归因完整率（来自 `coverage/attribution.json`）；
4. Agent 决策有效率（EFFECTIVE / 有确定性结论的评估数）。

全部只读 run 目录；缺数据就写 null / `available:false`，**不拿 0 冒充**
—— "没测到"和"省了 0 秒"是两件事。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.decision.eval import (
    EFFECTIVE, INEFFECTIVE, REGRESSED, UNCERTAIN, read_records, summarize,
)
from src.core.provenance.report import build_attribution_report

SCHEMA = "engineering_metrics_v1"

_HMS = re.compile(r"(\d+):(\d{2}):(\d{2})")


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


def _hms_seconds(text: Any) -> Optional[float]:
    if not isinstance(text, str):
        return None
    m = _HMS.search(text)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def _parse_ts(text: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _regression(root: Path) -> Dict[str, Any]:
    reports = sorted(root.glob("regression_run/**/report.json"))
    if not reports:
        legacy = root / "regression_run" / "report.json"
        reports = [legacy] if legacy.is_file() else []
    total_s = 0.0
    tasks = passed = failed = unknown = 0
    found = False
    for path in reports:
        doc = _read_json(path)
        if not doc:
            continue
        found = True
        secs = _hms_seconds(doc.get("total_time"))
        if secs is None:
            secs = sum(_num(t.get("elapsed")) or 0.0
                       for t in (doc.get("tasks") or []) if isinstance(t, dict))
        total_s += secs
        stats = doc.get("stats") or {}
        tasks += int(doc.get("total") or 0)
        passed += int(stats.get("pass") or 0)
        failed += int(stats.get("fail") or 0)
        unknown += int(stats.get("unknown") or 0)
    return {
        "total_seconds": round(total_s, 2) if found else None,
        "tasks": tasks if found else None,
        "passed": passed if found else None,
        "failed": failed if found else None,
        "unknown": unknown if found else None,
    }


def _run_wall_seconds(root: Path) -> Optional[float]:
    for name in ("events.jsonl", "run_events.jsonl"):
        path = root / "docs" / name
        if not path.is_file():
            continue
        start = end = None
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                kind = doc.get("event_type") or doc.get("kind") or ""
                ts = _parse_ts(doc.get("ts"))
                if ts is None:
                    continue
                if kind == "run.started" and start is None:
                    start = ts
                elif kind in ("run.finished", "run.failed", "run.cancelled"):
                    end = ts
        except OSError:
            continue
        if start and end:
            return round(max(0.0, (end - start).total_seconds()), 2)
    return None


def _incremental(root: Path) -> Dict[str, Any]:
    doc = _read_json(root / "incremental" / "plan.json")
    if not doc:
        return {"available": False,
                "reason": "没有 incremental/plan.json（未启用增量验证）"}
    return {
        "available": True,
        "baseline_run": doc.get("baseline_run", ""),
        "selected_tests": len(doc.get("selected_tests") or []),
        "all_tests": int(doc.get("all_tests") or 0),
        "estimated_full_seconds": doc.get("estimated_full_seconds"),
        "estimated_selected_seconds": doc.get("estimated_selected_seconds"),
        "estimated_savings_seconds": doc.get("estimated_savings_seconds"),
        "estimated_savings_pct": doc.get("estimated_savings_pct"),
        "confidence": doc.get("confidence", ""),
        "estimated": bool(doc.get("estimated", True)),
    }


def _decision(root: Path) -> Dict[str, Any]:
    records = read_records(root)
    summary = summarize(records)
    by = summary["by_status"]
    denominator = by[EFFECTIVE] + by[INEFFECTIVE] + by[REGRESSED]
    return {
        "evaluated": len(records),
        "effective": by[EFFECTIVE],
        "ineffective": by[INEFFECTIVE],
        "regressed": by[REGRESSED],
        "uncertain": by[UNCERTAIN],
        # 分母**不含 UNCERTAIN**：判不出来的决策不该拉低"有效率"
        "effectiveness_rate": round(by[EFFECTIVE] / denominator, 4) if denominator else None,
    }


def _attribution(root: Path) -> Dict[str, Any]:
    doc = _read_json(root / "coverage" / "attribution.json")
    if not doc:
        doc = build_attribution_report(root)
    return {
        "hit_bins": int(doc.get("hit_bins") or 0),
        "attribution_rate": doc.get("attribution_rate"),
        "test_seed_rate": doc.get("test_seed_rate"),
        "exact_rate": doc.get("exact_rate"),
        "weak_rate": doc.get("weak_rate"),
    }


def _collect(run_root: str | Path) -> Dict[str, Any]:
    root = Path(run_root)
    return {
        "schema": SCHEMA,
        "run_id": root.name,
        "regression": _regression(root),
        "run_wall_seconds": _run_wall_seconds(root),
        "incremental": _incremental(root),
        "attribution": _attribution(root),
        "decision": _decision(root),
    }


def _pct_drop(base: Optional[float], current: Optional[float]) -> Optional[float]:
    if base is None or current is None or base <= 0:
        return None
    return round((base - current) / base * 100.0, 2)


def _runs_baseline(baseline: str | Path) -> Dict[str, Any]:
    b = Path(baseline)
    if not b.is_dir():
        return {"error": f"基线目录不存在: {b}"}
    doc = _read_json(b / "docs" / "engineering_metrics.json")
    return doc if doc else _collect(b)


def collect(run_root: str | Path, baseline: Optional[str | Path] = None) -> Dict[str, Any]:
    """当前 run 的四个指标；给了 baseline 就附上相对基线的变化。"""
    out = _collect(run_root)
    if baseline:
        base = _runs_baseline(baseline)
        base_reg = (base.get("regression") or {}).get("total_seconds")
        cur_reg = (out.get("regression") or {}).get("total_seconds")
        out["baseline"] = {
            "run_id": base.get("run_id", Path(str(baseline)).name),
            "regression_total_seconds": base_reg,
            "regression_reduction_pct": _pct_drop(base_reg, cur_reg),
            "attribution_rate_delta": (
                round((out["attribution"].get("attribution_rate") or 0)
                      - (base.get("attribution", {}).get("attribution_rate") or 0), 4)
                if out["attribution"].get("attribution_rate") is not None
                and base.get("attribution", {}).get("attribution_rate") is not None
                else None),
            "decision_rate_delta": (
                round((out["decision"].get("effectiveness_rate") or 0)
                      - (base.get("decision", {}).get("effectiveness_rate") or 0), 4)
                if out["decision"].get("effectiveness_rate") is not None
                and base.get("decision", {}).get("effectiveness_rate") is not None
                else None),
        }
    out["notes"] = _notes(out)
    return out


def _notes(out: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    if out["regression"]["total_seconds"] is None:
        notes.append("没有回归耗时数据（report.json 缺失）")
    if not out["incremental"].get("available"):
        notes.append(out["incremental"].get("reason", ""))
    if out["decision"]["effectiveness_rate"] is None:
        notes.append("没有带确定性结论的决策评估（全为 UNCERTAIN 或未运行）")
    if out["attribution"]["hit_bins"] == 0:
        notes.append("没有命中 bin，归因完整率按 0 计")
    return [n for n in notes if n]


def write(run_root: str | Path, *, baseline: Optional[str | Path] = None,
          event_store=None) -> Dict[str, Any]:
    root = Path(run_root)
    report = collect(root, baseline)
    path = root / "docs" / "engineering_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    report["path"] = str(path)
    if event_store is not None:
        event_store.append(
            "metrics.collected", status="ok",
            payload={"path": path.relative_to(root).as_posix(),
                     "regression_seconds": report["regression"]["total_seconds"],
                     "attribution_rate": report["attribution"]["attribution_rate"],
                     "decision_rate": report["decision"]["effectiveness_rate"]},
            source="metrics",
            dedup_key=f"metrics:{root.name}")
    return report
