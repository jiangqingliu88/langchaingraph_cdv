"""
CLI命令 - 使用Click框架 + Rich显示
"""
import asyncio
import sys
from pathlib import Path
from typing import Optional
import click
import json
from rich.console import Console
from rich.table import Table
import yaml
from src.database.repository import save_task, save_pipeline_run, get_recent_tasks
from src.database.connection import init_db
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
from rich import box
import json

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.registry import AgentRegistry
from src.core.orchestrator import VerificationOrchestrator, VerificationWorkflow, WorkflowPhase
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
    """IC验证智能体CLI"""
    
    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = AgentRegistry.get_instance()
        self.orchestrator: Optional[VerificationOrchestrator] = None
        self.initialized = False
        self.agent_config = {}
    
    def get_agent_config(self, role):
        return self.agent_config.get("agents", {}).get(role, {})
    
    async def initialize(self):
        """初始化系统"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Initializing agents...", total=9)
            
            spec_planner = SpecAndTestPlanner()
            await spec_planner.initialize()
            self.registry.set_agent_instance("spec_and_test_planner", spec_planner)
            progress.advance(task)
            
            architect = VerificationArchitect()
            await architect.initialize()
            self.registry.set_agent_instance("verification_architect", architect)
            progress.advance(task)
            
            sequence_eng = SequenceEngineer()
            await sequence_eng.initialize()
            self.registry.set_agent_instance("sequence_engineer", sequence_eng)
            progress.advance(task)
            
            assertion_eng = AssertionEngineer()
            await assertion_eng.initialize()
            self.registry.set_agent_instance("assertion_engineer", assertion_eng)
            progress.advance(task)
            
            coverage_mgr = CoverageManager()
            await coverage_mgr.initialize()
            self.registry.set_agent_instance("coverage_manager", coverage_mgr)
            progress.advance(task)
            
            regression_mgr = RegressionManager()
            await regression_mgr.initialize()
            self.registry.set_agent_instance("regression_manager", regression_mgr)
            progress.advance(task)
            
            debug_eng = DebugEngineer()
            await debug_eng.initialize()
            self.registry.set_agent_instance("debug_engineer", debug_eng)
            progress.advance(task)
            
            qa = QualityAssurance()
            await qa.initialize()
            self.registry.set_agent_instance("quality_assurance", qa)
            progress.advance(task)
            
            report_gen = ReportGenerator()
            await report_gen.initialize()
            self.registry.set_agent_instance("report_generator", report_gen)
            progress.advance(task)
        
        console.print("[green]All 9 agents initialized![/green]")
        
        # 创建编排器
        self.orchestrator = VerificationOrchestrator(self.registry)
        
        # 注册工作流
        self._register_workflows()
        
        self.initialized = True
    
    def _register_workflows(self):
        """注册预定义工作流"""
        # 从配置加载工作流
        pipelines = self.settings.agent_config.get("pipelines", {})
        
        for pipeline_name, pipeline_config in pipelines.items():
            phases = []
            for phase_config in pipeline_config.get("phases", []):
                phases.append(WorkflowPhase(
                    name=phase_config["name"],
                    agent_role=phase_config.get("agent", ""),
                    parallel=phase_config.get("parallel", False),
                    parallel_agents=phase_config.get("agents", [])
                ))
            
            workflow = VerificationWorkflow(
                name=pipeline_config["name"],
                description=pipeline_config.get("name", ""),
                phases=phases
            )
            self.orchestrator.register_workflow(workflow)
    
    async def run_verification(self, spec_file: str, workflow: str = "full_verification"):
        """运行验证流程"""
        if not self.initialized:
            await self.initialize()
        
        # 读取规格文件
        spec_path = Path(spec_file)
        if not spec_path.exists():
            console.print(f"[red]错误: 文件不存在 - {spec_file}[/red]")
            return
        
        with open(spec_path, "r", encoding="utf-8") as f:
            spec_content = f.read()
        
        console.print(Panel.fit(
            f"[bold cyan]开始执行验证流程[/bold cyan]\n"
            f"工作流: {workflow}\n"
            f"规格文件: {spec_file}",
            title="IC验证智能体系统"
        ))
        
        # 执行工作流
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]执行验证流程...", total=None)
            
            result = await self.orchestrator.execute_workflow(
                workflow,
                {"input": spec_content}
            )
            
            progress.update(task, description="[green]验证流程完成!")
        
        # 显示结果
        self._display_results(result)
    
    def _display_results(self, result: dict):
        """显示验证结果"""
        console.print("\n")
        console.print(Panel.fit(
            f"[bold]验证结果摘要[/bold]",
            title="Results"
        ))
        
        # 创建结果表格
        table = Table(title="阶段执行结果")
        table.add_column("阶段", style="cyan")
        table.add_column("状态", style="bold")
        table.add_column("详情")
        
        phase_results = result.get("phase_results", {})
        for phase_name, phase_result in phase_results.items():
            if hasattr(phase_result, 'success'):
                status = "[green]✓ 成功[/green]" if phase_result.success else "[red]✗ 失败[/red]"
                detail = phase_result.data.get("output", "")[:100] if phase_result.data else ""
            else:
                # 并行结果
                successes = all(
                    r.success if hasattr(r, 'success') else False 
                    for r in phase_result
                )
                status = "[green]✓ 成功[/green]" if successes else "[yellow]⚠ 部分失败[/yellow]"
                detail = f"{len(phase_result)}个Agent并行执行"
            
            table.add_row(phase_name, status, detail)
        
        console.print(table)
        
        # 显示会话信息
        console.print(f"\n[dim]会话ID: {result.get('session_id')}[/dim]")
    
    def show_status(self):
        """显示系统状态"""
        if not self.registry:
            console.print("[red]系统未初始化[/red]")
            return
        
        table = Table(title="Agent状态")
        table.add_column("Agent", style="cyan")
        table.add_column("角色", style="green")
        table.add_column("状态")
        table.add_column("任务数")
        
        for role, agent in self.registry.get_all_instances().items():
            try:
                metrics = agent.get_metrics()
                table.add_row(
                    metrics.get("display_name", role),
                    role,
                    metrics.get("status", "unknown"),
                    str(metrics.get("tasks_completed", 0))
                )
            except:
                table.add_row(role, role, "error", "0")
        
        console.print(table)
    
    def list_workflows(self):
        """列出可用工作流"""
        if not self.orchestrator:
            console.print("[red]系统未初始化[/red]")
            return
        
        table = Table(title="可用工作流")
        table.add_column("名称", style="cyan")
        table.add_column("描述")
        table.add_column("阶段数")
        
        for name, workflow in self.orchestrator.workflows.items():
            table.add_row(
                name,
                workflow.description,
                str(len(workflow.phases))
            )
        
        console.print(table)

# Click CLI定义
@click.group()
@click.version_option(version="1.0.0")
@click.pass_context
def cli(ctx):
    """IC验证智能体系统 - 多Agent协作验证平台"""
    ctx.ensure_object(dict)
    ctx.obj['app'] = VerificationCLI()

@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
@click.option('--workflow', '-w', default='full_verification', help='full_verification or quick_check')
@click.option('--output', '-o', type=click.Path(), help='output JSON file')
@click.option('--bypass', is_flag=True, help='Use mock data, skip LLM')
def verify(spec_file, workflow, bypass, output):
    """Run full verification pipeline with orchestrator"""
    app = VerificationCLI()
    
    async def run():
        import time, json as j
        
        await app.initialize()
        
        with open(spec_file, 'r', encoding='utf-8') as f:
            spec = f.read()
        
        # 优先从 YAML 加载，fallback 到硬编码
        # 从 YAML 配置或 agent_config 加载
        pipelines = app.agent_config.get("pipelines", {}) if hasattr(app, 'agent_config') else {}
        wf = pipelines.get(workflow, {})
        if not wf or not wf.get("phases"):
            wf = {
                "name": workflow,
                "phases": [
                    {"name": "spec", "agent": "spec_and_test_planner", "input": "$spec"},
                    {"name": "arch", "agent": "verification_architect", "input": "$spec.output"},
                    {"name": "seq", "agent": "sequence_engineer", "input": "$arch.output", "parallel_group": 1},
                    {"name": "assert", "agent": "assertion_engineer", "input": "$arch.output", "parallel_group": 1},
                    {"name": "regress", "agent": "regression_manager", "input": "$seq.output"},
                    {"name": "cover", "agent": "coverage_manager", "input": "$regress.output"},
                    {"name": "qa", "agent": "quality_assurance", "input": "$cover.output"},
                ]
            }
        phases = wf["phases"]
        
        console.print(Panel.fit(f"[bold]{wf['name']}[/bold] | {len(phases)} phases | bypass={bypass}", title="Pipeline"))
        
        async def _execute_phase(name, agent_role, phase, context, results):
            progress.update(overall, description=f"[cyan]{name}")
            
            agent = app.registry.get_agent_instance(agent_role)
            if not agent:
                results[name] = {"status": "skip", "time": 0}
                progress.advance(overall)
                return
            
            # 解析输入引用
            inp_ref = phase.get("input", "")
            inp = spec
            if inp_ref.startswith("$") and "." in inp_ref:
                parts = inp_ref[1:].split(".")
                key = "$" + parts[0]
                if key in context:
                    inp = context[key].get(parts[1], spec)
            
            t0 = time.time()
            cfg = app.get_agent_config(agent_role)
            max_retries = cfg.get("retry", {}).get("max_retries", 3)
            retry_count = 0
            result = None
            
            while retry_count <= max_retries:
                try:
                    result = await agent.execute_task({"input": inp, "bypass": bypass})
                    if result.success:
                        break
                    retry_count += 1
                    if retry_count <= max_retries:
                        progress.console.print(f"  [yellow]Retry {retry_count}/{max_retries}[/yellow]")
                except Exception as e:
                    retry_count += 1
                    if retry_count <= max_retries:
                        progress.console.print(f"  [yellow]Error retry {retry_count}: {e}[/yellow]")
                    else:
                        result = type('obj', (object,), {'success': False, 'error': str(e)})()
            
            elapsed = time.time() - t0
            
            if result and result.success:
                progress.console.print(f"  [green]OK[/green] {name} ({elapsed:.1f}s)")
                context[f"${name}"] = result.data
                results[name] = {"status": "passed", "time": elapsed}
            else:
                err_msg = getattr(result, 'error', 'unknown') if result else 'no result'
                progress.console.print(f"  [yellow]DEGRADED[/yellow] {name} - {err_msg[:60]}")
                results[name] = {"status": "degraded", "time": elapsed, "error": err_msg}
                context[f"${name}"] = {"output": inp}
            
            progress.advance(overall)
        
        # Phase级别进度条
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            overall = progress.add_task("[cyan]Overall Pipeline", total=len(phases))
            
            results = {}
            context = {"$spec": {"output": spec}}
            
            # 按 parallel_group 分组
            groups = {}
            for phase in phases:
                g = phase.get("parallel_group", 0)
                if g not in groups:
                    groups[g] = []
                groups[g].append(phase)
            
            import asyncio as aio
            
            for g, group_phases in sorted(groups.items()):
                if g == 0:
                    for phase in group_phases:
                        await _execute_phase(phase["name"], phase["agent"], phase, context, results)
                else:
                    progress.console.print(f"[cyan]Parallel group {g}: {[p['name'] for p in group_phases]}[/cyan]")
                    tasks = [_execute_phase(p["name"], p["agent"], p, context, results) for p in group_phases]
                    await aio.gather(*tasks)
        
        # 汇总报告
        passed = sum(1 for v in results.values() if v["status"] == "passed")
        degraded = sum(1 for v in results.values() if v["status"] == "degraded")
        total_time = sum(v["time"] for v in results.values())
        
        console.print()
        console.print(Panel.fit(
            f"[bold]Pipeline Complete[/bold]\n"
            f"[green]Passed: {passed}[/green] | [yellow]Degraded: {degraded}[/yellow] | Total: {len(phases)}\n"
            f"Total time: {total_time:.1f}s",
            border_style="green" if degraded == 0 else "yellow"
        ))
        
        # 保存到数据库
        try:
            await save_pipeline_run(workflow, spec_file, len(phases), passed, degraded, total_time, results)
        except:
            pass
        
        if output:
            with open(output, "w", encoding="utf-8") as f:
                j.dump({"workflow": workflow, "results": results}, f, indent=2)
            console.print(f"[green]Saved: {output}[/green]")
    
    asyncio.run(run())
@cli.command()
def workflows():
    """列出可用工作流"""
    console.print("[bold]Available workflows:[/bold]")
    console.print("  full_verification - 7 phases")
    console.print("  quick_check - 3 phases")

@cli.command()
@click.argument('project_name')
@click.option('--description', '-d', help='project description')
def create_project(project_name, description):
    """创建新项目"""
    console.print(f"[green]Project created: {project_name}[/green]")

@cli.command()
def init():
    """初始化系统配置"""
    console.print("[bold cyan]初始化IC验证智能体系统配置[/bold cyan]")
    
    # 创建必要的目录
    dirs = [
        "output",
        "logs",
        "data",
        "waveforms"
    ]
    
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        console.print(f"  [green]✓[/green] 创建目录: {dir_name}")
    
    # 创建.env文件(如果不存在)
    env_path = Path(".env")
    if not env_path.exists():
        with open(env_path, "w") as f:
            f.write("""# LLM配置
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4-turbo
LLM_TEMPERATURE=0.0

