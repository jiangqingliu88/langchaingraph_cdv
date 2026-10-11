"""
SignOffAI CLI — 增强版命令行接口

对标 git/docker 的命令行体验，支持 CI/CD 集成和交互式调试。
23 个命令组，50+ 子命令。

用法:
  vagent --help
  vagent verify --help
  vagent signoff <run_id> --type tapeout
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# ── UTF-8 强制编码 (修复 Windows 中文乱码) ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ── structlog 统一写 stderr（stdout 保留给业务输出/--json，不被日志污染）──
import structlog  # noqa: E402
structlog.configure(logger_factory=structlog.WriteLoggerFactory(sys.stderr))

from src.layers.l2_orchestration.executors.registry import ExecutorRegistry
from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.layers.l2_orchestration.governance.approval import create_approval_gate, ApprovalDecision, PipelineTerminatedError
from src.cli.output import OutputAdapter, common_options, get_output_adapter

console = Console()

# ═══════════════════════════════════════════════════════════════
# Agent 初始化
# ═══════════════════════════════════════════════════════════════

# 七 Agent 角色映射（闭环架构 design/model/verify/ops/coverage/debug/audit）
AGENT_ALIASES = {
    "design": "design", "model": "model", "verify": "verify",
    "ops": "ops", "coverage": "coverage", "debug": "debug", "audit": "audit",
}
AGENT_HELP = ", ".join(AGENT_ALIASES.keys())


class VerificationCLI:
    """CLI Agent 初始化器 (向后兼容)"""

    def __init__(self):
        self.settings = None
        self.registry = ExecutorRegistry.get_instance()
        self.agent_config = {}

    async def initialize(self):
        from src.executors import DesignExecutor, ModelExecutor, VerifyExecutor, OpsExecutor, CoverageExecutor, DebugExecutor, AuditExecutor
        agents = [
            ("design", DesignExecutor()),
            ("model", ModelExecutor()),
            ("verify", VerifyExecutor()),
            ("ops", OpsExecutor()),
            ("coverage", CoverageExecutor()),
            ("debug", DebugExecutor()),
            ("audit", AuditExecutor()),
        ]
        for role, agent in agents:
            await agent.initialize()
            self.registry.set_agent_instance(role, agent)
        console.print("[green]7 agents initialized[/green]")


def _init_service():
    """初始化 PipelineExecutionService (幂等)"""
    service = PipelineExecutionService.get_instance()
    if not service.initialized:
        asyncio.run(service.initialize_agents())
    return service


def _find_run_id(run_id: str = None) -> str | None:
    """查找 run_id: 指定或最新"""
    if run_id:
        return run_id
    service = PipelineExecutionService.get_instance()
    runs = service.list_runs()
    if runs:
        return runs[-1]["run_id"]
    return None


# ═══════════════════════════════════════════════════════════════
# 主命令入口
# ═══════════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.version_option(version="2.0.0", prog_name="SignOffAI")
@click.option("-p", "--print", "prompt", default="", help="单次查询模式（非交互），如 -p '生成 APB 验证计划'")
@click.option("-c", "--continue", "continue_mode", is_flag=True, help="继续上次会话")
@click.option("-r", "--resume", "resume_id", help="恢复指定会话 ID")
@click.pass_context
def cli(ctx, prompt, continue_mode, resume_id):
    """SignOffAI — AI 驱动的芯片验证签核平台

    无参数进入交互式 REPL；-p 'prompt' 单次查询；-c 继续；-r 恢复。
    """
    # 无子命令时，进入 REPL 或单次查询
    if ctx.invoked_subcommand is None:
        from src.cli.repl import run_interactive, run_once
        if prompt:
            run_once(prompt)       # vagent -p "prompt"
        elif continue_mode:
            run_interactive(continue_latest=True)   # vagent -c
        elif resume_id:
            run_interactive(session_id=resume_id)   # vagent -r <id>
        else:
            run_interactive()      # vagent 进入 REPL


# ═══════════════════════════════════════════════════════════════
# vagent init
# ═══════════════════════════════════════════════════════════════

@cli.command()
@common_options
def init(json_output, quiet, verbose, output_dir):
    """初始化输出目录结构"""
    from src.layers.l1_infrastructure.output_config import make_output_root
    out = get_output_adapter(json_output, quiet)
    root = make_output_root(output_dir or None)
    paths = [root, "logs", f"{root}/docs", f"{root}/docs/de", f"{root}/docs/dv"]
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)
    Path(f"{root}/.gitkeep").touch(exist_ok=True)
    Path("logs/.gitkeep").touch(exist_ok=True)
    out.print_success(f"Initialized — {root}/ logs/ created")


# ═══════════════════════════════════════════════════════════════
# vagent verify — 覆盖率驱动闭环
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.argument("spec_file", required=False, type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="输出目录")
@click.option("--design-style", default="baseline", help="设计风格（baseline/pipeline/low_power）")
@click.option("--target", type=float, default=None, help="覆盖率目标（默认从配置读）")
@click.option("--max-rounds", type=int, default=5, help="最大闭环轮次")
@click.option("--approval", default="threshold",
              type=click.Choice(["interactive", "auto", "threshold"]),
              help="审批模式（默认 threshold：仅高危动作询问；无人值守请显式指定 auto）")
@click.option("--full-regression", is_flag=True, help="全量回归（跑所有 case，默认增量只跑未 passed）")
@click.option("--verify-only", is_flag=True, help="验证专注模式：bypass design/model，直接 UVM 验证（预置 RTL + 黄金模型）")
@click.option("--sim-mode", "sim_modes", default=None, multiple=True,
              help="回归的仿真业务（可重复：--sim-mode wave --sim-mode cov）；"
                   "默认 cov+wave（覆盖率 + 波形）—— 要省机时就显式只给 cov。"
                   "可用词条见 src/tools/regression_tools/sim_modes.py")
@click.option("--no-manual-gate", "manual_gate", flag_value=False, default=True,
              help="关闭分级回归的**人工节点**（loopback 全过也不停车等人放行）。"
                   "默认开启：门是默认该在的。工作台工具栏上也有同一个开关")
@click.option("--rtl", "rtl_dir", type=click.Path(exists=True),
              help="外部 RTL 目录（验开源 IP 用）：拿这份现成 RTL 当 DUT，"
                   "**自动跳过 design/model**，不再由 design agent 生成")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
@click.option("--summary", is_flag=True, help="仅输出最终摘要")
@click.option("--quiet", "-q", is_flag=True, help="只打印错误")
def verify(spec_file, output, design_style, target, max_rounds,
           approval, full_regression, verify_only, sim_modes, json_output, summary,
           quiet, manual_gate, rtl_dir):
    # **spec 与 --rtl 二选一、互斥**：
    #   给 spec  → 走原来的路（design agent 生成 RTL）
    #   给 --rtl  → RTL 是唯一输入，**规格从 DUT 分析出来**（不指向 spec）
    # 两个都给会互相打脸（spec 说的和 RTL 实现的不一致时听谁的？），
    # 一个都不给则没有输入 —— 两种都当场拒掉，别让它跑到下游才含糊地失败。
    # **默认 spec**：不给 spec、也不给 --rtl 时用它 —— 省得每次敲全路径。
    # 只在 `--rtl` 缺席时套用：`--rtl` 是"RTL 唯一输入"，那时候默认值一填
    # 就变成"两个都给"，被下面的互斥挡掉（那是正确行为，不是 bug）。
    if not spec_file and not rtl_dir:
        _default = Path("specs/apb_uart/apb_uart_spec.md")
        if _default.exists():
            spec_file = str(_default)
            console.print(f"[dim]未指定 spec，用默认：{spec_file}[/dim]")
        else:
            raise click.UsageError(
                f"没给 spec，默认的 {_default} 也不存在（工作目录下找不到）。"
                "请显式给 spec，或用 --rtl 给 RTL")
    if bool(spec_file) == bool(rtl_dir):
        raise click.UsageError(
            "spec 与 --rtl 二选一：给了 --rtl 就不用 spec "
            "（规格会从 DUT 分析生成）；没给 --rtl 就必须给 spec")
    """AI 驱动的芯片验证闭环（覆盖率驱动：case 回归 → coverage → 决策迭代）

    
    示例:
      vagent verify spec.md                              # 默认闭环
      vagent verify spec.md --design-style pipeline      # 指定设计风格
      vagent verify spec.md --target 90 --max-rounds 8   # 指定覆盖率目标/轮次
      vagent verify spec.md --json                       # CI JSON 输出
    """
    out = get_output_adapter(json_output, quiet)
    from src.layers.l1_infrastructure.output_config import make_output_root
    output_root = make_output_root(output)
    approval_gate = create_approval_gate(approval)

    # 回归模式开关：--full-regression → 全量跑所有 case（覆盖默认增量）
    if full_regression:
        from config.settings import Settings
        Settings.get_instance().verification.incremental_regression = False

    if not quiet and not json_output:
        console.print(f"[bold cyan]═══ Closed Loop: coverage-driven ═══[/bold cyan]")

    async def run():
        service = PipelineExecutionService.get_instance()
        spec = (Path(spec_file).read_text(encoding="utf-8")
                if spec_file else "")   # --rtl 模式下无 spec：由 DUT 分析生成
        return await service.run_closed_loop(
            spec_text=spec, output_root=output_root,
            target=target, max_rounds=max_rounds,
            design_style=design_style, approval_gate=approval_gate,
            bypass_design_model=verify_only,
            # `multiple=True` 给的是 tuple；空则交默认（cov）
            sim_modes=list(sim_modes) or None,
            # 分级回归的人工节点（loopback 全过后停下等人放行）。默认开。
            manual_gate=manual_gate,
            rtl_dir=str(rtl_dir or ""),
        )

    result = asyncio.run(run())

    if json_output:
        click.echo(json.dumps({
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "passed": result.get("passed", 0),
            "total": result.get("total", 0),
            "overall_score": result.get("overall_score", 0),
            "final_coverage": result.get("final_coverage", 0),
            "effective_coverage": result.get("effective_coverage", 0),
            "converged": result.get("converged", False),
            "phases": result.get("phases", []),
        }, indent=2, ensure_ascii=False, default=str))
        sys.exit(0 if result.get("converged") else 1)

    if summary:
        cov = result.get("final_coverage", 0)
        eff = result.get("effective_coverage", 0)
        click.echo(f"Run: {result.get('run_id')} | {result.get('status')} "
                   f"| coverage={cov}% effective={eff}%")
        return

    table = Table(title=f"Closed Loop Results — {result.get('run_id')}")
    table.add_column("Phase")
    table.add_column("Status")
    table.add_column("Score")
    table.add_column("Time")
    for p in result.get("phases", []):
        st = p.get("status", "?")
        icon = {
            "passed": "[green]PASS[/green]", "failed": "[red]FAIL[/red]",
            "skipped": "[dim]SKIP[/dim]", "planned": "[dim]PLAN[/dim]",
            "decision": "[cyan]DECIDE[/cyan]", "blocked": "[yellow]BLOCK[/yellow]",
            "error": "[red]ERR[/red]",
        }.get(st, st)
        sc = str(p.get("score", "")) if p.get("score") is not None else "-"
        table.add_row(p.get("name", "?"), icon, sc, f"{p.get('time', 0)}s")
    console.print(table)

    cov = result.get("final_coverage", 0)
    eff = result.get("effective_coverage", 0)
    conv = result.get("converged", False)
    console.print(f"[bold]Coverage: {cov}%  Effective: {eff}%  "
                  f"Converged: {'[green]YES[/green]' if conv else '[yellow]NO[/yellow]'}[/bold]")

    if result.get("evidence", {}).get("evidence_path"):
        _print_evidence_chain(result["evidence"]["evidence_path"])


def _print_evidence_chain(evidence_path: str):
    """打印证据链摘要"""
    try:
        console.print(f"\n[bold cyan]=== Evidence Chain ===[/bold cyan]")
        chain = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        for name, layer in chain.get("layers", {}).items():
            pct = round(layer["passed"] / max(layer["total"], 1) * 100)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            console.print(f"  [{bar}] {layer['description']}: {layer['passed']}/{layer['total']} PASS")
        fc = chain.get("functional_coverage", {})
        if fc:
            cgs = fc.get("covergroups", [])
            fc_pct = fc.get("overall_coverage", 0)
            fc_bar = "█" * (int(fc_pct) // 10) + "░" * (10 - int(fc_pct) // 10)
            holes = fc.get("holes_by_priority", {})
            console.print(f"  [{fc_bar}] Functional Coverage: {fc_pct}% "
                          f"({len(cgs)} covergroups, P0:{holes.get('P0',0)} P1:{holes.get('P1',0)} holes)")
            for cg in cgs[:5]:
                cps = len(cg.get("coverpoints", []))
                console.print(f"         {cg['name']}: {cg['actual']}% (goal: {cg['goal']}%, {cps} CPs)")
        console.print(f"\n  Signoff Ready: {'[green]YES[/green]' if chain.get('signoff_ready') else '[red]NO[/red]'}  "
                      f"|  Overall: {'[green]PASS[/green]' if chain.get('overall_status') == 'PASS' else '[red]FAIL[/red]'}")
    except Exception:
        pass


@cli.command("check-env-arch")
@click.option("--output", "-o", "output_dir", type=click.Path(), help="输出目录（run 目录）")
@click.option("--test", "-t", "test_name", default=None, help="定向测试名（默认自动解析 loopback > directed > base）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def check_env_arch(output_dir, test_name, json_output):
    """验收 UVM env 架构：端口归属（通用）+ scoreboard 定向 case（通用）。"""
    from src.tools.uvm_tools.tool_check_env_arch.main import check_env_arch as _check_env_arch
    if not output_dir:
        console.print("[red]需要 --output 指定 run 目录，如 vagent check-env-arch -o output/apb_uart_run_xxx[/red]")
        return
    result = _check_env_arch(output_dir, test_name=test_name)
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    po = result.get("port_ownership", {})
    sb = result.get("scoreboard", {})
    status = result.get("status", "FAIL")
    console.print(f"\n[bold]{'[green]✅ PASS[/green]' if status == 'PASS' else '[red]❌ FAIL[/red]'}[/bold] env 架构验收")
    console.print(f"  [bold]端口归属[/bold]  {po.get('status')} — {po.get('message')}")
    for w in po.get("warnings", []):
        console.print(f"    [yellow]⚠ {w}[/yellow]")
    for v in po.get("violations", []):
        console.print(f"    [red]✗ {v}[/red]")
    console.print(f"  [bold]scoreboard[/bold]  {sb.get('status')} — {sb.get('message')}")


def _do_compile_check(result: dict):
    """UVM 后编译检查"""
    ctx = result["ctx"]
    console.print("\n[bold cyan]Compile Check[/bold cyan]")
    fl = ctx.get("env", {}).get("filelist", "") if hasattr(ctx, "get") else ""
    out_dir = ctx.get("env", {}).get("output_dir", "") if hasattr(ctx, "get") else ""
    if fl and Path(fl).exists():
        try:
            from src.tools.regression_tools.regression_framework.adapters.regression_runner import RegressionRunner
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
        except Exception as e:
            console.print(f"[yellow]Compile skipped: {e}[/yellow]")
    else:
        console.print(f"[yellow]Filelist not found: {fl}[/yellow]")


# ═══════════════════════════════════════════════════════════════
# vagent multi — 多模块软件流水（并发跑多个规格，EDA 等待不阻塞）
# ═══════════════════════════════════════════════════════════════

@cli.command("multi")
@click.option("--spec", "-s", "spec_files", multiple=True, type=click.Path(exists=True),
              help="规格文件（可多次指定，每个是一个模块）")
@click.option("--modules", "-m", "modules_file", type=click.Path(exists=True),
              help="模块列表 JSON/YAML 文件（[{name, spec_file, target, design_style}, ...]）")
@click.option("--output", "-o", type=click.Path(), help="输出根目录（每模块独立子目录）")
@click.option("--concurrency", "-n", default=4, type=int, help="并发上限（默认 4）")
@click.option("--design-style", default="baseline", help="设计风格（baseline/pipeline/low_power）")
@click.option("--max-rounds", default=5, type=int, help="每模块最大闭环轮次")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def multi(spec_files, modules_file, output, concurrency, design_style, max_rounds, json_output):
    """多模块软件流水：并发验证多个规格，EDA 等待期间互相推进（不阻塞）

    \b
    示例:
      vagent multi -s a.md -s b.md -s c.md                   # 三个模块流水并行
      vagent multi --modules modules.yaml -n 4               # 从列表文件 + 并发 4
      vagent multi -s a.md -s b.md --design-style pipeline   # 指定设计风格
    """
    out = get_output_adapter(json_output)

    module_specs = []
    if modules_file:
        text = Path(modules_file).read_text(encoding="utf-8", errors="replace")
        try:
            import yaml
            module_specs = yaml.safe_load(text) or []
        except Exception:
            module_specs = json.loads(text) if text.strip().startswith("[") else []
        if not isinstance(module_specs, list):
            out.print_error("模块列表文件必须是 list")
            return
    for sf in spec_files:
        module_specs.append({"name": Path(sf).stem, "spec_file": sf,
                             "design_style": design_style, "max_rounds": max_rounds})

    if not module_specs:
        out.print_error("无模块。用 -s <spec> 或 --modules <file> 指定。")
        return

    console.print(f"[bold cyan]═══ 多模块软件流水：{len(module_specs)} 模块，"
                  f"并发上限 {concurrency} ═══[/bold cyan]")
    for i, m in enumerate(module_specs):
        src = m.get("spec_file") or str(m.get("spec_text", ""))[:40]
        console.print(f"  [{i+1}] {m.get('name', f'module_{i+1}')} <- {src}")

    service = PipelineExecutionService.get_instance()

    async def run():
        return await service.run_multi_module(
            module_specs=module_specs, output_root=output or "output",
            design_style=design_style, max_rounds=max_rounds, max_concurrency=concurrency,
        )

    results = asyncio.run(run())

    if json_output:
        click.echo(json.dumps(results, indent=2, ensure_ascii=False, default=str))
        return

    table = Table(title=f"Multi-Module Results ({len(results)} modules)")
    table.add_column("Module")
    table.add_column("Status")
    table.add_column("Coverage")
    table.add_column("Converged")
    for i, r in enumerate(results):
        name = module_specs[i].get("name", f"module_{i+1}")
        if isinstance(r, Exception):
            table.add_row(name, "[red]ERROR[/red]", "-", "-")
            continue
        if not isinstance(r, dict):
            table.add_row(name, "[dim]?[/dim]", "-", "-")
            continue
        cov = r.get("final_coverage", 0)
        conv = r.get("converged", False)
        table.add_row(name, "[green]DONE[/green]", f"{cov}%",
                      "[green]YES[/green]" if conv else "[yellow]NO[/yellow]")
    console.print(table)


# ═══════════════════════════════════════════════════════════════
# vagent plan — 一站式验证闭环
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.argument("spec", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="输出目录")
@click.option("--design-style", default="baseline", help="设计风格（baseline/pipeline/low_power）")
@click.option("--target", type=float, default=None, help="覆盖率目标（默认从配置读）")
@click.option("--max-rounds", type=int, default=5, help="最大闭环轮次")
@click.option("--dry-run", is_flag=True, help="只打印计划，不执行")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
@click.pass_context
def plan(ctx_obj, spec, output, design_style, target, max_rounds, dry_run, json_output):
    """一站式验证闭环：从 Spec 到签核报告（覆盖率驱动）"""
    out = get_output_adapter(json_output)

    click.echo()
    click.echo("🧠 SignOffAI 验证闭环计划")
    click.echo(f"   Spec:        {spec}")
    click.echo(f"   设计风格:    {design_style}")
    click.echo(f"   覆盖率目标:  {target or '默认(配置)'}")
    click.echo(f"   最大轮次:    {max_rounds}")
    click.echo()
    for i, role in enumerate(AGENT_ALIASES.keys(), 1):
        click.echo(f"   [{i}/{len(AGENT_ALIASES)}] {role}")

    if dry_run:
        click.echo()
        click.echo("📋 Dry-run 模式，不执行。")
        return

    click.echo()
    click.echo("▶️ 开始执行...")
    ctx_obj.invoke(
        verify,
        spec_file=spec, output=output, design_style=design_style,
        # 不再硬编码 auto：plan 之前强行全放行，且 plan 自身没有 --approval 开关，
        # 用户无从覆盖。现在沿用 verify 的默认档（threshold）。
        target=target, max_rounds=max_rounds,
        json_output=json_output, summary=False, quiet=False,
    )


# vagent signoff — 签核命令 (P0)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def signoff():
    """签核报告生成与证据链管理"""
    pass


@signoff.command("generate")
@click.argument("run_id", required=False)
@click.option("--type", "-t", "report_type", default="milestone",
              type=click.Choice(["tapeout", "milestone", "interim", "final"]),
              help="签核类型")
@click.option("--title", help="签核标题")
@click.option("--project-id", type=int, help="项目 ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_generate(run_id, report_type, title, project_id, json_output):
    """为指定 run 生成签核报告

    \b
    示例:
      vagent signoff generate <run_id>                     # 里程碑签核
      vagent signoff generate <run_id> --type tapeout      # 流片签核
      vagent signoff generate <run_id> --type final        # 最终签核
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified and no runs found")
        sys.exit(1)

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))

        title_text = title or f"Signoff: {report_type} — {rid}"
        out.print_result({
            "run_id": rid,
            "title": title_text,
            "type": report_type,
            "state": manifest.state,
            "overall_score": manifest.overall_score,
            "passed": manifest.passed,
            "total": manifest.total_phases,
            "evidence_hash": manifest.evidence_hash[:16] if manifest.evidence_hash else "N/A",
            "generated_at": manifest.generated_at,
        }, title=f"Signoff Report — {report_type}")

        # 持久化到 DB
        if project_id:
            try:
                from src.layers.l4_memory.persistence.repository import create_signoff
                import asyncio as _a
                sid = _a.run(create_signoff(
                    project_id=project_id, title=title_text,
                    report_type=report_type,
                    summary={"run_id": rid, "score": manifest.overall_score,
                             "passed": manifest.passed, "total": manifest.total_phases},
                    requester_id=1, run_id=rid,
                    manifest_hash=manifest.manifest_hash,
                ))
                out.print_success(f"Signoff saved to DB (id={sid})")
            except Exception as e:
                out.print_error(f"DB save failed: {e}")

    except Exception as e:
        out.print_error(f"Signoff generation failed: {e}")
        sys.exit(1)


