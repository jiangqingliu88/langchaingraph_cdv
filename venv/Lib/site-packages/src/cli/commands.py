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
from src.agents.architect import VerificationArchitect
from src.agents.sequence_engineer import SequenceEngineer
from src.agents.assertion_engineer import AssertionEngineer
from src.agents.coverage_manager import CoverageManager
from src.agents.regression_manager import RegressionManager
from src.agents.debug_engineer import DebugEngineer
from src.agents.quality_assurance import QualityAssurance
from src.agents.report_generator import ReportGenerator
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
            ("verification_architect", VerificationArchitect()),
            ("sequence_engineer", SequenceEngineer()),
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
        console.print("[green]All 9 agents initialized[/green]")

@click.group()
def cli():
    pass

@cli.command()
def init():
    Path("output").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    console.print("[green]Initialized[/green]")

@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
@click.option('--bypass', is_flag=True)
def analyze(spec_file, bypass):
    app = VerificationCLI()
    async def run():
        await app.initialize()
        spec = Path(spec_file).read_text(encoding='utf-8')
        agent = app.registry.get_agent_instance("spec_and_test_planner")
        agent.config["bypass"] = bypass
        result = await agent.execute_task({"input": spec, "bypass": bypass})
        if result.success:
            console.print(Panel(str(result.data.get("output", ""))[:1000], title="Result"))
        else:
            console.print(f"[red]{result.error}[/red]")
    asyncio.run(run())

@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
@click.option('--workflow', '-w', default='full_verification')
@click.option('--bypass', is_flag=True)
@click.option('--output', '-o', type=click.Path())
def verify(spec_file, workflow, bypass, output):
    app = VerificationCLI()
    async def run():
        await app.initialize()
        spec = Path(spec_file).read_text(encoding='utf-8')
        phases = [
            ("spec", "spec_and_test_planner"),
            ("arch", "verification_architect"),
            ("seq", "sequence_engineer"),
            ("assert", "assertion_engineer"),
            ("regress", "regression_manager"),
            ("cover", "coverage_manager"),
            ("qa", "quality_assurance"),
        ]
        if workflow == 'quick_check':
            phases = phases[:3]
        table = Table(title=f"Pipeline: {workflow}")
        table.add_column("Phase")
        table.add_column("Status")
        table.add_column("Time")
        results = {}
        prev = spec
        for name, role in phases:
            agent = app.registry.get_agent_instance(role)
            if not agent:
                table.add_row(name, "N/A", "-")
                continue
            agent.config["bypass"] = bypass
            t0 = time.time()
            try:
                r = await agent.execute_task({"input": prev, "bypass": bypass})
                t1 = time.time() - t0
                if r.success:
                    table.add_row(name, "[green]OK[/green]", f"{t1:.1f}s")
                    prev = r.data.get("output", prev)
                    results[name] = "passed"
                else:
                    table.add_row(name, "[red]FAIL[/red]", f"{t1:.1f}s")
                    console.print(f"[red]  Error: {r.error[:200] if r.error else 'unknown'}[/red]")
            except Exception as e:
                table.add_row(name, "[red]ERR[/red]", f"{time.time()-t0:.1f}s")
        console.print(table)
        passed = sum(1 for v in results.values() if v == "passed")
        console.print(f"[bold]Result: {passed}/{len(phases)}[/bold]")
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
    console.print("[dim]History: run ic-verify verify first[/dim]")

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
            console.print("[dim]No debug logs yet. Run ic-verify verify first.[/dim]")

@cli.command()
def workflows():
    console.print("full_verification - 7 phases")
    console.print("quick_check - 3 phases")

@cli.command()
@click.option('--bypass', is_flag=True)
def repl(bypass):
    console.print("[cyan]REPL mode[/cyan]")
    console.print("Commands: analyze | arch | seq | assert | quit")
    app = VerificationCLI()
    asyncio.run(app.initialize())
    ctx = {"spec": ""}
    while True:
        try:
            cmd = console.input("> ").strip()
        except:
            break
        if cmd in ('quit', 'exit'):
            break
        if cmd == 'help':
            console.print("analyze <spec> | arch | seq | assert | quit")
            continue
        role_map = {"analyze": "spec_and_test_planner", "arch": "verification_architect",
                    "seq": "sequence_engineer", "assert": "assertion_engineer"}
        role = role_map.get(cmd.split()[0], "")
        agent = app.registry.get_agent_instance(role) if role else None
        if agent:
            agent.config["bypass"] = bypass
            inp = ctx.get("spec", cmd)
            r = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
            if r.success:
                console.print(Panel(str(r.data.get("output", ""))[:500]))
                ctx["spec"] = r.data.get("output", "")
    console.print("[dim]Bye[/dim]")

def main():
    cli()

if __name__ == "__main__":
    main()
