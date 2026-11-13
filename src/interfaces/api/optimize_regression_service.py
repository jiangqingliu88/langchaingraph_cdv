"""回归效率优化 —— 应用服务 facade（CLI 与 Workbench 共用）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def read_report(run_dir: Path) -> Dict[str, Any]:
    for path in sorted(Path(run_dir).glob("regression_run/**/report.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            return doc
    return {}


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8", newline="\n")


def latest_with_regression(runs: List[Path]) -> Optional[Path]:
    for run in reversed(runs):
        if (run / "inputs" / "yaml" / "uvm" / "regression.yaml").is_file():
            return run
        if (run / "inputs" / "yaml" / "regression.yaml").is_file():
            return run
    return None


def test_filter(selected: List[str], seed_plan: Dict[str, Any]) -> Optional[str]:
    """按选中用例（和 seed 裁剪）拼回归框架的 test 正则。"""
    if not selected:
        return None
    parts = []
    for name in selected:
        plan = (seed_plan or {}).get(name) or {}
        seeds = [str(s) for s in (plan.get("keep") or [])]
        escaped = re.escape(name)
        if plan.get("mode") == "reduced" and seeds:
            parts.append(f"^{escaped}(?:_run_\\d+)?_seed_"
                         f"(?:{'|'.join(re.escape(s) for s in seeds)})$")
        else:
            parts.append(f"^{escaped}(?:_run_\\d+)?(?:_seed_\\d+)?$")
    return ",".join(parts)


def execute_plan(run_dir: Path, plan: Dict[str, Any]) -> Dict[str, Any]:
    """在指定 run 上跑一次优化后的回归；返回前后对比。"""
    from src.core.optimize.result import compare_reports
    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager

    run_dir = Path(run_dir)
    before = read_report(run_dir)
    _write_json(run_dir / "optimize" / "baseline_regression.json", before)
    selected = plan.get("selected_tests") or []
    tests = test_filter(selected, plan.get("seed_plan") or {})
    InfrastructureManager(run_dir).run_regression(mode="local", tests=tests)
    after = read_report(run_dir)
    result = compare_reports(before, after)
    result["selected_tests"] = selected
    result["skipped_tests"] = plan.get("skipped_tests") or []
    result["seed_plan"] = plan.get("seed_plan") or {}
    result["reduced_seed_tests"] = plan.get("reduced_seed_tests") or []
    _write_json(run_dir / "optimize" / "result.json", result)
    return result


def analyze_plan(*, project: str | Path = ".", history: str | Path | None = None,
                 policy_path: str | Path | None = None,
                 output: str | Path | None = None, execute: bool = False,
                 reduce_seeds: bool = False) -> Dict[str, Any]:
    from src.core.optimize.history import collect_history, find_run_dirs
    from src.core.optimize.plan import build_plan, write_plan

    runs = find_run_dirs(Path(project), Path(history) if history else None)
    if not runs:
        raise FileNotFoundError(f"没有找到历史 run（{project} / {history}）")
    report = collect_history(runs)
    policy_doc: Dict[str, Any] = {}
    if policy_path:
        try:
            import yaml
            policy_doc = yaml.safe_load(Path(policy_path).read_text(encoding="utf-8")) or {}
        except Exception:                       # noqa: BLE001
            policy_doc = {"path": str(policy_path)}
    plan = build_plan(report,
                      policy={"path": str(policy_path)} if policy_path else policy_doc,
                      reduce_seeds=reduce_seeds)
    target_run = Path(output) if output else runs[-1]
    write_plan(target_run, plan)
    result = None
    if execute:
        exec_run = latest_with_regression(runs) or target_run
        result = execute_plan(exec_run, plan)
        plan["execute_result"] = result
        write_plan(target_run, plan)
    return {"history": report, "plan": plan, "result": result,
            "runs": [str(r) for r in runs]}