# 数据库配置
DB_URL=sqlite+aiosqlite:///ic_verification.db

# Agent配置
AGENT_MAX_AGENTS=9
AGENT_VERBOSE=true
""")
        console.print("  [green]✓[/green] 创建.env配置文件")
    else:
        console.print("  [yellow]⚠[/yellow] .env文件已存在")
    
    console.print("\n[bold green]初始化完成![/bold green]")
    console.print("下一步:")
    console.print("  1. 编辑.env文件，配置API密钥")
    console.print("  2. 运行 'ic-verify verify <spec_file>' 开始验证")

@cli.command()
@click.option('--bypass', is_flag=True, help='Use mock data, skip LLM')
def repl(bypass):
    """Interactive REPL mode - chat with verification agents"""
    app = VerificationCLI()
    
    async def init():
        await app.initialize()
        console.print("[green]All agents ready. Type 'help' for commands, 'quit' to exit.[/green]")
        return app
    
    app = asyncio.run(init())
    
    context = {"spec": "", "last_output": ""}
    
    console.print(Panel.fit(
        "[bold cyan]IC Verification REPL[/bold cyan]\n"
        "Commands: analyze <spec> | plan | arch | seq | assert | cover | debug | qa | help | quit",
        title="Welcome"
    ))
    
    while True:
        try:
            cmd = console.input("[bold cyan]ic-verify>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break
        
        if not cmd:
            continue
        
        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        
        if action == 'quit' or action == 'exit':
            console.print("[dim]Goodbye![/dim]")
            break
        
        elif action == 'help':
            console.print("""
