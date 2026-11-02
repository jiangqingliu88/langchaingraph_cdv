"""CLI 命令组：版本差异对比（diff）。

从 `src/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
共享 helper 仍从 `commands` 导入，别在这里再造一份。
"""
from __future__ import annotations

import json  # noqa: F401
from pathlib import Path  # noqa: F401

import click
from rich.table import Table  # noqa: F401

from src.cli.output import common_options, get_output_adapter  # noqa: F401
from src.cli.commands import (  # noqa: F401
    cli, console, _repo, _resolve_run, _extract_requirements_from_md,
)

@cli.group()
def diff():
    """版本差异对比"""
    pass


@diff.command("coverage")
@click.option("--run-a", required=True, help="Run A ID")
@click.option("--run-b", required=True, help="Run B ID")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json"]), help="输出格式")
def diff_coverage(run_a, run_b, fmt):
    """覆盖率对比

    \b
    示例:
      vagent diff coverage --run-a <id1> --run-b <id2>
      vagent diff coverage --run-a <id1> --run-b <id2> --format json
    """
    out = get_output_adapter(fmt == "json")
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        cov_a = ma.metadata.get("coverage", {})
        cov_b = mb.metadata.get("coverage", {})

        if isinstance(cov_a, dict) and isinstance(cov_b, dict):
            rows = [
                ["Line Coverage", f"{cov_a.get('line_pct', 0):.1f}%", f"{cov_b.get('line_pct', 0):.1f}%",
                 f"{cov_b.get('line_pct', 0) - cov_a.get('line_pct', 0):+.1f}%"],
                ["Branch Coverage", f"{cov_a.get('branch_pct', 0):.1f}%", f"{cov_b.get('branch_pct', 0):.1f}%",
                 f"{cov_b.get('branch_pct', 0) - cov_a.get('branch_pct', 0):+.1f}%"],
                ["Toggle Coverage", f"{cov_a.get('toggle_pct', 0):.1f}%", f"{cov_b.get('toggle_pct', 0):.1f}%",
                 f"{cov_b.get('toggle_pct', 0) - cov_a.get('toggle_pct', 0):+.1f}%"],
                ["Overall", f"{cov_a.get('coverage_pct', 0):.1f}%", f"{cov_b.get('coverage_pct', 0):.1f}%",
                 f"{cov_b.get('coverage_pct', 0) - cov_a.get('coverage_pct', 0):+.1f}%"],
            ]
            out.print_table(["Metric", f"Run A ({run_a[:12]})", f"Run B ({run_b[:12]})", "Delta"],
                            rows, title="Coverage Diff")
        else:
            out.print_error("Coverage data not available")

    except Exception as e:
        out.print_error(f"Diff failed: {e}")


@diff.command("spec")
@click.option("--old", "old_spec", required=True, type=click.Path(exists=True), help="旧规格文件")
@click.option("--new", "new_spec", required=True, type=click.Path(exists=True), help="新规格文件")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json"]), help="输出格式")
def diff_spec(old_spec, new_spec, fmt):
    """规格变更影响分析

    \b
    示例:
      vagent diff spec --old spec_v1.md --new spec_v2.md
    """
    out = get_output_adapter(fmt == "json")
    try:
        old_text = Path(old_spec).read_text(encoding="utf-8")
        new_text = Path(new_spec).read_text(encoding="utf-8")

        old_reqs = _extract_requirements_from_md(old_text)
        new_reqs = _extract_requirements_from_md(new_text)

        old_ids = {r["id"] for r in old_reqs}
        new_ids = {r["id"] for r in new_reqs}

        added = new_ids - old_ids
        removed = old_ids - new_ids
        kept = old_ids & new_ids

        out.print_result({
            "old_file": old_spec,
            "new_file": new_spec,
            "old_requirements": len(old_reqs),
            "new_requirements": len(new_reqs),
            "added": len(added),
            "removed": len(removed),
            "unchanged": len(kept),
            "added_list": sorted(added),
            "removed_list": sorted(removed),
        }, title="Spec Change Impact")

    except Exception as e:
        out.print_error(f"Spec diff failed: {e}")


