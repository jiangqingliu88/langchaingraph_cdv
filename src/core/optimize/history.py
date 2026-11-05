"""回归历史分析（`regression_history_v1`）。

只读历史 run 目录里的 `regression_run/**/report.json`：
每条 test 的通过/失败/未知次数、实际耗时、种子、以及（有 per-test 精确归因时）
覆盖到哪些 bin。**没有精确归因就不判断"低边际"** —— 不拿合并覆盖率猜。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

SCHEMA = "regression_history_v1"
_SEED_RE = re.compile(r"_seed_(\d+)")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _base_test(name: str) -> str:
    name = str(name or "")
    if name.startswith("test_"):
        name = name[5:]
    return _SEED_RE.sub("", name).rstrip("_") or name


def _seed_of(name: str, work_dir: str = "") -> Optional[int]:
    for text in (str(name or ""), str(work_dir or "")):
        m = _SEED_RE.search(text)
        if m:
            return int(m.group(1))
    return None


def find_run_dirs(project: str | Path = ".", history: str | Path | None = None) -> List[Path]:
    roots = [Path(history)] if history else [Path(project)]
    out: List[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        if (root / "regression_run").is_dir():
            out.append(root)
            continue
        out.extend(p for p in sorted(root.glob("output_*")) if p.is_dir())
        out.extend(p for p in sorted(root.glob("*/output_*")) if p.is_dir())
    seen, unique = set(), []
    for p in out:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _exact_bins(run: Path) -> Dict[str, Set[str]]:
    """从 attribution.json 取 exact 归属：test → bin 集合。"""
    doc = _read_json(run / "coverage" / "attribution.json")
    out: Dict[str, Set[str]] = defaultdict(set)
    for item in doc.get("bins") or []:
        if not isinstance(item, dict) or item.get("confidence") != "exact":
            continue
        bin_id = str(item.get("bin") or "")
        for test in item.get("tests") or []:
            if bin_id and test:
                out[str(test)].add(bin_id)
    return dict(out)


def _report_tasks(run: Path) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for path in sorted(run.glob("regression_run/**/report.json")):
        for task in _read_json(path).get("tasks") or []:
            if isinstance(task, dict):
                tasks.append(task)
    # 老布局 / 没有 report.json 时退回归一化文本
    if tasks:
        return tasks
    for path in sorted(run.glob("regression_run/**/report_summary.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = re.match(r"(pass|fail|unknown)\s*:\s*(\S+)\s+\(([^)]*)\)(?:\s+\[([\d.]+)s\])?",
                         line.strip(), re.I)
            if m:
                tasks.append({"name": m.group(2), "status": m.group(1).lower(),
                              "work_dir": m.group(3),
                              "elapsed": float(m.group(4) or 0)})
    return tasks


def collect_history(run_dirs: Iterable[str | Path]) -> Dict[str, Any]:
    runs = [Path(r) for r in run_dirs]
    tests: Dict[str, Dict[str, Any]] = {}
    run_summaries: List[Dict[str, Any]] = []
    for run in runs:
        bins = _exact_bins(run)
        tasks = _report_tasks(run)
        if not tasks:
            continue
        seen_tests: Set[str] = set()
        for task in tasks:
            name = _base_test(task.get("name") or task.get("work_dir") or "")
            if not name:
                continue
            status = str(task.get("status") or "unknown").lower()
            elapsed = float(task.get("elapsed") or 0.0)
            seed = _seed_of(task.get("name") or "", task.get("work_dir") or "")
            entry = tests.setdefault(name, {
                "test": name, "runs": 0, "pass": 0, "fail": 0, "unknown": 0,
                "elapsed": [], "seeds": set(), "by_seed": {},
                "bins_exact": set(), "last_status": "",
            })
            if name not in seen_tests:
                entry["runs"] += 1
                seen_tests.add(name)
            entry[status] = entry.get(status, 0) + 1
            entry["elapsed"].append(elapsed)
            entry["last_status"] = status
            entry["bins_exact"].update(bins.get(name, set()))
            key = "none" if seed is None else str(seed)
            entry["seeds"].add(key)
            seed_entry = entry["by_seed"].setdefault(
                key, {"runs": 0, "pass": 0, "fail": 0, "unknown": 0, "elapsed": []})
            seed_entry["runs"] += 1
            seed_entry[status] = seed_entry.get(status, 0) + 1
            seed_entry["elapsed"].append(elapsed)
        run_summaries.append({"run": run.name, "tasks": len(tasks),
                              "exact_tests": len(bins)})

    out_tests: Dict[str, Any] = {}
    total_elapsed = 0.0
    for name, e in sorted(tests.items()):
        elapsed = e.pop("elapsed")
        e["avg_elapsed"] = round(sum(elapsed) / len(elapsed), 2) if elapsed else 0.0
        e["max_elapsed"] = round(max(elapsed), 2) if elapsed else 0.0
        e["seeds"] = sorted(e["seeds"])
        for s in e["by_seed"].values():
            vals = s.pop("elapsed")
            s["avg_elapsed"] = round(sum(vals) / len(vals), 2) if vals else 0.0
        e["bins_exact"] = sorted(e["bins_exact"])
        total_elapsed += e["avg_elapsed"]
        out_tests[name] = e
    return {
        "schema": SCHEMA,
        "runs": run_summaries,
        "tests": out_tests,
        "summary": {"tests": len(out_tests), "avg_total_seconds": round(total_elapsed, 2)},
    }
