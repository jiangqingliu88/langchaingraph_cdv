"""四个工程指标（`engineering_metrics_v1`）。

1. 回归总耗时（秒）与相对基线的下降比例；
2. 增量回归相对全量回归的预计节省（来自 `incremental/plan.json`）；
3. Coverage Bin → Test/Seed 的归因完整率（来自 `coverage/attribution.json`）；
4. Agent 决策有效率（EFFECTIVE / 有确定性结论的评估数）。

全部只读 run 目录；缺数据就写 null / `available:false`，**不拿 0 冒充**
—— "没测到"和"省了 0 秒"是两件事。
"""
from __future__ import annotations
from src.core.contracts import versions

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.decision.eval import (
    EFFECTIVE, INEFFECTIVE, REGRESSED, UNCERTAIN, read_records, summarize,
)
from src.core.provenance.report import build_attribution_report

SCHEMA = versions.ENGINEERING_METRICS

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
    confidence = str(doc.get("confidence", ""))
    return {
        "available": True,
        "baseline_run": doc.get("baseline_run", ""),
        "selected_tests": len(doc.get("selected_tests") or []),
        "all_tests": int(doc.get("all_tests") or 0),
        "estimated_full_seconds": doc.get("estimated_full_seconds"),
        "estimated_selected_seconds": doc.get("estimated_selected_seconds"),
        "estimated_savings_seconds": doc.get("estimated_savings_seconds"),
        "estimated_savings_pct": doc.get("estimated_savings_pct"),
        "confidence": confidence,
        # **对冲指标**：没有依赖映射时保守跑全量（节省为 0）。单看"savings"
        # 会系统性偏乐观 —— 这个布尔让趋势视图能数"有多大比例在保守全量"。
        "conservative": confidence == "conservative_all",
        "estimated": bool(doc.get("estimated", True)),
    }


