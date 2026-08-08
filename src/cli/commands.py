import asyncio, sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
from src.core.registry import AgentRegistry
from src.agents.spec_planner import SpecAndTestPlanner
from src.agents.design_architect import DesignArchitect
from src.agents.verify_architect import VerificationArchitect
from src.agents.test_engineer import TestEngineer
from src.agents.assertion_engineer import AssertionEngineer
from src.agents.coverage_manager import CoverageManager
from src.agents.regression_manager import RegressionManager
from src.agents.debug_engineer import DebugEngineer
from src.agents.quality_assurance import QualityAssurance
from src.agents.report_generator import ReportGenerator
from src.agents.model_agent import ModelAgent
from config.settings import Settings

console = Console()

class VerificationCLI:
    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = AgentRegistry.get_instance()
        self.agent_config = {}
    def get_agent_config(self, role):
        return self.agent_config.get("agents", {}).get(role, {})
    async def initialize(self):
        agents = [
            ("spec_and_test_planner", SpecAndTestPlanner()),
            ("design_architect", DesignArchitect()),
            ("verification_architect", VerificationArchitect()),
            ("model_agent", ModelAgent()),
            ("test_engineer", TestEngineer()),
            ("assertion_engineer", AssertionEngineer()),
            ("coverage_manager", CoverageManager()),
            ("regression_manager", RegressionManager()),
            ("debug_engineer", DebugEngineer()),
            ("quality_assurance", QualityAssurance()),
            ("report_generator", ReportGenerator()),
        ]
        for role, agent in agents:
            await agent.initialize()
            self.registry.set_agent_instance(role, agent)
        console.print("[green]All 11 agents initialized[/green]")

@click.group()
def cli():
    pass

@cli.command()
def init():
    Path("output").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    console.print("[green]Initialized[/green]")

# ── vagent dump: 复现 + 导出签核证据包 ──

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
    from src.core.manifest import (
        ManifestBuilder, EvidencePackager,
        build_manifest, list_sessions as list_all_sessions,
    )

    # ── 列出 sessions ──
    if list_sessions_flag or not session_id:
        sessions = list_all_sessions()
        if not sessions:
            console.print("[dim]No execution sessions found. Run 'vagent verify' first.[/dim]")
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
            console.print(f"[dim]Tip: vagent dump {session_id} -o evidence.zip[/dim] 导出证据包")
        return

    # ── 展示 session 详情 ──
    builder = ManifestBuilder()
    manifest = builder.build(session_id=session_id)

    if not manifest.workflow and not manifest.phases:
        console.print(f"[red]Session '{session_id}' not found or has no trace data.[/red]")
        return

    # JSON 输出模式
    if json_output:
        console.print(builder.to_json(manifest))
        return

    # 导出模式
    if output:
        packager = EvidencePackager()
        zip_path = packager.package(manifest, Path(output))
        console.print(f"\n[bold green]✅ 签核证据包已导出[/bold green]")
        console.print(f"   文件: [cyan]{zip_path}[/cyan]")
        console.print(f"   大小: {zip_path.stat().st_size / 1024:.1f} KB")
        console.print(f"   Manifest: [cyan]{zip_path.with_suffix('.manifest.json')}[/cyan]")

        # 验证
        verify_result = packager.verify(zip_path)
        if verify_result["valid"]:
            console.print(f"   [green]✓ 完整性验证通过[/green]")
        else:
            for issue in verify_result["issues"]:
                console.print(f"   [red]✗ {issue}[/red]")
        return

    # ── 交互式展示 ──
    console.print(Panel.fit(
        f"[bold]Session: {manifest.session_id}[/bold]\n"
        f"Workflow: {manifest.workflow}  |  State: {manifest.state}\n"
        f"Time: {manifest.started_at[:19] if manifest.started_at else '?'} → "
        f"{manifest.completed_at[:19] if manifest.completed_at else '?'}\n"
        f"Output: {manifest.output_root}",
        title="SignOffAI — Session Dump"
    ))

    # 阶段表
    table = Table(title="Execution Trace")
    table.add_column("#", style="dim")
    table.add_column("Phase")
    table.add_column("Status")
    table.add_column("Score")
    table.add_column("Retries")
    table.add_column("Time")
    for i, p in enumerate(manifest.phases, 1):
        icon = {"passed": "[green]PASS[/green]", "degraded": "[yellow]DEGR[/yellow]",
                "failed": "[red]FAIL[/red]", "skipped": "[dim]SKIP[/dim]",
                "error": "[red]ERR[/red]"}.get(p.status, p.status)
        table.add_row(
            str(i), p.phase_name, icon,
            str(p.score), str(p.retries), f"{p.elapsed_s:.1f}s"
        )
    console.print(table)

    # 汇总
    console.print(f"\n[bold]Passed: {manifest.passed}/{manifest.total_phases}  "
                  f"Score: {manifest.overall_score}/100  "
                  f"Iterations: {manifest.iteration_count}[/bold]")

    # 产物统计
    console.print(f"[dim]Artifacts: {manifest.output_file_count} files  "
                  f"Evidence Hash: {manifest.evidence_hash[:16]}...[/dim]")

    if manifest.failed > 0:
        console.print(f"\n[red]⚠ {manifest.failed} failed phases:[/red]")
        for p in manifest.phases:
            if p.status in ("failed", "error") and p.error:
                console.print(f"  [red]{p.phase_name}: {p.error[:120]}[/red]")

    console.print(f"\n[dim]Tip: vagent dump {session_id} -o evidence.zip[/dim] 导出签核证据包")

