"""`vagent mental` —— 心智模型 IR（Mental IR）。

从 spec 提炼：验证目标、假设、歧义、验证意图、风险，落盘到
`<run>/mental_ir/{mental_ir.json,mental_ir.yaml,manifest.json}`。
独立路径，不改 supervisor 闭环。
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.cli.commands import cli, console


@cli.group("mental")
def mental_group():
    """Mental IR：从 spec 生成「心智模型」，供人审阅与后续验证引用。"""


@mental_group.command("build")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="输出 run 目录（默认 output_mental_<spec 名>）",
)
@click.option("--module", default="", help="模块名（默认取 spec 文件名）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def mental_build(spec, output, module, json_output):
    """从 spec 生成 Mental IR 并落盘。"""
    from src.agent_plane.specialists.mental.main import MentalIRError, run

    text = spec.read_text(encoding="utf-8", errors="replace")
    out = output or Path(f"output_mental_{spec.stem}")
    try:
        result = run(text, out, module=module or spec.stem, spec_path=str(spec))
    except MentalIRError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    counts = result["counts"]
    console.print(f"[green]✓ Mental IR[/green] {result['module']} → {result['files']['dir']}")
    console.print(
        f"  goals={counts['goals']} assumptions={counts['assumptions']} "
        f"ambiguities={counts['ambiguities']}"
        f"(blocking={counts['blocking_ambiguities']}) "
        f"intents={counts['verification_intents']} risks={counts['risks']}"
    )
    console.print(f"  digest={result['digest'][:12]}…  json={result['files']['json']}")


__all__ = ["mental_group"]
