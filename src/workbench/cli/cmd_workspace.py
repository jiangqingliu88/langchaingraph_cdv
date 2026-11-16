"""工作区命令 —— ChipStack L4/L5 目录的显式操作入口。

`project` 管工程（L2/L3）的建立与验收；`workspace` 管一次运行（L4）的目录、
manifest、CLI 日志、agent 产物与归档。两者共用同一份 `ProjectLayout`。
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from src.workbench.cli.commands import cli, console
from src.workbench.cli.layout_output import (
    dump_json, layer_lines, load_layout, print_agents, print_checks,
    print_layers, print_runs,
)


@cli.group()
def workspace():
    """工作区（run 目录 / manifest / 日志 / agent 产物 / 归档）"""
    pass


@workspace.command("init")
@click.option("--name", default="", help="设计名（默认当前目录名）")
@click.option("--top", default="", help="顶层 module 名")
@click.option("--template", "-t", default="default",
              type=click.Choice(["default", "uart", "alu", "axi"]))
@click.option("--artifact-root", default="", help="产物根")
@click.option("--force", is_flag=True, help="目录非空时补齐缺失文件")
def workspace_init(name, top, template, artifact_root, force):
    """在当前目录建立 ChipStack 工程目录（L2/L3/L4/L5）"""
    target = Path.cwd().resolve()
    if any(target.iterdir()) and not force:
        console.print(f"[yellow]{target} 不是空目录；用 --force 补齐缺失文件。[/yellow]")
    layout = load_layout(target, artifact_root or None)
    layout.scaffold(name=name or target.name, top=top or target.name,
                    template=template, artifact_root=artifact_root)
    console.print(f"[green]工程目录就绪：{layout.design_root}[/green]")
    print_layers(layout)


@workspace.command("show")
@click.option("--json", "-j", "json_output", is_flag=True)
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_show(json_output, root, artifact_root):
    """显示 L0–L5 目录树"""
    layout = load_layout(root, artifact_root or None)
    if json_output:
        click.echo(dump_json(layout.summary()))
        return
    for line in layer_lines(layout):
        console.print(line)


@workspace.command("check")
@click.option("--strict", is_flag=True, help="WARN 也算失败")
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_check(strict, root, artifact_root):
    """验收清单（CS-DIR-REQ-001 §7）"""
    layout = load_layout(root, artifact_root or None)
    failures = print_checks(layout)
    if failures or (strict and any(row["status"] == "WARN" for row in layout.audit())):
        sys.exit(1)


@workspace.command("new-run")
@click.argument("top", required=False)
@click.option("--run-id", default="", help="自定义 RUN_ID（默认 UTC 时间戳）")
@click.option("--scope", default="run", type=click.Choice(["run", "streamlined"]),
              help="run 级隔离目录或按设计聚合目录")
@click.option("--entrypoint", default="vagent workspace new-run")
@click.option("--agents", default="", help="逗号分隔的 agent id（写入 manifest）")
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_new_run(top, run_id, scope, entrypoint, agents, root, artifact_root):
    """新建一次运行的目录契约（<top>-<run_id>/）"""
    layout = load_layout(root, artifact_root or None)
    if not layout.config and not layout.design_root.is_dir():
        console.print("[red]当前目录不是工程根；先运行 `vagent workspace init`。[/red]")
        sys.exit(1)
    invoked = [a.strip() for a in agents.split(",") if a.strip()]
    run = layout.create_run(top or layout.top_module or layout.design_root.name,
                            run_id=run_id or None, scope=scope,
                            entrypoint=entrypoint, agents=invoked)
    run.log_cli(["vagent", "workspace", "new-run", top or ""],
                note=f"scope={scope}")
    console.print(f"[green]run 已创建：{run.root}[/green]")
    console.print(f"[dim]manifest：{run.manifest_path}[/dim]")
    console.print(f"[dim]CLI 日志：{layout.cli_logs_dir}[/dim]")
    console.print("[dim]agent 产物目录会按 R-020 在 agent 首次登记时创建。[/dim]")


@workspace.command("runs")
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_runs(root, artifact_root):
    """列出运行索引"""
    print_runs(load_layout(root, artifact_root or None))


@workspace.command("agents")
@click.option("--run-id", default="")
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_agents(run_id, root, artifact_root):
    """五个 Agent Domain 的产物目录状态"""
    print_agents(load_layout(root, artifact_root or None), run_id)


@workspace.command("log")
@click.option("--run-id", default="", help="默认最新 run")
@click.option("--note", default="", help="日志备注")
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_log(run_id, note, root, artifact_root):
    """为一次 CLI 调用落 `cli_logs/cli_YYYYMMDD-HHMMSS.log`"""
    layout = load_layout(root, artifact_root or None)
    run = _latest_run(layout, run_id)
    if run is None:
        console.print("[red]没有可用的 run；先 `workspace new-run`。[/red]")
        sys.exit(1)
    path = run.log_cli(["vagent", "workspace", "log"], note=note)
    console.print(f"[green]已写入：{path}[/green]")


@workspace.command("archive")
@click.argument("agent")
@click.option("--run-id", default="", help="默认最新 run")
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_archive(agent, run_id, root, artifact_root):
    """把 agent 目录归档为 `<design>.<agent>.<timestamp>`"""
    from src.agent_plane.domains import agent_spec

    layout = load_layout(root, artifact_root or None)
    run = _latest_run(layout, run_id)
    if run is None:
        console.print("[red]没有可用的 run。[/red]")
        sys.exit(1)
    try:
        spec = agent_spec(agent)
    except KeyError:
        console.print(f"[red]未登记的 agent：{agent}[/red]")
        sys.exit(1)
    target = run.archive_agent(spec.agent_id)
    if target is None:
        console.print(f"[yellow]{spec.agent_id} 在 {run.root} 下还没有产物目录。[/yellow]")
        sys.exit(1)
    console.print(f"[green]已归档：{target}[/green]")


@workspace.command("backup")
@click.argument("paths", nargs=-1, required=True)
@click.option("--reason", default="", help="备份原因（写入 backup_manifest.json）")
@click.option("--run-id", default="", help="默认最新 run")
@click.option("--root", default=".")
@click.option("--artifact-root", default="")
def workspace_backup(paths, reason, run_id, root, artifact_root):
    """修改 RTL 前留 backup/（R-025）；路径相对 DESIGN_ROOT"""
    layout = load_layout(root, artifact_root or None)
    run = _latest_run(layout, run_id)
    if run is None:
        console.print("[red]没有可用的 run；先 `workspace new-run`。[/red]")
        sys.exit(1)
    target = run.backup(paths, reason=reason)
    if target is None:
        console.print("[yellow]没有找到可备份的文件。[/yellow]")
        sys.exit(1)
    console.print(f"[green]备份完成：{target}[/green]")


def _latest_run(layout, run_id: str):
    runs = layout.list_runs()
    if run_id:
        for row in runs:
            if str(row.get("run_id") or "") == run_id:
                return layout.open_run(run_id, row.get("top_module"),
                                       scope=str(row.get("scope") or "run"))
        return None
    if not runs:
        return None
    row = runs[-1]
    return layout.open_run(str(row.get("run_id")), row.get("top_module"),
                           scope=str(row.get("scope") or "run"))