@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
def analyze(spec_file):
    """单步分析规格文件"""
    app = VerificationCLI()
    async def run():
        await app.initialize()
        spec = Path(spec_file).read_text(encoding='utf-8')
        agent = app.registry.get_agent_instance("spec_and_test_planner")
        result = await agent.execute_task({"input": spec})
        if result.success:
            console.print(Panel(str(result.data.get("output", ""))[:1000], title="Result"))
        else:
            console.print(f"[red]{result.error}[/red]")
    asyncio.run(run())

@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
@click.option('--workflow', '-w', default='full_verification')
@click.option('--refine', is_flag=True, help='LLM refine: template foundation + LLM polish + iterative fix')
@click.option('--compile', is_flag=True, help='Run QuestaSim compile after UVM phase')
@click.option('--output', '-o', type=click.Path())
def verify(spec_file, workflow, compile, output, refine):
    """完整验证流水线 —— 每阶段实时输出"""
    from src.core.execution import PipelineExecutionService
    output_root = output or "output"
    if refine:
        console.print("[bold cyan]LLM Refine mode: template foundation + LLM polish + iterative fix[/bold cyan]")
    async def run():
        service = PipelineExecutionService.get_instance()
        spec = Path(spec_file).read_text(encoding='utf-8')

        console.print(f"[bold cyan]═══ Pipeline: {workflow} ═══[/bold cyan]")

        def progress(phase, status, msg):
            icon = {"running": ">", "passed": "+", "failed": "X", "error": "!"}.get(status, ".")
            color = {"running": "yellow", "passed": "green", "failed": "red", "error": "red"}.get(status, "")
            clean_msg = str(msg).replace("[", "(").replace("]", ")")  # avoid Rich markup conflicts
            console.print(f"  [{color}][{icon}] {phase:8s}[/{color}] {clean_msg}")

        result = await service.run_pipeline(
            spec_text=spec, workflow=workflow, output_root=output_root,
            on_progress=progress, refine=refine)

        # Build agent role map for display
        agent_info = {}
        for role, inst in service.registry.get_all_instances().items():
            agent_info[inst.role] = getattr(inst, 'produces', '') or ''
        # Map phase name → role
        from src.core.execution import FULL_PHASES
        phase_map = {p[0]: p[1] for p in FULL_PHASES}

        # Table summary
        table = Table(title=f"Results")
        table.add_column("Phase"); table.add_column("Produces"); table.add_column("Status"); table.add_column("Score"); table.add_column("Retries"); table.add_column("Time")
        for p in result["phases"]:
            st = p["status"]
            icon = "[green]PASS[/green]" if st == "passed" else ("[yellow]DEGRADED[/yellow]" if st == "degraded" else ("[red]FAIL[/red]" if st == "failed" else "[dim]SKIP[/dim]"))
            sc = str(p.get("score", "")) if p.get("score") else "-"
            rt = str(p.get("retries", 0))
            role = phase_map.get(p["name"], "")
            prod = agent_info.get(role, "-")
            table.add_row(p["name"], prod, icon, sc, rt, f"{p['time']}s")
        console.print(table)
        overall = result.get("overall_score", 0)
        ov_color = "green" if overall >= 80 else "yellow" if overall >= 50 else "red"
        console.print(f"[bold]Passed: {result['passed']}/{result['total']}  Score: [{ov_color}]{overall}/100[/{ov_color}][/bold]")
        cov = result.get("ctx", {}).get("coverage", {})
        if isinstance(cov, dict):
            rc = cov.get("_real_coverage", {})
            if rc:
                console.print(f"[cyan]Coverage: line={rc.get('line_pct',0):.1f}% branch={rc.get('branch_pct',0):.1f}% toggle={rc.get('toggle_pct',0):.1f}%[/cyan]")

        # ── 可选：UVM 后编译（通过 RegressionRunner） ──
        if compile and any(p["name"] == "UVM" and p["status"] == "passed" for p in result["phases"]):
            ctx = result["ctx"]
            console.print("\n[bold cyan]Compile Check[/bold cyan]")
            fl = ctx.get("env", {}).get("filelist", "")
            out_dir = ctx.get("env", {}).get("output_dir", "")
            if fl and Path(fl).exists():
                from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner
                runner = RegressionRunner(
                    env_output_dir=out_dir,
                    filelist=fl,
                    top_module=ctx.get("env", {}).get("env_name", "dut") + "_bench_tb_top",
                )
                rc = runner.compile()
                if rc["status"] == "PASS":
                    console.print(f"[green]Compile PASS ({rc['time_s']}s, {rc.get('errors', 0)} errors)[/green]")
                else:
                    console.print(f"[red]Compile FAIL ({rc.get('errors', 0)} errors)[/red]")
            else:
                console.print(f"[yellow]Filelist not found: {fl}[/yellow]")

    asyncio.run(run())