[bold]Available commands:[/bold]
  [cyan]analyze <spec>[/cyan]  - Analyze design specification
  [cyan]plan[/cyan]           - Generate test plan from last analysis
  [cyan]arch[/cyan]           - Generate UVM architecture
  [cyan]seq[/cyan]            - Generate test sequences
  [cyan]assert[/cyan]         - Generate SVA assertions
  [cyan]cover[/cyan]          - Coverage analysis
  [cyan]debug[/cyan]          - Debug analysis
  [cyan]qa[/cyan]             - Quality review
  [cyan]status[/cyan]         - Show agent status
  [cyan]context[/cyan]        - Show current context
  [cyan]clear[/cyan]          - Clear context
  [cyan]quit[/cyan]           - Exit REPL
""")
        
        elif action == 'status':
            table = Table(title="Agent Status")
            table.add_column("Agent")
            table.add_column("Status")
            for role, agent in app.registry.get_all_instances().items():
                try:
                    m = agent.get_metrics()
                    table.add_row(m.get("display_name", role), m.get("status", "?"))
                except:
                    table.add_row(role, "error")
            console.print(table)
        
        elif action == 'context':
            console.print(f"[dim]Spec length: {len(context['spec'])} chars[/dim]")
            console.print(f"[dim]Last output: {context['last_output'][:100]}...[/dim]")
        
        elif action == 'clear':
            context = {"spec": "", "last_output": ""}
            console.print("[green]Context cleared[/green]")
        
        elif action == 'analyze':
            spec_text = arg if arg else context.get("spec", "")
            if not spec_text:
                console.print("[red]No spec provided. Use: analyze <spec_text>[/red]")
                continue
            context["spec"] = spec_text
            agent = app.registry.get_agent_instance("spec_and_test_planner")
            if agent:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Analyzing..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": spec_text, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Analysis[/green]"))
        
        elif action == 'plan':
            agent = app.registry.get_agent_instance("spec_and_test_planner")
            inp = context.get("last_output", context.get("spec", ""))
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Planning..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": f"Generate test plan from: {inp}", "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Test Plan[/green]"))
        
        elif action == 'arch':
            agent = app.registry.get_agent_instance("verification_architect")
            inp = context.get("last_output", context.get("spec", ""))
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Designing architecture..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    output = result.data.get("output", "")
                    context["last_output"] = output
                    if 'class ' in output or 'module ' in output:
                        console.print(Syntax(output[:500], "systemverilog", theme="monokai"))
                    else:
                        console.print(Panel(output[:500], title="[green]Architecture[/green]"))
        
        elif action == 'seq':
            agent = app.registry.get_agent_instance("sequence_engineer")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Generating sequences..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Syntax(context["last_output"][:500], "systemverilog", theme="monokai"))
        
        elif action == 'assert':
            agent = app.registry.get_agent_instance("assertion_engineer")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Generating assertions..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Syntax(context["last_output"][:500], "systemverilog", theme="monokai"))
        
        elif action == 'cover':
            agent = app.registry.get_agent_instance("coverage_manager")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Analyzing coverage..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Coverage[/green]"))
        
        elif action == 'debug':
            agent = app.registry.get_agent_instance("debug_engineer")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Debugging..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Debug[/green]"))
        
        elif action == 'qa':
            agent = app.registry.get_agent_instance("quality_assurance")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Reviewing..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]QA Review[/green]"))
        
        else:
            console.print(f"[red]Unknown command: {action}. Type 'help'[/red]")


@cli.command()
def status():
    """View all agent status"""
    app = VerificationCLI()
    async def run():
        await app.initialize()
        table = Table(title="Agent Status")
        table.add_column("Agent", style="cyan")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Tasks")
        for role, agent in app.registry.get_all_instances().items():
            try:
                m = agent.get_metrics()
                table.add_row(m.get("display_name", role), role, m.get("status", "?"), str(m.get("tasks_completed", 0)))
            except:
                table.add_row(role, role, "error", "0")
        console.print(table)
    asyncio.run(run())

@cli.command()
def history():
    async def run():
        await init_db()
        tasks = await get_recent_tasks(20)
        table = Table(title='Task History')
        table.add_column('Agent')
        table.add_column('Status')
        table.add_column('Time')
        for t in tasks:
            table.add_row(t['agent'], t['status'], f"{t['time']:.1f}s")
        console.print(table)
    asyncio.run(run())

def main():
    """主入口"""
    cli()

if __name__ == "__main__":
    main()