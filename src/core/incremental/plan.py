"""增量验证计划（`incremental/plan.json`）。

链路：RTL diff → 依赖分析 → 受影响用例 → 预计节省。

**不自动替用户决定"可以不跑"**：没有依赖映射时 selected=全部、confidence=
`conservative_all`、节省为 0。只有存在 `coverage/test_dependencies.json`（或
regression.yaml 的 `file_pattern`）时才真正缩小范围。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.core.incremental.dependencies import (
    affected_tests, all_tests, load_dependency_map,
)
from src.core.incremental.deps_gen import (
    generate_dependency_map, write_dependency_map,
)
from src.core.incremental.rtl_diff import diff_runs, snapshot

SCHEMA = "incremental_plan_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _base_name(name: str) -> str:
    name = str(name or "")
    if name.startswith("test_"):
        name = name[5:]
    parts = name.split("_seed_")
    return parts[0] if parts else name


def _test_elapsed(run_root: Path) -> Dict[str, float]:
    """从基线回归报告取每条 test 的实际耗时（同名取最大）。"""
    out: Dict[str, float] = {}
    for path in sorted(run_root.glob("regression_run/**/report.json")):
        doc = _read_json(path)
        for task in doc.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            name = _base_name(task.get("name") or "")
            try:
                elapsed = float(task.get("elapsed") or 0.0)
            except (TypeError, ValueError):
                continue
            if name:
                out[name] = max(out.get(name, 0.0), elapsed)
    return out


def _estimate(tests: List[str], selected: List[str],
              elapsed: Dict[str, float]) -> Dict[str, Any]:
    if not elapsed or not tests:
        return {"estimated": False, "estimated_full_seconds": None,
                "estimated_selected_seconds": None,
                "estimated_savings_seconds": None, "estimated_savings_pct": None}
    avg = sum(elapsed.values()) / len(elapsed)
    full = sum(elapsed.get(t, avg) for t in tests)
    chosen = sum(elapsed.get(t, avg) for t in selected)
    saved = max(0.0, full - chosen)
    return {
        "estimated": True,
        "estimated_full_seconds": round(full, 2),
        "estimated_selected_seconds": round(chosen, 2),
        "estimated_savings_seconds": round(saved, 2),
        "estimated_savings_pct": round(saved / full * 100.0, 2) if full > 0 else 0.0,
    }


def _load_dependencies(current: Path,
                       dependency_map: Optional[Dict[str, set]] = None
                       ) -> Tuple[Dict[str, Set[str]], str, Dict[str, Any],
                                  Dict[str, Any]]:
    dep = dependency_map if dependency_map is not None else load_dependency_map(current)
    source = "sidecar"
    auto_doc: Dict[str, Any] = {}
    sidecar_doc: Dict[str, Any] = {}
    if dependency_map is None:
        sidecar_doc = _read_json(current / "coverage" / "test_dependencies.json")
    if not dep:
        # 没有 sidecar：自动生成（file_pattern → env/testpoint/RTL 启发式）。
        auto_doc = generate_dependency_map(current)
        dep = {str(name): set((value or {}).get("files") or [])
               for name, value in (auto_doc.get("tests") or {}).items()
               if (value or {}).get("files")}
        source = str(auto_doc.get("source") or "none")
    return dep, source, auto_doc, sidecar_doc


def build_plan(baseline_run: str | Path, current_run: str | Path, *,
               dependency_map: Optional[Dict[str, set]] = None,
               tests: Optional[List[str]] = None) -> Dict[str, Any]:
    base = Path(baseline_run)
    cur = Path(current_run)
    diff = diff_runs(base, cur)
    dep, source, auto_doc, sidecar_doc = _load_dependencies(cur, dependency_map)
    all_names = tests if tests is not None else (all_tests(cur) or sorted(dep))
    affected = affected_tests(diff["changed"], dep, all_names)
    elapsed = _test_elapsed(base)
    estimate = _estimate(all_names, affected["selected"], elapsed)
    notes: List[str] = []
    if dep == {}:
        notes.append("没有依赖映射（sidecar / file_pattern / 自动生成均不可用），"
                     "只能保守跑全量")
    if auto_doc:
        notes.extend(str(n) for n in (auto_doc.get("notes") or []))
        if auto_doc.get("unmapped_tests"):
            notes.append(f"{len(auto_doc['unmapped_tests'])} 条用例依赖未识别，"
                         "按 undeclared 保守全跑")
    if diff["changed"]:
        notes.append(f"RTL 变更 {len(diff['changed'])} 个文件")
    else:
        notes.append("RTL 无变更")
    return {
        "schema": SCHEMA,
        "baseline_run": base.name,
        "current_run": cur.name,
        "baseline_rtl_files": len(snapshot(base)),
        "current_rtl_files": len(snapshot(cur)),
        "changed": diff,
        "dependency_source": source,
        "dependency_map": {"source": source, "tests": len(dep),
                           "unmapped": len((auto_doc or sidecar_doc)
                                           .get("unmapped_tests") or [])},
        "all_tests": len(all_names),
        "selected_tests": affected["selected"],
        "excluded_tests": affected["excluded"],
        "undeclared_tests": affected["undeclared"],
        "confidence": affected["confidence"],
        "reason": affected["reason"],
        **estimate,
        "notes": notes,
        "_auto_dependency_doc": auto_doc if (auto_doc and dep) else {},
    }


def write_plan(baseline_run: str | Path, current_run: str | Path,
               **kwargs) -> Dict[str, Any]:
    plan = build_plan(baseline_run, current_run, **kwargs)
    auto_doc = plan.pop("_auto_dependency_doc", {}) or {}
    if auto_doc.get("tests"):
        # 物化 sidecar：下一次增量计划直接复用，也能被证据包收走。
        auto_doc["path"] = write_dependency_map(current_run, auto_doc)
    path = Path(current_run) / "incremental" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    plan["path"] = str(path)
    return plan
