"""Interfaces Plane 的 Specification Compiler 入口（只读编译，不执行 EDA）。"""

from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.cli.commands import cli


def _load(path: str) -> dict:
    source = Path(path)
    text = source.read_text(encoding="utf-8", errors="strict")
    if source.suffix.lower() in (".yaml", ".yml"):
        import yaml

        return yaml.safe_load(text) or {}
    return json.loads(text)


@cli.group("specification")
def specification_group():
    """Specification Lifecycle / IR 编译 / Readiness（不是新平面）。"""


@specification_group.command("compile")
@click.argument("document", type=click.Path(exists=True, dir_okay=False, path_type=str))
@click.option("--out", default="", help="可选输出 JSON 文件或目录")
@click.option("--json", "json_output", is_flag=True, help="完整契约和校验报告")
def specification_compile(document: str, out: str, json_output: bool):
    """编译结构化 Specification Contract；VALIDATED=0/CONFLICT=1/INCOMPLETE=2。"""
    from src.mental_ir_plane.specification_compiler import SpecSchemaError
    from src.orchestration_plane.specification_workflow import SpecificationWorkflow

    try:
        result = SpecificationWorkflow().run(_load(document))
    except (SpecSchemaError, OSError, UnicodeError, ValueError) as exc:
        raise click.ClickException(f"Specification 无法编译：{exc}") from exc
    payload = result.to_dict()
    if out:
        target = Path(out)
        if target.is_dir() or not target.suffix:
            target = target / "specification_readiness.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"{result.status}: {result.contract.document_id}")
        click.echo(f"spec_hash={result.spec_hash} execution_allowed={result.execution_allowed}")
        click.echo(f"counts={json.dumps(result.counts, ensure_ascii=False)}")
        for issue in result.issues:
            click.echo(f"  {issue.code}: {issue.message}")
    raise SystemExit(0 if result.status == "VALIDATED" else 1 if result.status == "CONFLICT" else 2)


@specification_group.command("lifecycle")
def specification_lifecycle():
    """展示九个业务生命周期阶段；由 IR 统一定义。"""
    from src.mental_ir_plane.specification_compiler import LIFECYCLE

    for index, name in enumerate(LIFECYCLE, start=1):
        click.echo(f"{index:02d}  {name}")


__all__ = ["specification_group"]
