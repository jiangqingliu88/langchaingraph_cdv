"""按功能分块的接口时序闭环入口，不是独立的第十平面。"""

from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.cli.commands import cli

DEFAULT_FIXTURE = Path(__file__).resolve().parents[3] / "examples/interface_timing/axi_stream"
DEFAULT_OUT = Path(__file__).resolve().parents[3] / "review_bundle/chipstack_artifacts"


@cli.group("interface-timing")
def interface_timing_group():
    """Source → Temporal IR → Binding → Monitor → RTL Evidence。"""


@interface_timing_group.command("run-slice")
@click.option(
    "--fixture",
    default=str(DEFAULT_FIXTURE),
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=str),
)
@click.option(
    "--out", "out_root", default=str(DEFAULT_OUT), show_default=True, type=click.Path(file_okay=False, path_type=str)
)
@click.option("--seed", default=4242, show_default=True, type=int)
@click.option("--legacy-layout", "legacy_layout", is_flag=True, help="保留旧的 run-* 平铺产物，不写项目工作区")
@click.option("--top-design-name", "top_design_name", default="", help="工作区项目目录名；默认 fixture 目录名")
@click.option("--allow-incomplete", is_flag=True, help="允许无仿真器环境查看 INCOMPLETE 证据；不改变实际裁决。")
@click.option("--json", "json_output", is_flag=True)
def interface_timing_run_slice(
    fixture: str,
    out_root: str,
    seed: int,
    allow_incomplete: bool,
    json_output: bool,
    legacy_layout: bool,
    top_design_name: str,
):
    """编译并仿真一个 AXI-Stream 稳定性闭环。"""
    from src.orchestration_plane.interface_timing_workflow import TemporalSlicePipeline

    if seed < 0:
        raise click.BadParameter("seed 必须为非负整数")
    if top_design_name:
        from src.runtime_plane.artifacts.chipstack_workspace import _safe_name

        try:
            _safe_name(top_design_name)
        except ValueError as exc:
            raise click.BadParameter(str(exc)) from exc
    design_name = top_design_name or None
    layout = "legacy" if legacy_layout else "chipstack"
    result = TemporalSlicePipeline(fixture, out_root, layout=layout, top_design_name=design_name).run(seed=seed)
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"{result['overall_status']}: interface_timing_v1")
        click.echo(f"simulation_kind={result.get('simulation_kind', 'not_started')}")
        for row in result.get("scenarios") or []:
            click.echo(
                f"  {row['scenario']}: expected={row['expected_status']} "
                f"actual={row['actual_status']} met={row['expectation_met']}"
            )
        workspace = result.get("workspace") or {}
        if workspace.get("project_root"):
            click.echo(f"project_workspace={workspace['project_root']}")
        if result.get("evidence_manifest"):
            click.echo(f"evidence={result['evidence_manifest']}")
        if result.get("reason"):
            click.echo(f"reason={result['reason']}")
    raise SystemExit(
        0
        if result["overall_status"] == "PASS" or (allow_incomplete and result["overall_status"] == "INCOMPLETE")
        else 1
        if result["overall_status"] in ("FAIL", "CONFLICT")
        else 2
    )


@interface_timing_group.command("runs")
@click.option(
    "--workspace",
    default=str(DEFAULT_OUT),
    show_default=True,
    type=click.Path(exists=True, file_okay=False, path_type=str),
)
@click.option("--design", "design_name", default="", help="限定设计名；默认列出全部运行")
@click.option("--json", "json_output", is_flag=True, help="机器可读的跨运行索引")
def interface_timing_runs(workspace: str, design_name: str, json_output: bool):
    """读取独立 artifacts.sqlite；这不启动仿真，也不改变原始结论。"""
    from src.runtime_plane.artifacts.chipstack_workspace import read_workspace_runs

    rows = read_workspace_runs(workspace, design_name or None)
    if json_output:
        click.echo(json.dumps({"runs": rows}, ensure_ascii=False, indent=2))
    else:
        click.echo(f"runs={len(rows)}")
        for row in rows:
            click.echo(f"  {row['design_name']} {row['run_id']} {row['overall_status']} {row['simulation_kind']}")


__all__ = ["interface_timing_group"]
