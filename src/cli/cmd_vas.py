"""`vagent vas` — Verification Agentic System 1.0 entry point."""
from __future__ import annotations

import json
from pathlib import Path

import click

from src.cli.commands import cli, console
from src.vas.engine.protocols import NullEngine
from src.vas.orchestration.orchestrator import (
    OrchestratorConfig, VerificationOrchestrator,
)


@cli.group("vas")
def vas_group():
    """Verification Agentic System：IR 驱动的验证闭环。"""


@vas_group.command("run")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False,
                                        path_type=Path))
@click.option("--design-top", default="", help="DUT 顶层 module 名")
@click.option("--target", type=float, default=95.0, show_default=True)
@click.option("--workspace", "-o", default="output_vas", show_default=True)
@click.option("--max-rounds", type=int, default=2, show_default=True)
@click.option("--authorized", is_flag=True,
              help="声明本次为授权运行（仅影响 gate 的人工决策占位）")
@click.option("--json", "-j", "json_output", is_flag=True)
def vas_run(spec, design_top, target, workspace, max_rounds,
            authorized, json_output):
    """按 Intent → Design → Execution → Evidence 的闭环跑一次验证。"""
    text = spec.read_text(encoding="utf-8", errors="replace")
    orch = VerificationOrchestrator(
        engine=NullEngine(),
        config=OrchestratorConfig(
            target=target, max_rounds=max_rounds,
            authorized=authorized, workspace=workspace))
    result = orch.run(spec_text=text, design={"top": design_top})
    doc = result.to_dict()
    if json_output:
        click.echo(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        console.print(f"[cyan]VAS[/cyan] status={result.status} "
                      f"phase={result.phase}")
        for blocker in result.blockers:
            console.print(f"  [red]✗ {blocker}[/red]")
        console.print(f"  evidence: {result.evidence_dir}")


__all__ = ["vas_group"]
