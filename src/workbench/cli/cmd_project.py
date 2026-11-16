"""项目管理命令 —— 全部走 ChipStack 五层工程目录架构。

`project init` 一次建出 L2 输入 / L3 配置 / L4 产物根 / L5 工作流目录；
`status` / `layout` / `check` / `runs` 只读地查看同一份 `ProjectLayout`。
不再生成 `output_<user>_<ts>` 那种游离于架构之外的目录。
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import click

from src.workbench.cli.commands import (
    _get_git_info, cli, console, get_output_adapter,
)
from src.workbench.cli.layout_output import (
    dump_json, layer_lines, load_layout, print_agents, print_checks,
    print_layers, print_runs, summary_payload,
)


def _root_option(func):
    return click.option("--root", default=".", show_default=True,
                        help="DESIGN_ROOT（默认当前目录）")(func)


def _artifact_option(func):
    return click.option("--artifact-root", default="",
                        help="产物根（默认读 cli_config.yaml，否则 chipstack_artifacts/）")(func)


@cli.group()
def project():
    """项目管理（ChipStack 工程目录架构）"""
    pass


@project.command("init")
@click.argument("name")
@click.option("--dir", "directory", default=".", show_default=True,
              help="父目录；NAME 为绝对路径时忽略")
@click.option("--top", default="", help="顶层 module 名（默认与 NAME 相同）")
@click.option("--template", "-t", default="default",
              type=click.Choice(["default", "uart", "alu", "axi"]),
              help="输入模板")
@click.option("--artifact-root", default="",
              help="产物根（默认 chipstack_artifacts/）")
@click.option("--force", is_flag=True, help="目录已存在时补齐缺失文件")
def project_init(name, directory, top, template, artifact_root, force):
    """创建 ChipStack 工程目录（L2 输入 / L3 配置 / L4 产物 / L5 工作流）

    \b
    示例:
      vagent project init sync_fifo --top sync_fifo
      vagent project init sync_fifo -t uart --dir D:/work
      vagent project init . --top sync_fifo --force     # 就地初始化当前目录
    """
    target = Path(name).expanduser()
    if not target.is_absolute():
        target = Path(directory).expanduser() / target
    target = target.resolve()

    if target.exists():
        non_empty = any(target.iterdir())
        if non_empty and not force:
            console.print(f"[red]目录已存在且非空：{target}[/red]")
            console.print("[dim]用 --force 补齐缺失文件（不覆盖已有输入）。[/dim]")
            sys.exit(1)

    layout = load_layout(target, artifact_root or None)
    scaffolded = layout.scaffold(
        name=name if name not in ("", ".") else target.name,
        top=top or target.name,
        template=template,
        artifact_root=artifact_root,
    )
    console.print(f"[green]ChipStack 工程已生成：{scaffolded.design_root}[/green]")
    console.print(f"[dim]产物根：{scaffolded.artifact_root}[/dim]")
    print_layers(scaffolded)
    console.print(
        "\n[dim]下一步：把 spec 放进 spec/、RTL 放进 rtl/，然后 "
        f"`cd {scaffolded.design_root} && vagent workspace new-run {scaffolded.top_module}`[/dim]")


@project.command("status")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
@_root_option
@_artifact_option
def project_status(json_output, root, artifact_root):
    """当前工程状态（分层、验收、最近运行）"""
    layout = load_layout(root, artifact_root or None)
    if json_output:
        click.echo(dump_json(summary_payload(layout)))
        return
    print_layers(layout)
    print_checks(layout)
    print_runs(layout)


@project.command("info")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
@_root_option
@_artifact_option
def project_info(json_output, root, artifact_root):
    """工程详细信息（目录、配置、git、spec）"""
    layout = load_layout(root, artifact_root or None)
    info = {
        "name": layout.design_root.name,
        "path": str(layout.design_root),
        "artifact_root": str(layout.artifact_root),
        "top_module": layout.top_module,
        "config": layout.config,
        "git": _get_git_info(layout.design_root),
        "specs": [
            {"path": str(p.relative_to(layout.design_root)), "size": p.stat().st_size}
            for p in sorted((layout.design_root / "spec").rglob("*"))
            if p.is_file()
        ] if (layout.design_root / "spec").is_dir() else [],
        "runs": layout.list_runs(),
    }
    if json_output:
        click.echo(dump_json(info))
        return
    out = get_output_adapter(json_output)
    out.print_result(info, title=f"Project: {layout.design_root.name}")
    print_layers(layout)


@project.command("layout")
@_root_option
@_artifact_option
def project_layout(root, artifact_root):
    """打印 L0–L5 五层目录树"""
    layout = load_layout(root, artifact_root or None)
    for line in layer_lines(layout):
        console.print(line)


@project.command("check")
@click.option("--strict", is_flag=True, help="WARN 也算失败")
@_root_option
@_artifact_option
def project_check(strict, root, artifact_root):
    """按 CS-DIR-REQ-001 §7 验收当前工程目录"""
    layout = load_layout(root, artifact_root or None)
    failures = print_checks(layout)
    if failures or (strict and any(
            row["status"] == "WARN" for row in layout.audit())):
        sys.exit(1)


@project.command("runs")
@_root_option
@_artifact_option
def project_runs(root, artifact_root):
    """列出 run_manifest.json 里的运行"""
    layout = load_layout(root, artifact_root or None)
    print_runs(layout)


@project.command("agents")
@click.option("--run-id", default="", help="指定 run（默认最新）")
@_root_option
@_artifact_option
def project_agents(run_id, root, artifact_root):
    """列出五个 Agent Domain 与固定产物目录"""
    layout = load_layout(root, artifact_root or None)
    print_agents(layout, run_id)


@project.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def project_list(json_output):
    """列出数据库里登记的所有项目"""
    out = get_output_adapter(json_output)
    try:
        projects = asyncio.run(_list_db_projects())
        if projects:
            rows = [[str(p["id"]), p["name"], p.get("description", ""),
                     p.get("status", "?"), p.get("created_at", "")[:19]] for p in projects]
            out.print_table(["ID", "Name", "Description", "Status", "Created"], rows, title="Projects")
        else:
            out.print_success("No projects in database. Use 'vagent project init <name>' to create one.")
    except Exception as e:
        out.print_error(f"DB access failed: {e}")


@project.command("clean")
@click.option("--yes", "-y", is_flag=True, help="不确认直接删除")
@click.option("--legacy", is_flag=True, help="同时清理旧的 output*/logs/")
@_root_option
@_artifact_option
def project_clean(yes, legacy, root, artifact_root):
    """删除产物根（L4）—— 输入与配置不受影响，可原地重跑

    \b
    示例:
      vagent project clean            # 删除 chipstack_artifacts/
      vagent project clean --legacy   # 顺带清理旧 output*/ 与 logs/
    """
    layout = load_layout(root, artifact_root or None)
    targets = []
    if layout.artifact_root.exists():
        targets.append(layout.artifact_root)
    if legacy:
        targets.extend(sorted(layout.design_root.glob("output*")))
        if (layout.design_root / "logs").exists():
            targets.append(layout.design_root / "logs")
    if not targets:
        console.print("[dim]没有可清理的产物目录[/dim]")
        return
    for target in targets:
        if not yes and not click.confirm(f"删除 {target}？", default=False):
            continue
        shutil.rmtree(target, ignore_errors=True)
        console.print(f"[green]已清理：{target}[/green]")


async def _get_db_stats() -> dict:
    try:
        from src.knowledge_plane.persistence.repository import get_dashboard_stats
        return await get_dashboard_stats()
    except Exception:
        return {}


async def _list_db_projects() -> list:
    try:
        from src.knowledge_plane.persistence.repository import list_projects
        return await list_projects()
    except Exception:
        return []


async def _trace_requirement(req_id: str):
    try:
        from src.knowledge_plane.persistence.repository import get_requirement_trace
        return await get_requirement_trace(req_id)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# vagent web — Web 服务器
# ═══════════════════════════════════════════════════════════════

@cli.command("web")
@click.option("--host", default="127.0.0.1", help="Bind address")
@click.option("--port", default=8000, help="Port")
@click.option("--reload", is_flag=True, help="Auto-reload on code changes")
def web_command(host, port, reload):
    """Web 仪表盘（已移除 —— 个人级 CLI，禁止 Web 前端）"""
    console.print("[yellow]Web 前端已移除（CLAUDE.md 规定：个人级 CLI，禁止 Web 开发）。[/yellow]")
    console.print("[dim]所有功能通过命令行接口交付：vagent verify / runs / logs / show / trend ...[/dim]")
