"""CLI 工程服务工作流 —— 三类场景共用一个入口与同一条执行链路。

    vagent optimize-regression   # 回归效率优化
    vagent coverage-closure      # 覆盖率收敛

它们**不新建引擎**：历史分析读 run 目录，执行复用 `InfrastructureManager`
（回归）与 `PipelineExecutionService`（闭环），结果写 run 的 `optimize/` /
`closure/` 目录，并进证据链。
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import click
from rich.table import Table  # noqa: F401

from src.cli.commands import cli, console
from src.cli.output import get_output_adapter


def _read_report(run_dir: Path):
    for path in sorted(run_dir.glob("regression_run/**/report.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            return doc
    return {}


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8", newline="\n")


def _latest_with_regression(runs):
    for run in reversed(runs):
        if (run / "inputs" / "yaml" / "uvm" / "regression.yaml").is_file():
            return run
        if (run / "inputs" / "yaml" / "regression.yaml").is_file():
            return run
    return None


def _execute_optimized(run_dir: Path, plan: dict) -> dict:
    """在指定 run 上跑一次优化后的回归；返回前后对比。"""
    from src.core.optimize.result import compare_reports
    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager

    before = _read_report(run_dir)
    _write_json(run_dir / "optimize" / "baseline_regression.json", before)
    selected = plan.get("selected_tests") or []
    tests = None
    if selected:
        tests = "^(?:" + "|".join(re.escape(t) for t in selected) + ")$"
    InfrastructureManager(run_dir).run_regression(mode="local", tests=tests)
    after = _read_report(run_dir)
    result = compare_reports(before, after)
    result["selected_tests"] = selected
    result["skipped_tests"] = plan.get("skipped_tests") or []
    _write_json(run_dir / "optimize" / "result.json", result)
    return result


@cli.command("optimize-regression")
@click.option("--project", type=click.Path(file_okay=False, path_type=Path),
              default=Path("."), show_default=True, help="项目根（扫描 output_*）")
@click.option("--history", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="历史 run 目录（缺省用 project 下的 output_*）")
@click.option("--policy", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="签核策略 YAML（只记录进计划，不改变判定）")
@click.option("--output", "-o", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="计划落点（缺省用最新 run 目录）")
@click.option("--execute", is_flag=True,
              help="在最新 run 上执行优化后的回归（会重跑该 run 的 regression_run）")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def optimize_regression(project, history, policy, output, execute, json_output):
    """回归效率优化：历史 → 顺序/低边际用例 → 计划 →（可选）执行与对比。"""
    from src.core.optimize.history import collect_history, find_run_dirs
    from src.core.optimize.plan import build_plan, write_plan

    runs = find_run_dirs(project, history)
    if not runs:
        raise click.ClickException(f"没有找到历史 run（{project} / {history}）")
    report = collect_history(runs)
    policy_doc = {}
    if policy:
        try:
            import yaml
            policy_doc = yaml.safe_load(policy.read_text(encoding="utf-8")) or {}
        except Exception:
            policy_doc = {"path": str(policy)}
    plan = build_plan(report, policy={"path": str(policy)} if policy else policy_doc)
    target_run = output or runs[-1]
    write_plan(target_run, plan)
    result = None
    if execute:
        exec_run = _latest_with_regression(runs) or target_run
        result = _execute_optimized(exec_run, plan)
        plan["execute_result"] = result
        write_plan(target_run, plan)

    if json_output:
        click.echo(json.dumps({"history": report, "plan": plan, "result": result},
                              indent=2, ensure_ascii=False, default=str))
        return
    table = Table(title="Regression Optimization")
    table.add_column("项", style="cyan")
    table.add_column("值")
    table.add_row("历史 run", str(len(runs)))
    table.add_row("用例", str(plan["tests"]))
    table.add_row("flaky / failing", f"{len(plan['flaky'])} / {len(plan['failing'])}")
    table.add_row("低边际跳过", f"{len(plan['skipped_tests'])} 条")
    table.add_row("预计节省", f"{plan['estimated_savings_seconds']}s "
                              f"({plan['estimated_savings_pct']}%)")
    table.add_row("置信度", plan["confidence"])
    table.add_row("计划", plan.get("path", ""))
    console.print(table)
    if result:
        console.print(f"[green]执行结果：[/green]节省 {result['elapsed_seconds']['saved']}s，"
                      f"状态变化 {len(result['status_changes'])} 条")
    for note in plan.get("notes") or []:
        console.print(f"[dim]· {note}[/dim]")


def _run_dir_from_coverage(path: Path) -> Path:
    return path.parent if path.name == "coverage" else path


def _find_spec(project: Path, module: str) -> Path | None:
    for pattern in (f"specs/{module}/*.md", "specs/*/*.md"):
        for p in sorted(project.glob(pattern)):
            if p.is_file():
                return p
    return None


@cli.command("coverage-closure")
@click.option("--project", type=click.Path(file_okay=False, path_type=Path),
              default=Path("."), show_default=True, help="项目根（找 spec/rtl）")
@click.option("--coverage", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="已有覆盖率的 run 目录，或它的 coverage/ 子目录")
@click.option("--target", type=float, default=98.0, show_default=True,
              help="目标覆盖率（百分点）")
@click.option("--spec", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="执行时用的 spec（缺省从 project/specs 找）")
@click.option("--rtl", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="执行时用的 RTL（缺省用 run/rtl）")
@click.option("--config", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="执行时用的 casemodel.yaml")
@click.option("--output", "-o", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="执行时的输出目录（缺省新建 output_closure_*）")
@click.option("--execute", is_flag=True,
              help="用现有闭环执行收敛（会真实跑 UVM/回归，耗时较长）")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def coverage_closure(project, coverage, target, spec, rtl, config, output, execute,
                     json_output):
    """Coverage Closure：缺口 → 定向动作计划 →（可选）用现有闭环执行。"""
    from src.core.closure.plan import write_closure_plan

    run_dir = _run_dir_from_coverage(coverage)
    plan = write_closure_plan(run_dir, target)
    result = None
    if execute:
        if not plan["actions"] and plan["current_coverage"] >= target:
            console.print("[green]已达标，无需执行收敛[/green]")
        else:
            result = _execute_closure(project, run_dir, target, spec, rtl, config, output)
            _write_json(run_dir / "closure" / "result.json", result)
            plan["execute_result"] = result
            _write_json(Path(plan["path"]), plan)

    if json_output:
        click.echo(json.dumps({"plan": plan, "result": result}, indent=2,
                              ensure_ascii=False, default=str))
        return
    table = Table(title=f"Coverage Closure — {plan['run_id']}")
    table.add_column("项", style="cyan")
    table.add_column("值")
    table.add_row("当前 / 目标", f"{plan['current_coverage']}% / {plan['target']}%")
    table.add_row("缺口", f"{plan['gap_count']} 个 TP / {plan['gap_to_target']} 点")
    table.add_row("动作", ", ".join(sorted({a["action"] for a in plan["actions"]})) or "-")
    table.add_row("计划", plan.get("path", ""))
    console.print(table)
    if result:
        console.print(f"[green]收敛执行完成：[/green]{result.get('after', {}).get('functional_pct')}% "
                      f"（run={result.get('run_id', '')}）")
    for note in plan.get("notes") or []:
        console.print(f"[dim]· {note}[/dim]")


def _execute_closure(project, run_dir, target, spec, rtl, config, output):
    """复用现有闭环：`--rtl` 当 DUT，spec 当分析输入；不另造收敛引擎。"""
    from src.layers.l1_infrastructure.layout import casemodel_path
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.layers.l2_orchestration.execution import PipelineExecutionService
    from src.layers.l2_orchestration.governance.approval import create_approval_gate

    rtl_dir = rtl or (run_dir / "rtl" if (run_dir / "rtl").is_dir() else None)
    spec_path = spec
    if spec_path is None:
        try:
            spec_doc = json.loads((run_dir / "spec.json").read_text(encoding="utf-8"))
            module = str(spec_doc.get("design_name") or spec_doc.get("module") or "")
        except (OSError, ValueError):
            module = ""
        spec_path = _find_spec(project, module)
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path else ""
    out_root = make_output_root(str(output) if output else f"output_closure_{run_dir.name}")
    if config:
        dest = casemodel_path(out_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(Path(config).read_text(encoding="utf-8"), encoding="utf-8")

    async def _run():
        service = PipelineExecutionService.get_instance()
        return await service.run_closed_loop_streaming(
            spec_text=spec_text, output_root=out_root, target=target,
            design_style="baseline", approval_gate=create_approval_gate("auto"),
            rtl_dir=str(rtl_dir or ""), checkpointing=False)

    asyncio.run(_run())
    from src.core.incremental.run_diff import write_run_diff
    diff = write_run_diff(run_dir, Path(make_output_root(out_root)))
    return {"run_id": Path(make_output_root(out_root)).name,
            "after": diff.get("current", {}).get("coverage", {}),
            "before": diff.get("baseline", {}).get("coverage", {}),
            "deltas": diff.get("deltas", {}), "run_diff": diff.get("path", "")}
