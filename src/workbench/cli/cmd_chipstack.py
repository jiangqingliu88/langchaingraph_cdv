"""ChipStack 2.0 CLI 对齐入口。

提供手册中的命令名与 TUI/setup/skills 入口；真实执行仍复用既有 Agent /
Harness / Engine。没有 Cadence 专有后端时明确返回 NOT_IMPLEMENTED / NOT_RUN，
不补造结果。
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.chipstack_compat import (
    GUIDE_TUI_MODES,
    build_artifact_review_html,
    install_skills,
    seed_skills,
)
from src.workbench.cli.commands import cli, console
from src.workbench.modes.agent_chat import chat_and_render


def _json_echo(value) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _not_implemented(what: str, reason: str) -> None:
    console.print(f"[yellow]NOT_IMPLEMENTED[/yellow] {what}")
    console.print(f"[dim]{reason}[/dim]")
    raise SystemExit(2)


def _chat_options(fn):
    fn = click.argument("prompt")(fn)
    fn = click.option("--workspace", default=None, help="项目工作区（默认当前目录）")(fn)
    fn = click.option("--session", "session_id", default=None, help="沿用既有 session")(fn)
    fn = click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")(fn)
    return fn


def _chat_group(name: str, preset_id: str, help_text: str) -> click.Group:
    @click.group(name=name, help=help_text)
    def _group():
        pass

    @_group.command("chat")
    @_chat_options
    def _chat(prompt, workspace, session_id, json_output):
        """与该 agent 对话一轮。"""
        chat_and_render(preset_id, prompt, workspace=workspace,
                        session_id=session_id, json_output=json_output)

    return _group


def _existing_group(name: str) -> click.Group | None:
    group = cli.commands.get(name)
    return group if isinstance(group, click.Group) else None


# ════════════════════════════════════════════════════════════════
# 各 Agent 的 ChipStack 命令名
# ════════════════════════════════════════════════════════════════

def _mental_generate():
    @click.command("generate")
    @click.option("--spec", "spec_path", required=True, type=click.Path(exists=True, dir_okay=False))
    @click.option("--module", required=True)
    @click.option("--out", "output_dir", default=".", type=click.Path(file_okay=False))
    @click.option("--inconsistency-analysis", is_flag=True,
                  help="请求 RTL/Spec 一致性检查（当前实现会明确报告 NOT_IMPLEMENTED）")
    def _cmd(spec_path, module, output_dir, inconsistency_analysis):
        """从 spec 生成 Mental Model IR。"""
        from src.agent_plane.design_understanding.mental_model_agent.main import run

        spec_text = Path(spec_path).read_text(encoding="utf-8", errors="replace")
        result = run(spec_text, output_dir, module=module, spec_path=str(spec_path))
        _json_echo(result)
        if inconsistency_analysis:
            console.print("[yellow]--inconsistency-analysis 尚未接入；"
                          "RTL/Spec 一致性检查保持 NOT_RUN。[/yellow]")
    return _cmd


_mental = _existing_group("mental-model")
if _mental is not None:
    _mental.add_command(_mental_generate())


_simulation = _chat_group("simulation-agent", "unit_testing",
                          "Unit Testing / simulation-agent（纯 SV TB）")


@_simulation.command("run")
@click.option("--rtl", "rtl_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--module", default="")
@click.option("--out", "output_dir", default=".", type=click.Path(file_okay=False))
@click.option("--no-compile", is_flag=True)
@click.option("--no-simulate", is_flag=True)
def _simulation_run(rtl_path, module, output_dir, no_compile, no_simulate):
    """生成 TB → 编译 → 运行 → report（无 EDA 时如实 SKIPPED）。"""
    from src.agent_plane.design_verification.simulation_agent.main import run

    _json_echo(run(rtl_path, output_dir, module=module,
                   compile=not no_compile, simulate=not no_simulate))


cli.add_command(_simulation)

_formal = _chat_group("formal-agent", "formal", "Formal Agent")


@_formal.command("plan")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--module", required=True)
@click.option("--out", "output_dir", default=".", type=click.Path(file_okay=False))
def _formal_plan(spec_path, module, output_dir):
    """生成 FormalPlan（性质/假设/证明义务；engine.ran=false）。"""
    from src.agent_plane.verification.formal_agent.main import run

    spec_text = Path(spec_path).read_text(encoding="utf-8", errors="replace")
    _json_echo(run(spec_text, output_dir, module=module, spec_path=str(spec_path)))


@_formal.command("launch-full-flow")
@click.option("--spec", "spec_path", required=True)
@click.option("--module", required=True)
@click.option("--out", "output_dir", default=".")
@click.option("--formal-flow-mode", default="streamlined")
def _formal_full(spec_path, module, output_dir, formal_flow_mode):
    """Jasper/TCL 全流程（本仓库未内置形式引擎）。"""
    _not_implemented(
        "formal-agent launch-full-flow",
        "本仓库没有 JasperGold / TCL / proof 后端；请使用 `formal-agent plan` 生成 "
        "FormalPlan，或接入真实引擎后改写 engine.ran。"
        f"（formal_flow_mode={formal_flow_mode}）",
    )


cli.add_command(_formal)

_coverage = _chat_group("functional-coverage-agent", "functional_coverage",
                        "Functional Coverage Agent")


@_coverage.command("launch-full-flow")
@click.option("--rtl", "rtl_path", required=True)
@click.option("--module", required=True)
@click.option("--out", "output_dir", default=".")
def _coverage_full(rtl_path, module, output_dir):
    _not_implemented(
        "functional-coverage-agent launch-full-flow",
        "covergroup 生成与 Jasper 不可达删除尚未接入；当前只有 chat/只读工具。",
    )


cli.add_command(_coverage)

_uvm = _chat_group("uvm-agentic-flow", "uvm", "UVM Test Plan + Coding Agent")


@_uvm.command("generate")
@click.option("--spec", "spec_path", required=True)
@click.option("--out", "output_dir", default=".")
def _uvm_generate(spec_path, output_dir):
    _not_implemented(
        "uvm-agentic-flow generate",
        "UVm testplan/UVM coding 全流程尚未接入；请使用 `uvm-agentic-flow chat` 或 "
        "既有 `vagent uvm` 入口。",
    )


cli.add_command(_uvm)

_debug = _chat_group("dv-debug-agent", "debug", "DV Debug Agent")


@_debug.command("auto-debug")
@click.option("--simulation-db-path", required=True,
              type=click.Path(exists=True, file_okay=False))
def _auto_debug(simulation_db_path):
    _not_implemented(
        "dv-debug-agent auto-debug",
        f"Verisium Debug / xcelium failure DB 后端未内置；DB={simulation_db_path}",
    )


cli.add_command(_debug)

_lint = click.Group("lint-autofix-agent", help="Lint AutoFix（SuperLint 未内置）")


@_lint.command("run")
@click.option("--rtl", "rtl_path", required=True)
@click.option("--extract-only", is_flag=True)
@click.option("--apply-unsafe", is_flag=True)
def _lint_run(rtl_path, extract_only, apply_unsafe):
    _not_implemented(
        "lint-autofix-agent run",
        "Jasper SuperLint 后端未内置；不产生真实 lint 报告，也不修改 RTL。",
    )


cli.add_command(_lint)

_early = click.Group("rtl-early-estimation", help="RTL Early Estimation（Joules 未内置）")


@_early.command("run")
@click.option("--rtl", "rtl_path", required=True)
def _early_run(rtl_path):
    _not_implemented("rtl-early-estimation run",
                     "Joules PPA 后端未内置；不生成面积/功耗/性能数值。")


cli.add_command(_early)


# ════════════════════════════════════════════════════════════════
# filelist-tools
# ════════════════════════════════════════════════════════════════

@cli.group("filelist-tools")
def filelist_tools():
    """filelist 工具。"""


@filelist_tools.command("build")
@click.option("--rtl-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False))
@click.option("--pattern", "pattern", default="*.sv,*.v,*.svh",
              help="逗号分隔的扩展名")
def _filelist_build(rtl_dir, out_path, pattern):
    """扫描 RTL 目录并写出 `.f` filelist（相对 rtl-dir）。"""
    root = Path(rtl_dir).resolve()
    suffixes = []
    for item in pattern.split(","):
        suffix = item.strip()
        if not suffix:
            continue
        if suffix.startswith("*"):
            suffix = suffix[1:]
        if not suffix.startswith("."):
            suffix = "." + suffix
        suffixes.append(suffix)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in suffixes)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(p.relative_to(root).as_posix() + "\n" for p in files),
                      encoding="utf-8")
    console.print(f"[green]{len(files)} 个文件 → {target}[/green]")


# ════════════════════════════════════════════════════════════════
# tui
# ════════════════════════════════════════════════════════════════

@cli.group("tui", invoke_without_command=True)
@click.option("--mode", type=click.Choice(GUIDE_TUI_MODES), default=None,
              help="领域模式（mental_model / formal / functional_coverage / uvm / rtl_designer / debug / workflows）")
@click.option("--session-name", default="", help="命名 TUI 会话（存 chipstack_artifacts/tui/sessions/）")
@click.pass_context
def tui(ctx, mode, session_name):
    """TUI 主窗口；与老 PySide6 GUI 并列，共用 chat/plan/verify。"""
    if ctx.invoked_subcommand is not None:
        return
    from src.workbench.tui import run_tui

    raise SystemExit(run_tui(mode=mode or "", session_name=session_name))


# ════════════════════════════════════════════════════════════════
# setup / install-skills / mcp / experimental
# ════════════════════════════════════════════════════════════════

@cli.group("setup")
def setup_group():
    """安装/维护：artifact-review-html、seed-skills。"""


def _latest_run_dir(workspace: str | None = None) -> Path:
    from src.runtime_plane.core.project_layout import ProjectLayout

    layout = ProjectLayout.discover(workspace)
    runs = layout.list_runs()
    if not runs:
        raise click.UsageError(f"{layout.artifact_root} 下没有 run_manifest.json")
    row = runs[-1]
    return layout.open_run(str(row.get("run_id")), row.get("top_module"),
                           scope=str(row.get("scope") or "run")).root


@setup_group.command("artifact-review-html")
@click.option("--run", "run_dir", default="", type=click.Path(exists=True, file_okay=False),
              help="运行目录；留空取当前工程最新 run")
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False))
@click.option("--workspace", default=None)
def _artifact_review_html(run_dir, out_path, workspace):
    """导出单文件离线产物浏览器（ARTIFACTS / MENTAL MODEL 的静态版）。"""
    source = Path(run_dir) if run_dir else _latest_run_dir(workspace)
    target = build_artifact_review_html(source, out_path)
    console.print(f"[green]已导出：{target}[/green]")


@setup_group.command("seed-skills")
@click.option("--source", default="", type=click.Path(exists=True, file_okay=False))
def _seed_skills(source):
    """把默认 skills 复制到 `$CHIPSTACK_HOME/skills`（不覆盖已有）。"""
    written = seed_skills(source=source or None)
    if not written:
        console.print("[dim]没有新增 skill（目录为空或已存在同名 skill）[/dim]")
    for path in written:
        console.print(f"[green]+ {path}[/green]")


@cli.group("install-skills")
def install_skills_group():
    """把 skills 安装到 coding agent。"""


@install_skills_group.command("claude-code")
@click.option("--project", is_flag=True, help="装到当前项目 .claude/skills")
def _install_claude(project):
    try:
        written = install_skills("claude-code", project=project)
    except Exception as exc:  # noqa: BLE001 CLI 边界给可读错误
        raise click.ClickException(str(exc)) from exc
    for path in written:
        console.print(f"[green]+ {path}[/green]")


@cli.group("mcp")
def mcp_group():
    """MCP 入口（本仓库未内置 MCP server）。"""


@mcp_group.command("run")
@click.option("--transport", type=click.Choice(["stdio", "http"]), default="stdio")
@click.option("--port", default=8100)
def _mcp_run(transport, port):
    _not_implemented("mcp run",
                     "本仓库当前没有内置 MCP server；不要启动假服务。"
                     f"（requested transport={transport}, port={port}）")


@mcp_group.command("install-skills")
@click.argument("client", default="claude-code")
def _mcp_install_skills(client):
    _not_implemented("mcp install-skills",
                     "MCP 客户端配置写入尚未实现；请用 `vagent install-skills claude-code`。")


@cli.group("experimental")
def experimental_group():
    """实验性命令（对应 2.0 手册的 --experimental）。"""


_rtlgen = _chat_group("rtl-generation", "rtl_designer", "RTL Upgrade（实验性）")
_rtlgen.command("orchestrate")(
    click.option("--rtl", "rtl_path", required=True)(
        click.option("--change-request", required=True)(
            lambda rtl_path, change_request: _not_implemented(
                "experimental rtl-generation orchestrate",
                "RTL 升级编排未接入；请使用 `rtl-generation chat` 生成候选，"
                "修改 RTL 前必须 backup。"))))
experimental_group.add_command(_rtlgen)


__all__ = ["filelist_tools", "tui", "setup_group", "install_skills_group",
           "mcp_group", "experimental_group"]
