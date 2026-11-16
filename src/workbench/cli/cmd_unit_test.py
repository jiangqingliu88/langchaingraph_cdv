"""`vagent unit-test` —— 纯 SV 单元 testbench（不引入 UVM）。

生成 TB 后调用真实 vlog/vsim；没有 EDA 时状态是 GENERATED_ONLY，不是 PASS。
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.cli.commands import cli, console


@cli.group("unit-test")
def unit_test_group():
    """Unit Testing：生成纯 SV testbench，编译/运行并如实报告。"""


@unit_test_group.command("build")
@click.argument("rtl", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="输出 run 目录（默认 output_unit_<rtl 名>）",
)
@click.option("--module", default="", help="DUT 模块名（默认从 RTL 解析）")
@click.option("--no-compile", is_flag=True, help="只生成 TB，不调 vlog")
@click.option("--no-sim", is_flag=True, help="编译后不调 vsim")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def unit_test_build(rtl, output, module, no_compile, no_sim, json_output):
    """生成 unit testbench → 编译 → 运行。"""
    from src.agent_plane.specialists.common import SpecialistError
    from src.agent_plane.specialists.unit_testing.main import run

    out = output or Path(f"output_unit_{rtl.stem}")
    try:
        result = run(rtl, out, module=module, compile=not no_compile, simulate=not no_sim)
    except SpecialistError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✓ Unit Test[/green] {result['module']} → {Path(result['report']).parent}")
    console.print(f"  status={result['status']} compile={result['compile']} run={result['run']}")
    console.print(f"  tb={result['tb']}")


__all__ = ["unit_test_group"]


@unit_test_group.command("chat")
@click.argument("prompt")
@click.option("--workspace", default=None, help="项目工作区（默认当前目录）")
@click.option("--session", "session_id", default=None, help="沿用既有 session")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def unit_test_chat(prompt, workspace, session_id, json_output):
    """与 Unit Testing 对话（与 GUI 同一份模式配置）。"""
    from src.workbench.modes.agent_chat import chat_and_render

    chat_and_render("unit_testing", prompt, workspace=workspace, session_id=session_id, json_output=json_output)
