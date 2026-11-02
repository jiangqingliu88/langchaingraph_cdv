"""回归优化计划（`regression_optimize_v1`）。

优化**不是**删测试。这里只做两类决定：

1. 执行顺序：flaky / failing 先跑（尽早暴露问题）；慢用例靠后。
2. 低边际用例：只有**精确 per-test 归因**证明它的 bin 已被其他用例完全覆盖，
   且历史上从未失败，才建议在优化回归里跳过；否则一律不跳过。

没有精确归因 → `confidence=analysis_only`、`skipped_tests=[]`、节省 0。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

SCHEMA = "regression_optimize_v1"


def _always_pass(e: Dict[str, Any]) -> bool:
    return int(e.get("pass") or 0) > 0 and int(e.get("fail") or 0) == 0


def _low_marginal(tests: Dict[str, Dict[str, Any]]) -> List[str]:
    """bin 已被其他"精确归因"用例完全覆盖、且从未失败的用例。"""
    with_bins = {name: set(e.get("bins_exact") or [])
                 for name, e in tests.items() if e.get("bins_exact")}
    if not with_bins:
        return []
    out: List[str] = []
    for name, bins in with_bins.items():
        if not bins or not _always_pass(tests[name]):
            continue
        others: Set[str] = set()
        for other, other_bins in with_bins.items():
            if other != name:
                others.update(other_bins)
        if bins.issubset(others):
            out.append(name)
    return sorted(out)


def _classify(tests: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    flaky = sorted(n for n, e in tests.items()
                   if int(e.get("pass") or 0) > 0 and int(e.get("fail") or 0) > 0)
    failing = sorted(n for n, e in tests.items()
                     if int(e.get("fail") or 0) > 0 and int(e.get("pass") or 0) == 0)
    unknown = sorted(n for n, e in tests.items() if int(e.get("unknown") or 0) > 0)
    slow = [n for n, _ in sorted(tests.items(),
                                 key=lambda kv: kv[1].get("avg_elapsed") or 0,
                                 reverse=True)[:5]]
    return {"flaky": flaky, "failing": failing, "unknown": unknown, "slow": slow}


def _order(groups: List[str], all_names: List[str]) -> List[str]:
    ordered: List[str] = []
    for name in groups + all_names:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _seed_key(seed: str):
    try:
        return (0, int(seed))
    except (TypeError, ValueError):
        return (1, str(seed))


def _seed_sides(by_seed: Dict[str, Dict[str, Any]]):
    def _bad(value: Dict[str, Any]) -> bool:
        return bool(int(value.get("fail") or 0)
                    or int(value.get("unknown") or 0))

    bad = sorted([s for s, v in by_seed.items() if _bad(v)], key=_seed_key)
    good = sorted([s for s, v in by_seed.items() if not _bad(v)], key=_seed_key)
    return bad, good


def _seed_decision(entry: Dict[str, Any], by_seed: Dict[str, Dict[str, Any]],
                   bad: List[str], good: List[str], *,
                   reduce_seeds: bool, min_seed_runs: int):
    seeds = sorted(by_seed, key=_seed_key)
    keep = list(seeds)
    dropped: List[str] = []
    mode = "full"
    reason = "保留全部 seed"
    if reduce_seeds and not bad and int(entry.get("fail") or 0) == 0             and int(entry.get("unknown") or 0) == 0:
        stable = all(int((by_seed[s] or {}).get("pass") or 0) >= min_seed_runs
                     for s in seeds)
        if stable and len(seeds) > 1 and good:
            keep = [good[0]]
            dropped = [s for s in seeds if s not in keep]
            mode = "reduced"
            reason = (f"{len(seeds)} 个 seed 均 ≥{min_seed_runs} 次通过，"
                      f"只保留 seed={keep[0]}")
        elif not stable:
            reason = f"每个 seed 通过次数不足 {min_seed_runs}，不裁剪"
    elif bad:
        reason = f"{len(bad)} 个 seed 出现过 fail/unknown，保留全部"
    return mode, keep, dropped, reason


def _seed_plan(tests: Dict[str, Dict[str, Any]], *,
               reduce_seeds: bool = False,
               min_seed_runs: int = 3) -> Dict[str, Dict[str, Any]]:
    """每用例的 seed 计划。

    **默认只排序、不裁剪**：任何一个 seed 出现过 fail/unknown，或该用例整体
    不稳定，就保留全部 seed。只有显式 `reduce_seeds=True`、且每个 seed 都有
    `min_seed_runs` 次以上通过、无 fail/unknown 时，才只保留一个 seed。

    `priority` 是执行顺序建议（坏的 seed 在前）；当前执行器按目录顺序跑，
    这个字段先作为计划事实落盘。
    """
    out: Dict[str, Dict[str, Any]] = {}
    for name, entry in tests.items():
        by_seed = {s: v for s, v in (entry.get("by_seed") or {}).items()
                   if s != "none"}
        if not by_seed:
            continue
        bad, good = _seed_sides(by_seed)
        mode, keep, dropped, reason = _seed_decision(
            entry, by_seed, bad, good,
            reduce_seeds=reduce_seeds, min_seed_runs=min_seed_runs)
        out[name] = {"mode": mode,
                     "seeds": sorted(by_seed, key=_seed_key),
                     "keep": keep, "dropped": dropped,
                     "priority": bad + good, "reason": reason}
    return out


def build_plan(history: Dict[str, Any],
               policy: Optional[Dict[str, Any]] = None, *,
               reduce_seeds: bool = False,
               min_seed_runs: int = 3) -> Dict[str, Any]:
    tests = history.get("tests") or {}
    groups = _classify(tests)
    skipped = _low_marginal(tests)
    skip_set = set(skipped)
    selected = sorted(n for n in tests if n not in skip_set)
    ordered = _order(groups["flaky"] + groups["failing"] + groups["slow"],
                     sorted(tests))
    seeds = _seed_plan(tests, reduce_seeds=reduce_seeds,
                       min_seed_runs=min_seed_runs)
    reduced = sorted(n for n, s in seeds.items() if s.get("mode") == "reduced")
    savings = sum(float(tests[n].get("avg_elapsed") or 0.0) for n in skipped)
    total = float(history.get("summary", {}).get("avg_total_seconds") or 0.0)
    notes: List[str] = []
    if not skipped:
        notes.append("没有精确 per-test 归因证明低边际覆盖，不跳过任何用例")
    if groups["unknown"]:
        notes.append(f"{len(groups['unknown'])} 条用例历史上出现过 unknown"
                     "（编译/挂死），优先排查")
    if not reduce_seeds:
        notes.append("seed 默认全量；要按历史裁剪稳定 seed，显式加 --reduce-seeds")
    elif reduced:
        notes.append(f"{len(reduced)} 条用例按 seed 历史裁剪（只保留 1 个稳定 seed）")
    return {
        "schema": SCHEMA,
        "based_on_runs": [r.get("run") for r in history.get("runs") or []],
        "tests": len(tests),
        "flaky": groups["flaky"], "failing": groups["failing"],
        "unknown": groups["unknown"], "slow": groups["slow"],
        "ordered_tests": ordered,
        "selected_tests": selected,
        "skipped_tests": skipped,
        "seed_plan": seeds,
        "seed_reduction_enabled": bool(reduce_seeds),
        "reduced_seed_tests": reduced,
        "estimated_savings_seconds": round(savings, 2),
        "estimated_savings_pct": round(savings / total * 100.0, 2) if total else 0.0,
        "confidence": "exact" if skipped else "analysis_only",
        "policy": policy or {},
        "notes": notes,
    }


def write_plan(output_root: str | Path, plan: Dict[str, Any]) -> Dict[str, Any]:
    path = Path(output_root) / "optimize" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    plan["path"] = str(path)
    return plan
