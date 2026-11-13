"""会话 / 运行查询命令（Phase 2.4）。

从 `src/interfaces/cli/commands.py` 拆出：dump / watch / status / history /
workflows / exp。导入本模块即注册到 `cli`。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from src.interfaces.cli.commands import (
    AGENT_ALIASES, PipelineExecutionService, VerificationCLI,
    cli, console, get_output_adapter,
)


@cli.command("dump")
@click.argument("session_id", required=False)
@click.option("--output", "-o", type=click.Path(), help="导出证据包 zip 路径")
@click.option("--list", "-l", "list_sessions_flag", is_flag=True, help="列出所有可复现的 session")
@click.option("--json", "-j", "json_output", is_flag=True, help="以 JSON 格式输出 manifest")
def dump(session_id, output, list_sessions_flag, json_output):
    """复现任一 Agent 步骤或导出签核证据包

    \b
    用法:
      vagent dump              # 列出所有可复现的 session
      vagent dump -l           # 同上
      vagent dump <session_id> # 展示该 session 的完整执行轨迹
      vagent dump <session_id> -o evidence.zip  # 导出签核证据包
    """
    from src.layers.l2_orchestration.evidence.manifest import (
        ManifestBuilder, EvidencePackager,
        build_manifest, list_sessions as list_all_sessions,
    )

    if list_sessions_flag or not session_id:
        sessions = list_all_sessions()
        if not sessions:
            console.print("[dim]No execution sessions found. Run 'vagent verify' first.[/dim]")
            return
        if json_output:
            click.echo(json.dumps(sessions, indent=2, ensure_ascii=False, default=str))
            return
        table = Table(title="SignOffAI — 可复现的执行记录")
        table.add_column("Session ID", style="cyan")
        table.add_column("Workflow")
        table.add_column("Timestamp")
        table.add_column("Source")
        for s in sessions[:20]:
            table.add_row(
                s["session_id"],
                s.get("workflow", "?"),
                s.get("timestamp", "")[:19] if s.get("timestamp") else "?",
                Path(s.get("trace_file", "")).name if s.get("trace_file") else "?",
            )
        console.print(table)
        if session_id:
            console.print(f"\n[dim]Tip: vagent dump {session_id}[/dim] 查看详情")
        return

    builder = ManifestBuilder()
    manifest = builder.build(session_id=session_id)

    if not manifest.workflow and not manifest.phases:
        console.print(f"[red]Session '{session_id}' not found or has no trace data.[/red]")
        return

    if json_output:
        console.print(builder.to_json(manifest))
        return

    if output:
        packager = EvidencePackager()
        zip_path = packager.package(manifest, Path(output))
        console.print(f"\n[bold green]签核证据包已导出[/bold green]")
        console.print(f"   文件: [cyan]{zip_path}[/cyan]")
        console.print(f"   大小: {zip_path.stat().st_size / 1024:.1f} KB")
        verify_result = packager.verify(zip_path)
        if verify_result["valid"]:
            console.print(f"   [green]✓ 完整性验证通过[/green]")
        else:
            for issue in verify_result["issues"]:
                console.print(f"   [red]✗ {issue}[/red]")
        return

    console.print(Panel.fit(
        f"[bold]Session: {manifest.session_id}[/bold]\n"
        f"Workflow: {manifest.workflow}  |  State: {manifest.state}\n"
        f"Time: {manifest.started_at[:19] if manifest.started_at else '?'} → "
        f"{manifest.completed_at[:19] if manifest.completed_at else '?'}\n"
        f"Output: {manifest.output_root}",
        title="SignOffAI — Session Dump"
    ))

    table = Table(title="Execution Trace")
    table.add_column("#", style="dim")
    table.add_column("Phase")
    table.add_column("Status")
    table.add_column("Score")
    table.add_column("Retries")
    table.add_column("Time")
    for i, p in enumerate(manifest.phases, 1):
        icon = {
            "passed": "[green]PASS[/green]", "degraded": "[yellow]DEGR[/yellow]",
            "failed": "[red]FAIL[/red]", "skipped": "[dim]SKIP[/dim]",
            "error": "[red]ERR[/red]",
        }.get(p.status, p.status)
        table.add_row(str(i), p.phase_name, icon, str(p.score), str(p.retries), f"{p.elapsed_s:.1f}s")
    console.print(table)

    console.print(f"\n[bold]Passed: {manifest.passed}/{manifest.total_phases}  "
                  f"Score: {manifest.overall_score}/100  "
                  f"Iterations: {manifest.iteration_count}[/bold]")
    console.print(f"[dim]Artifacts: {manifest.output_file_count} files  "
                  f"Evidence Hash: {manifest.evidence_hash[:16]}...[/dim]")

    if manifest.failed > 0:
        console.print(f"\n[red]⚠ {manifest.failed} failed phases:[/red]")
        for p in manifest.phases:
            if p.status in ("failed", "error") and p.error:
                console.print(f"  [red]{p.phase_name}: {p.error[:120]}[/red]")

    console.print(f"\n[dim]Tip: vagent dump {session_id} -o evidence.zip[/dim] 导出签核证据包")


# ═══════════════════════════════════════════════════════════════
# vagent watch — 实时监控流水线
# ═══════════════════════════════════════════════════════════════

@cli.command("watch")
@click.option("--run-id", "-r", help="监控指定 run_id")
@click.option("--interval", "-i", default=1, help="轮询间隔 (秒), 默认 1s")
@click.option("--follow", "-f", is_flag=True, help="持续监控直到完成")
@click.option("--compact", "-c", is_flag=True, help="紧凑模式（单行刷新）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 格式输出")
def watch(run_id, interval, follow, compact, json_output):
    """实时监控流水线执行状态

    \b
    用法:
      vagent watch              # 监控最新 running 状态的 run
      vagent watch -r <run_id>  # 监控指定 run
      vagent watch -f           # 持续监控直到完成
    """
    service = PipelineExecutionService.get_instance()

    def _find_run():
        if run_id:
            return run_id
        for rid, state in service._runs.items():
            if state.get("state") == "running":
                return rid
        runs = list(service._runs.items())
        if runs:
            return runs[-1][0]
        return None

    def _render(phase_name, status, score, elapsed):
        icons = {
            "passed": "[green]✔[/green]", "degraded": "[yellow]⚠[/yellow]",
            "failed": "[red]✘[/red]", "running": "[cyan]⏳[/cyan]",
            "skipped": "[dim]·[/dim]", "error": "[red]!![/red]",
        }
        icon = icons.get(status, "?")
        score_str = f"[dim]{score:3d}[/dim]" if score else "[dim]  -[/dim]"
        elapsed_str = f"[dim]{elapsed:5.1f}s[/dim]" if elapsed else "[dim]     -[/dim]"
        return f"  {icon} {phase_name:8s} {score_str} {elapsed_str}"

    try:
        rid = _find_run()
        if not rid:
            console.print("[yellow]No active or recent pipeline runs found.[/yellow]")
            return

        console.print(f"[bold]SignOffAI Watch — {rid}[/bold]")
        console.print(f"[dim]Interval: {interval}s | {'Follow mode' if follow else 'Snapshot'} | Ctrl+C to stop[/dim]")

        iteration = 0
        while True:
            state = service.get_run_status(rid)
            if not state:
                try:
                    from src.knowledge.persistence.repository import get_pipeline_run_by_run_id
                    state = asyncio.run(get_pipeline_run_by_run_id(rid))
                    if state:
                        state = {
                            "run_id": state.get("run_id", rid),
                            "state": state.get("state", "unknown"),
                            "phases": state.get("phases", state.get("phases_json", [])),
                            "passed": state.get("passed", 0),
                            "total": state.get("total", 0),
                        }
                except Exception:
                    pass

            if not state:
                console.print(f"[red]Run {rid} not found[/red]")
                return

            phases = state.get("phases", [])
            if isinstance(phases, str):
                try:
                    phases = json.loads(phases)
                except Exception:
                    phases = []

            if json_output:
                click.echo(json.dumps(state, indent=2, ensure_ascii=False, default=str))
                if not follow:
                    break
                time.sleep(interval)
                continue

            run_state = state.get("state", "unknown")
            state_color = {
                "running": "cyan", "completed": "green",
                "completed_with_errors": "yellow",
            }.get(run_state, "white")
            passed = state.get("passed", 0)
            total = state.get("total", len(phases))
            pct = round(passed / max(total, 1) * 100)

            if compact and iteration > 0:
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                sys.stdout.write(f"\r[{state_color}]● {run_state:20s}[/{state_color}] [{bar}] {passed}/{total} ({pct}%)  ")
                sys.stdout.flush()
            else:
                console.print(f"\n[bold {state_color}]● {run_state}[/bold {state_color}]  "
                              f"Passed: [green]{passed}[/green]/{total} ({pct}%)  "
                              f"Phases: {len(phases)}")
                if phases:
                    table = Table(show_header=False, box=None, padding=(0, 1))
                    table.add_column("icon", width=4)
                    table.add_column("phase", width=10)
                    table.add_column("score", width=6)
                    table.add_column("time", width=10)
                    for p in phases:
                        if isinstance(p, dict):
                            table.add_row(*_render(
                                p.get("name", "?"),
                                p.get("status", "unknown"),
                                p.get("score", 0),
                                p.get("time", 0),
                            ).split("  ", 3))
                    console.print(table)

            if run_state in ("completed", "completed_with_errors"):
                console.print(f"\n[bold green]Pipeline complete.[/bold green]")
                break

            iteration += 1
            if not follow:
                break
            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[dim]Watch stopped. Pipeline continues in background.[/dim]")


# ═══════════════════════════════════════════════════════════════
# vagent status
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def status(json_output):
    """查看所有 Agent 状态"""
    out = get_output_adapter(json_output)
    try:
        app = VerificationCLI()
        asyncio.run(app.initialize())
        rows = []
        for role, agent in app.registry.get_all_instances().items():
            m = agent.get_metrics()
            rows.append([
                m.get("display_name", role),
                role,
                m.get("status", "?"),
                str(m.get("tasks_completed", 0)),
                str(m.get("tasks_failed", 0)),
            ])
        out.print_table(
            ["Display Name", "Role", "Status", "Completed", "Failed"],
            rows, title="Agent Status"
        )
    except Exception as e:
        out.print_error(str(e))


# ═══════════════════════════════════════════════════════════════
# vagent history
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--limit", "-n", default=20, help="历史记录数量")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def history(limit, json_output):
    """查看最近的运行历史"""
    out = get_output_adapter(json_output)
    try:
        runs = asyncio.run(_get_history(limit))
        if not runs:
            out.print_success("No history yet. Run 'vagent verify' first.")
            return
        if json_output:
            click.echo(json.dumps(runs, indent=2, ensure_ascii=False, default=str))
        else:
            rows = [[r["run_id"][:16], r.get("workflow", "?"), r.get("state", "?"),
                     f"{r.get('passed',0)}/{r.get('total',0)}",
                     r.get("started_at", "")[:19]] for r in runs]
            out.print_table(["Run ID", "Workflow", "State", "Passed", "Started"], rows, title="Run History")
    except Exception as e:
        out.print_error(str(e))


async def _get_history(limit: int = 20) -> list:
    service = PipelineExecutionService.get_instance()
    runs = service.list_runs()[-limit:]
    result = []
    for r in runs:
        detail = service.get_run_status(r["run_id"]) or {}
        result.append({**r, **detail})
    return result


# ═══════════════════════════════════════════════════════════════
# vagent workflows
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def workflows(json_output):
    """列出七 Agent 闭环架构"""
    out = get_output_adapter(json_output)
    roles = list(AGENT_ALIASES.keys())
    info = [{"name": "closed_loop_7agents", "phases": roles, "phase_count": len(roles)}]

    if json_output:
        click.echo(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        table = Table(title="Seven-Agent Closed Loop")
        table.add_column("Architecture", style="cyan")
        table.add_column("Agents")
        table.add_column("Count")
        for w in info:
            table.add_row(w["name"], " → ".join(w["phases"]), str(w["phase_count"]))
        console.print(table)


# ═══════════════════════════════════════════════════════════════
# vagent exp — 成长层总览（debug 经验 + coverage 归因校准）
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exp(json_output):
    """查看系统"成长层"：debug 经验库 + coverage 归因校准

    \b
    示例:
      vagent exp              # 成长层总览
      vagent exp --json       # JSON 输出
    """
    out = get_output_adapter(json_output)
    from src.knowledge.debug_experience import get_debug_experience_store
    from src.knowledge.coverage_experience import get_coverage_experience_store

    dstore = get_debug_experience_store()
    cstore = get_coverage_experience_store()
    debug_stats = dstore.stats()
    reason_acc = cstore.reason_accuracy()
    action_eff = cstore.action_effectiveness()
    blacklist = cstore.get_blacklist()

    if json_output:
        click.echo(json.dumps({
            "debug_experience": debug_stats,
            "coverage_calibration": {
                "reason_accuracy": reason_acc,
                "action_effectiveness": action_eff,
                "unreachable_blacklist": blacklist,
            },
        }, indent=2, ensure_ascii=False, default=str))
        return

    console.print(f"[bold]成长层总览[/bold]")
    console.print(f"[dim]debug 经验: {debug_stats['total']} 条（可复用 {debug_stats['reusable']}）[/dim]")

    if action_eff:
        t = Table(title="决策动作成效（delta 覆盖率反馈）")
        t.add_column("动作", style="cyan")
        t.add_column("次数", justify="right")
        t.add_column("改善率", justify="right")
        t.add_column("平均 Δ覆盖", justify="right")
        for act, m in action_eff.items():
            t.add_row(act, str(m["trials"]), f"{m['improve_rate']:.0%}", f"{m['avg_delta']:+.1f}%")
        console.print(t)

    if reason_acc:
        t2 = Table(title="gap 归因准确率")
        t2.add_column("归因", style="yellow")
        t2.add_column("次数", justify="right")
        t2.add_column("改善", justify="right")
        t2.add_column("置信度", justify="right")
        for r, m in reason_acc.items():
            t2.add_row(r, str(m["trials"]), f"{m['improved']}/{m['trials']}", f"{m['confidence']:.0%}")
        console.print(t2)

    if blacklist:
        console.print(f"[yellow]unreachable 黑名单（多次 refactor 仍不涨）: {', '.join(blacklist)}[/yellow]")
    else:
        console.print("[dim]暂无 unreachable 黑名单[/dim]")


