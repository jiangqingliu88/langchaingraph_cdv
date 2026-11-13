"""SignOffAI CLI 命令组：工程指标 / 增量验证 / run diff。

这些命令**只读 run 目录**，不跑 EDA、不调 LLM：
    vagent metrics show -o <run> [--baseline <run>]
    vagent incremental plan --baseline <run> --current <run>
    vagent diff runs --baseline <run> --current <run>
"""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.table import Table  # noqa: F401

from src.interfaces.cli.commands import cli, console
from src.interfaces.cli.cmd_diff import diff


def _fmt_pct(value, digits=2):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_seconds(value):
    if value is None:
        return "-"
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return str(value)


@cli.group("metrics")
def metrics_group():
    """工程收益指标（回归耗时 / 增量节省 / 归因完整率 / 决策有效率）"""
    pass


@metrics_group.command("show")
@click.option("-o", "--output", type=click.Path(file_okay=False, path_type=Path),
              default=".", show_default=True, help="run 目录")
@click.option("--baseline", type=click.Path(exists=True, file_okay=False,
                                            path_type=Path), default=None,
              help="基线 run 目录（用于计算下降比例）")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def metrics_show(output, baseline, json_output):
    """显示四个工程指标。"""
    from src.core.metrics.engineering import collect

    report = collect(output, baseline=baseline)
    if json_output:
        click.echo(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return
    reg = report["regression"]
    att = report["attribution"]
    dec = report["decision"]
    inc = report["incremental"]
    wl = report.get("worklist") or {}
    table = Table(title=f"Engineering Metrics — {report['run_id']}")
    table.add_column("指标", style="cyan")
    table.add_column("值")
    table.add_column("说明", style="dim")
    table.add_row("回归总耗时", _fmt_seconds(reg.get("total_seconds")),
                  f"{reg.get('tasks') or 0} 个任务")
    base = report.get("baseline") or {}
    table.add_row("相对基线下降", _fmt_pct(base.get("regression_reduction_pct")),
                  f"基线 {_fmt_seconds(base.get('regression_total_seconds'))}")
    table.add_row("增量预计节省", _fmt_seconds(inc.get("estimated_savings_seconds"))
                  if inc.get("available") else "-",
                  (f"{inc.get('estimated_savings_pct')}% · "
                   f"{inc.get('selected_tests')}/{inc.get('all_tests')} 条"
                   if inc.get("available") else inc.get("reason", "")))
    table.add_row(
        "义务 worklist",
        _fmt_seconds(wl.get("worklist_seconds")) if wl.get("available") else "-",
        (f"{wl.get('selected_tests')} 条 test · 省 "
         f"{wl.get('savings_pct')}%（全量 {_fmt_seconds(wl.get('full_seconds'))}）"
         if wl.get("available") else wl.get("reason", "")))
    table.add_row("归因完整率", _fmt_pct((att.get("attribution_rate") or 0) * 100
                                        if att.get("attribution_rate") is not None else None),
                  f"hit bins {att.get('hit_bins')} · exact {_fmt_pct((att.get('exact_rate') or 0) * 100)}")
    table.add_row("决策有效率", _fmt_pct((dec.get("effectiveness_rate") or 0) * 100
                                        if dec.get("effectiveness_rate") is not None else None),
                  f"effective {dec.get('effective')} / "
                  f"evaluated {dec.get('evaluated')} · uncertain {dec.get('uncertain')}")
    console.print(table)
    for note in report.get("notes") or []:
        console.print(f"[dim]· {note}[/dim]")


@metrics_group.command("trend")
@click.option("-o", "--output", type=click.Path(file_okay=False, path_type=Path),
              default=".", show_default=True, help="run 目录（同目录下取最近 N 个）")
@click.option("--last", type=int, default=10, show_default=True,
              help="取最近多少个 run")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def metrics_trend(output, last, json_output):
    """连续 N 个 run 的工程指标趋势（含**保守全量比例**）。"""
    from src.core.metrics.engineering import trend

    report = trend(output, last=last)
    if json_output:
        click.echo(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return
    table = Table(title=f"Engineering Trend — 最近 {len(report['runs'])} 个 run")
    table.add_column("run", style="cyan")
    table.add_column("回归耗时")
    table.add_column("增量")
    table.add_column("归因完整率")
    table.add_column("决策有效率")
    for row in report["runs"]:
        inc = ("保守全量" if row["conservative"]
               else (row["incremental_confidence"] or "-"))
        if not row["incremental_available"]:
            inc = "-"
        table.add_row(
            row["run"], _fmt_seconds(row["regression_seconds"]), inc,
            _fmt_pct((row["attribution_rate"] or 0) * 100
                     if row["attribution_rate"] is not None else None),
            _fmt_pct((row["decision_rate"] or 0) * 100
                     if row["decision_rate"] is not None else None))
    console.print(table)
    counts = report["counts"]
    rate = report["conservative_rate"]
    console.print(f"[dim]有增量计划 {counts['with_incremental']}/{counts['runs']} 个 run · "
                  f"保守全量 {counts['conservative']} 个"
                  + (f"（{rate:.0%}）" if rate is not None else "") + "[/dim]")


@cli.group("incremental")
def incremental_group():
    """增量验证：RTL diff → 依赖分析 → 受影响用例 → 节省估算"""
    pass


@incremental_group.command("plan")
@click.option("--baseline", required=True, type=click.Path(exists=True, file_okay=False,
                                                           path_type=Path),
              help="基线 run 目录")
@click.option("--current", required=True, type=click.Path(exists=True, file_okay=False,
                                                          path_type=Path),
              help="当前 run 目录（计划写到它的 incremental/plan.json）")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def incremental_plan(baseline, current, json_output):
    """生成增量回归计划（不自动执行回归）。"""
    from src.core.incremental.plan import write_plan

    plan = write_plan(baseline, current)
    if json_output:
        click.echo(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
        return
    table = Table(title=f"Incremental Plan — {plan['current_run']}")
    table.add_column("项", style="cyan")
    table.add_column("值")
    table.add_row("RTL 变更", f"{len(plan['changed']['changed'])} 个文件")
    table.add_row("回归范围", f"{len(plan['selected_tests'])}/{plan['all_tests']} 条")
    table.add_row("置信度", plan["confidence"])
    table.add_row("预计节省", _fmt_seconds(plan.get("estimated_savings_seconds"))
                  + f" ({_fmt_pct(plan.get('estimated_savings_pct'))})")
    table.add_row("计划文件", plan.get("path", ""))
    console.print(table)
    if plan.get("notes"):
        for note in plan["notes"]:
            console.print(f"[dim]· {note}[/dim]")


@incremental_group.command("deps")
@click.option("--run", "run_root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="run 目录（读 env/testpoints/attribution/rtl）")
@click.option("--write", is_flag=True,
              help="写到 <run>/coverage/test_dependencies.json")
@click.option("--force", is_flag=True, help="覆盖已有 sidecar")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def incremental_deps(run_root, write, force, json_output):
    """从 run 产物自动生成用例依赖映射（file_pattern → env/testpoint/RTL）。"""
    from src.core.incremental.deps_gen import generate_dependency_map

    doc = generate_dependency_map(run_root, write=write, force=force)
    if json_output:
        click.echo(json.dumps(doc, indent=2, ensure_ascii=False, default=str))
        return
    table = Table(title=f"Dependency Map — {Path(run_root).name}")
    table.add_column("项", style="cyan")
    table.add_column("值")
    table.add_row("来源", str(doc.get("source") or "none"))
    table.add_row("用例", f"{len(doc.get('tests') or {})} 条"
                  f"（{doc.get('coverage_of_tests') or '?'}）")
    table.add_row("未映射", f"{len(doc.get('unmapped_tests') or [])} 条")
    table.add_row("文件", str(doc.get("path") or "（未写盘，加 --write）"))
    console.print(table)
    for note in doc.get("notes") or []:
        console.print(f"[dim]· {note}[/dim]")


@diff.command("runs")
@click.option("--baseline", required=True, type=click.Path(exists=True, file_okay=False,
                                                           path_type=Path))
@click.option("--current", required=True, type=click.Path(exists=True, file_okay=False,
                                                          path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def diff_runs(baseline, current, json_output):
    """两次运行的验证智能对比（覆盖率/TP/回归/决策/归因/RTL）。"""
    from src.core.incremental.run_diff import write_run_diff

    report = write_run_diff(baseline, current)
    if json_output:
        click.echo(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return
    d = report["deltas"]
    table = Table(title=f"Run Diff — {report['baseline']['run_id']} → {report['current']['run_id']}")
    table.add_column("指标", style="cyan")
    table.add_column("变化")
    table.add_row("功能覆盖率", _fmt_pct(d.get("functional_pct")))
    table.add_row("代码覆盖率", _fmt_pct(d.get("overall_pct")))
    table.add_row("TP HIT", str(d.get("tp_hit")))
    table.add_row("TP MISS", str(d.get("tp_miss")))
    table.add_row("回归耗时", _fmt_seconds(d.get("regression_seconds")))
    table.add_row("决策有效率", _fmt_pct((d.get("decision_rate") or 0) * 100
                                        if d.get("decision_rate") is not None else None))
    table.add_row("归因完整率", _fmt_pct((d.get("attribution_rate") or 0) * 100
                                        if d.get("attribution_rate") is not None else None))
    table.add_row("RTL 变更", f"{len(report['rtl']['changed'])} 个文件")
    console.print(table)
