"""`vagent formal` —— 形式化验证计划（Formal IR）。

只生成性质/假设/证明义务与引擎需求，**不假装跑过形式引擎**。
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.cli.commands import cli, console


@cli.group("formal")
def formal_group():
    """Formal IR：生成形式化验证计划（不跑引擎）。"""


@formal_group.command("build")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="输出 run 目录（默认 output_formal_<spec 名>）",
)
@click.option("--module", default="", help="模块名（默认取 spec 文件名）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def formal_build(spec, output, module, json_output):
    """从 spec 生成 Formal IR 并落盘到 `<run>/formal/`。"""
    from src.agent_plane.specialists.common import SpecialistError
    from src.agent_plane.specialists.formal.main import run

    text = spec.read_text(encoding="utf-8", errors="replace")
    out = output or Path(f"output_formal_{spec.stem}")
    try:
        result = run(text, out, module=module or spec.stem, spec_path=str(spec))
    except SpecialistError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    counts = result["counts"]
    engine = result.get("engine") or {}
    console.print(f"[green]✓ Formal IR[/green] {result['module']} → {result['files']['dir']}")
    console.print(
        f"  assert={counts['assert']} assume={counts['assume']} "
        f"cover={counts['cover']} obligations={counts['proof_obligations']}"
        f"（unproved={counts['unproved_obligations']}）"
    )
    console.print(f"  engine_ran={engine.get('ran')} reason={engine.get('reason', '')}")
    console.print(f"  digest={result['digest'][:12]}…  json={result['files']['json']}")


__all__ = ["formal_group"]


@formal_group.command("chat")
@click.argument("prompt")
@click.option("--workspace", default=None, help="项目工作区（默认当前目录）")
@click.option("--session", "session_id", default=None, help="沿用既有 session")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def formal_chat(prompt, workspace, session_id, json_output):
    """与 Formal 对话（与 GUI 同一份模式配置）。"""
    from src.workbench.modes.agent_chat import chat_and_render

    chat_and_render("formal", prompt, workspace=workspace, session_id=session_id, json_output=json_output)