@signoff.command("export")
@click.argument("run_id", required=False)
@click.option("--output", "-o", default="evidence.zip", help="输出 zip 路径")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_export(run_id, output, json_output):
    """导出签核证据包

    \b
    示例:
      vagent signoff export <run_id> -o evidence.zip
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        sys.exit(1)

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder, EvidencePackager
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))

        packager = EvidencePackager()
        zip_path = packager.package(manifest, Path(output))

        # Verify
        verify_result = packager.verify(zip_path)

        out.print_result({
            "zip_path": str(zip_path),
            "size_kb": round(zip_path.stat().st_size / 1024, 1),
            "valid": verify_result["valid"],
            "issues": verify_result["issues"],
            "manifest_hash": manifest.manifest_hash[:16] if manifest.manifest_hash else "N/A",
        }, title="Evidence Package Exported")

    except Exception as e:
        out.print_error(f"Export failed: {e}")
        sys.exit(1)


@signoff.command("verify")
@click.argument("run_id", required=False)
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_verify(run_id, json_output):
    """验证证据链完整性

    \b
    示例:
      vagent signoff verify <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        sys.exit(1)

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))

        issues = []
        if manifest.passed < manifest.total_phases:
            issues.append(f"{manifest.failed} phases failed")
        if manifest.overall_score < 50:
            issues.append(f"Overall score too low: {manifest.overall_score}")
        if not manifest.evidence_hash:
            issues.append("No evidence hash — artifacts may be incomplete")

        valid = len(issues) == 0
        out.print_result({
            "run_id": rid,
            "valid": valid,
            "issues": issues,
            "overall_score": manifest.overall_score,
            "passed": manifest.passed,
            "total": manifest.total_phases,
        }, title="Evidence Chain Verification")

    except Exception as e:
        out.print_error(f"Verification failed: {e}")
        sys.exit(1)


@signoff.command("checklist")
@click.argument("run_id", required=False)
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_checklist(run_id, json_output):
    """输出签核检查清单

    \b
    示例:
      vagent signoff checklist <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        sys.exit(1)

    checklist = [
        {"item": "Specification completeness", "required": True},
        {"item": "Design architecture review", "required": True},
        {"item": "UVM environment validation", "required": True},
        {"item": "Test point coverage ≥ 95%", "required": True},
        {"item": "Regression pass rate ≥ 99%", "required": False},
        {"item": "Code coverage ≥ 90%", "required": True},
        {"item": "Functional coverage ≥ 95%", "required": True},
        {"item": "Assertion coverage ≥ 80%", "required": False},
        {"item": "Debug analysis complete", "required": False},
        {"item": "QA review passed", "required": True},
        {"item": "Signoff report generated", "required": True},
    ]

    # ── 动态检查：Exclude 待审批未处理 → 阻断签核（放弃必须闭环：提议→审批）──
    exclude_pending = 0
    try:
        reg = _exclude_registry()
        exclude_pending = reg.stats().get("pending", 0)
        reg.close()
    except Exception:
        pass
    if exclude_pending:
        checklist.append({
            "item": f"Exclude 待审批未处理（{exclude_pending} 条，阻断）",
            "required": True, "pending_excludes": exclude_pending,
        })
    else:
        checklist.append({"item": "Exclude 无待审批（放弃已闭环）", "required": False})

    if json_output:
        click.echo(json.dumps({"run_id": rid, "checklist": checklist}, indent=2, ensure_ascii=False))
    else:
        table = Table(title=f"Signoff Checklist — {rid}")
        table.add_column("#")
        table.add_column("Item")
        table.add_column("Required")
        for i, item in enumerate(checklist, 1):
            req = "[red]Required[/red]" if item["required"] else "[dim]Optional[/dim]"
            table.add_row(str(i), item["item"], req)
        console.print(table)


@signoff.command("diff")
@click.argument("run_a")
@click.argument("run_b")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_diff(run_a, run_b, json_output):
    """两次签核对比

    \b
    示例:
      vagent signoff diff <run_id_a> <run_id_b>
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        diff = {
            "run_a": {"id": run_a, "score": ma.overall_score, "passed": ma.passed, "total": ma.total_phases},
            "run_b": {"id": run_b, "score": mb.overall_score, "passed": mb.passed, "total": mb.total_phases},
            "delta": {
                "score": mb.overall_score - ma.overall_score,
                "passed": mb.passed - ma.passed,
            },
        }
        out.print_result(diff, title="Signoff Diff")

    except Exception as e:
        out.print_error(f"Diff failed: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# vagent diff — 版本差异对比 (P0)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def diff():
    """版本差异对比"""
    pass


@diff.command("coverage")
@click.option("--run-a", required=True, help="Run A ID")
@click.option("--run-b", required=True, help="Run B ID")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json"]), help="输出格式")
def diff_coverage(run_a, run_b, fmt):
    """覆盖率对比

    \b
    示例:
      vagent diff coverage --run-a <id1> --run-b <id2>
      vagent diff coverage --run-a <id1> --run-b <id2> --format json
    """
    out = get_output_adapter(fmt == "json")
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        cov_a = ma.metadata.get("coverage", {})
        cov_b = mb.metadata.get("coverage", {})

        if isinstance(cov_a, dict) and isinstance(cov_b, dict):
            rows = [
                ["Line Coverage", f"{cov_a.get('line_pct', 0):.1f}%", f"{cov_b.get('line_pct', 0):.1f}%",
                 f"{cov_b.get('line_pct', 0) - cov_a.get('line_pct', 0):+.1f}%"],
                ["Branch Coverage", f"{cov_a.get('branch_pct', 0):.1f}%", f"{cov_b.get('branch_pct', 0):.1f}%",
                 f"{cov_b.get('branch_pct', 0) - cov_a.get('branch_pct', 0):+.1f}%"],
                ["Toggle Coverage", f"{cov_a.get('toggle_pct', 0):.1f}%", f"{cov_b.get('toggle_pct', 0):.1f}%",
                 f"{cov_b.get('toggle_pct', 0) - cov_a.get('toggle_pct', 0):+.1f}%"],
                ["Overall", f"{cov_a.get('coverage_pct', 0):.1f}%", f"{cov_b.get('coverage_pct', 0):.1f}%",
                 f"{cov_b.get('coverage_pct', 0) - cov_a.get('coverage_pct', 0):+.1f}%"],
            ]
            out.print_table(["Metric", f"Run A ({run_a[:12]})", f"Run B ({run_b[:12]})", "Delta"],
                            rows, title="Coverage Diff")
        else:
            out.print_error("Coverage data not available")

    except Exception as e:
        out.print_error(f"Diff failed: {e}")


@diff.command("spec")
@click.option("--old", "old_spec", required=True, type=click.Path(exists=True), help="旧规格文件")
@click.option("--new", "new_spec", required=True, type=click.Path(exists=True), help="新规格文件")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json"]), help="输出格式")
def diff_spec(old_spec, new_spec, fmt):
    """规格变更影响分析

    \b
    示例:
      vagent diff spec --old spec_v1.md --new spec_v2.md
    """
    out = get_output_adapter(fmt == "json")
    try:
        old_text = Path(old_spec).read_text(encoding="utf-8")
        new_text = Path(new_spec).read_text(encoding="utf-8")

        old_reqs = _extract_requirements_from_md(old_text)
        new_reqs = _extract_requirements_from_md(new_text)

        old_ids = {r["id"] for r in old_reqs}
        new_ids = {r["id"] for r in new_reqs}

        added = new_ids - old_ids
        removed = old_ids - new_ids
        kept = old_ids & new_ids

        out.print_result({
            "old_file": old_spec,
            "new_file": new_spec,
            "old_requirements": len(old_reqs),
            "new_requirements": len(new_reqs),
            "added": len(added),
            "removed": len(removed),
            "unchanged": len(kept),
            "added_list": sorted(added),
            "removed_list": sorted(removed),
        }, title="Spec Change Impact")

    except Exception as e:
        out.print_error(f"Spec diff failed: {e}")


@diff.command("regression")
@click.option("--run-a", required=True, help="Run A ID")
@click.option("--run-b", required=True, help="Run B ID")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json"]), help="输出格式")
def diff_regression(run_a, run_b, fmt):
    """回归结果对比

    \b
    示例:
      vagent diff regression --run-a <id1> --run-b <id2>
    """
    out = get_output_adapter(fmt == "json")
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        reg_a = ma.metadata.get("regression", {})
        reg_b = mb.metadata.get("regression", {})

        if isinstance(reg_a, dict) and isinstance(reg_b, dict):
            out.print_result({
                "run_a": {"passed": reg_a.get("passed", 0), "failed": reg_a.get("failed", 0),
                          "total": reg_a.get("total", 0)},
                "run_b": {"passed": reg_b.get("passed", 0), "failed": reg_b.get("failed", 0),
                          "total": reg_b.get("total", 0)},
                "delta_passed": reg_b.get("passed", 0) - reg_a.get("passed", 0),
                "delta_failed": reg_b.get("failed", 0) - reg_a.get("failed", 0),
            }, title="Regression Diff")
        else:
            out.print_error("Regression data not available")

    except Exception as e:
        out.print_error(f"Diff failed: {e}")


@diff.command("audit")
@click.option("--run-a", required=True, help="Run A ID (基准)")
@click.option("--run-b", required=True, help="Run B ID (对比)")
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "json", "detail"]), help="输出格式")
def diff_audit(run_a, run_b, fmt):
    """字段级审计 diff — 精确定位两次签核之间的差异

    \b
    示例:
      vagent diff audit --run-a run_20260810 --run-b run_20260812
      vagent diff audit --run-a run_20260810 --run-b run_20260812 --format json
      vagent diff audit --run-a run_20260810 --run-b run_20260812 --format detail

    输出: 每个阶段的字段级变更（added/removed/changed）
    """
    out = get_output_adapter(fmt == "json")
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder, EvidencePackager
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        diff = EvidencePackager.diff(ma, mb)

        if fmt == "json":
            out.print_result(diff)
        elif fmt == "detail":
            # 详细输出：每个字段的 hash 对比
            table = Table(title=f"Audit Diff: {run_a[:16]} vs {run_b[:16]}")
            table.add_column("Phase", style="cyan")
            table.add_column("Changed Fields", style="yellow")
            table.add_column("Added", style="green")
            table.add_column("Removed", style="red")
            table.add_column("Score Δ", style="magenta")

            for pname, pdiff in diff.get("phase_diffs", {}).items():
                changed = ", ".join(pdiff.get("changed_fields", [])[:5])
                if len(pdiff.get("changed_fields", [])) > 5:
                    changed += f" +{len(pdiff['changed_fields']) - 5} more"
                added = str(len(pdiff.get("added_fields", []))) if pdiff.get("added_fields") else "-"
                removed = str(len(pdiff.get("removed_fields", []))) if pdiff.get("removed_fields") else "-"
                score_d = pdiff.get("score_delta", 0)
                score_str = f"{score_d:+.0f}" if score_d != 0 else "-"
                table.add_row(pname, changed or "-", added, removed, score_str)

            console.print(table)
            console.print(f"\n[dim]{diff['summary']}[/dim]")
        else:
            # table: 简洁摘要
            rows = []
            has_changes = False
            for pname, pdiff in diff.get("phase_diffs", {}).items():
                n_changed = len(pdiff.get("changed_fields", []))
                n_added = len(pdiff.get("added_fields", []))
                n_removed = len(pdiff.get("removed_fields", []))
                if n_changed + n_added + n_removed > 0:
                    has_changes = True
                    rows.append([pname, str(n_changed), str(n_added), str(n_removed),
                                 str(pdiff.get("unchanged", 0)), f"{pdiff.get('score_delta', 0):+.0f}"])

            if rows:
                out.print_table(
                    ["Phase", "Changed", "Added", "Removed", "Unchanged", "Score Δ"],
                    rows, title="Field-Level Audit Diff"
                )
                console.print(f"\n[dim]{diff['summary']}[/dim]")
            else:
                console.print("[green]No field-level changes detected — runs are identical[/green]")

    except Exception as e:
        out.print_error(f"Audit diff failed: {e}")


