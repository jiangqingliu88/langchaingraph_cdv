"""SignOffAI CLI 命令组：主验证流程（init / verify / multi / plan）

从 `src/interfaces/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json
import sys  # noqa: F401
from datetime import datetime  # noqa: F401
from pathlib import Path

import click  # noqa: F401
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.interfaces.cli.output import common_options, get_output_adapter  # noqa: F401
from src.interfaces.cli.commands import (  # noqa: F401
    cli, console,
    EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_WAITING, EXIT_STRICT,
    _repo, _resolve_run, _init_service, _find_run_id,
    _strict_semantic_gate,
    _extract_requirements_from_md, _get_git_info,
    _exclude_registry, _output_junit, _output_gitlab_ci,
    _checkpoint_db, _resume_closed_loop, _report_resume,
    _approver_name, _sha256_path, _write_approval_record, _decide,
)

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

def _warn_spec_and_rtl(spec_file, rtl_dir) -> None:
    if spec_file and rtl_dir:
        console.print("[yellow]spec + --rtl 同时给出：RTL 作为 DUT，spec 作为分析/"
                      "参考模型输入，跳过 design。[/yellow]")


def _verify_kwargs(**kw) -> dict:
    """CLI 参数 → `run_verify_async` 的关键字（归一空值与 tuple）。"""
    return {
        "spec_file": str(kw.get("spec_file") or ""),
        "output_root": str(kw.get("output") or "output"),
        "target": kw.get("target"),
        "max_rounds": kw.get("max_rounds"),
        "design_style": kw.get("design_style"),
        "bypass_design_model": kw.get("verify_only"),
        "sim_modes": list(kw.get("sim_modes") or []) or None,
        "manual_gate": kw.get("manual_gate"),
        "rtl_dir": str(kw.get("rtl_dir") or ""),
        "vplan": str(kw.get("vplan") or ""),
        "approval": kw.get("approval"),
        "checkpointing": kw.get("checkpoint"),
        "full_regression": kw.get("full_regression"),
        "incremental_from": str(kw.get("incremental_from") or ""),
        "origin": "cli",
    }


def _resolve_spec_input(spec_file, rtl_dir):
    """默认 spec（只在 `--rtl` 缺席时套用），返回解析后的 spec 路径。"""
    if not spec_file and not rtl_dir:
        default = Path("specs/apb_uart/apb_uart_spec.md")
        if default.exists():
            console.print(f"[dim]未指定 spec，用默认：{default}[/dim]")
            return str(default)
        raise click.UsageError(
            f"没给 spec，默认的 {default} 也不存在（工作目录下找不到）。"
            "请显式给 spec，或用 --rtl 给 RTL")
    return spec_file


def _is_vplan_dir(path) -> bool:
    return bool(path) and Path(path).is_dir()


def _run_vplan_project(root: Path, output, json_output: bool, rtl_dir) -> None:
    """`verify <vplan-project-dir>` 的规划层分支（不跑 EDA）。"""
    if not ((root / "docs" / "specs").is_dir()
            and (root / "data" / "contract_matrix").is_dir()):
        raise click.UsageError(
            f"{root} 是目录，但不是 VPlan 项目"
            "（缺 docs/specs 或 data/contract_matrix）")
    if rtl_dir:
        raise click.UsageError(
            "VPlan 项目当前只接规划/契约层，不接受 --rtl；执行层尚未接入")
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.ir.vplan import (
        VPlanError, load_project, write_plan_only_run)

    try:
        proj = load_project(root)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc
    run_dir = output or make_output_root(f"output_vplan_{proj.module}")
    summary = write_plan_only_run(proj, run_dir)
    _print_vplan_summary(summary, json_output)


def _print_vplan_summary(summary: dict, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    counts = summary["counts"]
    console.print(f"[green]✓ VPlan 规划 IR[/green] → {summary['run']}")
    console.print(f"  契约 {counts['contracts']}："
                  f"{counts['contracts_by_status']}")
    console.print(f"  TP {counts['testpoints']}："
                  f"{counts['testpoints_by_status']}")
    console.print(f"  case {counts['cases']}：{counts['cases_by_status']}")
    console.print("  [yellow]执行阶段未运行（PLAN_ONLY）：没有 EDA 证据，"
                  "不可签核[/yellow]")


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
@click.option("--incremental-from", type=click.Path(exists=True, file_okay=False),
              default=None, help="增量验证基线 run 目录：按 RTL diff + 依赖映射只跑受影响用例"
                                "（没有依赖映射时保守跑全量，并落 incremental/plan.json）")
@click.option("--verify-only", is_flag=True, help="验证专注模式：bypass design/model，直接 UVM 验证（预置 RTL + 黄金模型）")
@click.option("--sim-mode", "sim_modes", default=None, multiple=True,
              help="回归的仿真业务（可重复：--sim-mode wave --sim-mode cov）；"
                   "默认 cov+wave（覆盖率 + 波形）—— 要省机时就显式只给 cov。"
                   "可用词条见 src/layers/l2_orchestration/regression_tools/sim_modes.py")
@click.option("--no-manual-gate", "manual_gate", flag_value=False, default=True,
              help="关闭分级回归的**人工节点**（loopback 全过也不停车等人放行）。"
                   "默认开启：门是默认该在的。工作台工具栏上也有同一个开关")
@click.option("--checkpoint/--no-checkpoint", "checkpoint", default=True,
              help="落检查点（docs/checkpoints.sqlite）：高危动作的审批从"
                   "「进程内阻塞等答案」变成「停下来、关掉进程、过后来答」。"
                   "**默认开** —— 关掉就只能守着终端；无人值守请配 `--approval auto`")
@click.option("--strict-semantic", is_flag=True,
              help="严格语义：签核判为 PASS_WITH_CAVEAT（硬门禁过了但有软缺口，"
                   "如约束未激活 / ucdb 零命中）时以非零码退出。CI 用 —— 人看报告时"
                   "那几行是提示，上了流水线就得当失败")
@click.option("--rtl", "rtl_dir", type=click.Path(exists=True),
              help="外部 RTL 目录：拿现成 RTL 当 DUT；给了它自动跳过 design，"
                   "spec 仍作为分析/建模输入（可同时给 --rtl 和 spec）")
@click.option("--vplan", "vplan", type=click.Path(exists=True, file_okay=False),
              default=None, help="VPlan 项目根（含 data/*.csv 与 cases/*.yaml）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
@click.option("--summary", is_flag=True, help="仅输出最终摘要")
@click.option("--quiet", "-q", is_flag=True, help="只打印错误")
def verify(spec_file, output, design_style, target, max_rounds,
           approval, full_regression, incremental_from, verify_only, sim_modes,
           json_output, summary, quiet, manual_gate, checkpoint,
           strict_semantic, rtl_dir, vplan):
    # ── VPlan 项目：目录 + docs/specs + data/contract_matrix ──
    # 规划层接入：直接从 `docs/specs/*.csv` 与 `data/contract_matrix/*.csv`
    # 生成 TP/Case/契约 IR。**不读旧 case 模型**，也不跑 EDA —— 因此
    # 产物明确是 PLAN_ONLY，不能签核。
    if _is_vplan_dir(spec_file):
        _run_vplan_project(Path(spec_file), output, json_output, rtl_dir)
        return

    # **spec 与 --rtl 二选一、互斥**：
    #   给 spec  → 走原来的路（design agent 生成 RTL）
    #   给 --rtl  → RTL 是唯一输入，**规格从 DUT 分析出来**（不指向 spec）
    # 两个都给会互相打脸（spec 说的和 RTL 实现的不一致时听谁的？），
    # 一个都不给则没有输入 —— 两种都当场拒掉，别让它跑到下游才含糊地失败。
    spec_file = _resolve_spec_input(spec_file, rtl_dir)
    _warn_spec_and_rtl(spec_file, rtl_dir)
    """AI 驱动的芯片验证闭环（覆盖率驱动：case 回归 → coverage → 决策迭代）

    
    示例:
      vagent verify spec.md                              # 默认闭环
      vagent verify spec.md --design-style pipeline      # 指定设计风格
      vagent verify spec.md --target 90 --max-rounds 8   # 指定覆盖率目标/轮次
      vagent verify spec.md --json                       # CI JSON 输出
    """
    out = get_output_adapter(json_output, quiet)

    if not quiet and not json_output:
        console.print(f"[bold cyan]═══ Closed Loop: coverage-driven ═══[/bold cyan]")

    # **唯一入口**：预检（输出目录 / VPlan 项目 / 全量开关 / 增量基线）在
    # `VerifyRequest.prepare()`，CLI 只做参数解析与输出渲染。
    from src.interfaces.api import run_verify_async

    result = asyncio.run(run_verify_async(**_verify_kwargs(
        spec_file=spec_file, output=output, target=target,
        max_rounds=max_rounds, design_style=design_style,
        verify_only=verify_only, sim_modes=sim_modes, manual_gate=manual_gate,
        rtl_dir=rtl_dir, vplan=vplan, approval=approval,
        checkpoint=checkpoint, full_regression=full_regression,
        incremental_from=incremental_from)))
    output_root = result.get("output_root") or str(output or "output")

    # **挂起不是失败**：图停在人工节点上，运行没结束、状态在检查点里。
    # 这一步要显式说出来，并给出继续的那条命令 —— 否则人看到的就是"跑完了、
    # 什么都没发生"，而真相是"它停在半路等人答话"。
    if result.get("interrupted"):
        pending = result.get("pending") or {}
        rid = result.get("run_id", "")
        if json_output:
            click.echo(json.dumps({
                "run_id": rid, "interrupted": True,
                "pending_stage": pending.get("stage", "approval"),
                "pending": pending,
                "resume_hint": f"vagent resume --run {rid} --decision approve",
            }, indent=2, ensure_ascii=False, default=str))
            sys.exit(EXIT_WAITING)
        console.print()
        console.print(Panel.fit(
            f"运行**停在人工节点**上：{pending.get('stage', 'approval')}\n"
            f"运行没有结束 —— 状态落在检查点里，随时可以接着答。\n\n"
            f"  继续：vagent resume --run {rid} --decision approve\n"
            f"  驳回：vagent resume --run {rid} --decision reject\n"
            f"  或：  vagent approve --run {rid} --reason \"...\"\n\n"
            f"理由：{pending.get('reason', '（未给）')}",
            title="[yellow]等待人工审批[/yellow]", border_style="yellow"))
        sys.exit(EXIT_WAITING)

    # `--strict-semantic`：签核判为 PASS_WITH_CAVEAT 时**当失败**。
    #
    # 为什么不把开关穿进图里：audit 判什么、存不存在 `<run>/report.json`，
    # **跑完就知道了** —— 在 CLI 这层读一次即可，不必为它改 PipelineState、
    # 也不能为它加一条要穿过 24 个节点的参数。判据只有一处（audit 写的
    # `verdict`），这里只是换个处置方式。
    if strict_semantic:
        _strict_semantic_gate(Path(output_root), result.get("run_id") or "")

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
        sys.exit(EXIT_OK if result.get("converged") else EXIT_FAIL)

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
    from src.generation.uvm_tools.checking.tool_check_env_arch.main import check_env_arch as _check_env_arch
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
            from src.layers.l2_orchestration.regression_tools.regression_framework.adapters.regression_runner import RegressionRunner
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

    from src.interfaces.api import run_multi_module_async

    results = asyncio.run(run_multi_module_async(
        module_specs=module_specs, output_root=output or "output",
        design_style=design_style, max_rounds=max_rounds,
        max_concurrency=concurrency,
    ))

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

# ═══════════════════════════════════════════════════════════════
# vagent diff — 版本差异对比 (P0)
# ═══════════════════════════════════════════════════════════════