def _worklist(root: Path) -> Dict[str, Any]:
    """义务 worklist vs 全量回归的耗时对照（**逐 task 实测耗时回放**）。

    口径：从 `regression_run/**/report.json` 的 `tasks[].elapsed` 取每条
    test 的实测耗时；worklist 选中哪些 test 由 `status/worklist.json` 决定，
    build 任务**照跑**（编译不能跳过）。把选中的 test 耗时 + 全部 build 耗时
    相加，就是"按义务驱动只跑这些"的实测对照 —— 不是拍脑袋的估算。

    缺 worklist / 缺 report / 匹配不到 test 都写 `available:false` 并给原因，
    **不拿 0 冒充"没省时间"**。
    """
    doc = _read_json(root / "status" / "worklist.json")
    if not doc.get("available"):
        return {"available": False,
                "reason": "没有可用的 status/worklist.json"}
    selected = {str(item.get("test") or "")
                for item in (doc.get("items") or [])
                if isinstance(item, dict) and item.get("test")}
    if not selected:
        return {"available": False, "reason": "worklist 没有选中任何 test"}
    reports = sorted(root.glob("regression_run/**/report.json"))
    if not reports:
        return {"available": False, "reason": "没有 regression_run/**/report.json"}
    def _selected_name(name: str) -> str:
        """回归任务名带 `_seed_<n>` / `_run_<n>` 后缀，worklist 用 base 名。"""
        if name in selected:
            return name
        for test in selected:
            if (name.startswith(test + "_seed_")
                    or name.startswith(test + "_run_")):
                return test
        return ""

    def _is_test_task(task: Dict[str, Any]) -> bool:
        """`work_dir` 里带 `test_` 子目录 = 一条用例；否则是 build 任务。"""
        work_dir = str(task.get("work_dir") or "")
        return "/test_" in work_dir or "\\test_" in work_dir

    worklist_s = full_s = 0.0
    matched_tests: set = set()
    slowest: Dict[str, Any] = {}
    for path in reports:
        rep = _read_json(path)
        for task in rep.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            secs = _num(task.get("elapsed")) or 0.0
            full_s += secs
            if not _is_test_task(task):
                worklist_s += secs    # 编译 / 环境准备：worklist 也必须跑
                continue
            if secs > float(slowest.get("seconds") or 0):
                slowest = {"name": str(task.get("name") or ""),
                           "seconds": round(secs, 2)}
            base = _selected_name(str(task.get("name") or ""))
            if base:
                matched_tests.add(base)
                worklist_s += secs    # 选中的 test：计入 worklist 时间
            elif "loopback" in str(task.get("work_dir") or "").lower():
                worklist_s += secs    # loopback 是环境自检，永远不被过滤
            # 其它未选中的 test：**不计入** worklist 时间
    if not matched_tests:
        return {"available": False,
                "reason": "worklist 选中的 test 在回归报告里匹配不到"}
    selected_s = worklist_s
    return {
        "available": True,
        "open_obligations": int(doc.get("open") or 0),
        "obligations": int(doc.get("obligations") or 0),
        "selected_tests": len(selected),
        "matched_tests": len(matched_tests),
        "full_seconds": round(full_s, 2),
        "worklist_seconds": round(selected_s, 2),
        "savings_seconds": round(full_s - selected_s, 2),
        "savings_pct": (round((full_s - selected_s) / full_s * 100, 2)
                        if full_s > 0 else None),
        # 单条病态慢用例（本机实测有 11146s 的）会把原始节省率拉得很难看；
        # 给一个"去掉最慢一条"的对照，读者自己能判断该信哪个。
        "slowest_test": slowest,
        "full_seconds_excluding_slowest": (round(full_s - float(
            slowest.get("seconds") or 0), 2)),
        "savings_pct_excluding_slowest": (
            round((full_s - float(slowest.get("seconds") or 0) - selected_s)
                  / (full_s - float(slowest.get("seconds") or 0)) * 100, 2)
            if full_s > float(slowest.get("seconds") or 0) else None),
        # 数据来源写明：这是同一轮 run 里逐 test 的**实测**耗时，不是估算
        "method": "per-task elapsed replay",
        "basis": "measured",
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


#: 规则 → 红灯类别。**归因是分类，不是判定**；认不出的规则进 unattributed。
_RULE_CATEGORY = {
    "case_without_binding": "contract_gap",
    "unknown_dimension": "contract_gap",
    "checker_without_tp": "contract_gap",
    "CASE_GROUPS_EMPTY": "contract_gap",
    "CASE_SVA_UNDECLARED": "contract_gap",
    "CASE_SCB_UNDECLARED": "contract_gap",
    "CASE_ITEM_NO_CELL": "contract_gap",
    "waiver_incomplete": "governance",
    "waiver_expired": "governance",
    "waiver_invalid_date": "governance",
    "cell_red": "stimulus_gap",
    "cell_yellow": "stimulus_gap",
    "cell_without_checker": "checker_gap",
    "CASE_SVA_VACUOUS": "checker_gap",
    "CASE_SCB_NOT_EXECUTED": "checker_gap",
    "case_without_evd": "signoff_gap",
    "evd_legacy": "evidence_gap",
    "duplicate_id": "model_drift",
    "case_synthesized": "model_drift",
    "unknown_test": "model_drift",
    "CASE_IR_EVIDENCE_MISMATCH": "model_drift",
    "CASE_STATUS_OVERCLAIM": "model_drift",
    "AUTHORITY_DIFF": "infra_error",
    "COVERAGE_REGRESSION": "regression",
    "QUALITY_GATE_BLOCKED": "quality",
    "QUALITY_GATE_WARN": "quality",
}


def _red_rules(root: Path) -> List[Dict[str, Any]]:
    """gate blocker + closure error → 统一的红灯条目。"""
    gates = _read_json(root / "coverage" / "gates.json")
    closure = _read_json(root / "coverage" / "case_closure.json")
    rules: List[Dict[str, Any]] = []
    for source in (gates.get("blockers"), closure.get("errors")):
        for item in source or []:
            if isinstance(item, dict):
                rules.append({"rule": str(item.get("rule") or ""),
                              "target": item.get("target", ""),
                              "message": item.get("message", "")})
    return rules


def _classify_rules(rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_category: Dict[str, int] = {}
    unattributed: Dict[str, int] = {}
    for item in rules:
        rule = item["rule"]
        category = _RULE_CATEGORY.get(rule)
        if category:
            by_category[category] = by_category.get(category, 0) + 1
        else:
            key = rule or "<unknown>"
            unattributed[key] = unattributed.get(key, 0) + 1
    total = len(rules)
    attributed = total - sum(unattributed.values())
    return {
        "blockers": total,
        "by_category": dict(sorted(by_category.items())),
        "unattributed": dict(sorted(unattributed.items())),
        "attribution_completeness": (round(attributed / total, 4)
                                     if total else None),
    }


def _triage(root: Path) -> Dict[str, Any]:
    """人工裁决（`docs/triage.json`）→ 误报率；没有就标未知，不编 0。"""
    triage = _read_json(root / "docs" / "triage.json")
    records = [r for r in (triage.get("records") or [])
               if isinstance(r, dict) and r.get("verdict")]
    fp = sum(1 for r in records if r.get("verdict") == "false_positive")
    triaged = len(records)
    return {
        "available": bool(triaged),
        "triaged": triaged,
        "false_positive": fp,
        "rate": round(fp / triaged, 4) if triaged else None,
        "note": ("无 docs/triage.json —— 误报率未知，不按 0 计"
                 if not triaged else ""),
    }


def _red_lights(root: Path) -> Dict[str, Any]:
    """红灯分类 + 归因完整率 + 误报率（有 triage 才有，不编 0）。

    · **分类**：gate blocker / closure error 的规则 → 类别（`contract_gap` /
      `stimulus_gap` / `model_drift` / `infra_error` …）。
    · **归因完整率**：能归到类别的红灯 / 全部红灯。归因不完整时，
      自动补齐动作就无从谈起。
    · **误报率**：只在 `docs/triage.json` 有记录时计算 —— 没有人工裁决就不能
      声称"误报率 0"。
    """
    classified = _classify_rules(_red_rules(root))
    holes = _read_json(root / "coverage" / "coverage_holes.json")
    hole_actions: Dict[str, int] = {}
    for hole in holes.get("holes") or []:
        if isinstance(hole, dict) and hole.get("action"):
            action = str(hole["action"])
            hole_actions[action] = hole_actions.get(action, 0) + 1
    return {
        **classified,
        "coverage_holes": dict(sorted(hole_actions.items())),
        "false_positive": _triage(root),
    }


def _collect(run_root: str | Path) -> Dict[str, Any]:
    root = Path(run_root)
    return {
        "schema": SCHEMA,
        "run_id": root.name,
        "regression": _regression(root),
        "run_wall_seconds": _run_wall_seconds(root),
        "incremental": _incremental(root),
        "worklist": _worklist(root),
        "attribution": _attribution(root),
        "decision": _decision(root),
        "red_lights": _red_lights(root),
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
    red = out.get("red_lights") or {}
    completeness = red.get("attribution_completeness")
    if red.get("blockers") and completeness is not None and completeness < 1:
        notes.append(f"红灯归因不完整：{red['blockers']} 条 blocker 中"
                     f"只有 {round(completeness * 100, 1)}% 能归到类别 —— "
                     f"未归类：{', '.join(sorted(red.get('unattributed') or {})) or '—'}")
    if not (red.get("false_positive") or {}).get("available"):
        notes.append("没有 docs/triage.json —— 误报率未知，不按 0 计")
    return [n for n in notes if n]


def trend(run_root: str | Path, last: int = 10) -> Dict[str, Any]:
    """连续 N 个 run 的工程指标趋势（读各 run 已落盘的 `engineering_metrics.json`）。

    单 run 快照回答不了"效率到底有没有提升"；两 run diff 又太短。这里按
    同目录下 run 的落盘时间取最近 N 个，顺手给出**保守全量比例** —— 没有它，
    "预计节省"会系统性偏乐观（算不出依赖时就保守全量，节省为 0）。
    """
    root = Path(run_root).resolve()
    candidates: List[Tuple[float, Path]] = []
    parent = root.parent if root.parent != root else root
    try:
        for path in parent.iterdir():
            if not path.is_dir():
                continue
            metrics_file = path / "docs" / "engineering_metrics.json"
            if metrics_file.is_file():
                candidates.append((metrics_file.stat().st_mtime, path))
    except OSError:
        pass
    if not any(path == root for _ts, path in candidates):
        metrics_file = root / "docs" / "engineering_metrics.json"
        if metrics_file.is_file():
            candidates.append((metrics_file.stat().st_mtime, root))
    candidates.sort(key=lambda item: (item[0], item[1].name))
    selected = candidates[-max(1, int(last or 1)):]
    rows: List[Dict[str, Any]] = []
    for _ts, path in selected:
        doc = _read_json(path / "docs" / "engineering_metrics.json")
        inc = doc.get("incremental") or {}
        conservative = inc.get("conservative")
        if conservative is None:
            conservative = str(inc.get("confidence") or "") == "conservative_all"
        rows.append({
            "run": path.name,
            "regression_seconds": (doc.get("regression") or {}).get("total_seconds"),
            "attribution_rate": (doc.get("attribution") or {}).get("attribution_rate"),
            "decision_rate": (doc.get("decision") or {}).get("effectiveness_rate"),
            "incremental_available": bool(inc.get("available")),
            "incremental_confidence": inc.get("confidence", ""),
            "conservative": bool(conservative),
        })
    with_inc = [r for r in rows if r["incremental_available"]]
    conservative = [r for r in with_inc if r["conservative"]]
    return {
        "schema": "engineering_trend_v1",
        "runs": rows,
        "counts": {"runs": len(rows), "with_incremental": len(with_inc),
                   "conservative": len(conservative)},
        "conservative_rate": (round(len(conservative) / len(with_inc), 4)
                              if with_inc else None),
    }


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
