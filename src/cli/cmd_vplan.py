"""`vagent vplan` —— 把 spec-first 项目接进执行内核。

当前只做**规划/契约层**：读 `docs/specs/*.csv` + `data/contract_matrix/*.csv`，
写出 `coverage/testpoints.*`、`coverage/case_ir.json`、`contract/*`。
不跑 EDA，不产生 `signoff_evidence/`，所以产物不可签核。
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from src.cli.commands import cli, console


@cli.group("vplan")
def vplan_group():
    """AI VPlan 规划层（spec-first 项目 → TP/契约 IR）。"""


@vplan_group.command("status")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--allow-spec-drift", is_flag=True,
              help="spec 与 spec_meta 哈希不符时仍读取（仅预览）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_status(project, allow_spec_drift, json_output):
    """只读：项目计数与契约/TP/case 状态。"""
    from src.layers.l3_decision.vplan import VPlanError, load_project

    try:
        proj = load_project(project, allow_spec_drift=allow_spec_drift)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc
    summary = {
        "project": str(proj.root),
        "module": proj.module,
        "dut": proj.dut,
        "spec_hash": proj.spec_hash,
        "requirements": len(proj.requirements),
        "features": len(proj.features),
        "topics": len(proj.topics),
        "contracts": len(proj.contracts),
        "contracts_by_status": proj.status_counts,
        "testpoints": len(proj.testpoints),
        "testpoints_by_status": proj.tp_status_counts,
        "cases": len(proj.cases),
        "cases_by_status": proj.case_status_counts,
        "warnings": proj.warnings,
    }
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    console.print(f"[cyan]{proj.module}[/cyan] · DUT={proj.dut} · "
                  f"spec={proj.spec_path.name}")
    console.print(f"  需求 {summary['requirements']} / feature "
                  f"{summary['features']} / 专题 {summary['topics']}")
    console.print(f"  契约 {summary['contracts']}："
                  f"{summary['contracts_by_status']}")
    console.print(f"  TP {summary['testpoints']}："
                  f"{summary['testpoints_by_status']}")
    console.print(f"  case {summary['cases']}："
                  f"{summary['cases_by_status']}")
    for warning in proj.warnings:
        console.print(f"  [yellow]! {warning}[/yellow]")


@vplan_group.command("build")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--output", "-o", type=click.Path(file_okay=False),
              default=None, help="输出 run 目录（默认 output_vplan_<module>_<时间戳>）")
@click.option("--allow-spec-drift", is_flag=True,
              help="spec 与 spec_meta 哈希不符时仍生成（仅预览，不可签核）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_build(project, output, allow_spec_drift, json_output):
    """把 VPlan 项目写成一次只规划的 run（TP/Case/契约 IR）。"""
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.layers.l3_decision.vplan import (
        VPlanError, load_project, write_plan_only_run,
    )

    try:
        proj = load_project(project, allow_spec_drift=allow_spec_drift)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc

    out = output or make_output_root(f"output_vplan_{proj.module}")
    summary = write_plan_only_run(proj, out)
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    counts = summary["counts"]
    console.print(f"[green]✓ VPlan 规划 IR[/green] → {summary['run']}")
    console.print(f"  契约 {counts['contracts']}：{counts['contracts_by_status']}")
    console.print(f"  TP {counts['testpoints']}：{counts['testpoints_by_status']}")
    console.print(f"  case {counts['cases']}：{counts['cases_by_status']}")
    console.print("  [yellow]执行阶段未运行（PLAN_ONLY）：没有 EDA 证据，"
                  "不可签核[/yellow]")
