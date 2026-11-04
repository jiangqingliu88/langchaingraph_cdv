"""humanview IR 的命令组：covg / sva / scb 的校验与 Markdown 视图。"""
from __future__ import annotations

import json

import click

from src.cli.commands import cli, console, EXIT_FAIL, EXIT_OK


@cli.group()
def humanview():
    """人类可维护的验证 IR（covg / sva / scb）"""
    pass


def _print_validation(title: str, result: dict, as_json: bool) -> int:
    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return EXIT_OK if result.get("ok") else EXIT_FAIL
    console.print(f"[bold]{title}[/bold]  "
                  f"{'[green]OK[/green]' if result.get('ok') else '[red]FAIL[/red]'}")
    for metric in result.get("metrics") or []:
        color = "green" if metric.get("ok") else "yellow"
        console.print(f"  {metric['name']}: [{color}]{metric['covered']}/"
                      f"{metric['total']} ({metric['pct']}%)[/{color}]")
    for err in result.get("errors") or []:
        console.print(f"  [red]error[/red] {err}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]warn[/yellow] {warn}")
    return EXIT_OK if result.get("ok") else EXIT_FAIL


@humanview.command("case-xlsx")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--bindings", "-b", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="case_bindings_v1 YAML（CASE → dimensions/cells/tests）")
@click.option("--module", "-m", default="", help="模块名")
@click.option("--out", "-o", default="", help="写 case_ir.json 的路径")
@click.option("--emit-bindings", "emit_bindings", default="",
              help="写 case_bindings_v1 空骨架（只填 dimensions/cells/tests）")
@click.option("--json", "-j", "as_json", is_flag=True, help="JSON 输出")
def humanview_case_xlsx(path, bindings, module, out, emit_bindings, as_json):
    """业务测试点表（xlsx）→ Case IR（CCAT/CASE；不自动猜维度）"""
    from src.layers.l3_decision.case_ir import (bindings_skeleton,
                                             project_from_xlsx,
                                             validate_case_doc)

    doc = project_from_xlsx(path, module=module, bindings=bindings)
    result = validate_case_doc(doc)
    payload = doc.to_dict()
    if out:
        from pathlib import Path

        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        click.echo(f"已写到 {target}")
    if emit_bindings:
        import yaml as _yaml

        from pathlib import Path

        target = Path(emit_bindings)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_yaml.safe_dump(bindings_skeleton(doc),
                                          allow_unicode=True, sort_keys=False),
                          encoding="utf-8", newline="\n")
        click.echo(f"绑定骨架已写到 {target}（每条 CASE 填 dimensions/cells/tests）")
    if as_json:
        click.echo(json.dumps({"case_ir": payload, "validation": result},
                              indent=2, ensure_ascii=False, default=str))
        return
    counts = payload.get("counts") or {}
    console.print(f"[bold]Case IR（xlsx）[/bold] {counts}")
    for err in result.get("errors") or []:
        console.print(f"  [red]error[/red] {err.get('message')}")
    for warn in result.get("warnings") or []:
        console.print(f"  [yellow]warn[/yellow] {warn.get('message')}")


@humanview.command("covg")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "-j", "as_json", is_flag=True, help="JSON 输出")
@click.option("--markdown", "-m", is_flag=True, help="输出 Markdown 视图")
def humanview_covg(path, as_json, markdown):
    """功能覆盖率 IR：纵横矩阵 / 路径 / 追溯 校验"""
    from src.tools.humanview.covg_ir import (render_covg_markdown,
                                             validate_covg_text)

    if markdown:
        click.echo(render_covg_markdown(path))
        return
    raise SystemExit(_print_validation("covg_ir", validate_covg_text(path), as_json))


@humanview.command("sva")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "-j", "as_json", is_flag=True, help="JSON 输出")
@click.option("--markdown", "-m", is_flag=True, help="输出 Markdown 视图")
def humanview_sva(path, as_json, markdown):
    """SVA 分解 IR：契约覆盖 / 非 vacuous / 七类 / 重复 校验"""
    from src.tools.humanview.sva_ir import (render_sva_markdown,
                                            validate_sva_text)

    if markdown:
        click.echo(render_sva_markdown(path))
        return
    raise SystemExit(_print_validation("sva_ir", validate_sva_text(path), as_json))


@humanview.command("scb")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "-j", "as_json", is_flag=True, help="JSON 输出")
@click.option("--markdown", "-m", is_flag=True, help="输出 Markdown 视图")
def humanview_scb(path, as_json, markdown):
    """Scoreboard IR：契约 / 执行率 / 五类 / 账本平衡 校验"""
    from src.tools.humanview.scb_ir import (render_scb_markdown,
                                            validate_scb_text)

    if markdown:
        click.echo(render_scb_markdown(path))
        return
    raise SystemExit(_print_validation("scb_ir", validate_scb_text(path), as_json))
