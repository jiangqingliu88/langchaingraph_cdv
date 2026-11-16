"""`vagent modes` —— 两种前端模式的唯一清单。

CLI（headless）与 PySide6 UI/TUI（interactive）。chat / plan / verify 是两种
模式共用的交互方式，不是第三种前端。
"""
from __future__ import annotations

import json

import click

from src.workbench.cli.commands import cli, console
from src.workbench.frontends import rows


@cli.command("modes")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def modes_command(json_output):
    """列出两种前端模式及其能力。"""
    data = rows()
    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    console.print("[bold]前端模式（两种）[/bold]\n")
    for mode in data:
        flag = "headless" if mode["headless"] else "interactive"
        console.print(f"[bold cyan]{mode['title']}[/bold cyan]  [dim]({flag})[/dim]")
        console.print("  入口：")
        for entry in mode["entrypoints"]:
            console.print(f"    · {entry}")
        console.print("  能力：")
        for capability in mode["capabilities"]:
            console.print(f"    · {capability}")
        if mode.get("note"):
            console.print(f"  [dim]{mode['note']}[/dim]")
        console.print()
    console.print("[dim]chat / plan / verify 是两种模式共用的交互方式，不是第三种前端。[/dim]")
