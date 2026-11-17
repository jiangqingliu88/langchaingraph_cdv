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
    from src.agent_plane.design_understanding.mental_model_agent.main import MentalIRError, run

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


@mental_group.command("unify")
@click.option("--mental", "mental_path", default=None, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Mental IR JSON")
@click.option("--dplan", "dplan_path", default=None, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="DPlan JSON（设计/模型契约）")
@click.option("--vplan", "vplan_path", default=None, type=click.Path(exists=True, path_type=Path),
              help="VPlan 项目根或 JSON 快照")
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False, path_type=Path),
              help="统一 IR JSON 输出路径")
@click.option("--project-id", default="", help="项目作用域 id（默认取 design/module）")
@click.option("--top", "top_module", default="", help="顶层 module 名")
@click.option("--mode", type=click.Choice(["import_only", "logical_projection", "reviewed_projection"]),
              default="logical_projection")
@click.option("--views-out", default=None, type=click.Path(dir_okay=False, path_type=Path),
              help="可选：同时导出三种投影视图 JSON")
@click.option("--json", "-j", "json_output", is_flag=True, help="只输出摘要 JSON")
def mental_unify(mental_path, dplan_path, vplan_path, out_path, project_id,
                 top_module, mode, views_out, json_output):
    """把 Mental / DPlan / VPlan 合并为统一 IR（分层投影，不升级证据）。"""
    from src.mental_ir_plane.unified import build_unified_ir, views, write_unified

    if not any((mental_path, dplan_path, vplan_path)):
        raise click.UsageError("至少提供 --mental / --dplan / --vplan 之一")

    mental = json.loads(mental_path.read_text(encoding="utf-8")) if mental_path else None
    dplan = json.loads(dplan_path.read_text(encoding="utf-8")) if dplan_path else None
    vplan = None
    if vplan_path:
        if vplan_path.is_dir():
            from src.mental_ir_plane.vplan.source import load_project

            vplan = load_project(vplan_path)
        else:
            vplan = json.loads(vplan_path.read_text(encoding="utf-8"))

    artifacts = []
    if mental_path:
        artifacts.append(("mental", str(mental_path), mental))
    if dplan_path:
        artifacts.append(("dplan", str(dplan_path), dplan))
    if vplan_path:
        artifacts.append(("vplan", str(vplan_path), vplan))

    ir = build_unified_ir(project_id=project_id, top_module=top_module,
                          mental=mental, dplan=dplan, vplan=vplan,
                          artifacts=artifacts, mode=mode)
    write_unified(ir, out_path)
    if views_out:
        Path(views_out).parent.mkdir(parents=True, exist_ok=True)
        Path(views_out).write_text(
            json.dumps(views(ir), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = ir.summary()
    summary["path"] = str(out_path)
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✓ 统一 IR[/green] {ir.project.project_id} → {out_path}")
    console.print(f"  mode={ir.mode}  entities={summary['entities']}")
    console.print(f"  relations={summary['relations']} "
                  f"(candidate={summary['candidate_relations']}) "
                  f"issues={summary['issues']} blocking={summary['blocking_issues']}")
    console.print(f"  semantic_digest={summary['semantic_digest'][:16]}…")


@mental_group.group("dplan")
def dplan_group():
    """DPlan IR（设计/模型契约）。"""


@dplan_group.command("check")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "-j", "json_output", is_flag=True)
def dplan_check(path, json_output):
    """加载并检查 DPlan IR 的结构缺口（不补内容）。"""
    from src.mental_ir_plane.dplan import load_dplan, validate

    plan = load_dplan(path)
    report = validate(plan)
    if json_output:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]DPlan IR[/green] {plan.design_name or '（无 design_name）'}")
    console.print(f"  status={report['status']}  counts={report['counts']}")
    console.print(f"  digest={report['digest'][:16]}…")
    for item in report["issues"]:
        console.print(f"  [{item['severity']}] {item['kind']}: {item['message']}")


@dplan_group.command("normalize")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False, path_type=Path))
def dplan_normalize(path, out_path):
    """原始 DPlan JSON → 稳定 `dplan_ir_v1`（保留 extra / embedded_vplan）。"""
    from src.mental_ir_plane.dplan import load_dplan, write_dplan

    plan = load_dplan(path)
    write_dplan(plan, out_path)
    console.print(f"[green]✓ DPlan IR[/green] {plan.design_name} → {out_path}")
    console.print(f"  counts={plan.counts()}  digest={plan.digest()[:16]}…")


__all__ = ["mental_group"]


@mental_group.command("chat")
@click.argument("prompt")
@click.option("--workspace", default=None, help="项目工作区（默认当前目录）")
@click.option("--session", "session_id", default=None, help="沿用既有 session")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def mental_chat(prompt, workspace, session_id, json_output):
    """与 Mental Model 对话（与 GUI 同一份模式配置）。"""
    from src.workbench.modes.agent_chat import chat_and_render

    chat_and_render("mental_model", prompt, workspace=workspace, session_id=session_id, json_output=json_output)
