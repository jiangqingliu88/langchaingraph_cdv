"""`vagent vplan` —— 把 spec-first 项目接进执行内核。

`build` 只做规划/契约层：读 `docs/specs/*.csv` + `data/contract_matrix/*.csv`，
写出 `coverage/testpoints.*`、`coverage/case_ir.json`、`contract/*`。
`execute` 在此之上用 VPlan 的 case 契约 + 执行资产派生运行期
`inputs/casemodel.yaml`，再交给现有 verify 内核跑 UVM/回归/证据。
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import click
import yaml

from src.cli.commands import cli, console


@cli.group("vplan")
def vplan_group():
    """AI VPlan 规划层（spec-first 项目 → TP/契约 IR）。"""


@vplan_group.command("status")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--allow-spec-drift", is_flag=True,
              help="spec 与 spec_meta 哈希不符时仍读取（仅预览）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_status(project, allow_spec_drift, json_output):
    """只读：项目计数与契约/TP/case 状态。"""
    from src.layers.l3_decision.vplan import VPlanError, load_project

    try:
        proj = load_project(project, allow_spec_drift=allow_spec_drift)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc
    summary = {
        "project": str(proj.root),
        "module": proj.module,
        "dut": proj.dut,
        "spec_hash": proj.spec_hash,
        "requirements": len(proj.requirements),
        "features": len(proj.features),
        "topics": len(proj.topics),
        "contracts": len(proj.contracts),
        "contracts_by_status": proj.status_counts,
        "testpoints": len(proj.testpoints),
        "testpoints_by_status": proj.tp_status_counts,
        "cases": len(proj.cases),
        "cases_by_status": proj.case_status_counts,
        "warnings": proj.warnings,
    }
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    console.print(f"[cyan]{proj.module}[/cyan] · DUT={proj.dut} · "
                  f"spec={proj.spec_path.name}")
    console.print(f"  需求 {summary['requirements']} / feature "
                  f"{summary['features']} / 专题 {summary['topics']}")
    console.print(f"  契约 {summary['contracts']}："
                  f"{summary['contracts_by_status']}")
    console.print(f"  TP {summary['testpoints']}："
                  f"{summary['testpoints_by_status']}")
    console.print(f"  case {summary['cases']}："
                  f"{summary['cases_by_status']}")
    for warning in proj.warnings:
        console.print(f"  [yellow]! {warning}[/yellow]")


@vplan_group.command("build")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--output", "-o", type=click.Path(file_okay=False),
              default=None, help="输出 run 目录（默认 output_vplan_<module>_<时间戳>）")
@click.option("--allow-spec-drift", is_flag=True,
              help="spec 与 spec_meta 哈希不符时仍生成（仅预览，不可签核）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_build(project, output, allow_spec_drift, json_output):
    """把 VPlan 项目写成一次只规划的 run（TP/Case/契约 IR）。"""
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.layers.l3_decision.vplan import (
        VPlanError, load_project, write_plan_only_run,
    )

    try:
        proj = load_project(project, allow_spec_drift=allow_spec_drift)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc

    out = output or make_output_root(f"output_vplan_{proj.module}")
    summary = write_plan_only_run(proj, out)
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    counts = summary["counts"]
    console.print(f"[green]✓ VPlan 规划 IR[/green] → {summary['run']}")
    console.print(f"  契约 {counts['contracts']}：{counts['contracts_by_status']}")
    console.print(f"  TP {counts['testpoints']}：{counts['testpoints_by_status']}")
    console.print(f"  case {counts['cases']}：{counts['cases_by_status']}")
    console.print("  [yellow]执行阶段未运行（PLAN_ONLY）：没有 EDA 证据，"
                  "不可签核[/yellow]")


@vplan_group.command("package-assets")
@click.argument("run", type=click.Path(exists=True, file_okay=False,
                                       path_type=Path))
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_package_assets(run, json_output):
    """把 run 里 SignOffAI 生成的 UVM 资产整理成 VPlan sv/ 布局。"""
    from src.layers.l3_decision.vplan import package_run_assets, scan_assets

    summary = package_run_assets(run)
    summary["scanned"] = len(scan_assets(run))
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✓ VPlan sv/ 布局[/green] → {summary['sv_root']}")
    console.print(f"  资产 {summary['assets']} 个（复制 {summary['copied']}，"
                  f"跳过 {summary['skipped']}）")
    console.print(f"  登记：{summary['registry']}")
    console.print("  [yellow]全部 candidate：未编译、无运行证据，不能冒充 active[/yellow]")


@vplan_group.command("execute")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--output", "-o", type=click.Path(file_okay=False),
              default=None, help="输出 run 目录（默认 output_vplan_<module>_<时间戳>）")
@click.option("--max-rounds", default=1, show_default=True,
              help="闭环最大轮次")
@click.option("--sim-mode", "sim_modes", multiple=True,
              help="仿真业务（可重复）；默认 cov")
@click.option("--dry-run", is_flag=True,
              help="只生成运行期模型并打印命令，不跑 UVM/EDA")
@click.option("--low-memory", is_flag=True,
              help="低内存机器：vopt 用 -O0（置 SIGNOFFAI_VOPT_ARGS=-voptargs=-O0）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_execute(project, output, max_rounds, sim_modes, dry_run,
                  low_memory, json_output):
    """用 VPlan case/契约 + 执行资产跑现有 verify 内核（UVM/回归/证据）。"""
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.layers.l3_decision.vplan import (
        VPlanError, load_project, write_execution_model,
    )

    try:
        proj = load_project(project)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc
    rtl_dir = proj.root / "rtl"
    if not rtl_dir.is_dir():
        raise click.ClickException(
            f"缺少 RTL 目录 {rtl_dir}；执行层需要 DUT（可先放 rtl/*.sv）")

    out = output or make_output_root(f"output_vplan_{proj.module}")
    work = Path(tempfile.mkdtemp(prefix=f"vplan_{proj.module}_"))
    model_path = write_execution_model(proj, work)
    summary = {
        "project": str(proj.root),
        "run": str(out),
        "rtl": str(rtl_dir),
        "derived_model": str(model_path),
        "spec": str(proj.spec_path),
        "max_rounds": int(max_rounds),
        "sim_modes": list(sim_modes) or ["cov"],
        "low_memory": bool(low_memory),
    }
    if dry_run:
        _env = ("SIGNOFFAI_VOPT_ARGS=-voptargs=-O0 "
                if low_memory else "")
        summary["command"] = (
            f"{_env}vagent verify --rtl {rtl_dir} --config {model_path} "
            f"--verify-only --approval auto --no-manual-gate "
            f"--no-checkpoint -o {out}")
        if json_output:
            click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            console.print(f"[cyan]VPlan execute (dry-run)[/cyan] → {out}")
            console.print(f"  派生模型：{model_path}")
            console.print(f"  RTL：{rtl_dir}")
            console.print(f"  等价命令：{summary['command']}")
        return

    from src.app.services import run_verify_async

    _prev_vopt = os.environ.get("SIGNOFFAI_VOPT_ARGS")
    if low_memory:
        os.environ["SIGNOFFAI_VOPT_ARGS"] = "-voptargs=-O0"
    try:
        result = asyncio.run(run_verify_async(
            # 执行层的 DUT 名必须来自 RTL（npu_sched），而不是自然语言 spec
            # （从 spec 猜出来的 `dut` 会让 util_comp 的 seq_item 类型对不上）。
            spec_file="",
            output_root=str(out),
            target=95.0,
            max_rounds=int(max_rounds),
            bypass_design_model=True,
            rtl_dir=str(rtl_dir),
            casemodel=str(model_path),
            sim_modes=list(sim_modes) or ["cov"],
            manual_gate=False,
            approval="auto",
            checkpointing=False,
            origin="vplan",
        ))
    finally:
        if _prev_vopt is None:
            os.environ.pop("SIGNOFFAI_VOPT_ARGS", None)
        else:
            os.environ["SIGNOFFAI_VOPT_ARGS"] = _prev_vopt
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    # 把 C-* ↔ TP ↔ case 的 sidecar 写进**实际 run**，供后续 gate/审计回查。
    if isinstance(result, dict) and result.get("output_root"):
        from src.core.runtime.atomic import atomic_write_json, atomic_write_text
        from src.layers.l3_decision.vplan.build import build_contract_link

        run_root = Path(str(result["output_root"]))
        (run_root / "contract").mkdir(parents=True, exist_ok=True)
        (run_root / "docs").mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            run_root / "contract" / "plan_link.yaml",
            yaml.safe_dump(build_contract_link(proj),
                           allow_unicode=True, sort_keys=False))
        atomic_write_json(run_root / "docs" / "vplan_source.json", {
            "schema": "vplan_source_v1",
            "project_root": str(proj.root),
            "module": proj.module,
            "dut": proj.dut,
            "spec_hash": proj.spec_hash,
            "contracts_by_status": proj.status_counts,
            "testpoints_by_status": proj.tp_status_counts,
            "cases_by_status": proj.case_status_counts,
            "execution": "RUN",
        })
        from src.layers.l3_decision.vplan import package_run_assets

        summary["assets"] = package_run_assets(run_root, proj.module)
        summary["run"] = str(run_root)

    summary["result"] = result if isinstance(result, dict) else str(result)
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return
    console.print(f"[green]✓ VPlan execute[/green] → {out}")
    if isinstance(result, dict):
        console.print(f"  status={result.get('status', '?')} "
                      f"coverage={result.get('final_coverage', '?')}")
    console.print("  真实证据由现有 verify 内核产出；契约状态仍需 gate 才能从 "
                  "assume 推进")