def _extract_requirements_from_md(text: str) -> list:
    """从 Markdown 提取需求 ID"""
    import re
    reqs = []
    for match in re.finditer(r'\*\*(REQ_\w+)\*\*', text):
        reqs.append({"id": match.group(1), "line": text[:match.start()].count("\n") + 1})
    return reqs


# ═══════════════════════════════════════════════════════════════
# vagent dump — 复现 + 导出签核证据包
# ═══════════════════════════════════════════════════════════════

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
                    from src.layers.l4_memory.persistence.repository import get_pipeline_run_by_run_id
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
    from src.layers.l4_memory.debug_experience import get_debug_experience_store
    from src.layers.l4_memory.coverage_experience import get_coverage_experience_store

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


# ═══════════════════════════════════════════════════════════════
# vagent tool — 工具发现与直接调用 (P1)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def tool():
    """工具发现与直接调用"""
    pass


@tool.command("list")
@click.option("--agent", "-a", "agent_name", help="列出某 Agent 的工具")
@click.option("--risk", "-r", type=click.Choice(["safe", "write", "danger"]), help="按风险等级过滤")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def tool_list(agent_name, risk, json_output):
    """列出所有已注册工具

    \b
    示例:
      vagent tool list                              # 所有工具
      vagent tool list --agent verify_architect     # 某 Agent 的工具
      vagent tool list --risk safe                  # 按风险等级过滤
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    all_tools = []
    for role, agent in app.registry.get_all_instances().items():
        if agent_name and role != agent_name and agent_name != role:
            continue
        for t in (agent.tools or []):
            tname = getattr(t, "name", str(t))
            tdesc = getattr(t, "description", "") or ""
            ttype = type(t).__name__
            # Determine risk from tool_system if registered
            risk_level = "safe"  # default
            all_tools.append({
                "name": tname, "description": str(tdesc)[:100],
                "agent": role, "type": ttype, "risk": risk_level,
            })

    if risk:
        all_tools = [t for t in all_tools if t["risk"] == risk]

    out.print_table(
        ["Tool", "Agent", "Risk", "Description"],
        [[t["name"], t["agent"], t["risk"], t["description"]] for t in all_tools],
        title=f"Tools ({len(all_tools)} registered)"
    )


@tool.command("show")
@click.argument("tool_name")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def tool_show(tool_name, json_output):
    """查看工具详情（Schema/描述/风险等级）

    \b
    示例:
      vagent tool show run_vcs
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    for role, agent in app.registry.get_all_instances().items():
        for t in (agent.tools or []):
            tname = getattr(t, "name", str(t))
            if tname == tool_name:
                info = {
                    "name": tname,
                    "description": getattr(t, "description", ""),
                    "agent": role,
                    "type": type(t).__name__,
                    "has_schema": hasattr(t, "args_schema"),
                }
                if hasattr(t, "args_schema") and t.args_schema:
                    info["schema"] = str(t.args_schema.schema())[:500]
                out.print_result(info, title=f"Tool: {tool_name}")
                return
    out.print_error(f"Tool '{tool_name}' not found")


@tool.command("call")
@click.argument("tool_name")
@click.option("--args", "-a", default="{}", help="JSON 参数字符串")
@click.option("--gap", help="Coverage gap 参数 (gen_test_sv)")
@click.option("--out", "out_path", help="输出路径参数")
@click.option("--path", help="文件路径参数 (read_report)")
def tool_call(tool_name, args, gap, out_path, path):
    """直接调用工具（绕过 LLM）

    \b
    示例:
      vagent tool call gen_test_sv --gap burst_16 --out test.sv
      vagent tool call read_report --path output/coverage.json
      vagent tool call run_vcs --args '{"tb":"tb_top.sv"}'
    """
    app = VerificationCLI()
    asyncio.run(app.initialize())

    for role, agent in app.registry.get_all_instances().items():
        for t in (agent.tools or []):
            tname = getattr(t, "name", str(t))
            if tname != tool_name:
                continue
            func = getattr(t, "func", None) or t

            # Build args
            call_args = {}
            try:
                call_args = json.loads(args)
            except json.JSONDecodeError:
                pass
            if gap:
                call_args["gap"] = gap
            if out_path:
                call_args["out_path"] = out_path
            if path:
                call_args["path"] = path

            try:
                if callable(func):
                    result = func(call_args.pop("input_str", str(call_args)), **call_args) if "input_str" in call_args else func(str(call_args))
                else:
                    result = str(t)
                console.print(Panel(str(result)[:2000], title=f"[yellow]{tool_name}[/yellow] ({role})"))
            except Exception as e:
                # Try simpler invocation
                try:
                    if callable(func):
                        result = func()
                        console.print(Panel(str(result)[:2000], title=f"[yellow]{tool_name}[/yellow] ({role})"))
                    else:
                        console.print(f"[red]Cannot call tool {tool_name}: {e}[/red]")
                except Exception as e2:
                    console.print(f"[red]Tool error: {e2}[/red]")
            return

    console.print(f"[red]Tool '{tool_name}' not found[/red]")


@tool.command("history")
@click.option("--limit", "-n", default=20, help="记录数量")
@click.option("--tool", "tool_filter", help="指定工具")
def tool_history(limit, tool_filter):
    """查看工具调用历史

    \b
    示例:
      vagent tool history                   # 最近 20 条
      vagent tool history --limit 50        # 最近 50 条
      vagent tool history --tool run_vcs    # 指定工具
    """
    try:
        from src.layers.l2_orchestration.communication.tool_system import ToolRegistry
        # 工具调用历史通过 debug_logger 追踪
        console.print("[dim]Tool call history:[/dim]")
        from src.layers.l2_orchestration.middleware.debug_logger import tracer
        # tracer doesn't have tool history directly, use file-based approach
        log_dir = Path("logs/execution")
        if log_dir.exists():
            for f in sorted(log_dir.glob("exec_*.jsonl"), reverse=True)[:3]:
                content = f.read_text(encoding="utf-8")
                for line in content.strip().split("\n")[:limit]:
                    try:
                        entry = json.loads(line)
                        if entry.get("event") == "tool_call":
                            tname = entry.get("tool", "?")
                            if tool_filter and tname != tool_filter:
                                continue
                            console.print(f"  [cyan]{entry.get('timestamp','')[:19]}[/cyan] "
                                          f"[yellow]{tname}[/yellow] by {entry.get('agent','')} "
                                          f"({entry.get('elapsed',0):.1f}s)")
                    except Exception:
                        pass
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ═══════════════════════════════════════════════════════════════
# vagent agent — Agent 管理命令组 (P1)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def agent():
    """Agent 管理与单独执行"""
    pass


@agent.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def agent_list(json_output):
    """列出所有 Agent + 摘要

    \b
    示例:
      vagent agent list
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    rows = []
    for alias, role in AGENT_ALIASES.items():
        inst = app.registry.get_agent_instance(role)
        if inst:
            m = inst.get_metrics()
            tool_count = len(inst.tools or [])
            produces = getattr(inst, "produces", "-") or "-"
            consumes = ", ".join(getattr(inst, "consumes", []) or []) or "-"
            rows.append([
                alias, inst.display_name, m.get("status", "?"),
                produces, consumes, str(tool_count),
                str(m.get("tasks_completed", 0)),
            ])
    out.print_table(
        ["Alias", "Name", "Status", "Produces", "Consumes", "Tools", "Tasks"],
        rows, title="Agent Overview"
    )


@agent.command("show")
@click.argument("role")
@click.option("--tools", is_flag=True, help="列出该 Agent 的工具")
@click.option("--contract", is_flag=True, help="显示 consumes/produces/min_score")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def agent_show(role, tools, contract, json_output):
    """查看单个 Agent 详情

    \b
    示例:
      vagent agent show spec                    # 查看 spec agent
      vagent agent show spec --tools            # 列出工具
      vagent agent show spec --contract         # 显示 I/O 契约
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    resolved_role = role
    inst = app.registry.get_agent_instance(resolved_role)
    if not inst:
        out.print_error(f"Agent '{role}' not found. Available: {', '.join(AGENT_ALIASES.keys())}")
        return

    info = {
        "alias": role,
        "role": resolved_role,
        "display_name": inst.display_name,
        "description": inst.description,
        "status": inst.status.value if hasattr(inst.status, "value") else str(inst.status),
        "task_type": getattr(inst, "task_type", "N/A"),
        "produces": getattr(inst, "produces", "-"),
        "consumes": getattr(inst, "consumes", []),
        "min_score": getattr(inst, "min_score", 50),
        "max_retries": getattr(inst, "max_retries", 2),
        "metrics": inst.get_metrics(),
    }

    if tools:
        tool_list = []
        for t in (inst.tools or []):
            tname = getattr(t, "name", str(t))
            tdesc = getattr(t, "description", "") or ""
            tool_list.append({"name": tname, "description": str(tdesc)[:120]})
        info["tools"] = tool_list

    out.print_result(info, title=f"Agent: {inst.display_name}")


@agent.command("run")
@click.argument("role")
@click.option("--input", "-i", "input_text", help="JSON 输入文本")
@click.option("--spec", "-s", "spec_file", type=click.Path(exists=True), help="从文件读取输入")
@click.option("--dry-run", is_flag=True, help="不真正执行，只打印会调用哪些工具")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def agent_run(role, input_text, spec_file, dry_run, json_output):
    """单独执行某个 Agent

    \b
    示例:
      vagent agent run spec --input '{"spec":{"features":["add","sub"]}}'
      vagent agent run spec --spec alu_spec.md
      vagent agent run spec --spec alu_spec.md --dry-run
    """
    out = get_output_adapter(json_output)
    resolved_role = role
    service = PipelineExecutionService.get_instance()

    if dry_run:
        app = VerificationCLI()
        asyncio.run(app.initialize())
        inst = app.registry.get_agent_instance(resolved_role)
        if not inst:
            out.print_error(f"Agent '{role}' not found")
            return
        tool_names = [getattr(t, "name", str(t)) for t in (inst.tools or [])]
        consumes = getattr(inst, "consumes", [])
        produces = getattr(inst, "produces", "-")
        out.print_result({
            "agent": role,
            "tools_will_call": tool_names,
            "consumes": consumes,
            "produces": produces,
        }, title=f"Dry Run: {inst.display_name}")
        return

    input_content = input_text or ""
    if spec_file:
        input_content = Path(spec_file).read_text(encoding="utf-8")

    if not input_content:
        out.print_error("No input provided. Use --input or --spec.")
        return

    async def run():
        result = await service.run_single_agent(resolved_role, input_content)
        return result

    result = asyncio.run(run())

    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    elif result["success"]:
        output = result.get("output", "")
        console.print(Panel(str(output)[:2000], title=f"[green]{role} output[/green]"))
    else:
        out.print_error(result.get("error", "Unknown error"))


# ═══════════════════════════════════════════════════════════════
# vagent debug — 调试命令增强 (P1, 替换 debug_log)
# ═══════════════════════════════════════════════════════════════

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
    from src.layers.l4_memory.debug_experience import get_debug_experience_store
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


# ═══════════════════════════════════════════════════════════════
# vagent repl — 向后兼容别名
# ═══════════════════════════════════════════════════════════════

@cli.command(hidden=True)
def repl():
    """向后兼容: 使用 vagent debug repl"""
    console.print("[dim]Note: 'vagent repl' is deprecated. Use 'vagent debug repl' instead.[/dim]")
    ctx = click.Context(debug_repl)
    debug_repl.invoke(ctx)


# ═══════════════════════════════════════════════════════════════
# vagent config — 配置管理 (P2)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def config():
    """配置管理"""
    pass


@config.command("show")
@click.option("--section", "-s", help="只看某配置段: llm, agent, db, verify, platform")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def config_show(section, json_output):
    """显示当前配置

    \b
    示例:
      vagent config show                   # 全部配置
      vagent config show --section llm     # LLM 配置
      vagent config show --section agent   # Agent 配置
    """
    out = get_output_adapter(json_output)
    from config.settings import Settings
    s = Settings.get_instance()

    all_config = {
        "llm": {
            "provider": s.llm.provider,
            "model": s.llm.model,
            "temperature": s.llm.temperature,
            "max_tokens": s.llm.max_tokens,
            "base_url": s.llm.base_url,
        },
        "agent": {
            "max_agents": s.agent.max_agents,
            "max_iterations": s.agent.max_iterations,
            "timeout": s.agent.timeout,
            "verbose": s.agent.verbose,
            "fallback_on_llm_error": s.agent.fallback_on_llm_error,
        },
        "database": {
            "url": s.database.url,
            "echo": s.database.echo,
        },
        "verification": {
            "regression_timeout": s.verification.regression_timeout,
            "coverage_target": s.verification.coverage_target,
            "max_retries": s.verification.max_retries,
        },
        "platform": {
            "env": s.platform.env,
            "demo_enabled": s.platform.demo_enabled,
            "audit_retention_days": s.platform.audit_retention_days,
        },
    }

    if section:
        if section in all_config:
            out.print_result({section: all_config[section]}, title=f"Config: {section}")
        else:
            out.print_error(f"Unknown section: {section}. Available: {', '.join(all_config.keys())}")
    else:
        out.print_result(all_config, title="Current Configuration")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """修改配置

    \b
    示例:
      vagent config set llm.model deepseek-flash
      vagent config set llm.temperature 0.3
      vagent config set agent.max_iterations 10

    注意: 此命令修改的是运行时环境变量，持久化需手动编辑 .env 文件。
    """
    # Map key → env var
    env_map = {
        "llm.model": "LLM_MODEL",
        "llm.temperature": "LLM_TEMPERATURE",
        "llm.max_tokens": "LLM_MAX_TOKENS",
        "llm.api_key": "LLM_API_KEY",
        "llm.base_url": "LLM_BASE_URL",
        "agent.max_iterations": "AGENT_MAX_ITERATIONS",
        "agent.verbose": "AGENT_VERBOSE",
        "agent.timeout": "AGENT_TIMEOUT",
        "agent.fallback_on_llm_error": "AGENT_FALLBACK_ON_LLM_ERROR",
        "verify.coverage_target": "VERIFY_COVERAGE_TARGET",
        "verify.max_retries": "VERIFY_MAX_RETRIES",
        "db.url": "DB_URL",
        "platform.env": "PLATFORM_ENV",
    }

    env_var = env_map.get(key)
    if not env_var:
        console.print(f"[red]Unknown config key: {key}[/red]")
        console.print(f"[dim]Available: {', '.join(env_map.keys())}[/dim]")
        return

    os.environ[env_var] = value
    console.print(f"[green]Set {key} = {value} (env: {env_var})[/green]")
    console.print(f"[dim]Note: This only affects the current session. Edit .env for persistence.[/dim]")


@config.command("init")
def config_init():
    """生成默认 .env 文件"""
    env_path = Path(".env")
    if env_path.exists():
        console.print(f"[yellow].env already exists at {env_path.absolute()}[/yellow]")
        if click.confirm("Overwrite?"):
            pass
        else:
            return

    template = """# SignOffAI Configuration
# Generated by: vagent config init

# LLM Provider
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-flash
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com/v1

# Agent Settings
AGENT_MAX_ITERATIONS=8
AGENT_TIMEOUT=300
AGENT_VERBOSE=true
AGENT_FALLBACK_ON_LLM_ERROR=true

# Verification
VERIFY_COVERAGE_TARGET=95.0
VERIFY_MAX_RETRIES=3

# Database
DB_URL=sqlite+aiosqlite:///ic_verification.db

# Platform
PLATFORM_ENV=development
PLATFORM_DEMO_ENABLED=true
"""
    env_path.write_text(template, encoding="utf-8")
    console.print(f"[green].env file created at {env_path.absolute()}[/green]")


@config.command("validate")
def config_validate():
    """校验配置完整性"""
    from config.settings import Settings
    try:
        s = Settings.get_instance()
        issues = []

        if s.is_production:
            if not s.platform.jwt_secret:
                issues.append("PLATFORM_JWT_SECRET not set (production)")
            if not s.llm.api_key:
                issues.append("LLM_API_KEY not set (production)")
            if s.platform.demo_enabled:
                issues.append("PLATFORM_DEMO_ENABLED=true in production")

            prod_issues = s.validate_production()
            issues.extend(prod_issues)

        if issues:
            console.print("[red]Configuration issues:[/red]")
            for i in issues:
                console.print(f"  [red]✗ {i}[/red]")
        else:
            console.print("[green]✓ Configuration is valid[/green]")

        console.print(f"[dim]Environment: {s.platform.env}[/dim]")
        console.print(f"[dim]LLM Provider: {s.llm.provider} / {s.llm.model}[/dim]")

    except Exception as e:
        console.print(f"[red]Configuration validation failed: {e}[/red]")


