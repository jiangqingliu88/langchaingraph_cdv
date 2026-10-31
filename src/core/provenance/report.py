"""覆盖率归因完整率报告（`coverage/attribution.json`）。

用户要的链是：

    Coverage Bin → TP ID → Test Name → Seed → StimulusPlan → RTL Hash

Provenance DAG 已经能回答大部分；这里把它压成**可计量的完整率**，供
工程指标与签核证据引用。**不把 weak 说成 exact**：每个 bin 都带 confidence，
完整率按「五段链是否都有」算，缺一段就是缺一段。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from src.core.provenance.attribution import (
    HIT_STATUSES, Attribution, _bin_name, classify, read_json, sha256_file,
)

SCHEMA = "coverage_attribution_v1"


def _digest(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rtl_hash(root: Path) -> str:
    """RTL 聚合哈希 —— 与 lineage 同口径：排序后拼「文件名 + 文件哈希」。"""
    manifest = read_json(root / "docs" / "manifest.json")
    version = manifest.get("rtl_version") or {}
    if isinstance(version, dict) and version.get("content_hash"):
        return str(version["content_hash"])
    rtl = root / "rtl"
    if not rtl.is_dir():
        return ""
    parts = []
    for path in sorted(rtl.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            parts.append(f"{path.relative_to(rtl).as_posix()}:{sha256_file(path)}")
    return _digest(parts) if parts else ""


def _plan_sha(root: Path) -> str:
    doc = read_json(root / "coverage" / "stimulus_plan.json")
    if doc.get("sha256"):
        return str(doc["sha256"])
    path = root / "coverage" / "stimulus_plan.json"
    return sha256_file(path) if path.is_file() else ""


def _seeds_by_test(attr: Attribution) -> Dict[str, Set[int]]:
    return {test: set((info or {}).get("seeds") or set())
            for test, info in attr.tests.items()}


def _bin_entry(row: Dict[str, Any], attr: Attribution,
               seeds_by_test: Dict[str, Set[int]],
               plan_sha: str, rtl_hash: str) -> Dict[str, Any]:
    bin_id = _bin_name(row)
    tp_id = str(row.get("tp_id") or "")
    exact = sorted(attr.bin_tests_exact.get(bin_id) or set())
    weak = sorted(attr.bin_tests_weak.get(bin_id) or set())
    tests = exact or weak
    seeds = sorted({s for t in tests for s in seeds_by_test.get(t, set())})
    links = {
        "tp": bool(tp_id),
        "test": bool(tests),
        "seed": bool(seeds),
        "stimulus_plan": bool(plan_sha),
        "rtl": bool(rtl_hash),
    }
    return {
        "bin": bin_id, "tp_id": tp_id, "tests": tests, "seeds": seeds,
        "stimulus_plan_sha256": plan_sha, "rtl_hash": rtl_hash,
        "confidence": "exact" if exact else ("weak" if weak else "none"),
        "links": links,
        "complete": all(links.values()),
    }


def _completeness(bins: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(bins)
    counts = {k: sum(1 for b in bins if b["links"][k])
              for k in ("tp", "test", "seed", "stimulus_plan", "rtl")}
    complete = sum(1 for b in bins if b["complete"])
    exact = sum(1 for b in bins if b["confidence"] == "exact")
    weak = sum(1 for b in bins if b["confidence"] == "weak")
    rate = lambda n: round(n / total, 4) if total else 0.0
    return {
        "hit_bins": total,
        "with_tp": counts["tp"],
        "with_test": counts["test"],
        "with_seed": counts["seed"],
        "with_stimulus_plan": counts["stimulus_plan"],
        "with_rtl": counts["rtl"],
        "complete_chain": complete,
        "attribution_rate": rate(complete),
        "test_seed_rate": rate(sum(1 for b in bins
                                   if b["links"]["test"] and b["links"]["seed"])),
        "exact_rate": rate(exact),
        "weak_rate": rate(weak),
    }


def build_attribution_report(run_root: str | Path,
                             attribution: Optional[Attribution] = None) -> Dict[str, Any]:
    root = Path(run_root)
    attr = attribution or classify(root)
    matrix = read_json(root / "coverage" / "tp_matrix.json")
    rows = [r for r in (matrix.get("rows") or []) if isinstance(r, dict)]
    plan_sha = _plan_sha(root)
    rtl_hash = _rtl_hash(root)
    seeds_by_test = _seeds_by_test(attr)
    bins = [_bin_entry(r, attr, seeds_by_test, plan_sha, rtl_hash)
            for r in rows if str(r.get("status") or "") in HIT_STATUSES]
    stats = _completeness(bins)
    stats["bins_total"] = len(rows)
    notes = list(attr.notes)
    if stats["weak_rate"] and not stats["exact_rate"]:
        notes.append("没有 per-test 覆盖率 sidecar：bin→test 只能 weak，"
                     "完整率按 weak 计入")
    return {"schema": SCHEMA, "run_id": root.name,
            **stats, "bins": bins, "notes": notes}


def write_attribution_report(run_root: str | Path,
                             attribution: Optional[Attribution] = None) -> Dict[str, Any]:
    root = Path(run_root)
    report = build_attribution_report(root, attribution)
    path = root / "coverage" / "attribution.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    report["path"] = str(path)
    return report
