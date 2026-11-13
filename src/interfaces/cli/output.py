"""
CLI 输出适配器与公共参数

统一输出 —— 自动检测终端/CI/文件
所有命令共用的 click decorator
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Literal, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, TimeElapsedColumn, TimeRemainingColumn,
)

console = Console()


class OutputAdapter:
    """统一输出 — 自动检测终端/CI/文件"""

    def __init__(self, fmt: Literal["auto", "rich", "json", "plain"] = "auto"):
        self.fmt = fmt
        if self.fmt == "auto":
            # 检测是否为 CI 环境（无 TTY）
            if not sys.stdout.isatty() or os.environ.get("CI"):
                self.fmt = "json"
            else:
                self.fmt = "rich"

    def print_result(self, data: dict, title: str = ""):
        if self.fmt == "json":
            click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        elif self.fmt == "plain":
            for k, v in data.items():
                click.echo(f"{k}: {v}")
        else:
            if title:
                console.print(Panel(str(data)[:2000], title=title))
            else:
                console.print(data)

    def print_table(self, headers: list, rows: list, title: str = ""):
        if self.fmt == "json":
            result = []
            for row in rows:
                result.append(dict(zip(headers, row)))
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        elif self.fmt == "plain":
            click.echo("\t".join(headers))
            for row in rows:
                click.echo("\t".join(str(c) for c in row))
        else:
            table = Table(title=title) if title else Table()
            for h in headers:
                table.add_column(h)
            for row in rows:
                table.add_row(*[str(c) for c in row])
            console.print(table)

    def print_error(self, msg: str, code: int = 1) -> int:
        if self.fmt == "json":
            click.echo(json.dumps({"error": msg, "code": code}))
        else:
            console.print(f"[red]Error: {msg}[/red]")
        return code

    def print_success(self, msg: str):
        if self.fmt == "json":
            click.echo(json.dumps({"status": "ok", "message": msg}))
        else:
            console.print(f"[green]✓ {msg}[/green]")

    def print_progress(self, current: int, total: int, label: str):
        if self.fmt in ("json", "plain"):
            return
        pct = round(current / max(total, 1) * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        console.print(f"  [{bar}] {label}: {current}/{total} ({pct}%)")

    def create_progress(self) -> Progress:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        )


def common_options(f):
    """注入全局选项: --json / --quiet / --verbose / --output-dir"""
    f = click.option("--json", "-j", "json_output", is_flag=True, help="JSON 格式输出")(f)
    f = click.option("--quiet", "-q", is_flag=True, help="静默模式，只打印错误")(f)
    f = click.option("--verbose", "-v", is_flag=True, help="详细输出")(f)
    f = click.option("--output-dir", "-o", type=click.Path(), help="输出目录")(f)
    return f


def get_output_adapter(json_output: bool = False, quiet: bool = False) -> OutputAdapter:
    if json_output:
        return OutputAdapter("json")
    if quiet:
        return OutputAdapter("plain")
    return OutputAdapter("rich")
