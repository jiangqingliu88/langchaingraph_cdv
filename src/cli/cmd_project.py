"""项目管理命令（Phase 2.4）。

从 `src/cli/commands.py` 拆出：project init/status/info/list/clean + web。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import click

from src.cli.commands import (
    PipelineExecutionService, _get_git_info, cli, console, get_output_adapter,
)


@cli.group()
def project():
    """项目管理"""
    pass


@project.command("init")
@click.argument("name")
@click.option("--template", "-t", default="default",
              type=click.Choice(["default", "uart", "axi", "alu"]),
              help="项目模板")
def project_init(name, template):
    """创建新项目目录结构

    \b
    示例:
      vagent project init my_project                      # 默认模板
      vagent project init my_project --template uart      # UART 模板
      vagent project init my_project --template axi       # AXI 模板
    """
    project_dir = Path(name)
    if project_dir.exists():
        console.print(f"[red]Directory '{name}' already exists[/red]")
        return

    # Create directory structure
    from src.layers.l1_infrastructure.output_config import make_output_root
    project_output = make_output_root()
    dirs = [
        "specs", project_output, "logs",
        f"{project_output}/docs/de", f"{project_output}/docs/dv",
        "src/rtl", "src/tb", "src/executors",
    ]
    for d in dirs:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # Create default files
    (project_dir / "README.md").write_text(
        f"# {name}\n\nSignOffAI Project — Created with template: {template}\n", encoding="utf-8"
    )
    (project_dir / ".gitignore").write_text(
        "output_*/\noutput/\nlogs/\n*.pyc\n__pycache__/\n.env\n*.db\n", encoding="utf-8"
    )
    (project_dir / "valiflow.md").write_text(
        "---\nproject: " + name + "\n---\n\n## constraints\n\n## fi_profile\n\n## known_issues\n",
        encoding="utf-8"
    )

    # Template-specific files
    if template == "uart":
        (project_dir / "specs" / "uart_spec.md").write_text(
            "# UART Specification\n\n## Features\n- 8-N-1 configuration\n- Baud rate: 115200\n"
            "## Interfaces\n- NAME: uart_rx, TYPE: input, WIDTH: 1\n- NAME: uart_tx, TYPE: output, WIDTH: 1\n",
            encoding="utf-8"
        )
    elif template == "alu":
        (project_dir / "specs" / "alu_spec.md").write_text(
            "# ALU Specification\n\n## Features\n- Arithmetic: ADD, SUB, MUL\n- Logic: AND, OR, XOR\n"
            "## Interfaces\n- NAME: clk, TYPE: input, WIDTH: 1\n- NAME: rst_n, TYPE: input, WIDTH: 1\n",
            encoding="utf-8"
        )

    console.print(f"[green]Project '{name}' created with template '{template}'[/green]")
    console.print(f"[dim]Directory: {project_dir.absolute()}[/dim]")
    console.print(f"[dim]Next: cd {name} && vagent init && vagent verify specs/*.md[/dim]")


@project.command("status")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def project_status(json_output):
    """当前项目状态概览"""
    out = get_output_adapter(json_output)
    cwd = Path.cwd()

    status_info = {
        "directory": str(cwd),
        "has_output": bool(list(cwd.glob("output_*")) or (cwd / "output").exists()),
        "has_logs": (cwd / "logs").exists(),
        "has_specs": list((cwd / "specs").glob("*.md")) if (cwd / "specs").exists() else [],
        "has_valiflow": (cwd / "valiflow.md").exists(),
        "has_env": (cwd / ".env").exists(),
    }

    # List recent runs
    service = PipelineExecutionService.get_instance()
    runs = service.list_runs()[-5:]
    status_info["recent_runs"] = runs

    out.print_result(status_info, title="Project Status")


@project.command("info")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def project_info(json_output):
    """项目详细信息"""
    out = get_output_adapter(json_output)
    cwd = Path.cwd()

    info = {
        "name": cwd.name,
        "path": str(cwd.absolute()),
        "git": _get_git_info(cwd),
        "specs": [],
        "runs_count": 0,
    }

    specs_dir = cwd / "specs"
    if specs_dir.exists():
        for f in specs_dir.rglob("*.md"):
            info["specs"].append({
                "path": str(f.relative_to(cwd)),
                "size": f.stat().st_size,
            })

    service = PipelineExecutionService.get_instance()
    info["runs_count"] = len(service.list_runs())

    # DB stats
    try:
        stats = asyncio.run(_get_db_stats())
        info["db_stats"] = stats
    except Exception:
        pass

    out.print_result(info, title=f"Project: {cwd.name}")


@project.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def project_list(json_output):
    """列出所有项目"""
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
@click.option("--all", "clean_all", is_flag=True, help="清理所有（含日志）")
def project_clean(clean_all):
    """清理输出目录

    \b
    示例:
      vagent project clean              # 清理 output/
      vagent project clean --all        # 清理 output/ + logs/
    """
    cwd = Path.cwd()
    import shutil
    # 清理所有 output_ 前缀的目录（含旧 output/ 目录）
    removed_any = False
    for pattern in ["output"] + sorted(cwd.glob("output_*")):
        target = cwd / pattern if isinstance(pattern, str) else pattern
        if target.exists():
            shutil.rmtree(target)
            console.print(f"[green]Cleaned: {target.name}/[/green]")
            removed_any = True
    if clean_all and (logs := cwd / "logs").exists():
        shutil.rmtree(logs)
        console.print(f"[green]Cleaned: logs/[/green]")
        removed_any = True
    if not removed_any:
        console.print("[dim]No output directories found[/dim]")


async def _get_db_stats() -> dict:
    try:
        from src.layers.l4_memory.persistence.repository import get_dashboard_stats
        return await get_dashboard_stats()
    except Exception:
        return {}


async def _list_db_projects() -> list:
    try:
        from src.layers.l4_memory.persistence.repository import list_projects
        return await list_projects()
    except Exception:
        return []


async def _trace_requirement(req_id: str):
    try:
        from src.layers.l4_memory.persistence.repository import get_requirement_trace
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