# ═══════════════════════════════════════════════════════════════
# vagent project — 项目管理 (P2)
# ═══════════════════════════════════════════════════════════════

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


def _get_git_info(cwd: Path) -> dict:
    try:
        import subprocess
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=str(cwd),
                                         text=True).strip()
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(cwd),
                                         text=True).strip()
        return {"branch": branch, "commit": commit}
    except Exception:
        return {"branch": "N/A", "commit": "N/A"}


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


# ═══════════════════════════════════════════════════════════════
# vagent spec — 规格文档操作 (P2)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def spec():
    """规格文档操作"""
    pass


@spec.command("analyze")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", default="rich",
              type=click.Choice(["rich", "json", "table"]), help="输出格式")
def spec_analyze(spec_file, fmt):
    """分析规格文档，输出结构化 JSON

    \b
    示例:
      vagent spec analyze spec.md                   # Rich 格式
      vagent spec analyze spec.md --format json     # JSON 格式
      vagent spec analyze spec.md --format table    # 表格格式
    """
    out = get_output_adapter(fmt == "json")
    content = Path(spec_file).read_text(encoding="utf-8")

    # Extract structured info
    import re
    title_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Untitled"

    # Features / sections
    sections = re.findall(r'^##\s+(.+)', content, re.MULTILINE)

    # Requirements
    reqs = _extract_requirements_from_md(content)

    # Interfaces
    interfaces = []
    for m in re.finditer(r'NAME:\s*(\S+).*?TYPE:\s*(\S+).*?WIDTH:\s*(\d+)', content, re.DOTALL):
        interfaces.append({"name": m.group(1), "type": m.group(2), "width": m.group(3)})

    result = {
        "file": spec_file,
        "title": title,
        "sections": sections,
        "requirement_count": len(reqs),
        "requirements": reqs[:20],
        "interface_count": len(interfaces),
        "interfaces": interfaces[:20],
        "size": len(content),
        "lines": content.count("\n") + 1,
    }

    out.print_result(result, title=f"Spec Analysis: {Path(spec_file).name}")


@spec.command("validate")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def spec_validate(spec_file, json_output):
    """校验规格文档完整性

    \b
    示例:
      vagent spec validate spec.md
    """
    out = get_output_adapter(json_output)
    content = Path(spec_file).read_text(encoding="utf-8")

    issues = []
    warnings = []

    # Check for title
    if not content.startswith("#"):
        issues.append("Missing top-level title (should start with '# Title')")

    # Check for sections
    import re
    sections = re.findall(r'^##\s+(.+)', content, re.MULTILINE)
    if not sections:
        warnings.append("No second-level sections found")

    # Check for requirements
    reqs = _extract_requirements_from_md(content)
    if not reqs:
        warnings.append("No requirements found (format: **REQ_xxx**)")

    # Check for interfaces
    if "NAME:" not in content:
        warnings.append("No interface definitions found (format: NAME: xxx, TYPE: xxx, WIDTH: n)")

    valid = len(issues) == 0
    result = {
        "file": spec_file,
        "valid": valid,
        "issues": issues,
        "warnings": warnings,
        "sections": len(sections),
        "requirements": len(reqs),
    }

    if valid:
        out.print_result(result, title=f"✓ Spec Valid: {Path(spec_file).name}")
    else:
        out.print_result(result, title=f"✗ Spec Issues: {Path(spec_file).name}")


@spec.command("convert")
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--to", "target_format", required=True,
              type=click.Choice(["json", "md"]), help="目标格式")
@click.option("--output", "-o", type=click.Path(), help="输出文件路径")
def spec_convert(input_file, target_format, output):
    """规格格式转换: MD ↔ JSON

    \b
    示例:
      vagent spec convert spec.md --to json -o spec.json
      vagent spec convert spec.json --to md -o spec.md
    """
    content = Path(input_file).read_text(encoding="utf-8")

    if target_format == "json":
        result = {
            "source": input_file,
            "content": content,
            "title": "",
            "requirements": _extract_requirements_from_md(content),
            "lines": content.count("\n") + 1,
        }
        # Extract title
        import re
        tm = re.search(r'^#\s+(.+)', content, re.MULTILINE)
        if tm:
            result["title"] = tm.group(1).strip()
        output_json = json.dumps(result, indent=2, ensure_ascii=False)

        if output:
            Path(output).write_text(output_json, encoding="utf-8")
            console.print(f"[green]Converted to JSON: {output}[/green]")
        else:
            click.echo(output_json)

    elif target_format == "md":
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            console.print("[red]Input is not valid JSON[/red]")
            return

        md_lines = [f"# {data.get('title', 'Untitled')}", ""]
        for req in data.get("requirements", []):
            md_lines.append(f"**{req.get('id', 'REQ_?')}**: {req.get('description', '')}")
        md_lines.append("")

        output_md = "\n".join(md_lines)
        if output:
            Path(output).write_text(output_md, encoding="utf-8")
            console.print(f"[green]Converted to MD: {output}[/green]")
        else:
            click.echo(output_md)


@spec.command("trace")
@click.argument("req_id")
@click.option("--full", is_flag=True, help="完整追溯链")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def spec_trace(req_id, full, json_output):
    """追溯需求 → 模块 → 测试点

    \b
    示例:
      vagent spec trace REQ_ALU_001               # 基础追溯
      vagent spec trace REQ_ALU_001 --full        # 完整追溯链
    """
    out = get_output_adapter(json_output)
    try:
        trace_result = asyncio.run(_trace_requirement(req_id))
        if not trace_result:
            out.print_error(f"Requirement '{req_id}' not found")
            return

        if full:
            out.print_result(trace_result, title=f"Full Trace: {req_id}")
        else:
            summary = {
                "req_id": trace_result.get("req_id", req_id),
                "description": trace_result.get("description", ""),
                "is_covered": trace_result.get("is_covered", False),
                "source_doc": trace_result.get("source_doc", {}),
            }
            out.print_result(summary, title=f"Trace: {req_id}")

    except Exception as e:
        out.print_error(f"Trace failed: {e}")


async def _trace_requirement(req_id: str):
    try:
        from src.layers.l4_memory.persistence.repository import get_requirement_trace
        return await get_requirement_trace(req_id)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# vagent ci — CI/CD 集成 (P3)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def ci():
    """CI/CD 集成命令"""
    pass


@ci.command("verify")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, default=True, help="JSON 输出 (CI 默认)")
@click.option("--junit", is_flag=True, help="输出 JUnit XML")
@click.option("--gitlab", is_flag=True, help="GitLab CI 格式")
@click.option("--quiet", "-q", is_flag=True, help="静默模式")
def ci_verify(spec_file, json_output, junit, gitlab, quiet):
    """CI 模式运行验证（最小化输出 + 退出码）

    \b
    示例:
      vagent ci verify spec.md                     # CI 默认 JSON
      vagent ci verify spec.md --junit              # JUnit XML
      vagent ci verify spec.md --gitlab             # GitLab CI 格式
    """
    service = PipelineExecutionService.get_instance()
    spec = Path(spec_file).read_text(encoding="utf-8")

    async def run():
        result = await service.run_closed_loop(spec_text=spec, output_root=None)
        return result

    result = asyncio.run(run())

    if junit:
        _output_junit(result)
    elif gitlab:
        _output_gitlab_ci(result)
    else:
        # Default JSON
        click.echo(json.dumps({
            "status": "PASS" if result["passed"] == result["total"] else "FAIL",
            "passed": result["passed"],
            "total": result["total"],
            "score": result["overall_score"],
            "run_id": result["run_id"],
            "phases": [{"name": p["name"], "status": p["status"], "score": p.get("score", 0)}
                       for p in result["phases"]],
        }, indent=2, ensure_ascii=False))

    sys.exit(0 if result["passed"] == result["total"] else 1)


def _output_junit(result: dict):
    """生成 JUnit XML"""
    import xml.etree.ElementTree as ET
    testsuite = ET.Element("testsuite", {
        "name": "SignOffAI",
        "tests": str(result["total"]),
        "failures": str(result["total"] - result["passed"]),
        "errors": "0",
        "time": str(sum(p.get("time", 0) for p in result["phases"])),
        "timestamp": datetime.now().isoformat(),
    })
    for p in result["phases"]:
        testcase = ET.SubElement(testsuite, "testcase", {
            "classname": "SignOffAI.phase",
            "name": p["name"],
            "time": str(p.get("time", 0)),
        })
        if p["status"] in ("failed", "error"):
            ET.SubElement(testcase, "failure", {
                "message": f"Phase {p['name']} {p['status']}",
                "type": p["status"],
            })
    click.echo(ET.tostring(testsuite, encoding="unicode"))


def _output_gitlab_ci(result: dict):
    """输出 GitLab CI 格式报告"""
    passed = result["passed"]
    total = result["total"]
    score = result["overall_score"]

    metrics = [
        f"signoffai_passed {passed}",
        f"signoffai_total {total}",
        f"signoffai_score {score}",
    ]
    for p in result["phases"]:
        name = p["name"].lower()
        metrics.append(f"signoffai_phase_{name}_score {p.get('score', 0)}")

    click.echo("\n".join(metrics))
    click.echo(f"\n# SignOffAI Report: {passed}/{total} passed, Score: {score}/100")