@cli.command()
def status():
    app = VerificationCLI()
    async def run():
        await app.initialize()
        table = Table(title="Agent Status")
        table.add_column("Agent")
        table.add_column("Status")
        for role, agent in app.registry.get_all_instances().items():
            m = agent.get_metrics()
            table.add_row(m.get("display_name", role), m.get("status", "?"))
        console.print(table)
    asyncio.run(run())

@cli.command()
def history():
    console.print("[dim]History: run vagent verify first[/dim]")

@cli.command()
@click.option('--session', '-s', help='Session ID')
def debug_log(session):
    """View agent debug logs"""
    from src.middleware.debug_logger import debug_logger
    if session:
        entries = debug_logger.get_session_log(session)
        console.print(f"[bold]Session: {session}[/bold] ({len(entries)} entries)")
        for e in entries[:20]:
            ts = e.get("timestamp", "")[:19]
            if e.get("event"):
                console.print(f"  [cyan]{ts}[/cyan] {e['event']}: {e.get('workflow','')}")
            else:
                a = e.get("agent", {})
                s = "[green]OK[/green]" if e.get("success") else "[red]FAIL[/red]"
                console.print(f"  [cyan]{ts}[/cyan] {s} {a.get('name','')}: {str(e.get('input',''))[:50]}...")
    else:
        sessions = debug_logger.list_sessions()
        if sessions:
            table = Table(title="Debug Sessions")
            table.add_column("Session ID")
            table.add_column("Size")
            for s in sessions[:10]:
                table.add_row(s["session"], f"{s['size']}B")
            console.print(table)
        else:
            console.print("[dim]No debug logs yet. Run vagent verify first.[/dim]")

@cli.command()
def workflows():
    console.print("full_verification - 7 phases")
    console.print("quick_check - 3 phases")

# ── Agent 快捷名 → role 映射 ──
AGENT_ALIASES = {
    "spec":    "spec_and_test_planner",
    "design":  "design_architect",
    "UVM":     "verification_architect",
    "model":   "model_agent",
    "test":    "test_engineer",
    "assert":  "assertion_engineer",
    "cover":   "coverage_manager",
    "regress": "regression_manager",
    "debug":   "debug_engineer",
    "qa":      "quality_assurance",
    "report":  "report_generator",
}
AGENT_HELP = ", ".join(AGENT_ALIASES.keys())