@diff.command("regression")
@click.option("--run-a", required=True, help="Run A ID")
@click.option("--run-b", required=True, help="Run B ID")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json"]), help="输出格式")
def diff_regression(run_a, run_b, fmt):
    """回归结果对比

    \b
    示例:
      vagent diff regression --run-a <id1> --run-b <id2>
    """
    out = get_output_adapter(fmt == "json")
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        reg_a = ma.metadata.get("regression", {})
        reg_b = mb.metadata.get("regression", {})

        if isinstance(reg_a, dict) and isinstance(reg_b, dict):
            out.print_result({
                "run_a": {"passed": reg_a.get("passed", 0), "failed": reg_a.get("failed", 0),
                          "total": reg_a.get("total", 0)},
                "run_b": {"passed": reg_b.get("passed", 0), "failed": reg_b.get("failed", 0),
                          "total": reg_b.get("total", 0)},
                "delta_passed": reg_b.get("passed", 0) - reg_a.get("passed", 0),
                "delta_failed": reg_b.get("failed", 0) - reg_a.get("failed", 0),
            }, title="Regression Diff")
        else:
            out.print_error("Regression data not available")

    except Exception as e:
        out.print_error(f"Diff failed: {e}")


@diff.command("audit")
@click.option("--run-a", required=True, help="Run A ID (基准)")
@click.option("--run-b", required=True, help="Run B ID (对比)")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json", "detail"]), help="输出格式")
def diff_audit(run_a, run_b, fmt):
    """字段级审计 diff — 精确定位两次签核之间的差异

    \b
    示例:
      vagent diff audit --run-a run_20260810 --run-b run_20260812
      vagent diff audit --run-a run_20260810 --run-b run_20260812 --format json
      vagent diff audit --run-a run_20260810 --run-b run_20260812 --format detail

    输出: 每个阶段的字段级变更（added/removed/changed）
    """
    out = get_output_adapter(fmt == "json")
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder, EvidencePackager
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        diff = EvidencePackager.diff(ma, mb)

        if fmt == "json":
            out.print_result(diff)
        elif fmt == "detail":
            # 详细输出：每个字段的 hash 对比
            table = Table(title=f"Audit Diff: {run_a[:16]} vs {run_b[:16]}")
            table.add_column("Phase", style="cyan")
            table.add_column("Changed Fields", style="yellow")
            table.add_column("Added", style="green")
            table.add_column("Removed", style="red")
            table.add_column("Score Δ", style="magenta")

            for pname, pdiff in diff.get("phase_diffs", {}).items():
                changed = ", ".join(pdiff.get("changed_fields", [])[:5])
                if len(pdiff.get("changed_fields", [])) > 5:
                    changed += f" +{len(pdiff['changed_fields']) - 5} more"
                added = str(len(pdiff.get("added_fields", []))) if pdiff.get("added_fields") else "-"
                removed = str(len(pdiff.get("removed_fields", []))) if pdiff.get("removed_fields") else "-"
                score_d = pdiff.get("score_delta", 0)
                score_str = f"{score_d:+.0f}" if score_d != 0 else "-"
                table.add_row(pname, changed or "-", added, removed, score_str)

            console.print(table)
            console.print(f"\n[dim]{diff['summary']}[/dim]")
        else:
            # table: 简洁摘要
            rows = []
            has_changes = False
            for pname, pdiff in diff.get("phase_diffs", {}).items():
                n_changed = len(pdiff.get("changed_fields", []))
                n_added = len(pdiff.get("added_fields", []))
                n_removed = len(pdiff.get("removed_fields", []))
                if n_changed + n_added + n_removed > 0:
                    has_changes = True
                    rows.append([pname, str(n_changed), str(n_added), str(n_removed),
                                 str(pdiff.get("unchanged", 0)), f"{pdiff.get('score_delta', 0):+.0f}"])

            if rows:
                out.print_table(
                    ["Phase", "Changed", "Added", "Removed", "Unchanged", "Score Δ"],
                    rows, title="Field-Level Audit Diff"
                )
                console.print(f"\n[dim]{diff['summary']}[/dim]")
            else:
                console.print("[green]No field-level changes detected — runs are identical[/green]")

    except Exception as e:
        out.print_error(f"Audit diff failed: {e}")
