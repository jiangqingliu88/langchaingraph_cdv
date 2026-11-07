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
    for path in summary.get("skipped_paths") or []:
        console.print(f"    [yellow]未映射：{path}[/yellow]")
    console.print(f"  登记：{summary['registry']}")
    console.print("  [yellow]全部 candidate：未编译、无运行证据，不能冒充 active[/yellow]")


@vplan_group.command("clean-layout")
@click.argument("run", type=click.Path(exists=True, file_okay=False,
                                       path_type=Path))
@click.option("--apply", is_flag=True,
              help="真的删除顶层 agents/bench/env/build（默认只列出）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_clean_layout(run, apply, json_output):
    """删除内核的顶层工作目录，只保留 VPlan sv/ 布局。"""
    from src.layers.l3_decision.vplan import clean_legacy_dirs

    try:
        summary = clean_legacy_dirs(run, apply=apply)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if not summary["present"]:
        console.print("没有 legacy 目录需要清理")
        return
    if apply:
        console.print(f"[green]✓ 已删除[/green] "
                      f"{', '.join(summary['deleted'])}")
    else:
        console.print(f"[yellow]将删除（dry-run）：[/yellow] "
                      f"{', '.join(summary['present'])}")
        console.print("  确认后加 --apply")


@vplan_group.command("scan-assets")
@click.argument("run", type=click.Path(exists=True, file_okay=False,
                                       path_type=Path))
@click.option("--check", "check_only", is_flag=True,
              help="与 sv/asset_registry.csv 核对，不一致则失败")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_scan_assets(run, check_only, json_output):
    """扫描 run 的 sv/ 锚点；`--check` 核对登记表。"""
    import csv
    from src.layers.l3_decision.vplan import scan_assets

    rows = scan_assets(run)
    problems = []
    if check_only:
        reg = run / "sv" / "asset_registry.csv"
        if not reg.is_file():
            problems.append("sv/asset_registry.csv 不存在（先 package-assets）")
        else:
            with reg.open(encoding="utf-8-sig", newline="") as fh:
                registered = {r["path"] for r in csv.DictReader(fh)}
            scanned = {r["path"] for r in rows}
            for path in sorted(registered - scanned):
                problems.append(f"登记了但扫描不到：{path}")
            for path in sorted(scanned - registered):
                problems.append(f"扫描到但未登记：{path}")
    result = {"assets": len(rows), "problems": problems}
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        console.print(f"sv/ 资产：{len(rows)} 个")
        for problem in problems:
            console.print(f"  [red]✗ {problem}[/red]")
    if problems:
        raise SystemExit(1)


@vplan_group.command("link")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.argument("run", type=click.Path(exists=True, file_okay=False,
                                       path_type=Path))
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_link(project, run, json_output):
    """把一个 run 记进项目 evidence/index.json。"""
    from src.layers.l3_decision.vplan import link_run

    entry = link_run(project, run)
    if json_output:
        click.echo(json.dumps(entry, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✓ 证据索引[/green] {entry['run_id']}")
    console.print(f"  契约 {len(entry['contracts'])} / "
                  f"regression={entry['regression_status']} / "
                  f"TP {len(entry['tp_status'])}")


@vplan_group.command("gate")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--apply", is_flag=True,
              help="把 eligible 的契约写成 active（只改满足全部证据条件的行）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_gate(project, apply, json_output):
    """按证据评估 C-*：满足 TP/回归/资产条件才可能 active。"""
    from src.layers.l3_decision.vplan import apply_active, evaluate

    results = evaluate(project)
    changed = apply_active(project, results) if apply else 0
    if apply and changed:
        results = evaluate(project)
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    eligible = [r for r in results if r["eligible_active"]]
    blocked = [r for r in results if not r["eligible_active"]]
    summary = {
        "contracts": len(results),
        "by_status": counts,
        "eligible_active": len(eligible),
        "blocked": len(blocked),
        "changed": changed,
        "blocked_examples": blocked[:10],
    }
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        console.print(f"契约 {summary['contracts']}：{counts}")
        console.print(f"  eligible_active {len(eligible)} / blocked {len(blocked)}"
                      f" / changed {changed}")
        for row in blocked[:5]:
            console.print(f"  [yellow]• {row['contract_id']}: "
                          f"{'; '.join(row['reasons'])}[/yellow]")
    if any(r["status"] != "active" for r in results):
        raise SystemExit(1)


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
@click.option("--uvm-layout", type=click.Choice(["vplan", "legacy"]),
              default="vplan", show_default=True,
              help="UVM 生成布局：vplan = 生成期同时落 <run>/sv/；legacy = 只保留内核目录")
@click.option("--clean-legacy", is_flag=True,
              help="run 成功后删除顶层 agents/bench/env/build，只留 sv/")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_execute(project, output, max_rounds, sim_modes, dry_run,
                  low_memory, uvm_layout, clean_legacy, json_output):
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
        "uvm_layout": uvm_layout,
    }
    if dry_run:
        _env = ("SIGNOFFAI_VOPT_ARGS=-voptargs=-O0 "
                if low_memory else "")
        _env += f"SIGNOFFAI_UVM_LAYOUT={uvm_layout} "
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
    _prev_layout = os.environ.get("SIGNOFFAI_UVM_LAYOUT")
    if low_memory:
        os.environ["SIGNOFFAI_VOPT_ARGS"] = "-voptargs=-O0"
    os.environ["SIGNOFFAI_UVM_LAYOUT"] = uvm_layout
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
        if _prev_layout is None:
            os.environ.pop("SIGNOFFAI_UVM_LAYOUT", None)
        else:
            os.environ["SIGNOFFAI_UVM_LAYOUT"] = _prev_layout
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
        from src.layers.l3_decision.vplan import (
            clean_legacy_dirs, package_run_assets)

        summary["assets"] = package_run_assets(run_root, proj.module)
        summary["run"] = str(run_root)
        if clean_legacy and result.get("status") in {"CONVERGED", "PASS",
                                                     "COMPLETED"}:
            try:
                summary["legacy_cleaned"] = clean_legacy_dirs(
                    run_root, apply=True)
            except ValueError as exc:
                summary["legacy_cleaned_error"] = str(exc)

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