@cli.command()
def repl():
    """单 Agent 调试控制台 —— 逐个验证 Tool 代码"""
    console.print("[bold cyan]SignOffAI Agent Debug REPL[/bold cyan]")
    console.print(f"Agents: {AGENT_HELP}")
    console.print("Commands: [yellow]agents[/yellow] | [yellow]tools[/yellow] <agent> | [yellow]<agent>[/yellow] [input] | "
                   "[yellow]exec[/yellow] <agent> <tool> | [yellow]ctx[/yellow] | [yellow]quit[/yellow]")
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

        # ── quit ──
        if cmd in ('quit', 'exit', 'q'):
            break

        # ── help ──
        if cmd == 'help':
            console.print("[bold]Commands:[/bold]")
            console.print("  [yellow]agents[/yellow]              — 列出所有 Agent 及状态")
            console.print("  [yellow]tools[/yellow] <agent>       — 列出 Agent 的所有 Tool")
            console.print("  [yellow]<agent>[/yellow] [input]     — 执行 Agent（LLM），input 可选")
            console.print("  [yellow]exec[/yellow] <agent> <tool> — 直接调用 Tool 函数，查看返回值")
            console.print("  [yellow]ctx[/yellow]                 — 显示当前上下文（上一个 Agent 的输出）")
            console.print("  [yellow]quit[/yellow]                — 退出")
            continue

        # ── ctx ──
        if cmd == 'ctx':
            console.print(Panel(
                f"[bold]input[/bold]: {str(ctx['input'])[:200]}\n"
                f"[bold]output[/bold]: {str(ctx['output'])[:300]}\n"
                f"[bold]last_agent[/bold]: {ctx['last_agent']}",
                title="Context"
            ))
            continue

        # ── agents / ls ──
        if cmd in ('agents', 'ls'):
            table = Table(title="Registered Agents")
            table.add_column("Alias", style="cyan")
            table.add_column("Role")
            table.add_column("Display Name")
            table.add_column("Tools")
            for alias, role in AGENT_ALIASES.items():
                agent = app.registry.get_agent_instance(role)
                if agent:
                    tool_names = [t.name if hasattr(t, 'name') else str(t) for t in (agent.tools or [])]
                    table.add_row(alias, role, agent.display_name, ", ".join(tool_names[:4]))
            console.print(table)
            continue

        # ── tools ──
        if cmd == 'tools':
            if not args:
                console.print("[red]Usage: tools <agent_alias>[/red]")
                continue
            alias = args[0].lower()
            role = AGENT_ALIASES.get(alias, alias)
            agent = app.registry.get_agent_instance(role)
            if not agent:
                console.print(f"[red]Agent '{alias}' not found[/red]")
                continue
            table = Table(title=f"Tools: {agent.display_name} ({alias})")
            table.add_column("Name", style="yellow")
            table.add_column("Type")
            for t in (agent.tools or []):
                tname = getattr(t, 'name', str(t))
                ttype = type(t).__name__
                table.add_row(tname, ttype)
            console.print(table)
            continue

        # ── exec: 直接调用 Tool ──
        if cmd == 'exec':
            if len(args) < 2:
                console.print("[red]Usage: exec <agent_alias> <tool_name> [tool_args...][/red]")
                continue
            alias = args[0].lower()
            tool_name = args[1]
            tool_args = " ".join(args[2:]) if len(args) > 2 else "{}"
            role = AGENT_ALIASES.get(alias, alias)
            agent = app.registry.get_agent_instance(role)
            if not agent:
                console.print(f"[red]Agent '{alias}' not found[/red]")
                continue
            # 查找 tool
            target_tool = None
            for t in (agent.tools or []):
                if getattr(t, 'name', '') == tool_name or getattr(t, 'func', None) and getattr(t.func, '__name__', '') == tool_name:
                    target_tool = t
                    break
            if not target_tool:
                console.print(f"[red]Tool '{tool_name}' not found in {alias}[/red]")
                console.print(f"  Available: {', '.join(getattr(t, 'name', str(t)) for t in (agent.tools or []))}")
                continue
            try:
                # invoke the tool
                func = getattr(target_tool, 'func', None) or target_tool
                if callable(func):
                    result = func(tool_args)
                else:
                    result = str(target_tool)
                console.print(Panel(str(result)[:2000], title=f"[yellow]{tool_name}[/yellow] ({alias})"))
            except Exception as e:
                console.print(f"[red]Tool error: {e}[/red]")
            continue

        # ── agent execution ──
        alias = cmd
        role = AGENT_ALIASES.get(alias, alias)
        agent = app.registry.get_agent_instance(role)
        if not agent:
            console.print(f"[red]Unknown command/agent: {cmd}[/red] (try [yellow]help[/yellow])")
            continue

        # Build input: use args if provided, else use ctx output (from previous agent), else ctx input
        agent_input = " ".join(args) if args else (ctx.get("output") or ctx.get("input") or "")
        if not agent_input:
            agent_input = console.input(f"  input for [cyan]{alias}[/cyan]: ").strip()
        if not agent_input:
            console.print("[red]No input provided[/red]")
            continue

        console.print(f"  [{alias}] running (LLM)...")
        start = __import__('time').time()
        try:
            r = asyncio.run(agent.execute_task({"input": agent_input}))
            elapsed = __import__('time').time() - start
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

def main():
    cli()

# ── Web 服务器 ──

@cli.command("web")
@click.option('--host', default='127.0.0.1', help='Bind address')
@click.option('--port', default=8000, help='Port')
@click.option('--reload', is_flag=True, help='Auto-reload on code changes')
def web_command(host, port, reload):
    """启动 Web 仪表盘"""
    import uvicorn
    console.print(f"[bold cyan]SignOffAI Web Dashboard[/bold cyan]")
    console.print(f"  URL: [cyan]http://{host}:{port}[/cyan]")
    console.print(f"  API: [cyan]http://{host}:{port}/api/[/cyan]")
    uvicorn.run("src.web.api:app", host=host, port=port, reload=reload)

if __name__ == "__main__":
    main()
