"""SignOffAI CLI 命令组：覆盖率（coverage）

从 `src/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
命令实现保持不变，便于逐步搬迁与回滚。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json
import sys  # noqa: F401
from datetime import datetime  # noqa: F401
from pathlib import Path

import click  # noqa: F401
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.cli.output import common_options, get_output_adapter  # noqa: F401
from src.cli.commands import (  # noqa: F401
    cli, console,
    EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_WAITING, EXIT_STRICT,
    _repo, _resolve_run, _init_service, _find_run_id,
    _strict_semantic_gate,
    _extract_requirements_from_md, _get_git_info,
    _exclude_registry, _output_junit, _output_gitlab_ci,
    _checkpoint_db, _resume_closed_loop, _report_resume,
    _approver_name, _sha256_path, _write_approval_record, _decide,
)

@cli.group()
def coverage():
    """覆盖率管理"""
    pass


@coverage.command("report")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_report(run_id, json_output):
    """覆盖率报告

    \b
    示例:
      vagent coverage report --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))
        cov = manifest.metadata.get("coverage", {})

        if isinstance(cov, dict) and cov:
            out.print_result({
                "run_id": rid,
                "line_coverage": f"{cov.get('line_pct', 0):.1f}%",
                "branch_coverage": f"{cov.get('branch_pct', 0):.1f}%",
                "toggle_coverage": f"{cov.get('toggle_pct', 0):.1f}%",
                "overall": f"{cov.get('coverage_pct', 0):.1f}%",
            }, title=f"Coverage Report — {rid}")
        else:
            out.print_error("Coverage data not available")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("gaps")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_gaps(run_id, json_output):
    """覆盖率缺口

    \b
    示例:
      vagent coverage gaps --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))
        cov = manifest.metadata.get("coverage", {})

        if isinstance(cov, dict):
            gaps = cov.get("gaps", [])
            suggestions = cov.get("suggestions", [])
            out.print_result({
                "run_id": rid,
                "gaps": gaps[:20],
                "suggestions": suggestions[:10],
                "gap_count": len(gaps),
            }, title=f"Coverage Gaps — {rid}")
        else:
            out.print_error("Coverage data not available")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("exclude")
@click.option("--coverage", "-c", type=float, default=None, help="当前覆盖率（%，配合 --total 计算有效覆盖率）")
@click.option("--total", "-t", type=int, default=None, help="总覆盖点数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_exclude(coverage, total, json_output):
    """覆盖率里的 Exclude 视图：已放弃点 + 待审批 + 有效覆盖率

    \b
    示例:
      vagent coverage exclude                              # 已放弃/待审批摘要
      vagent coverage exclude -c 95 -t 100                 # 附有效覆盖率
    """
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        approved = reg.get_approved_excludes()
        pending = reg.list_pending()
        stats = reg.stats()
        result = {
            "stats": stats,
            "approved_points": sorted(reg.get_excluded_points()),
            "pending": [{"exclude_id": p["exclude_id"], "coverage_point": p["coverage_point"],
                         "type": p["exclude_type"], "reason": p["reason"]} for p in pending],
        }
        if coverage is not None and total is not None:
            result["effective"] = {
                "raw_coverage": coverage, "total_points": total,
                "excluded": stats["excluded_points"],
                "effective_total": max(total - stats["excluded_points"], 1),
                "effective_coverage": reg.effective_coverage(coverage, total),
            }

        if json_output:
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            return

        console.print(f"[bold]覆盖率 Exclude 视图[/bold] — "
                      f"已放弃 {stats['excluded_points']} 点 | 待审批 {stats['pending']}")
        if coverage is not None and total is not None:
            eff = result["effective"]
            console.print(f"[cyan]有效覆盖率: {eff['raw_coverage']}% → {eff['effective_coverage']}%"
                          f"（分母 {eff['total_points']} → {eff['effective_total']}）[/cyan]")
        if approved:
            console.print(f"\n[yellow]已批准（生效）:[/yellow]")
            for e in approved:
                console.print(f"   {e['exclude_id']}  {e['coverage_point']}  ({e['exclude_type']})")
        if pending:
            console.print(f"\n[bold red]待审批（阻断签核）:[/bold red]")
            for p in pending:
                console.print(f"   {p['exclude_id']}  {p['coverage_point']}  ({p['exclude_type']}) — "
                              f"vagent exclude approve {p['exclude_id']}")
        if not approved and not pending:
            console.print("[dim]暂无 Exclude。闭环会自动发现结构性死代码并提议；也可手动 'vagent exclude propose'。[/dim]")
    finally:
        reg.close()


@coverage.command("trend")
@click.option("--days", "-d", default=30, help="天数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_trend(days, json_output):
    """覆盖率趋势

    \b
    示例:
      vagent coverage trend --days 30
    """
    out = get_output_adapter(json_output)
    # Use regression trend as proxy
    try:
        from src.layers.l4_memory.persistence.repository import get_regression_trend
        trend = asyncio.run(get_regression_trend(days=days))
        out.print_result({"days": days, "data_points": len(trend), "trend": trend},
                         title=f"Coverage Trend ({days}d)")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("merge")
@click.option("--runs", required=True, help="逗号分隔的 run IDs")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_merge(runs, json_output):
    """合并多次覆盖率

    \b
    示例:
      vagent coverage merge --runs run_a,run_b,run_c
    """
    out = get_output_adapter(json_output)
    run_list = [r.strip() for r in runs.split(",")]

    # Aggregate coverage data
    aggregated = {"line_pct": 0, "branch_pct": 0, "toggle_pct": 0, "coverage_pct": 0}
    count = 0

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        for rid in run_list:
            manifest = builder.build(session_id=rid.replace("run_", ""))
            cov = manifest.metadata.get("coverage", {})
            if isinstance(cov, dict) and cov:
                for key in aggregated:
                    aggregated[key] += cov.get(key, 0)
                count += 1

        if count > 0:
            for key in aggregated:
                aggregated[key] = round(aggregated[key] / count, 1)

        out.print_result({
            "runs": run_list,
            "run_count": count,
            "merged_coverage": aggregated,
        }, title="Merged Coverage")
    except Exception as e:
        out.print_error(str(e))


# ═══════════════════════════════════════════════════════════════
# vagent env — UVM 环境操作 (P3)
# ═══════════════════════════════════════════════════════════════

