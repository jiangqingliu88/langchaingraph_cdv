"""
CLI命令 - 使用Click框架 + Rich显示
"""
import asyncio
import sys
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich import print as rprint
import json

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.registry import AgentRegistry
from src.core.orchestrator import VerificationOrchestrator, VerificationWorkflow, WorkflowPhase
from src.agents.spec_planner import SpecAndTestPlanner
from config.settings import Settings

console = Console()

class VerificationCLI:
    """IC验证智能体CLI"""
    
    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = AgentRegistry.get_instance()
        self.orchestrator: Optional[VerificationOrchestrator] = None
        self.initialized = False
    
    async def initialize(self):
        """初始化系统"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]初始化IC验证智能体系统...", total=None)
            
            # 初始化Agent
            agents_config = {}
            
            # 创建并注册Agents
            spec_planner = SpecAndTestPlanner()
            await spec_planner.initialize()
            self.registry.set_agent_instance("spec_and_test_planner", spec_planner)
            
            # TODO: 初始化其他8个Agent
            
            progress.update(task, description="[green]系统初始化完成!")
        
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
            metrics = agent.get_metrics()
            table.add_row(
                metrics["display_name"],
                role,
                metrics["status"],
                str(metrics["tasks_completed"])
            )
        
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
@click.option('--workflow', '-w', default='full_verification', 
              help='工作流名称 (full_verification/quick_check)')
@click.option('--output', '-o', type=click.Path(), help='输出结果文件')
def verify(spec_file, workflow, output):
    """运行IC验证流程
    
    SPEC_FILE: 设计规格文档路径
    """
    app = VerificationCLI()
    
    async def run():
        await app.initialize()
        result = await app.run_verification(spec_file, workflow)
        
        if output:
            import json
            # 转换结果为可序列化格式
            serializable_result = {
                "session_id": result.get("session_id"),
                "workflow": result.get("workflow"),
                "success": result.get("success"),
                "phase_results": {}
            }
            
            for phase, phase_result in result.get("phase_results", {}).items():
                if hasattr(phase_result, 'data'):
                    serializable_result["phase_results"][phase] = {
                        "success": phase_result.success,
                        "data": str(phase_result.data)
                    }
            
            with open(output, "w", encoding="utf-8") as f:
                json.dump(serializable_result, f, indent=2, ensure_ascii=False)
            console.print(f"\n[green]结果已保存到: {output}[/green]")
    
    asyncio.run(run())

@cli.command()
def status():
    """查看系统状态"""
    app = VerificationCLI()
    
    async def run():
        await app.initialize()
        app.show_status()
    
    asyncio.run(run())

@cli.command()
def workflows():
    """列出可用工作流"""
    app = VerificationCLI()
    
    async def run():
        await app.initialize()
        app.list_workflows()
    
    asyncio.run(run())

@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
def analyze(spec_file):
    """分析设计规格文档"""
    app = VerificationCLI()
    
    async def run():
        await app.initialize()
        
        with open(spec_file, "r", encoding="utf-8") as f:
            spec_content = f.read()
        
        agent = app.registry.get_agent_instance("spec_and_test_planner")
        if agent:
            with Progress(SpinnerColumn(), TextColumn("[cyan]分析规格..."), console=console) as progress:
                task = progress.add_task("", total=None)
                result = await agent.execute_task({"input": f"分析以下设计规格:\n{spec_content}"})
                progress.update(task, completed=True)
            
            if result.success:
                console.print(Panel(
                    result.data.get("output", "无输出"),
                    title="规格分析结果",
                    border_style="green"
                ))
            else:
                console.print(f"[red]分析失败: {result.error}[/red]")
    
    asyncio.run(run())

@cli.command()
@click.argument('project_name')
@click.option('--description', '-d', help='项目描述')
def create_project(project_name, description):
    """创建新的验证项目"""
    console.print(f"[green]创建项目: {project_name}[/green]")
    console.print(f"描述: {description or '无'}")

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

def main():
    """主入口"""
    cli()

if __name__ == "__main__":
    main()