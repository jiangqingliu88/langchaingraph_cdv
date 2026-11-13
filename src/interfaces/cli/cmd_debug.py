"""CLI 命令组：调试与交互（debug / repl）。

从 `src/interfaces/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
共享 helper 仍从 `commands` 导入，别在这里再造一份。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import sys  # noqa: F401
import time  # noqa: F401
from pathlib import Path  # noqa: F401

import click
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.interfaces.cli.output import common_options, get_output_adapter  # noqa: F401
from src.interfaces.cli.commands import (  # noqa: F401
    cli, console, AGENT_ALIASES, VerificationCLI,
)

@cli.group()
def debug():
    """调试命令组：日志查看、失败分析、交互调试"""
    pass


@debug.command("log")
@click.option("--run", "-r", "run_id", help="查看某次运行的完整日志")
@click.option("--phase", "-p", help="只看某阶段日志")
@click.option("--level", "-l", type=click.Choice(["error", "warn", "info"]), help="日志级别过滤")
@click.option("--agent", "-a", "agent_filter", help="只看某 Agent")
@click.option("--tail", "-n", default=50, help="最后 N 条")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def debug_log(run_id, phase, level, agent_filter, tail, json_output):
    """查看运行日志

    \b
    示例:
      vagent debug log --run <run_id>                    # 完整日志
      vagent debug log --run <run_id> --phase UVM        # UVM 阶段日志
      vagent debug log --run <run_id> --level error      # 只看错误
      vagent debug log --run <run_id> --agent debug_engineer  # 只看某 Agent
    """
    out = get_output_adapter(json_output)
    log_dir = Path("logs/execution")

    if not log_dir.exists():
        out.print_error("No log directory found")
        return

    entries = []
    log_files = sorted(log_dir.glob("exec_*.jsonl"), reverse=True)

    if run_id:
        session_id = run_id.replace("run_", "")
        log_files = [log_dir / f"exec_{session_id}.jsonl"]

    for lf in log_files[:5]:
        if not lf.exists():
            continue
        for line in lf.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if phase and entry.get("phase", "") != phase:
                    continue
                if agent_filter and entry.get("agent", "") != agent_filter:
                    continue
                if level and entry.get("level", "info") != level:
                    continue
                entries.append(entry)
            except Exception:
                pass

    entries = entries[-tail:]

    if json_output:
        click.echo(json.dumps(entries, indent=2, ensure_ascii=False, default=str))
    else:
        for e in entries:
            ts = e.get("timestamp", "")[:19]
            evt = e.get("event", "?")
            icon = {"pipeline_start": "▶", "pipeline_end": "■", "llm_call": "🧠",
                    "tool_call": "🔧", "file_write": "📄", "phase_start": "→",
                    "phase_end": "←"}.get(evt, "·")
            detail = str(e.get("workflow", e.get("tool", e.get("agent", ""))))[:40]
            status = e.get("status", e.get("success", ""))
            console.print(f"  [dim]{ts}[/dim] {icon} [{evt}] {detail} {status}")


@debug.command("analyze")
@click.option("--run", "-r", "run_id", help="分析某次运行的失败原因")
@click.option("--log", "-l", "log_file", type=click.Path(exists=True), help="分析仿真日志")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def debug_analyze(run_id, log_file, json_output):
    """分析失败原因（调用 debug_engineer）

    \b
    示例:
      vagent debug analyze --run <run_id>           # 分析 run 失败
      vagent debug analyze --log sim.log            # 分析仿真日志
    """
    out = get_output_adapter(json_output)

    if log_file:
        content = Path(log_file).read_text(encoding="utf-8", errors="replace")
        # Basic analysis
        error_lines = [l for l in content.split("\n") if "error" in l.lower() or "fail" in l.lower()]
        warning_lines = [l for l in content.split("\n") if "warn" in l.lower()]
        out.print_result({
            "file": log_file,
            "size": len(content),
            "error_count": len(error_lines),
            "warning_count": len(warning_lines),
            "sample_errors": error_lines[:10],
            "sample_warnings": warning_lines[:5],
        }, title="Log Analysis")
        return

    if run_id:
        service = PipelineExecutionService.get_instance()
        state = service.get_run_status(run_id)
        if not state:
            out.print_error(f"Run {run_id} not found")
            return

        failed_phases = [p for p in state.get("phases", [])
                         if p.get("status") in ("failed", "error")]
        out.print_result({
            "run_id": run_id,
            "state": state.get("state", "unknown"),
            "failed_phases": failed_phases,
            "passed": state.get("passed", 0),
            "total": state.get("total", 0),
        }, title="Failure Analysis")
        return

    out.print_error("Use --run <run_id> or --log <log_file>")


@debug.command("exp")
@click.option("--distill", is_flag=True, help="只显示可蒸馏成规则的成熟经验（成功≥3次且置信≥80%）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def debug_exp(distill, json_output):
    """查看 debug 经验库（错误指纹 → 已验证修复）

    \b
    示例:
      vagent debug exp              # 列出全部经验
      vagent debug exp --distill    # 只看成熟可蒸馏的经验
      vagent debug exp --json       # JSON 输出
    """
    out = get_output_adapter(json_output)
    from src.knowledge.debug_experience import get_debug_experience_store
    store = get_debug_experience_store()
    entries = store.distill_candidates() if distill else store.list_all()
    stats = store.stats()

    if json_output:
        click.echo(json.dumps({"stats": stats, "entries": entries},
                              indent=2, ensure_ascii=False, default=str))
        return

    if not entries:
        console.print(
            f"[dim]经验库为空（共 {stats['total']} 条）。跑一次带失败的验证后，"
            f"debug 会自动积累经验。[/dim]")
        return

    table = Table(title=f"Debug 经验库 — 共 {stats['total']} 条（可复用 {stats['reusable']}）")
    table.add_column("指纹", style="cyan", no_wrap=True)
    table.add_column("分类", style="yellow")
    table.add_column("修复", style="green")
    table.add_column("成功/失败", justify="right")
    table.add_column("置信度", justify="right")
    for e in entries:
        table.add_row(
            e["fingerprint"][:12],
            e["category"],
            (e["fix_name"] or e["root_cause"] or "—")[:30],
            f"{e['success_count']}/{e['fail_count']}",
            f"{e['confidence']:.0%}",
        )
    console.print(table)


@debug.command("repl")
@click.option("--agent", "-a", "agent_alias", help="进入指定 Agent 的调试模式")
def debug_repl(agent_alias):
    """交互式调试控制台

    \b
    示例:
      vagent debug repl                           # 通用 REPL
      vagent debug repl --agent spec              # 指定 Agent 的调试模式
    """
    console.print("[bold cyan]SignOffAI Debug REPL[/bold cyan]")
    console.print(f"Agents: {', '.join(AGENT_ALIASES.keys())}")
    console.print("Commands: [yellow]agents[/yellow] | [yellow]tools[/yellow] <agent> | "
                   "[yellow]<agent>[/yellow] [input] | [yellow]exec[/yellow] <agent> <tool> | "
                   "[yellow]ctx[/yellow] | [yellow]quit[/yellow]")
    app = VerificationCLI()
    asyncio.run(app.initialize())

    ctx = {"input": "", "output": "", "last_agent": None}

    while True:
        try:
            raw = console.input("[cyan]vagent>[/cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd in ("quit", "exit", "q"):
            break

        if cmd == "help":
            console.print("[bold]Commands:[/bold]")
            console.print("  [yellow]agents[/yellow]              — 列出所有 Agent 及状态")
            console.print("  [yellow]tools[/yellow] <agent>       — 列出 Agent 的所有 Tool")
            console.print("  [yellow]<agent>[/yellow] [input]     — 执行 Agent（LLM），input 可选")
            console.print("  [yellow]exec[/yellow] <agent> <tool> — 直接调用 Tool 函数")
            console.print("  [yellow]ctx[/yellow]                 — 显示当前上下文")
            console.print("  [yellow]quit[/yellow]                — 退出")
            continue

        if cmd == "ctx":
            console.print(Panel(
                f"[bold]input[/bold]: {str(ctx['input'])[:200]}\n"
                f"[bold]output[/bold]: {str(ctx['output'])[:300]}\n"
                f"[bold]last_agent[/bold]: {ctx['last_agent']}",
                title="Context"
            ))
            continue

        if cmd in ("agents", "ls"):
            table = Table(title="Registered Agents")
            table.add_column("Alias", style="cyan")
            table.add_column("Role")
            table.add_column("Display Name")
            table.add_column("Tools")
            for alias, role in AGENT_ALIASES.items():
                inst = app.registry.get_agent_instance(role)
                if inst:
                    tool_names = [getattr(t, "name", str(t)) for t in (inst.tools or [])]
                    table.add_row(alias, role, inst.display_name, ", ".join(tool_names[:4]))
            console.print(table)
            continue

        if cmd == "tools":
            if not args:
                console.print("[red]Usage: tools <agent_alias>[/red]")
                continue
            alias = args[0].lower()
            role = alias
            inst = app.registry.get_agent_instance(role)
            if not inst:
                console.print(f"[red]Agent '{alias}' not found[/red]")
                continue
            table = Table(title=f"Tools: {inst.display_name} ({alias})")
            table.add_column("Name", style="yellow")
            table.add_column("Type")
            for t in (inst.tools or []):
                tname = getattr(t, "name", str(t))
                ttype = type(t).__name__
                table.add_row(tname, ttype)
            console.print(table)
            continue

        if cmd == "exec":
            if len(args) < 2:
                console.print("[red]Usage: exec <agent_alias> <tool_name>[/red]")
                continue
            alias = args[0].lower()
            tool_name = args[1]
            tool_args = " ".join(args[2:]) if len(args) > 2 else "{}"
            role = alias
            inst = app.registry.get_agent_instance(role)
            if not inst:
                console.print(f"[red]Agent '{alias}' not found[/red]")
                continue
            target_tool = None
            for t in (inst.tools or []):
                if getattr(t, "name", "") == tool_name:
                    target_tool = t
                    break
            if not target_tool:
                console.print(f"[red]Tool '{tool_name}' not found[/red]")
                continue
            try:
                func = getattr(target_tool, "func", None) or target_tool
                if callable(func):
                    result = func(tool_args)
                else:
                    result = str(target_tool)
                console.print(Panel(str(result)[:2000], title=f"[yellow]{tool_name}[/yellow] ({alias})"))
            except Exception as e:
                console.print(f"[red]Tool error: {e}[/red]")
            continue

        # Agent execution
        alias = cmd
        role = alias
        inst = app.registry.get_agent_instance(role)
        if not inst:
            console.print(f"[red]Unknown command/agent: {cmd}[/red] (try [yellow]help[/yellow])")
            continue

        agent_input = " ".join(args) if args else (ctx.get("output") or ctx.get("input") or "")
        if not agent_input:
            agent_input = console.input(f"  input for [cyan]{alias}[/cyan]: ").strip()
        if not agent_input:
            console.print("[red]No input provided[/red]")
            continue

        console.print(f"  [{alias}] running (LLM)...")
        start = time.time()
        try:
            r = asyncio.run(inst.execute_task({"input": agent_input}))
            elapsed = time.time() - start
            if r.success:
                output = str(r.data.get("output", ""))
                console.print(f"  [green]OK[/green] ({elapsed:.1f}s)")
                console.print(Panel(output[:1500], title=f"{alias} output"))
                ctx["output"] = output
                ctx["input"] = agent_input
                ctx["last_agent"] = alias
            else:
                console.print(f"  [red]FAIL[/red] ({elapsed:.1f}s)")
                console.print(f"  [red]{r.error[:800] if r.error else 'unknown error'}[/red]")
        except Exception as e:
            console.print(f"  [red]EXCEPTION: {e}[/red]")

    console.print("[dim]Bye[/dim]")


@cli.command(hidden=True)
def repl():
    """向后兼容: 使用 vagent debug repl"""
    console.print("[dim]Note: 'vagent repl' is deprecated. Use 'vagent debug repl' instead.[/dim]")
    ctx = click.Context(debug_repl)
    debug_repl.invoke(ctx)