@ci.command("check")
def ci_check():
    """检查 CI 环境是否就绪"""
    checks = {}

    # Python version
    checks["python"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    # Click installed
    try:
        import click
        checks["click"] = click.__version__
    except Exception:
        checks["click"] = "MISSING"

    # Rich installed
    try:
        import rich
        checks["rich"] = rich.__version__
    except Exception:
        checks["rich"] = "MISSING"

    # SQLAlchemy
    try:
        import sqlalchemy
        checks["sqlalchemy"] = sqlalchemy.__version__
    except Exception:
        checks["sqlalchemy"] = "MISSING"

    # Environment
    checks["platform_env"] = os.environ.get("PLATFORM_ENV", "development")
    checks["llm_provider"] = os.environ.get("LLM_PROVIDER", "deepseek")
    checks["ci"] = os.environ.get("CI", "false")

    all_ok = "MISSING" not in checks.values()
    status = "[green]READY[/green]" if all_ok else "[yellow]PARTIAL[/yellow]"
    console.print(f"CI Environment: {status}")
    for k, v in checks.items():
        color = "green" if v != "MISSING" else "red"
        console.print(f"  [{color}]{k}: {v}[/{color}]")


@ci.command("precheck")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def ci_precheck(spec_file, json_output):
    """预检查（不实际执行）

    \b
    示例:
      vagent ci precheck spec.md
    """
    out = get_output_adapter(json_output)
    spec_path = Path(spec_file)
    content = spec_path.read_text(encoding="utf-8")

    checks = {
        "spec_exists": spec_path.exists(),
        "spec_size": spec_path.stat().st_size,
        "has_title": content.startswith("#"),
        "has_requirements": "**REQ_" in content,
        "has_interfaces": "NAME:" in content,
        "spec_lines": content.count("\n") + 1,
    }

    all_ok = all(checks.values()) if all(isinstance(v, bool) for v in [
        checks["spec_exists"], checks["has_title"],
        checks["has_requirements"], checks["has_interfaces"],
    ]) else False

    result = {"ready": all_ok, "checks": checks}
    out.print_result(result, title="CI Precheck")


# ═══════════════════════════════════════════════════════════════
# vagent regression — 回归管理 (P3)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def regression():
    """回归管理"""
    pass


# ── 分级回归：看各级状态 / 人工放行 ─────────────────────────────
#
# 分级回归（loopback → p0 → p1 → p2 → p3）在 loopback 全过之后有**人工节点**：
# 那级证的是"TB 自身自洽"（driver 发出的 == slave monitor 看到的），要不要接着
# 烧 P0 的机时由人拍。下面两个子命令就是那个人拍板的入口。

def _staged_doc(output_dir: str) -> dict:
    """读 run 目录下的分级结果 + 放行记录（都不存在就返回空）。"""
    root = Path(output_dir)
    doc: dict = {"stages": [], "approvals": []}
    for key, fname in (("stages", "regression_stages.json"),
                       ("approvals", "regression_approvals.json")):
        p = root / fname
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:                       # noqa: BLE001 坏文件当没有
            console.print(f"[yellow]⚠ 解析 {fname} 失败：{exc}[/yellow]")
            continue
        # 放行记录的数组键也叫 `approvals`，分级结果的叫 `stages` —— 用同一个 key 取
        doc[key] = data.get(key) or []
        if key == "stages":
            for k in ("status", "blocked_at", "blocked_reason", "awaiting"):
                if k in data:
                    doc[k] = data[k]
    return doc


@regression.command("stages")
@click.option("--output", "-o", "output_dir", type=click.Path(), help="输出目录（run 目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def regression_stages(output_dir, json_output):
    """看分级回归跑到哪一级、卡在哪、人工节点放行了没有。"""
    if not output_dir:
        console.print("[red]需要 --output 指定 run 目录，如 -o output_xxx[/red]")
        return
    doc = _staged_doc(output_dir)
    if json_output:
        click.echo(json.dumps(doc, ensure_ascii=False, indent=2))
        return
    if not doc["stages"]:
        console.print("[yellow]没找到分级结果（"
                      f"{Path(output_dir) / 'regression_stages.json'}）[/yellow]")
        return
    style = {"PASS": "[green]PASS[/green]", "FAIL": "[red]FAIL[/red]",
             "EMPTY": "[yellow]EMPTY[/yellow]",
             "WAITING_APPROVAL": "[cyan]待放行[/cyan]"}
    done = {a.get("after") for a in doc["approvals"]}
    console.print(f"\n[bold]分级回归[/bold]  "
                  f"status={style.get(doc.get('status', ''), doc.get('status'))}")
    for s in doc["stages"]:
        mark = "[cyan]✔已放行[/cyan]" if s["name"] in done else ""
        console.print(f"  {s['name']:<9} {style.get(s['status'], s['status']):<32}"
                      f" passed={s.get('passed', 0)} failed={s.get('failed', 0)}"
                      f" unknown={s.get('unknown', 0)}  {mark}")
    if doc.get("status") == "WAITING_APPROVAL" and doc.get("awaiting"):
        aw = doc["awaiting"]
        if aw["after"] in done:
            console.print(f"\n[green]{aw['after']} 已放行[/green] —— 重跑分级回归即从 "
                          f"{aw['next']} 继续（已过的级会重跑一遍）")
        else:
            console.print(f"\n[cyan]停在人工节点：{aw['after']} 已全过，"
                          f"进 {aw['next']} 前需人工放行[/cyan]")
            console.print(f"  {aw.get('hint', '')}")


@regression.command("approve")
@click.option("--output", "-o", "output_dir", type=click.Path(), help="输出目录（run 目录）")
@click.option("--after", "after", default="loopback", show_default=True,
              help="放行哪一级")
@click.option("--by", "approver", default="", help="审批人（必填，写进审计记录）")
@click.option("--note", default="", help="审批意见")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def regression_approve(output_dir, after, approver, note, json_output):
    """人工放行某一级，之后重跑分级回归即可进下一级。

    放行记录**绑定证据**（那一级的 total/passed/failed）—— 结果变了要重新批，
    批的永远是"你当时看到的那一份结果"。
    """
    if not output_dir or not approver:
        console.print("[red]需要 --output 指定 run 目录、--by 指定审批人[/red]")
        return
    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    infra = InfrastructureManager(output_dir)
    try:
        entry = infra.approve_stage(after, approver=approver, note=note)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    if json_output:
        click.echo(json.dumps(entry, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✔ 已放行 {after}[/green] → 下一步可进 "
                  f"{entry.get('next') or '（无）'}")
    console.print(f"  审批人 {entry['approver']} @ {entry['at']}"
                  + (f"　意见：{entry['note']}" if entry["note"] else ""))
    console.print(f"  记录：{Path(output_dir) / 'regression_approvals.json'}")


@regression.command("run")
@click.option("--tests", "-t", type=click.Path(exists=True), help="测试 YAML 配置")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_run(tests, json_output):
    """运行回归测试

    \b
    示例:
      vagent regression run --tests regression.yaml
    """
    out = get_output_adapter(json_output)
    if tests:
        config = Path(tests).read_text(encoding="utf-8")
        out.print_result({"config_file": tests, "size": len(config)},
                         title="Regression Config Loaded")
        console.print("[yellow]Regression execution requires active verification environment.[/yellow]")
        console.print("[dim]Use 'vagent verify <spec> --step regress' for full regression.[/dim]")
    else:
        out.print_error("Use --tests <yaml_file>")


@regression.command("report")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_report(run_id, json_output):
    """回归报告

    \b
    示例:
      vagent regression report --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l4_memory.persistence.repository import get_regression_history
        history = asyncio.run(get_regression_history())
        if history:
            latest = history[0]
            out.print_result(latest, title=f"Regression Report — {rid}")
        else:
            out.print_success("No regression history in DB")
    except Exception as e:
        out.print_error(str(e))


@regression.command("trend")
@click.option("--days", "-d", default=30, help="天数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_trend(days, json_output):
    """回归趋势

    \b
    示例:
      vagent regression trend --days 30
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l4_memory.persistence.repository import get_regression_trend
        trend = asyncio.run(get_regression_trend(days=days))
        if trend:
            out.print_result({"days": days, "data_points": len(trend), "trend": trend},
                             title=f"Regression Trend ({days}d)")
        else:
            out.print_success("No data for trend analysis")
    except Exception as e:
        out.print_error(str(e))


@regression.command("compare")
@click.option("--run-a", required=True, help="Run A ID")
@click.option("--run-b", required=True, help="Run B ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_compare(run_a, run_b, json_output):
    """两次回归对比

    \b
    示例:
      vagent regression compare --run-a <id1> --run-b <id2>
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        reg_a = ma.metadata.get("regression", {})
        reg_b = mb.metadata.get("regression", {})

        out.print_result({
            "run_a": {"id": run_a, "passed": reg_a.get("passed", "?"), "total": reg_a.get("total", "?")},
            "run_b": {"id": run_b, "passed": reg_b.get("passed", "?"), "total": reg_b.get("total", "?")},
        }, title="Regression Comparison")

    except Exception as e:
        out.print_error(str(e))


@regression.command("reference-finder")
@click.option("--repo", "-r", default=".", help="git 仓库路径（默认当前目录）")
@click.option("--good", required=True, help="已知通过的提交（起点）")
@click.option("--bad", default="HEAD", help="已知失败的提交（终点，默认 HEAD）")
@click.option("--config", "-c", "reg_yaml", required=True, type=click.Path(exists=True),
              help="回归配置 yaml（版本间保持同一份）")
@click.option("--test", "-t", "test_pattern", required=True, help="要复现的用例名/正则")
@click.option("--work-root", default=None, help="工作目录（worktree 与结论落这里）")
@click.option("--mode", type=click.Choice(["mock", "local"]), default="mock",
              help="执行模式（mock 只走流程不真跑 EDA）")
@click.option("--paths", default=None, help="逗号分隔，只考虑这些路径下的提交")
@click.option("--keep-worktrees", is_flag=True, help="保留各版本的 worktree（排查用，默认删）")
@click.option("--no-cache", is_flag=True, help="忽略结论缓存，强制重跑所有版本")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_reference_finder(repo, good, bad, reg_yaml, test_pattern, work_root,
                                mode, paths, keep_worktrees, no_cache, json_output):
    """溯源定位：哪个提交引入了这个失败

    在 good..bad 区间内二分，每个版本用独立 worktree 隔离后跑指定用例，
    收敛到第一个失败的提交。结论连同环境快照落盘，可审计。

    \b
    示例:
      vagent regression reference-finder \\
        --good v1.0 --bad HEAD --config regression.yaml --test smoke_basic
    """
    out = get_output_adapter(json_output)
    work_root = work_root or str(Path(repo) / "reference_finder_work")
    path_list = [p.strip() for p in paths.split(",") if p.strip()] if paths else None

    console.print(f"[dim]逐版本编译+仿真，请耐心；已跑过的版本会命中缓存。[/dim]")
    try:
        from src.layers.l1_infrastructure.reference_finder import ReferenceFinder
        finder = ReferenceFinder(
            repo_path=repo, work_root=work_root, reg_yaml=reg_yaml,
            test_pattern=test_pattern, mode=mode,
            keep_worktrees=keep_worktrees, use_cache=not no_cache, verbose=True)
        report = finder.find_first_bad(good, bad, paths=path_list)
    except Exception as e:
        out.print_error(str(e))
        return

    if json_output:
        out.print_result(report, title="Reference Finder")
        return

    if report.get("culprit"):
        console.print(f"\n[bold]引入提交[/bold]: [cyan]{report.get('culprit_short')}[/cyan] "
                      f"{report.get('subject', '')}")
        console.print(f"  最后一个好版本: {report.get('last_good_short')}")
        console.print(f"  置信度: [bold]{report.get('confidence')}[/bold]")
        if report.get("changed_files"):
            console.print("  改动文件: " + ", ".join(report["changed_files"][:8]))
    else:
        console.print(f"\n[yellow]未能定位[/yellow]: {report.get('reason', '')}")

    for c in report.get("caveats", []) or []:
        console.print(f"  [yellow]![/yellow] {c}")
    for x in report.get("inconclusive_revisions", []) or []:
        console.print(f"  [yellow]?[/yellow] {x['short']} inconclusive: {x['detail']}")

    console.print(f"\n[dim]结论: {work_root}/reference_finder_summary.md[/dim]")
    console.print(f"[dim]实测 {len(report.get('results', []))} 个版本，"
                  f"耗时 {report.get('elapsed_s')}s[/dim]")


# ═══════════════════════════════════════════════════════════════
# vagent coverage — 覆盖率管理 (P3)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def coverage():
    """覆盖率管理"""
    pass


@coverage.command("report")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_report(run_id, json_output):
    """覆盖率报告

    \b
    示例:
      vagent coverage report --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))
        cov = manifest.metadata.get("coverage", {})

        if isinstance(cov, dict) and cov:
            out.print_result({
                "run_id": rid,
                "line_coverage": f"{cov.get('line_pct', 0):.1f}%",
                "branch_coverage": f"{cov.get('branch_pct', 0):.1f}%",
                "toggle_coverage": f"{cov.get('toggle_pct', 0):.1f}%",
                "overall": f"{cov.get('coverage_pct', 0):.1f}%",
            }, title=f"Coverage Report — {rid}")
        else:
            out.print_error("Coverage data not available")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("gaps")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_gaps(run_id, json_output):
    """覆盖率缺口

    \b
    示例:
      vagent coverage gaps --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))
        cov = manifest.metadata.get("coverage", {})

        if isinstance(cov, dict):
            gaps = cov.get("gaps", [])
            suggestions = cov.get("suggestions", [])
            out.print_result({
                "run_id": rid,
                "gaps": gaps[:20],
                "suggestions": suggestions[:10],
                "gap_count": len(gaps),
            }, title=f"Coverage Gaps — {rid}")
        else:
            out.print_error("Coverage data not available")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("exclude")
@click.option("--coverage", "-c", type=float, default=None, help="当前覆盖率（%，配合 --total 计算有效覆盖率）")
@click.option("--total", "-t", type=int, default=None, help="总覆盖点数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_exclude(coverage, total, json_output):
    """覆盖率里的 Exclude 视图：已放弃点 + 待审批 + 有效覆盖率

    \b
    示例:
      vagent coverage exclude                              # 已放弃/待审批摘要
      vagent coverage exclude -c 95 -t 100                 # 附有效覆盖率
    """
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        approved = reg.get_approved_excludes()
        pending = reg.list_pending()
        stats = reg.stats()
        result = {
            "stats": stats,
            "approved_points": sorted(reg.get_excluded_points()),
            "pending": [{"exclude_id": p["exclude_id"], "coverage_point": p["coverage_point"],
                         "type": p["exclude_type"], "reason": p["reason"]} for p in pending],
        }
        if coverage is not None and total is not None:
            result["effective"] = {
                "raw_coverage": coverage, "total_points": total,
                "excluded": stats["excluded_points"],
                "effective_total": max(total - stats["excluded_points"], 1),
                "effective_coverage": reg.effective_coverage(coverage, total),
            }

        if json_output:
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            return

        console.print(f"[bold]覆盖率 Exclude 视图[/bold] — "
                      f"已放弃 {stats['excluded_points']} 点 | 待审批 {stats['pending']}")
        if coverage is not None and total is not None:
            eff = result["effective"]
            console.print(f"[cyan]有效覆盖率: {eff['raw_coverage']}% → {eff['effective_coverage']}%"
                          f"（分母 {eff['total_points']} → {eff['effective_total']}）[/cyan]")
        if approved:
            console.print(f"\n[yellow]已批准（生效）:[/yellow]")
            for e in approved:
                console.print(f"   {e['exclude_id']}  {e['coverage_point']}  ({e['exclude_type']})")
        if pending:
            console.print(f"\n[bold red]待审批（阻断签核）:[/bold red]")
            for p in pending:
                console.print(f"   {p['exclude_id']}  {p['coverage_point']}  ({p['exclude_type']}) — "
                              f"vagent exclude approve {p['exclude_id']}")
        if not approved and not pending:
            console.print("[dim]暂无 Exclude。闭环会自动发现结构性死代码并提议；也可手动 'vagent exclude propose'。[/dim]")
    finally:
        reg.close()


@coverage.command("trend")
@click.option("--days", "-d", default=30, help="天数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_trend(days, json_output):
    """覆盖率趋势

    \b
    示例:
      vagent coverage trend --days 30
    """
    out = get_output_adapter(json_output)
    # Use regression trend as proxy
    try:
        from src.layers.l4_memory.persistence.repository import get_regression_trend
        trend = asyncio.run(get_regression_trend(days=days))
        out.print_result({"days": days, "data_points": len(trend), "trend": trend},
                         title=f"Coverage Trend ({days}d)")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("merge")
@click.option("--runs", required=True, help="逗号分隔的 run IDs")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_merge(runs, json_output):
    """合并多次覆盖率

    \b
    示例:
      vagent coverage merge --runs run_a,run_b,run_c
    """
    out = get_output_adapter(json_output)
    run_list = [r.strip() for r in runs.split(",")]

    # Aggregate coverage data
    aggregated = {"line_pct": 0, "branch_pct": 0, "toggle_pct": 0, "coverage_pct": 0}
    count = 0

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        for rid in run_list:
            manifest = builder.build(session_id=rid.replace("run_", ""))
            cov = manifest.metadata.get("coverage", {})
            if isinstance(cov, dict) and cov:
                for key in aggregated:
                    aggregated[key] += cov.get(key, 0)
                count += 1

        if count > 0:
            for key in aggregated:
                aggregated[key] = round(aggregated[key] / count, 1)

        out.print_result({
            "runs": run_list,
            "run_count": count,
            "merged_coverage": aggregated,
        }, title="Merged Coverage")
    except Exception as e:
        out.print_error(str(e))


# ═══════════════════════════════════════════════════════════════
# vagent env — UVM 环境操作 (P3)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def env():
    """UVM 环境操作"""
    pass


@env.command("generate")
@click.option("--spec", "-s", "spec_file", type=click.Path(exists=True), required=True,
              help="规格文件")
@click.option("--output", "-o", default="output/uvm_env", help="输出目录")
def env_generate(spec_file, output):
    """生成 UVM 环境

    \b
    示例:
      vagent env generate --spec spec.md
    """
    from src.layers.l1_infrastructure.output_config import make_output_root
    output_dir = make_output_root(output) + "/uvm_env"
    console.print(f"[cyan]Generating UVM environment from {spec_file}...[/cyan]")
    console.print(f"[dim]Output: {output_dir}[/dim]")
    console.print("[yellow]Use 'vagent verify <spec> --step UVM' for full UVM environment generation.[/yellow]")


@env.command("validate")
@click.option("--dir", "-d", "env_dir", type=click.Path(exists=True), required=True,
              help="UVM 环境目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def env_validate(env_dir, json_output):
    """校验 UVM 环境

    \b
    示例:
      vagent env validate --dir output/agents
    """
    out = get_output_adapter(json_output)
    env_path = Path(env_dir)
    sv_files = list(env_path.rglob("*.sv"))
    pkg_files = list(env_path.rglob("*_pkg.sv"))
    issues = []

    if not sv_files:
        issues.append("No .sv files found")

    out.print_result({
        "directory": str(env_path),
        "sv_files": len(sv_files),
        "pkg_files": len(pkg_files),
        "issues": issues,
        "valid": len(issues) == 0,
    }, title=f"UVM Env Validation: {Path(env_dir).name}")


@env.command("compile")
@click.option("--dir", "-d", "env_dir", type=click.Path(exists=True), required=True,
              help="UVM 环境目录")
def env_compile(env_dir):
    """编译 UVM 环境

    \b
    示例:
      vagent env compile --dir output/agents
    """
    env_path = Path(env_dir)
    # 搜索 filelist.f（可能在 inputs/filelists/ 子目录下）
    filelists = list(env_path.glob("**/filelist.f"))
    if not filelists:
        console.print(f"[red]No filelist.f found in {env_dir}[/red]")
        return
    filelist = filelists[0]
    if len(filelists) > 1:
        console.print(f"[dim]Found {len(filelists)} filelists, using: {filelist}[/dim]")

    console.print(f"[cyan]Compiling with filelist: {filelist}[/cyan]")

    # 实际运行编译
    from src.tools.uvm_tools._tools_old import _build_filelist_for_tb, _run_compile_check
    from src.tools.lib.uvm_context import ctx as _uctx
    import json as _json

    output_dir = env_path
    # 尝试从 env.yaml 读取配置
    env_yaml = output_dir / "inputs" / "yaml" / "uvm" / "env.yaml"
    env_name = "dut_env"
    agents = []
    if env_yaml.exists():
        try:
            import yaml as _yaml
            with open(env_yaml, encoding="utf-8") as f:
                env_data = _yaml.safe_load(f)
            env_info = env_data.get("environment", {}) if isinstance(env_data, dict) else {}
            env_name = env_info.get("name", "dut_env")
            ag_list = env_info.get("agents", {})
            agents = list(ag_list.keys()) if isinstance(ag_list, dict) else []
        except Exception:
            pass

    if not agents:
        # 从 agents 目录推断
        ag_dir = output_dir / "agents"
        if ag_dir.exists():
            agents = [d.name for d in ag_dir.iterdir() if d.is_dir() and (d / f"{d.name}_pkg.sv").exists()]

    # _run_compile_check 期望 agents 是 [{"name": "xxx"}, ...] 格式
    agent_dicts = [{"name": a} for a in agents]
    _uctx.set(output_dir=str(output_dir), agents=agent_dicts, env_name=env_name)
    result = _run_compile_check(output_dir, agent_dicts, env_name)
    console.print(f"[bold]Compile:[/bold] {'PASS' if result.get('passed') else 'FAIL'}")
    console.print(f"  Errors: {result.get('errors', '?')}  Warnings: {result.get('warnings', '?')}")


@env.command("template")
@click.option("--type", "-t", "component_type", required=True,
              type=click.Choice(["agent", "scoreboard", "monitor", "driver", "sequence"]),
              help="组件类型")
@click.option("--name", "-n", required=True, help="组件名称")
@click.option("--output", "-o", default=".", help="输出目录")
def env_template(component_type, name, output):
    """生成单个 UVM 组件模板

    \b
    示例:
      vagent env template --type agent --name uart_rx
      vagent env template --type monitor --name axi_monitor
    """
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)

    templates = {
        "agent": (
            f"class {name}_agent extends uvm_agent;\n"
            f"  `uvm_component_utils({name}_agent)\n\n"
            f"  {name}_sequencer sqr;\n"
            f"  {name}_driver    drv;\n"
            f"  {name}_monitor   mon;\n\n"
            f"  function new(string name, uvm_component parent);\n"
            f"    super.new(name, parent);\n"
            f"  endfunction\n\n"
            f"  function void build_phase(uvm_phase phase);\n"
            f"    super.build_phase(phase);\n"
            f"    sqr = {name}_sequencer::type_id::create(\"sqr\", this);\n"
            f"    drv = {name}_driver::type_id::create(\"drv\", this);\n"
            f"    mon = {name}_monitor::type_id::create(\"mon\", this);\n"
            f"  endfunction\n\n"
            f"  function void connect_phase(uvm_phase phase);\n"
            f"    drv.seq_item_port.connect(sqr.seq_item_export);\n"
            f"  endfunction\n"
            f"endclass\n"
        ),
        "monitor": (
            f"class {name}_monitor extends uvm_monitor;\n"
            f"  `uvm_component_utils({name}_monitor)\n\n"
            f"  virtual {name}_if vif;\n\n"
            f"  function new(string name, uvm_component parent);\n"
            f"    super.new(name, parent);\n"
            f"  endfunction\n\n"
            f"  task run_phase(uvm_phase phase);\n"
            f"    forever begin\n"
            f"      @(posedge vif.clk);\n"
            f"      // Sample and write to analysis port\n"
            f"    end\n"
            f"  endtask\n"
            f"endclass\n"
        ),
    }

    content = templates.get(component_type, f"// {component_type} template: {name}\n")
    ext = ".sv" if component_type != "sequence" else ".sv"
    filename = f"{name}.sv"

    (out_dir / filename).write_text(content, encoding="utf-8")
    console.print(f"[green]Generated {component_type} template: {out_dir / filename}[/green]")


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


# ═══════════════════════════════════════════════════════════════
# vagent completion — Shell 自动补全
# ═══════════════════════════════════════════════════════════════

@cli.command(hidden=True)
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell):
    """生成 shell 自动补全脚本

    \b
    示例:
      vagent completion bash  > /etc/bash_completion.d/vagent
      vagent completion zsh   > ~/.zsh/completions/_vagent
      vagent completion fish  > ~/.config/fish/completions/vagent.fish
    """
    import os as _os
    prog_name = "vagent"

    if shell == "bash":
        click.echo(f"""
_vagent_completion() {{
    local IFS=$'\\n'
    COMPREPLY=($(env COMP_WORDS="${{COMP_WORDS[*]}}" \\
        COMP_CWORD=$COMP_CWORD \\
        _{prog_name.upper()}_COMPLETE=bash_complete $1))
    return 0
}}
complete -o nosort -F _vagent_completion {prog_name}
""")
    elif shell == "zsh":
        click.echo(f"""
#compdef {prog_name}
_vagent() {{
    local -a completions
    local -a completions_with_descriptions
    local -a response
    response=($({{env COMP_WORDS="${{words[*]}}" COMP_CWORD=$((CURRENT-1)) \\
        _{prog_name.upper()}_COMPLETE=zsh_complete {prog_name}}}))
    for key descr in ${{(kv)response}}; do
        if [[ "$descr" == "_" ]]; then
            completions+=("$key")
        else
            completions_with_descriptions+=("$key":"$descr")
        fi
    done
    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}}
compdef _vagent {prog_name}
""")
    elif shell == "fish":
        click.echo(f"""
function _{prog_name}_completion
    set -l response (env _{prog_name.upper()}_COMPLETE=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) {prog_name})
    for completion in $response
        echo $completion
    end
end
complete -f -c {prog_name} -a "(_{prog_name}_completion)"
""")


# ═══════════════════════════════════════════════════════════════
# vagent hub — ToolHub 管理 (Phase 1)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def hub():
    """统一工具注册中心管理"""
    pass


@hub.command("status")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def hub_status(json_output):
    """ToolHub 状态概览

    \b
    示例:
      vagent hub status
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        stats = hub.get_stats()
        result = {
            "total_tools": hub.tool_count,
            "categories": hub.categories,
            "tags": hub.tags,
            "tool_stats": stats,
            "agent_tools": {role: hub.list_by_agent(role) for role in
                           ["uvm", "test", "regress"]},
        }
        out.print_result(result, title="ToolHub Status")
    except Exception as e:
        out.print_error(str(e))


@hub.command("list")
@click.option("--agent", "-a", help="按 Agent 过滤")
@click.option("--tag", help="按标签过滤")
@click.option("--category", "-c", help="按分类过滤")
@click.option("--risk", type=click.Choice(["safe", "write", "danger"]), help="按风险等级过滤")
@click.option("--search", help="全文搜索")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def hub_list(agent, tag, category, risk, search, json_output):
    """列出所有已注册工具

    \b
    示例:
      vagent hub list                              # 所有工具
      vagent hub list --agent verify_architect     # 某 Agent
      vagent hub list --tag simulation             # 某标签
      vagent hub list --search vcs                 # 全文搜索
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        if search:
            manifests = hub.search(search)
        elif agent:
            manifests = hub.list_by_agent(agent)
        elif tag:
            manifests = hub.list_by_tag(tag)
        elif category:
            manifests = hub.list_by_category(category)
        elif risk:
            from src.layers.l2_orchestration.communication.tool_protocol import ToolRisk
            manifests = hub.list_by_risk(ToolRisk(risk))
        else:
            manifests = hub.list_all()

        rows = []
        for m in manifests:
            risk_icon = {"safe": "🟢", "write": "🟡", "danger": "🔴"}.get(m.risk_level.value, "⚪")
            rows.append([m.name, m.version, risk_icon, m.category or "-",
                         ", ".join(m.tags[:3]) or "-", m.description[:60]])
        out.print_table(
            ["Name", "Version", "Risk", "Category", "Tags", "Description"],
            rows, title=f"Tools ({len(rows)} registered)"
        )
    except Exception as e:
        out.print_error(str(e))


@hub.command("health")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def hub_health(json_output):
    """检查所有工具健康状态

    \b
    示例:
      vagent hub health
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        result = asyncio.run(hub.health_check())
        out.print_result(result, title="ToolHub Health Check")
    except Exception as e:
        out.print_error(str(e))


@hub.command("bootstrap")
def hub_bootstrap():
    """重新发现并加载所有工具（插件 + CLI + 内置）

    \b
    示例:
      vagent hub bootstrap
    """
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        # Reset
        hub._initialized = False
        hub._tools.clear()
        hub._manifests.clear()
        count = hub.bootstrap()
        console.print(f"[green]ToolHub bootstrapped: {count} tools loaded[/green]")
        console.print(f"  Categories: {hub.categories}")
        console.print(f"  Tags: {hub.tags[:20]}")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ═══════════════════════════════════════════════════════════════
# vagent plugin — 插件管理 (Phase 2)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def plugin():
    """插件管理"""
    pass


@plugin.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def plugin_list(json_output):
    """列出已安装插件

    \b
    示例:
      vagent plugin list
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.plugin_manager import PluginManager
        mgr = PluginManager()
        discovered = mgr.discover()

        rows = []
        for tool, roles in discovered:
            m = tool.manifest
            rows.append([m.name, m.version, m.author or "-", m.category or "-",
                         ", ".join(m.tags[:3]), "✅" if tool.check_health() else "❌"])
        out.print_table(["Name", "Version", "Author", "Category", "Tags", "Health"],
                        rows, title=f"Plugins ({len(rows)} discovered)")

        if mgr.errors:
            console.print("\n[yellow]Plugin errors:[/yellow]")
            for e in mgr.errors:
                console.print(f"  [red]{e['path']}: {e['error'][:120]}[/red]")
    except Exception as e:
        out.print_error(str(e))


@plugin.command("discover")
@click.option("--dir", "-d", "plugin_dir", help="扫描目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def plugin_discover(plugin_dir, json_output):
    """扫描插件目录

    \b
    示例:
      vagent plugin discover
      vagent plugin discover --dir ~/my_plugins
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.plugin_manager import PluginManager
        mgr = PluginManager()
        if plugin_dir:
            mgr.add_plugin_dir(plugin_dir)
        discovered = mgr.discover()

        out.print_result({
            "tools_found": len(discovered),
            "tools": [{"name": t.manifest.name, "version": t.manifest.version,
                       "category": t.manifest.category,
                       "tags": t.manifest.tags} for t, _ in discovered],
            "errors": mgr.errors,
            "plugin_dirs": mgr.plugin_dirs,
        }, title="Plugin Discovery")
    except Exception as e:
        out.print_error(str(e))


@plugin.command("install")
@click.argument("name")
@click.option("--version", "-v", help="版本")
@click.option("--upgrade", "-U", is_flag=True, help="升级")
def plugin_install(name, version, upgrade):
    """安装插件（从市场或本地）

    \b
    示例:
      vagent plugin install vcs_compile
      vagent plugin install vcs_compile --version 2.0.0
    """
    try:
        from src.layers.l2_orchestration.tool_marketplace import ToolMarketplace
        market = ToolMarketplace()
        success, msg = asyncio.run(market.install(name, version, upgrade))
        if success:
            console.print(f"[green]✓ {msg}[/green]")
        else:
            console.print(f"[red]✗ {msg}[/red]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@plugin.command("uninstall")
@click.argument("name")
def plugin_uninstall(name):
    """卸载插件

    \b
    示例:
      vagent plugin uninstall vcs_compile
    """
    try:
        from src.layers.l2_orchestration.tool_marketplace import ToolMarketplace
        market = ToolMarketplace()
        success, msg = market.uninstall(name)
        if success:
            console.print(f"[green]✓ {msg}[/green]")
        else:
            console.print(f"[red]✗ {msg}[/red]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@plugin.command("search")
@click.argument("query")
@click.option("--category", "-c", help="按分类过滤")
@click.option("--tag", help="按标签过滤")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def plugin_search(query, category, tag, json_output):
    """搜索工具市场

    \b
    示例:
      vagent plugin search vcs
      vagent plugin search compile --category simulation
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.tool_marketplace import ToolMarketplace
        market = ToolMarketplace()
        tags = [tag] if tag else None
        results = market.search(query, category=category, tags=tags)

        if json_output:
            click.echo(json.dumps([{
                "name": r.name, "version": r.version, "description": r.description,
                "author": r.author, "tags": r.tags, "category": r.category,
            } for r in results], indent=2, ensure_ascii=False))
        else:
            table = Table(title=f"Marketplace Search: '{query}'")
            table.add_column("Name", style="cyan")
            table.add_column("Version")
            table.add_column("Category")
            table.add_column("Description")
            for r in results[:20]:
                table.add_row(r.name, r.version, r.category or "-", r.description[:80])
            console.print(table)
    except Exception as e:
        out.print_error(str(e))


# ═══════════════════════════════════════════════════════════════
# vagent pipeline — 工具编排 (Phase 3)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def pipeline():
    """声明式工具编排"""
    pass


@pipeline.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def pipeline_list(json_output):
    """列出所有已注册流水线

    \b
    示例:
      vagent pipeline list
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.tool_orchestrator import ToolOrchestrator, BUILTIN_PIPELINES
        orch = ToolOrchestrator()

        # 注册内置流水线
        for name, pdef in BUILTIN_PIPELINES.items():
            orch.register_pipeline(pdef)

        rows = []
        for name, pdef in orch._pipelines.items():
            rows.append([name, pdef.version, pdef.description[:80],
                         str(len(pdef.steps)), ", ".join(s.id for s in pdef.steps[:5])])
        out.print_table(["Name", "Version", "Description", "Steps", "Step IDs"],
                        rows, title="Pipelines")
    except Exception as e:
        out.print_error(str(e))


@pipeline.command("run")
@click.argument("pipeline_name")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
@click.option("--dry-run", is_flag=True, help="只显示不执行")
def pipeline_run(pipeline_name, json_output, dry_run):
    """执行声明式工具流水线

    \b
    示例:
      vagent pipeline run uvm_quality_check
      vagent pipeline run code_generation --dry-run
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.tool_orchestrator import ToolOrchestrator, BUILTIN_PIPELINES
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        orch = ToolOrchestrator()
        for name, pdef in BUILTIN_PIPELINES.items():
            orch.register_pipeline(pdef)

        if dry_run:
            pipeline = orch._pipelines.get(pipeline_name)
            if not pipeline:
                out.print_error(f"Pipeline '{pipeline_name}' not found")
                return
            out.print_result({
                "name": pipeline.name,
                "steps": [{"id": s.id, "tool": s.tool, "depends_on": s.depends_on,
                           "condition": str(s.condition)} for s in pipeline.steps],
            }, title=f"Pipeline: {pipeline_name} (dry-run)")
            return

        def on_progress(step_id, status, msg):
            if not json_output:
                icon = {"running": "⏳", "passed": "✅", "failed": "❌"}.get(status, "·")
                console.print(f"  {icon} {step_id}: {msg}")

        result = asyncio.run(orch.run(pipeline_name, on_progress=on_progress))
        if json_output:
            click.echo(json.dumps({
                "pipeline": result.pipeline_name,
                "status": result.status.value,
                "passed": result.passed,
                "failed": result.failed,
                "skipped": result.skipped,
                "total_time_s": result.total_time_s,
                "steps": [{"id": s.step_id, "status": s.status.value, "elapsed_s": s.elapsed_s,
                           "error": s.error} for s in result.steps],
            }, indent=2, ensure_ascii=False))
        else:
            status_color = "green" if result.status.value == "passed" else "red"
            console.print(f"\n[bold {status_color}]Pipeline: {result.status.value}[/bold {status_color}]  "
                          f"({result.passed} passed, {result.failed} failed, "
                          f"{result.skipped} skipped, {result.total_time_s}s)")
    except Exception as e:
        out.print_error(str(e))


@pipeline.command("graph")
@click.argument("pipeline_name")
@click.option("--format", "-f", "fmt", default="mermaid",
              type=click.Choice(["mermaid", "dot"]), help="输出格式")
def pipeline_graph(pipeline_name, fmt):
    """生成流水线可视化图

    \b
    示例:
      vagent pipeline graph uvm_quality_check
      vagent pipeline graph uvm_quality_check --format dot
    """
    try:
        from src.layers.l2_orchestration.tool_orchestrator import ToolOrchestrator, BUILTIN_PIPELINES
        orch = ToolOrchestrator()
        for name, pdef in BUILTIN_PIPELINES.items():
            orch.register_pipeline(pdef)

        if fmt == "mermaid":
            click.echo(orch.to_mermaid(pipeline_name))
        else:
            click.echo(orch.to_dot(pipeline_name))
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ═══════════════════════════════════════════════════════════════
# vagent docs — 工具文档自动生成 (Phase 3)
# ═══════════════════════════════════════════════════════════════

@cli.group()
def docs():
    """文档自动生成"""
    pass


@docs.command("generate")
@click.option("--output", "-o", default="docs/tools", help="输出目录")
@click.option("--tool", help="只生成指定工具的文档")
def docs_generate(output, tool):
    """自动生成所有工具文档

    \b
    示例:
      vagent docs generate                     # 生成所有工具文档
      vagent docs generate --tool vcs_compile  # 只生成指定工具
      vagent docs generate -o docs/reference   # 指定输出目录
    """
    try:
        from src.layers.l2_orchestration.tool_doc_generator import ToolDocGenerator
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        gen = ToolDocGenerator(hub)

        if tool:
            manifest = hub.get_manifest(tool)
            if not manifest:
                console.print(f"[red]Tool '{tool}' not found[/red]")
                return
            md = gen.generate_tool_md(manifest)
            out_path = Path(output) / f"{tool}.md"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
            console.print(f"[green]Generated: {out_path}[/green]")
        else:
            results = gen.generate_all(output)
            console.print(f"[green]Generated {len(results)} files in {output}/[/green]")
            for name, path in sorted(results.items()):
                console.print(f"  [dim]{name}[/dim] → {path}")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@docs.command("preview")
@click.argument("tool_name")
def docs_preview(tool_name):
    """预览工具文档（终端输出）

    \b
    示例:
      vagent docs preview check_compile
    """
    try:
        from src.layers.l2_orchestration.tool_doc_generator import ToolDocGenerator
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        manifest = hub.get_manifest(tool_name)
        if not manifest:
            console.print(f"[red]Tool '{tool_name}' not found[/red]")
            return

        gen = ToolDocGenerator(hub)
        md = gen.generate_tool_md(manifest)
        console.print(Panel(md[:2000], title=f"Docs: {tool_name}"))
        if len(md) > 2000:
            console.print(f"[dim]... ({len(md)} chars total, use 'vagent docs generate --tool {tool_name}' for full)[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ═══════════════════════════════════════════════════════════════
# 业务 CLI 命令（RunRepository 磁盘扫描，面向工程师日常使用）
# ═══════════════════════════════════════════════════════════════

def _repo():
    from src.layers.l2_orchestration.run_repository import RunRepository
    return RunRepository("output")


def _resolve_run(repo, run_id):
    """解析 run_id：指定则用，否则取最新。"""
    if run_id:
        return run_id
    runs = repo.list_runs(1)
    return runs[0]["run_id"] if runs else None


# ── 查看与诊断类 ──

@cli.command("runs")
@click.option("--limit", "-n", default=20, help="显示数量")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def runs(limit, json_output):
    """列出所有 run（从 output 目录扫描：覆盖率/收敛/签核状态）"""
    out = get_output_adapter(json_output)
    repo = _repo()
    run_list = repo.list_runs(limit)
    if not run_list:
        out.print_success("无 run。先跑 'vagent verify' 或闭环。")
        return
    if json_output:
        click.echo(json.dumps(run_list, indent=2, ensure_ascii=False, default=str))
    else:
        rows = [[r["run_id"][:36], f"{r['final_coverage']}%",
                 "✓" if r["converged"] else "✗",
                 r.get("verdict", ""), r.get("signoff_status", "")] for r in run_list]
        out.print_table(["Run", "Coverage", "Converged", "Verdict", "Signoff"],
                        rows, title="Runs（磁盘扫描）")


@cli.command("logs")
@click.option("--run", "run_id", default="", help="run ID 或前缀（默认最新）")
@click.option("--stage", default="", help="阶段过滤（compile/sim/coverage）")
@click.option("--tail", "-t", default=0, help="只显示每个日志尾部 N 行")
def logs(run_id, stage, tail):
    """查看某 run 的日志文件"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    log_files = repo.logs(rid, stage)
    if not log_files:
        console.print("[yellow]无日志文件[/yellow]")
        return
    for lf in log_files:
        console.print(f"[cyan]{lf['name']}[/cyan] ({lf['size_kb']} KB)")
        if tail > 0:
            try:
                lines = Path(lf["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-tail:]:
                    console.print(f"  [dim]{line}[/dim]")
            except Exception:
                pass


@cli.command("show")
@click.option("--run", "run_id", default="", help="run ID 或前缀（默认最新）")
@click.option("--format", "fmt", default="json", type=click.Choice(["json"]), help="输出格式")
def show(run_id, fmt):
    """导出某 run 的完整结构数据（阶段/覆盖率/证据）"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run = repo.get_run(rid)
    click.echo(json.dumps(run, indent=2, ensure_ascii=False, default=str))


# ── 人工介入与修复类 ──

@cli.command("approve")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--reason", default="", help="审批理由（审计用）")
def approve(run_id, reason):
    """人工审批签核（记录理由，用于审计）"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    approval = {"action": "approve", "reason": reason,
                "at": datetime.now().isoformat(), "run": rid}
    (run_dir / "approval.json").write_text(
        json.dumps(approval, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]已审批 {rid[:32]}（理由: {reason or '无'}）[/green]")


@cli.command("reject")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--reason", default="", help="驳回理由（审计用）")
def reject(run_id, reason):
    """人工驳回签核（记录理由，用于审计）"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    approval = {"action": "reject", "reason": reason,
                "at": datetime.now().isoformat(), "run": rid}
    (run_dir / "approval.json").write_text(
        json.dumps(approval, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[red]已驳回 {rid[:32]}（理由: {reason or '无'}）[/red]")


@cli.command("patch")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--stage", default="", help="阶段名")
@click.option("--file", "file_path", default="", help="补丁文件路径")
def patch(run_id, stage, file_path):
    """记录人工补丁到 run（AI 修不好时的兜底，审计追踪）"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    patch_dir = run_dir / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "file": file_path,
              "at": datetime.now().isoformat(), "by": os.environ.get("USER", "engineer")}
    (patch_dir / f"patch_{int(time.time())}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]补丁已记录到 {rid[:32]}/patches/（stage={stage or 'any'}）[/green]")


# ── 归档与清理类 ──

@cli.command("archive")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--output", "output_zip", default="evidence.zip", help="输出 zip 路径")
def archive(run_id, output_zip):
    """打包 run 的签核证据（manifest + report + 覆盖率 + 证据链）"""
    import zipfile
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    evidence_files = ["docs/manifest.json", "docs/evidence_chain.json",
                      "report.json", "sim/coverage/coverage_result.json"]
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in evidence_files:
            f = run_dir / rel
            if f.exists():
                zf.write(f, arcname=f"{rid[:20]}/{rel}")
    console.print(f"[green]证据包已打包: {output_zip}[/green]")


@cli.command("clean")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--keep-logs", is_flag=True, help="保留日志")
def clean(run_id, keep_logs):
    """清理 run 的中间文件（build/work、uvm_regress），保留证据/日志"""
    import shutil
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    cleaned = []
    for sub in ["build", "uvm_regress"]:
        d = run_dir / sub
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            cleaned.append(sub)
    if not keep_logs:
        # 清理日志，但保留证据
        pass
    console.print(f"[green]已清理 {rid[:32]}: {', '.join(cleaned) or '无中间文件'}[/green]")


@cli.command("cleanup")
@click.option("--older-than", default="30d", help="清理 N 天前（如 30d / 7d）")
def cleanup(older_than):
    """清理 N 天前的 run 目录（磁盘管理）"""
    import shutil
    import re as _re
    m = _re.match(r"(\d+)d", older_than)
    days = int(m.group(1)) if m else 30
    cutoff = time.time() - days * 86400
    repo = _repo()
    cleaned = 0
    for d in repo.output_base.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            cleaned += 1
    console.print(f"[green]已清理 {cleaned} 个 {days} 天前的 run 目录[/green]")


# ── 报告与统计类 ──

@cli.command("trend")
@click.option("--limit", "-n", default=30, help="最近 N 次")
@click.option("--metric", default="coverage", type=click.Choice(["coverage"]))
def trend(limit, metric):
    """覆盖率趋势（最近 N 次 run）"""
    repo = _repo()
    data = repo.trend(metric, limit)
    if not data:
        console.print("[yellow]无数据[/yellow]")
        return
    for d in data:
        bar = "█" * int(d["coverage"] / 5)
        console.print(f"{d['run_id'][:28]:30} {d['coverage']:5.1f}% {bar}")


@cli.command("failures")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
def failures(run_id):
    """列出某 run 的失败阶段"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    fails = repo.failures(rid)
    if not fails:
        console.print("[green]无失败阶段[/green]")
        return
    for f in fails:
        console.print(f"[red]✗ {f.get('name', '?')}[/red] — {f.get('status', '')}")


@cli.command("projects")
def projects():
    """列出 output 目录里的项目（按前缀分组）"""
    repo = _repo()
    prefixes = {}
    for d in sorted(repo.output_base.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            prefix = d.name.split("_")[0] if "_" in d.name else d.name
            prefixes.setdefault(prefix, []).append(d.name)
    for prefix, dirs in sorted(prefixes.items()):
        console.print(f"[cyan]{prefix}[/cyan]: {len(dirs)} 个 run")


# ═══════════════════════════════════════════════════════════════
# vagent knowledge — 验证知识图谱（V2 语义图 / V4 跨项目复用）
# ═══════════════════════════════════════════════════════════════

@cli.group("knowledge")
def knowledge():
    """验证知识图谱：导出/导入签核证据包（跨项目复用）

    \b
    示例:
      vagent knowledge export gemm -c 96.0            # 导出本项目的签核证据包
      vagent knowledge import other_project_signoff.json   # 合并进本项目 KG
    """
    pass


@knowledge.command("export")
@click.argument("project_name")
@click.option("--output", "-o", "out_path", default=None,
              help="输出 JSON 路径（默认 <project>_signoff.json）")
@click.option("--coverage", "-c", type=float, default=None, help="本项目功能覆盖率（%%）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def knowledge_export(project_name, out_path, coverage, json_output):
    """导出签核证据包（KG + 覆盖率摘要）供其它项目导入复用。

    marketplace.export_signoff_package 一直存在却零调用（V4 的「签核证据包
    交换」因此从未真正发生），此处接上 CLI。
    """
    import asyncio
    out = get_output_adapter(json_output)
    try:
        from src.layers.l3_decision.knowledge.persistence import load_graph_from_db
        from src.layers.l3_decision.knowledge.marketplace import export_signoff_package
        g = asyncio.run(load_graph_from_db())
        if len(g) == 0:
            out.print_error("知识图谱为空：先跑一次 design 阶段把 KG 写入库")
            return
        path = out_path or f"{project_name}_signoff.json"
        cov = {"functional": coverage} if coverage is not None else {}
        p = export_signoff_package(g, project_name, cov, path)
        out.print_result({"project": project_name, "nodes": len(g),
                          "package": p, "coverage": cov}, title="签核证据包已导出")
    except Exception as e:
        out.print_error(f"导出失败: {e}")


@knowledge.command("import")
@click.argument("package_path", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def knowledge_import(package_path, json_output):
    """导入签核证据包并合并进本项目知识图谱（跨项目复用）。"""
    import asyncio
    out = get_output_adapter(json_output)
    try:
        from src.layers.l3_decision.knowledge.persistence import (
            load_graph_from_db, save_graph_to_db)
        from src.layers.l3_decision.knowledge.marketplace import (
            load_signoff_package, merge_package_into_graph)
        pkg = load_signoff_package(package_path)
        g = asyncio.run(load_graph_from_db())
        added = merge_package_into_graph(g, pkg)
        if added:
            asyncio.run(save_graph_to_db(g))
        out.print_result({"from_project": pkg.get("project", ""), "added_nodes": added,
                          "total_nodes": len(g)}, title=f"已合并 {added} 个新节点")
    except Exception as e:
        out.print_error(f"导入失败: {e}")


# ═══════════════════════════════════════════════════════════════
# vagent distill — Agent 自主蒸馏（L5 进化）
# ═══════════════════════════════════════════════════════════════

@cli.group("distill")
def distill():
    """Agent 自主蒸馏：把经验固化为能力（L5 进化）"""
    pass


@distill.command("run")
@click.option("--apply", is_flag=True, help="灰度上线（回归验证通过后固化）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def distill_run(apply, json_output):
    """扫描经验库 → 生成蒸馏提案 → 验证 → （可选）灰度上线"""
    out = get_output_adapter(json_output)
    try:
        from src.layers.l5_evolution.distillation import DistillationOrchestrator
        orch = DistillationOrchestrator("output")
        result = orch.run(apply=apply)
        if json_output:
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            console.print(f"[cyan]蒸馏扫描:[/cyan] {result['scanned']} 条提案"
                          f"（灰度上线 {result['applied']} 条）")
            for p in result["proposals"]:
                ch = {"debug_to_fix": "调试→模板", "gap_to_policy": "gap→策略",
                      "decision_weight": "决策→权重"}.get(p["channel"], p["channel"])
                console.print(f"  [{p['channel']}] {p['proposal_id']} — {ch}: {p['reasoning'][:50]}")
    except Exception as e:
        out.print_error(str(e))


@distill.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def distill_list(json_output):
    """列出已固化的蒸馏能力（live 模板/策略/权重）"""
    out = get_output_adapter(json_output)
    try:
        from src.layers.l5_evolution.distillation import DistillationOrchestrator
        orch = DistillationOrchestrator("output")
        result = {
            "templates": orch.get_live_templates(),
            "policy_bins": orch.get_live_policy_bins(),
            "weights": orch.get_live_weights(),
        }
        if json_output:
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            console.print(f"[cyan]已固化模板:[/cyan] {len(result['templates'])} 条")
            console.print(f"[cyan]已固化策略覆盖点:[/cyan] {len(result['policy_bins'])} 条")
            console.print(f"[cyan]已固化决策权重:[/cyan] {result['weights']}")
    except Exception as e:
        out.print_error(str(e))


@distill.command("rollback")
@click.argument("proposal_id")
def distill_rollback(proposal_id):
    """回滚某条已固化的蒸馏能力"""
    try:
        from src.layers.l5_evolution.distillation import DistillationOrchestrator
        orch = DistillationOrchestrator("output")
        if orch.rollback(proposal_id):
            console.print(f"[green]已回滚: {proposal_id}[/green]")
        else:
            console.print(f"[yellow]未找到 live 提案: {proposal_id}[/yellow]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ═══════════════════════════════════════════════════════════════
# vagent govern — 统一驾驭面板（预算/熔断/干预/决策可干预）
# ═══════════════════════════════════════════════════════════════

@cli.group("govern")
def govern():
    """统一驾驭层：预算 + 熔断 + 细粒度干预 + 决策可干预"""
    pass


@govern.command("status")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def govern_status(json_output):
    """查看驾驭状态：熔断器 + 预算 + 干预指令"""
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.governance.governor import Governor
        gov = Governor("output")
        status = gov.status()
        if json_output:
            click.echo(json.dumps(status, indent=2, ensure_ascii=False, default=str))
        else:
            b = status["breaker"]
            budget = status["budget"]
            console.print(Panel(
                f"[cyan]熔断（连续失败 ≥ {b['threshold']} 次）:[/cyan] {b['open'] or '无'}\n"
                f"[cyan]失败计数:[/cyan] {b['failures'] or '无'}\n"
                f"[cyan]Token:[/cyan] {budget['tokens']['used']}/{budget['tokens']['budget']}\n"
                f"[cyan]时间:[/cyan] {budget['time_s']['used']}s/{budget['time_s']['budget']}s\n"
                f"[cyan]EDA 调用:[/cyan] {budget['eda']['used']}/{budget['eda']['budget']}\n"
                f"[cyan]预算耗尽:[/cyan] {'是' if budget['exhausted'] else '否'}\n"
                f"[cyan]干预指令:[/cyan] {status['intervention'] or '无'}",
                title="驾驭状态（Governor）"))
    except Exception as e:
        out.print_error(str(e))


@govern.command("override")
@click.argument("action_type")
def govern_override(action_type):
    """人工接管决策：强制指定下一步动作（如 RELAX_CONSTRAINT / EXPAND_SEEDS）"""
    try:
        from src.layers.l2_orchestration.governance.governor import Intervention
        Intervention("output").write({"cmd": "override_action", "action_type": action_type})
        console.print(f"[green]已写入干预指令：override → {action_type}[/green]")
        console.print("[dim]下次闭环决策时会用此动作覆盖，执行后自动清除。[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@govern.command("reset")
@click.argument("action_type")
def govern_reset(action_type):
    """人工复位某动作的熔断状态"""
    try:
        from src.layers.l2_orchestration.governance.governor import CircuitBreaker
        # 熔断状态是内存态，复位需通过 Governor（新建实例会丢失状态）。
        # 这里用"清除干预 + 提示"：熔断是运行时内存态，重启即复位。
        console.print(f"[yellow]熔断是运行时内存态，重启 run 即复位。[/yellow]")
        console.print(f"[dim]若要强制继续，用 'vagent govern override {action_type}' 接管。[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ═══════════════════════════════════════════════════════════════
# vagent exclude — 允许放弃（有据可查地放弃，与"确保不漏测"同等重要）
# ═══════════════════════════════════════════════════════════════

@cli.group("exclude")
def exclude():
    """允许放弃：四步闭环（发现→归因→审计→调规）"""
    pass


def _exclude_registry():
    """Exclude 状态库（项目根 .signoffai/，跨 run 共享）。

    刻意不接受 output_dir：exclude 是治理产物，审计哈希链必须跨 run 连续，
    因此与 run 输出目录隔离——主循环 execution.py 用的也是项目根路径。
    历史上有过 output 相对路径的实现，结果是 CLI 批准的 exclude 主循环读不到。
    """
    from src.layers.l4_memory.exclude_registry import ExcludeRegistry
    return ExcludeRegistry()


@exclude.command("list")
@click.option("--status", "-s", "status_filter", default="all",
              type=click.Choice(["all", "approved", "proposed", "rejected"]),
              help="按状态过滤")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_list(status_filter, json_output):
    """列出 Exclude 记录（已批准/待审批/已拒绝）"""
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        approved = reg.get_approved_excludes()
        pending = reg.list_pending()
        stats = reg.stats()

        if json_output:
            click.echo(json.dumps({
                "stats": stats,
                "approved": approved,
                "pending": pending,
            }, indent=2, ensure_ascii=False, default=str))
            return

        console.print(f"[bold]Exclude 状态库[/bold] — "
                      f"批准 {stats['approved']} | 待审批 {stats['pending']} | "
                      f"已放弃点 {stats['excluded_points']}")

        type_label = {"unreachable": "结构死代码", "excluded_by_design": "规格不测",
                      "not_worth_it": "成本过高"}
        def _rows(entries):
            return [[e["exclude_id"], e["coverage_point"],
                     type_label.get(e["exclude_type"], e["exclude_type"]),
                     (e["reason"] or "—")[:36],
                     e.get("approver") or "—",
                     (e.get("audit_hash") or "")[:10] + "…" if e.get("audit_hash") else "—"]
                    for e in entries]

        if status_filter in ("all", "approved") and approved:
            out.print_table(["ID", "覆盖点", "类型", "理由", "审批人", "哈希指纹"],
                            _rows(approved), title="已批准（生效）")
        if status_filter in ("all", "proposed") and pending:
            out.print_table(["ID", "覆盖点", "类型", "理由", "审批人", "哈希指纹"],
                            _rows(pending), title="待审批")
        if status_filter == "all" and not approved and not pending:
            console.print("[dim]暂无 Exclude 记录。用 'vagent exclude propose' 提议。[/dim]")
    finally:
        reg.close()


@exclude.command("propose")
@click.argument("coverage_point")
@click.option("--reason", "-r", required=True, help="放弃理由（必填，审计依据）")
@click.option("--type", "-t", "exclude_type", default="not_worth_it",
              type=click.Choice(["unreachable", "excluded_by_design", "not_worth_it"]),
              help="归因分类")
@click.option("--evidence", "-e", default="", help="证据（波形/RTL 追溯等）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_propose(coverage_point, reason, exclude_type, evidence, json_output):
    """提议 Exclude（归因分类 → 待审批）

    \b
    示例:
      vagent exclude propose opcode[31:16] -r 'tie-off 固定死代码' -t unreachable
      vagent exclude propose burst_64      -r '规格不要求测 64 拍' -t excluded_by_design
    """
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        existing = reg.get_point_status(coverage_point)
        if existing:
            out.print_error(f"覆盖点 '{coverage_point}' 已存在（状态: {existing}）")
            return
        exclude_id = reg.propose_exclude(coverage_point, reason, exclude_type, evidence)
        out.print_result({"exclude_id": exclude_id, "coverage_point": coverage_point,
                          "type": exclude_type, "status": "proposed"},
                         title="Exclude 已提议（待审批）")
        console.print(f"[dim]审批: vagent exclude approve {exclude_id} --approver <姓名>[/dim]")
    finally:
        reg.close()


@exclude.command("approve")
@click.argument("exclude_id")
@click.option("--approver", "-a", default=None, help="审批人签名（默认取环境变量 USER）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_approve(exclude_id, approver, json_output):
    """审计门控：批准 Exclude（记录审批人 + 哈希指纹，接证据链）"""
    out = get_output_adapter(json_output)
    approver = approver or os.environ.get("USER", "engineer")
    reg = _exclude_registry()
    try:
        ok = reg.approve_exclude(exclude_id, approver)
        if ok:
            out.print_success(f"已批准 {exclude_id}（审批人: {approver}，哈希指纹已接入证据链）")
        else:
            out.print_error(f"Exclude {exclude_id} 不存在")
    finally:
        reg.close()


@exclude.command("reject")
@click.argument("exclude_id")
@click.option("--approver", "-a", default=None, help="审批人签名")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_reject(exclude_id, approver, json_output):
    """拒绝 Exclude（点仍需覆盖）"""
    out = get_output_adapter(json_output)
    approver = approver or os.environ.get("USER", "engineer")
    reg = _exclude_registry()
    try:
        reg.reject_exclude(exclude_id, approver)
        out.print_success(f"已拒绝 {exclude_id}（审批人: {approver}）")
    finally:
        reg.close()


@exclude.command("effective")
@click.option("--coverage", "-c", type=float, required=True, help="当前覆盖率（%）")
@click.option("--total", "-t", type=int, required=True, help="总覆盖点数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_effective(coverage, total, json_output):
    """动态调规：计算有效覆盖率 = coverage / (total - excluded)"""
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        excluded = len(reg.get_excluded_points())
        effective = reg.effective_coverage(coverage, total)
        result = {"raw_coverage": coverage, "total_points": total,
                  "excluded": excluded,
                  "effective_total": max(total - excluded, 1),
                  "effective_coverage": effective}
        out.print_result(result, title="有效覆盖率（Exclude 调规）")
        console.print(f"[dim]已放弃 {excluded} 点，从分母剔除后覆盖率 {coverage}% → {effective}%[/dim]")
    finally:
        reg.close()


# ═══════════════════════════════════════════════════════════════
# vagent case-model — case 属性完备性建模
# ═══════════════════════════════════════════════════════════════

@cli.group("case-model")
def case_model():
    """case 属性完备性建模（功能组织树 + P0/P1/P2 专题 + 维度约束组合）"""
    pass


@case_model.command("check")
@click.argument("models", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_check(models, json_output):
    """按 JSON Schema 校验 case 模型 YAML（语法 / 类型 / 必填 / 取值表形状）

    \b
    示例:
      vagent case-model check model.yaml            # 单文件
      vagent case-model check examples/             # 目录递归
    """
    out = get_output_adapter(json_output)
    from src.tools.casemodel_tools.cli import build_parser, cmd_check

    argv = ["check", *models] + (["--json"] if json_output else [])
    rc = cmd_check(build_parser().parse_args(argv))
    if rc and not json_output:
        out.print_error("schema check failed", code=rc)
    sys.exit(rc)


@case_model.command("analyze")
@click.argument("model", type=click.Path(exists=True))
@click.option("--cases", "-c", "cases_file", type=click.Path(exists=True),
              help="外部真实 case 列表（.yaml/.yml/.json/.csv），做反向核对")
@click.option("--report", "-o", "report_path", type=click.Path(),
              help="把完整文本报告写到文件")
@click.option("--seed", type=int, default=None, help="覆盖模型里的 generation.seed")
@click.option("--max-cases", type=int, default=None, help="覆盖 generation.max_cases")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_analyze(model, cases_file, report_path, seed, max_cases, json_output):
    """全量完备性分析：组织树 / 专题 / 正交性 / 交叉矩阵 / 取值覆盖 / 环境与检查

    \b
    示例:
      vagent case-model analyze model.yaml
      vagent case-model analyze model.yaml --cases real_cases.yaml
      vagent case-model analyze model.yaml --json -o report.txt
    """
    out = get_output_adapter(json_output)
    from src.tools.casemodel_tools.analysis import analyze_file
    from src.tools.casemodel_tools.cli import payload as _payload
    from src.tools.casemodel_tools.domain import CaseModelError as _CaseModelError
    from src.tools.casemodel_tools import text as _text

    try:
        result = analyze_file(model, cases=cases_file, seed=seed,
                              max_cases=max_cases)

        if json_output:
            payload = _payload(result)
            if result.external is not None:
                payload["external"] = result.external.to_dict()
            out.print_result(payload, title="case 属性完备性分析")
        else:
            text = _text.report(result)
            click.echo(text)
            if report_path:
                Path(report_path).parent.mkdir(parents=True, exist_ok=True)
                Path(report_path).write_text(text + "\n", encoding="utf-8")
                out.print_success(f"报告已写出: {report_path}")

        # 有 error → 退出码 1，warning 不阻断（与独立 CLI 一致）
        sys.exit(1 if result.errors else 0)
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)
    except Exception as exc:                      # noqa: BLE001
        out.print_error(f"分析失败: {exc}", code=2)
        sys.exit(2)


@case_model.command("tree")
@click.argument("model", type=click.Path(exists=True))
@click.option("--seed", type=int, default=None, help="覆盖模型里的 generation.seed")
@click.option("--max-cases", type=int, default=None, help="覆盖 generation.max_cases")
def case_model_tree(model, seed, max_cases):
    """只看功能组织树与专题

    \b
    示例:
      vagent case-model tree model.yaml
    """
    out = get_output_adapter(False)
    try:
        from src.tools.casemodel_tools.cli import build_parser, cmd_tree
        argv = ["tree", model]
        if seed is not None:
            argv += ["--seed", str(seed)]
        if max_cases is not None:
            argv += ["--max-cases", str(max_cases)]
        sys.exit(cmd_tree(build_parser().parse_args(argv)))
    except Exception as exc:                      # noqa: BLE001
        out.print_error(f"分析失败: {exc}", code=2)
        sys.exit(2)


@case_model.command("rules")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_rules(json_output):
    """列出全部校验规则

    \b
    示例:
      vagent case-model rules
      vagent case-model rules --json
    """
    from src.tools.casemodel_tools.cli import build_parser, cmd_rules
    argv = ["rules"] + (["--json"] if json_output else [])
    sys.exit(cmd_rules(build_parser().parse_args(argv)))


@case_model.command("generate")
@click.argument("model", type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "yaml", "json", "csv"]), help="输出格式")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="输出文件（缺省打到 stdout）")
@click.option("--seed", type=int, default=None, help="覆盖模型里的 generation.seed")
@click.option("--max-cases", type=int, default=None, help="覆盖 generation.max_cases")
def case_model_generate(model, fmt, output_path, seed, max_cases):
    """按属性组合生成 case 属性表（专题 → 树节点 → 维度 → 方法 → 组合）

    \b
    示例:
      vagent case-model generate model.yaml -f yaml -o cases.yaml
      vagent case-model generate model.yaml -f csv  -o cases.csv
    """
    out = get_output_adapter(False)
    from src.tools.casemodel_tools.cli import build_parser, cmd_generate
    from src.tools.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["generate", model, "--format", fmt, "--out", output_path or ""]
        if seed is not None:
            argv += ["--seed", str(seed)]
        if max_cases is not None:
            argv += ["--max-cases", str(max_cases)]
        sys.exit(cmd_generate(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)
    except Exception as exc:                      # noqa: BLE001
        out.print_error(f"生成失败: {exc}", code=2)
        sys.exit(2)


@case_model.command("uvm-tests")
@click.argument("model", type=click.Path(exists=True))
@click.option("--dimension", "-d", "dimensions", multiple=True,
              help="只要这些维度（按 id / 名称 / key 匹配）；可重复")
@click.option("--max-tests", type=int, default=32,
              help="最多导出多少条（默认 32；优先保留边界取值，截断会记账）")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="输出文件（缺省打到 stdout）")
def case_model_uvm_tests(model, dimensions, max_tests, output_path):
    """把属性取值摊平成 UVM 的 environment.tests 片段（一条 = 一个 UVM_TEST）

    产出的是一段 YAML 文本，贴进 env 清单的 `environment:` 下即可 ——
    本工具与 uvm_tools 之间只是**文件格式契约**，互不 import。

    \b
    示例:
      vagent case-model uvm-tests model.yaml -d D_ratio
      vagent case-model uvm-tests model.yaml -o tests.yaml
    """
    out = get_output_adapter(False)
    from src.tools.casemodel_tools.cli import build_parser, cmd_uvm_tests
    from src.tools.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["uvm-tests", model, "--max-tests", str(max_tests)]
        for name in dimensions:
            argv += ["--dimension", name]
        if output_path:
            argv += ["--out", output_path]
        sys.exit(cmd_uvm_tests(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)


@case_model.command("covergroups")
@click.argument("model", type=click.Path(exists=True))
@click.option("--module", "-m", default="dut",
              help="covergroup 名字里的模块名（默认 dut）")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="把 covergroup 写到文件（缺省打到 stdout）")
def case_model_covergroups(model, module, output_path):
    """覆盖点 → SystemVerilog covergroup（功能覆盖率方法学）

    维度 → covergroup、字段 → coverpoint、取值点 → bin、可组合的 cross_pair →
    cross。规则见 src/tools/casemodel_tools/coverage.py 的模块头。

    与 `uvm-tests` 是同一份分母的两面：那边说"这些取值点各跑一条用例"（激励），
    这边说"这些取值点各收一个 bin"（度量）—— 两边的数对得上，闭环才成立。

    \b
    示例:
      vagent case-model covergroups model.yaml -m apb_uart
      vagent case-model covergroups model.yaml -o coverage/apb_uart_cg.sv
    """
    out = get_output_adapter(False)
    from src.tools.casemodel_tools.cli import build_parser, cmd_covergroups
    from src.tools.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["covergroups", model, "--module", module]
        if output_path:
            argv += ["--out", output_path]
        sys.exit(cmd_covergroups(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)


@case_model.command("gui")
@click.argument("model", required=False, type=click.Path(exists=True))
def case_model_gui(model):
    """打开验证工作台并落在 case 建模模块上（不传模型则加载内置示例）

    \b
    示例:
      vagent case-model gui
      vagent case-model gui config/casemodel/examples/cpu_pipeline.yaml
    """
    try:
        from src.workbench.app import main as workbench_main
    except ImportError as exc:                    # PySide6 没装
        click.echo(
            "GUI 需要 PySide6，当前环境没有装：\n"
            f"  {exc}\n\n"
            "装法：pip install -e .[gui]　　或　　pip install PySide6\n"
            "（纯 CLI 用法 check / analyze / generate 不需要它）",
            err=True)
        sys.exit(2)
    argv = ["--module", "vms.casemodel"]
    if model:
        argv += ["--input", str(model)]
    sys.exit(workbench_main(argv))


# ═══════════════════════════════════════════════════════════════
# 人工变更证据链 —— 无 GUI 的那一半
# ═══════════════════════════════════════════════════════════════
#
# 界面上的「保存」会自动记账；在终端里用编辑器改文件**没有那个钩子**，所以
# 无 GUI 时这套东西等于不存在。这一组就是补那一半。
#
# 三条命令里 `check` 才是最要紧的：一条只在"你记得记账时才记账"的链，读的人
# 分不清"没人改"和"改了没记"——两者在链上都是一片空白。**没记的能被发现，
# 链才可信。**

@cli.group("evidence")
def evidence_group():
    """人工变更证据链（项目级，跨运行累积）

    \b
    记录的是"人在界面上/终端里改了哪个文件、为什么"。与某次运行的关系靠
    运行日志里的 human.edit 锚点，链本身不属于任何一次运行。

    \b
    示例:
      vagent evidence record rtl/dut.sv -m "修正握手时序"
      vagent evidence log
      vagent evidence check
    """
    pass


@evidence_group.command("record")
@click.argument("file_path", metavar="FILE")
@click.option("--message", "-m", "reason", default="",
              help="为什么改（会记进证据链；留空记为「未填理由」，不编理由）")
@click.option("--author", default="", help="署名（默认 PLATFORM_USER_NAME 或系统登录名）")
@click.option("--run-id", default="", help="同时往这次运行的日志写一条锚点")
@click.option("--root", "repo_root", default=".", help="仓库根（默认当前目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def evidence_record(file_path, reason, author, run_id, repo_root, json_output):
    """记录一次人工编辑（改完文件跑一下）

    \b
    示例:
      vagent evidence record config/ide/manual_nodes.yaml -m "超时 600 → 900"
    """
    out = get_output_adapter(json_output)
    from src.layers.l2_orchestration.evidence.human_edit import record_human_edit

    info = record_human_edit(file_path, reason, author=author, run_id=run_id,
                             repo_root=repo_root)
    if not info.get("recorded"):
        out.print_result({"recorded": False, "error": info.get("error", "记账失败")},
                         title="Evidence")
        sys.exit(1)

    if json_output:
        out.print_result(info, title="Evidence")
        return
    console.print(f"已记账 [bold]#{info['seq']}[/bold]　{info['file']}")
    console.print(f"  署名：{info['author']}　　理由：{info['reason']}")
    console.print(f"  内容哈希：{(info.get('content_hash') or '')[:16]}…")
    console.print(f"  链：{info['chain']}（共 {info['total_changes']} 条）")
    if run_id and not info.get("journal"):
        console.print(f"  [yellow]注意：没写进运行 {run_id} 的日志"
                      f"（找不到那次运行）[/yellow]")


@evidence_group.command("log")
@click.option("--limit", "-n", default=20, show_default=True, help="最多显示几条")
@click.option("--root", "repo_root", default=".", help="仓库根（默认当前目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def evidence_log(limit, repo_root, json_output):
    """看人工变更链 + 完整性自校验

    \b
    示例:
      vagent evidence log -n 5
    """
    out = get_output_adapter(json_output)
    from src.layers.l2_orchestration.evidence.human_edit import read_human_edits

    chain = read_human_edits(repo_root)
    if not chain["exists"]:
        out.print_result({"exists": False, "total_changes": 0, "path": chain["path"]},
                         title="Evidence")
        if not json_output:
            console.print(f"还没有人工变更记录。（会写到 {chain['path']}）")
        return

    records = list(reversed(chain["records"]))[:max(1, int(limit))]
    rows = [[str(r.get("seq", "")), str(r.get("timestamp", ""))[:19],
             str(r.get("file_path", "")), str(r.get("agent", "")),
             str(r.get("reason", ""))[:48]] for r in records]
    out.print_table(["#", "时间", "文件", "谁", "理由"], rows,
                    title=f"人工变更（共 {chain['total_changes']} 条）")
    if not json_output:
        state = "[green]完整[/green]" if chain["chain_valid"] else "[red]已断[/red]"
        console.print(f"链完整性：{state}　{chain['path']}")
        for issue in chain.get("issues", []):
            console.print(f"  [red]{issue.get('type')}[/red] {issue}")


@evidence_group.command("check")
@click.option("--root", "repo_root", default=".", help="仓库根（默认当前目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def evidence_check(repo_root, json_output):
    """对账：工作区改过、证据链里没有的文件

    \b
    链的价值不在「记了的有痕迹」，而在「没记的能被发现」—— 否则读链的人分不清
    「这段时间没人改」和「有人改了但没记账」。
    有未记账的改动时退出码为 1，可以直接拿去卡 CI。
    """
    out = get_output_adapter(json_output)
    from src.layers.l2_orchestration.evidence.human_edit import reconcile

    report = reconcile(repo_root)
    if json_output:
        out.print_result(report, title="Evidence check")
    elif not report["checked"]:
        console.print(f"[yellow]跳过：{report['reason']}[/yellow]")
    else:
        console.print(f"改动 {report['total_changed']} 个文件　"
                      f"已记账 {len(report['recorded'])}　"
                      f"未记账 {len(report['unrecorded'])}")
        for path in report["unrecorded"]:
            console.print(f"  [red]✗[/red] {path}")
        if report["ok"]:
            console.print("[green]✓ 改动都有痕迹。[/green]")
        else:
            console.print("[yellow]上面这些改过但没记账 —— 补上：[/yellow]")
            console.print("  vagent evidence record <文件> -m \"为什么改\"")
    # 不在 git 仓库里谈不上"对账"，不算失败；在仓库里且链断了 = 失败
    if report["checked"] and not report["ok"]:
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# 验证工作台（PySide6 桌面窗口）
# ═══════════════════════════════════════════════════════════════

@cli.group("gui")
def gui_group():
    """打开验证工作台（PySide6 桌面窗口，界面由 YAML 清单驱动）"""
    pass


@gui_group.command("run")
@click.argument("manifest", required=False, type=click.Path(exists=True))
@click.option("--module", "-m", default=None,
              help="启动后聚焦到这个模块 id（写在清单里的 id）")
@click.option("--input", "-i", default=None,
              help="覆盖指定模块的业务输入路径")
@click.option("--theme", default=None, help="主题名，留空用清单里的设置")
@click.option("--reset-layout", is_flag=True, help="忽略上次保存的窗口布局")
def gui_run(manifest, module, input, theme, reset_layout):
    """启动工作台。

    \b
    示例:
      vagent gui run                          # 用默认清单 config/workbench.yaml
      vagent gui run my.yaml                  # 用别的清单
      vagent gui run -m debug.sim_log         # 直接聚焦某个模块
    """
    args = [a for a in [manifest] if a]
    if module:
        args += ["--module", module]
    if input:
        args += ["--input", input]
    if theme:
        args += ["--theme", theme]
    if reset_layout:
        args += ["--reset-layout"]

    # PySide6 是可选依赖 —— 缺失时给装法而不是 traceback（约定：stderr + 退出码 2）
    try:
        from src.workbench.app import main as workbench_main
    except ImportError as exc:
        click.echo(
            "GUI 需要 PySide6，当前环境没有装：\n"
            f"  {exc}\n\n"
            "装法：pip install -e .[gui]　　或　　pip install PySide6\n"
            "（纯 CLI 用法 check / analyze / generate 不需要它）",
            err=True)
        sys.exit(2)
    sys.exit(workbench_main(args))


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    cli()


if __name__ == "__main__":
    main()
