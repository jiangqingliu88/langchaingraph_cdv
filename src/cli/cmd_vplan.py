"""`vagent vplan` —— 把 spec-first 项目接进执行内核。

`build` 只做规划/契约层：读 `docs/specs/*.csv` + `data/contract_matrix/*.csv`，
写出 `coverage/testpoints.*`、`coverage/case_ir.json`、`contract/*`。
`execute` 把 VPlan 项目挂到 run 的 `inputs/vplan/`，执行期由
`vplan.engine` 从 `data/*.csv` + `cases/*.yaml` 投影 TP/覆盖率/回归。
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

    _ensure_project_inputs(project, quiet=json_output)
    try:
        proj = load_project(project, allow_spec_drift=allow_spec_drift)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc
    from src.layers.l3_decision.vplan import review_status

    summary = {
        "project": str(proj.root),
        "module": proj.module,
        "dut": proj.dut,
        "spec_hash": proj.spec_hash,
        "review": review_status(proj),
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
    _print_review_status(summary["review"])
    for warning in proj.warnings:
        console.print(f"  [yellow]! {warning}[/yellow]")


def _print_review_status(status: dict) -> None:
    if status.get("reviewed"):
        console.print(f"  [green]人工审阅：已通过[/green]"
                      f"（{status.get('reviewer')} @ {status.get('at')}）")
        return
    parts = []
    if status.get("missing"):
        parts.append(f"缺输入 {status['missing']}")
    if status.get("unreviewed"):
        parts.append(f"未审阅 {status['unreviewed']}")
    if status.get("stale"):
        parts.append(f"已过期 {status['stale']}（审阅后又改过）")
    console.print(f"  [yellow]人工审阅：未通过[/yellow] —— "
                  f"{'；'.join(parts) or '未审阅'}")
    console.print("    LLM 抽取表必须先人工确认再执行："
                  "`vagent vplan review <project> --by <你的名字>`")


@vplan_group.command("review")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--by", "reviewer", default="",
              help="审阅人（写进 review.json；必填）")
@click.option("--note", default="", help="审阅意见")
@click.option("--check", is_flag=True,
              help="只检查状态；未审阅/已过期时退出码 1（CI 用）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_review(project, reviewer, note, check, json_output):
    """人工审阅 LLM 抽取的 docs/specs、data、cases，并记录哈希。

    审阅记录绑定**当前文件哈希**：之后人工改过任何一张表，审阅自动失效。
    `vplan execute` 会拒绝未审阅/已过期的项目（开发调试可加
    `--allow-unreviewed` 显式跳过）。
    """
    from src.layers.l3_decision.vplan import (
        VPlanError, load_project, record_review, review_status)

    try:
        proj = load_project(project)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc
    if check:
        status = review_status(proj)
        if json_output:
            click.echo(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            _print_review_status(status)
        if not status["reviewed"]:
            raise SystemExit(1)
        return
    try:
        manifest = record_review(proj, reviewer, note)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✓ 人工审阅已记录[/green] → "
                  f"{manifest['reviewer']} @ {manifest['at']}")
    console.print(f"  {Path(proj.root) / 'docs' / 'specs' / (proj.module + '_review.json')}")


@vplan_group.command("build")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--output", "-o", type=click.Path(file_okay=False),
              default=None, help="输出 run 目录（默认 output_vplan_<module>_<时间戳>）")
@click.option("--allow-spec-drift", is_flag=True,
              help="spec 与 spec_meta 哈希不符时仍生成（仅预览，不可签核）")
@click.option("--rebootstrap", is_flag=True,
              help="从源 spec 重写 docs/specs、data/*.csv、cases/*.yaml（覆盖现有草稿表）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_build(project, output, allow_spec_drift, rebootstrap, json_output):
    """把 VPlan 项目写成一次只规划的 run（TP/Case/契约 IR）。"""
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.layers.l3_decision.vplan import (
        VPlanError, load_project, write_plan_only_run,
    )

    _ensure_project_inputs(project, quiet=json_output, force=rebootstrap)
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
    from src.layers.l3_decision.vplan.assets import layout_mismatches

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
        problems.extend(layout_mismatches(run, rows))
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
    """把 run 记进 evidence/index.json，并把 VPlan 契约结构物化到 inputs/vplan。"""
    from src.layers.l3_decision.vplan import (
        link_run, load_project, materialize_project_inputs)

    proj = load_project(project)
    entry = link_run(project, run)
    inputs = materialize_project_inputs(proj, run)
    if json_output:
        entry["vplan_inputs"] = inputs
        click.echo(json.dumps(entry, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✓ 证据索引[/green] {entry['run_id']}")
    console.print(f"  契约 {len(entry['contracts'])} / "
                  f"regression={entry['regression_status']} / "
                  f"TP {len(entry['tp_status'])}")
    console.print(f"  VPlan 输入：{inputs['path']}")


@vplan_group.command("gate")
@click.argument("project", type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.option("--apply", is_flag=True,
              help="把 eligible 的契约写成 active（只改满足全部证据条件的行）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_gate(project, apply, json_output):
    """按证据评估 C-*：TP/回归/资产，或映射到的环境契约义务全部清偿。"""
    from src.layers.l3_decision.vplan import (
        VPlanError, apply_active, evaluate, load_project, require_review)

    if apply:
        # 未审阅的契约表不能被“证据”推进成 active —— 输入本身还没人看过。
        try:
            require_review(load_project(project))
        except VPlanError as exc:
            raise click.ClickException(str(exc)) from exc
    results = evaluate(project)
    changed = apply_active(project, results) if apply else 0
    if apply and changed:
        results = evaluate(project)
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    eligible = [r for r in results if r["eligible_active"]]
    blocked = [r for r in results if not r["eligible_active"]]
    drift = [r for r in results if r.get("active_drift")]
    summary = {
        "contracts": len(results),
        "by_status": counts,
        "eligible_active": len(eligible),
        "blocked": len(blocked),
        "active_unsupported": len(drift),
        "changed": changed,
        "blocked_examples": blocked[:10],
        "active_drift_examples": drift[:10],
    }
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        console.print(f"契约 {summary['contracts']}：{counts}")
        console.print(f"  eligible_active {len(eligible)} / blocked {len(blocked)}"
                      f" / active_unsupported {len(drift)} / changed {changed}")
        for row in blocked[:5]:
            console.print(f"  [yellow]• {row['contract_id']}: "
                          f"{'; '.join(row['reasons'])}[/yellow]")
        for row in drift[:5]:
            console.print(f"  [red]! active 但最新 run 不支持 {row['contract_id']}: "
                          f"{'; '.join(row['reasons'])}[/red]")
    if any(r["status"] != "active" for r in results) or drift:
        raise SystemExit(1)


_SOURCE_SPEC_NAMES = ("cmdsched.md", "spec.md", "design_spec.md")


def _source_spec(project: Path):
    """项目的源 spec：约定文件名优先，其次 docs/specs，最后根目录 `*.md`。"""
    for name in _SOURCE_SPEC_NAMES:
        path = project / name
        if path.is_file():
            return path
    spec_dir = project / "docs" / "specs"
    if spec_dir.is_dir():
        md = sorted(p for p in spec_dir.glob("*.md") if p.is_file())
        if md:
            return md[0]
    md = sorted(p for p in project.glob("*.md") if p.is_file())
    return md[0] if md else None


def _spec_contract(spec_text: str, module: str, llm: bool,
                   *, plan_tables: bool = True) -> dict:
    """spec → dplan 契约：确定性解析打底，LLM 抽取有值时覆盖。"""
    contract: dict = {}
    try:
        import json as _json
        from src.layers.l3_decision.spec_tools.main import analyze_specification

        raw = analyze_specification(spec_text)
        doc = (_json.loads(raw)
               if isinstance(raw, str) and raw.strip().startswith("{") else {})
        if isinstance(doc, dict) and not doc.get("error"):
            contract = {k: v for k, v in doc.items() if v}
    except Exception as exc:                       # noqa: BLE001 bootstrap 旁路
        console.print(f"[yellow]! 确定性 spec 解析失败：{exc}[/yellow]")
    use_llm = llm or os.environ.get(
        "SIGNOFFAI_SPEC_LLM", "").strip().lower() in ("1", "true", "yes")
    if use_llm:
        try:
            from src.executors.front.dplan import (
                extract_contracts, extract_plan_tables, merge_contracts)

            contract = merge_contracts(
                contract, extract_contracts(spec_text, module_hint=module))
            if plan_tables:
                # VPlan 六张表单独抽：和设计契约同一次调用会被输出上限截断。
                tables = extract_plan_tables(spec_text, module_hint=module)
                if tables:
                    contract = merge_contracts(contract, tables)
                else:
                    console.print("[yellow]! LLM 规划表抽取为空 —— 使用模块划分兜底"
                                  "（表仍是 assume/planned）[/yellow]")
        except Exception as exc:                   # noqa: BLE001 退回确定性
            console.print(f"[yellow]! LLM 契约抽取失败（退回确定性）：{exc}[/yellow]")
    # 确定性解析在抽不到标题时会填占位名 `dut`；项目目录名才是模块提示。
    if not contract.get("design_name") or contract["design_name"] in ("dut", "design"):
        contract["design_name"] = module
    return contract


def _has_project_tables(project: Path) -> bool:
    spec_dir = project / "docs" / "specs"
    return spec_dir.is_dir() and (
        any(spec_dir.glob("*_spec_meta.json"))
        or any(spec_dir.glob("*_testpoints.csv")))


def _ensure_project_inputs(project: Path, *, llm: bool = False,
                           quiet: bool = False, force: bool = False,
                           assets: bool = False):
    """从裸 spec bootstrap VPlan 项目骨架；`assets=True` 时补执行资产。

    spec → dplan → VPlan 是 front 的职责；CLI 只在入口触发。
    `force=True`（`--rebootstrap`）会覆盖现有表 —— 人工评审过的表会被重写，
    仅在 spec 变更或表还是 bootstrap 草稿时使用。
    已有表但缺 `data/execution_meta.csv`（如参考项目 demo）时，只补 `data/*.csv`
    与契约 sidecar，**不改 docs/specs 下的人工表**。
    """
    from src.executors.front.vplan import ProjectFormatError

    has_tables = _has_project_tables(project)
    need_assets = assets and not (project / "data" / "execution_meta.csv").is_file()
    if not force and has_tables and not need_assets:
        return None
    spec_path = _source_spec(project)
    if spec_path is None:
        return None
    spec_text = spec_path.read_text(encoding="utf-8", errors="replace")
    contract = _spec_contract(spec_text, project.name, llm,
                              plan_tables=not (has_tables and not force))
    try:
        if not force and has_tables:
            from src.executors.front.vplan import bootstrap_assets

            summary = bootstrap_assets(project, spec_text, contract)
            if not quiet:
                console.print(
                    f"[green]✓ 补齐执行资产[/green] {spec_path.name} → "
                    f"{summary['dimensions']} 维度（docs/specs 未改动）")
            return summary
        from src.executors.front.vplan import bootstrap_project

        summary = bootstrap_project(project, spec_text, contract)
    except ProjectFormatError as exc:
        raise click.ClickException(str(exc)) from exc
    if not quiet:
        console.print(
            f"[green]✓ 从 spec bootstrap VPlan[/green] {spec_path.name} → "
            f"需求 {summary['requirements']} / feature {summary['features']} / "
            f"契约 {summary['contracts']} / TP {summary['testpoints']} / "
            f"case {summary['cases']}")
        console.print("  格式/引用校验通过；全部 assume/planned：没有执行证据，"
                      "评审后仍需 gate 才能推进")
        for warning in (summary.get("validation") or {}).get("warnings") or []:
            console.print(f"  [yellow]! {warning}[/yellow]")
    return summary


def _exec_rtl(proj, from_spec):
    rtl = proj.root / "rtl"
    if not from_spec and not rtl.is_dir():
        raise click.ClickException(
            f"缺少 RTL 目录 {rtl}；执行层需要 DUT（可先放 rtl/*.sv，"
            "或用 --from-spec 从 spec 生成）")
    return rtl


def _exec_spec_text(proj, from_spec) -> str:
    if not from_spec:
        return ""
    header = f"<!-- module: {proj.module} -->\n"
    return header + proj.spec_path.read_text(encoding="utf-8",
                                             errors="replace")


def _dry_run_command(proj, rtl_dir, out, low_memory,
                     uvm_layout, from_spec) -> str:
    env = "SIGNOFFAI_VOPT_ARGS=-voptargs=-O0 " if low_memory else ""
    env += f"SIGNOFFAI_UVM_LAYOUT={uvm_layout} "
    if from_spec:
        env += f"SIGNOFFAI_SPEC_LLM=1 SIGNOFFAI_DESIGN_NAME={proj.module} "
    return (f"{env}vagent vplan execute {proj.root} -o {out} "
            f"--approval auto --no-manual-gate --no-checkpoint")


def _print_dry_run(summary, json_output, rtl_dir) -> None:
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    console.print(f"[cyan]VPlan execute (dry-run)[/cyan] → {summary['run']}")
    console.print(f"  VPlan 项目：{summary['project']}")
    console.print(f"  RTL：{rtl_dir}")
    console.print(f"  等价命令：{summary['command']}")


def _run_kernel(proj, out, spec_text, rtl_dir, max_rounds,
                sim_modes, low_memory, uvm_layout, from_spec,
                exact_output=False, allow_unreviewed=False):
    keys = ("SIGNOFFAI_VOPT_ARGS", "SIGNOFFAI_UVM_LAYOUT",
            "SIGNOFFAI_SPEC_LLM", "SIGNOFFAI_DESIGN_NAME",
            "SIGNOFFAI_VPLAN", "SIGNOFFAI_OUTPUT_EXACT",
            "SIGNOFFAI_ALLOW_UNREVIEWED")
    prev = {key: os.environ.get(key) for key in keys}
    os.environ["SIGNOFFAI_UVM_LAYOUT"] = uvm_layout
    if allow_unreviewed:
        os.environ["SIGNOFFAI_ALLOW_UNREVIEWED"] = "1"
    # VPlan 执行：没有 registry 模型时允许占位 predictor（不接 SCB），
    # 而不是让 env 生成硬失败 —— DUT 检查走 sample:dut + assertions 那条路。
    os.environ["SIGNOFFAI_VPLAN"] = "1"
    if exact_output:
        os.environ["SIGNOFFAI_OUTPUT_EXACT"] = "1"
    if low_memory:
        os.environ["SIGNOFFAI_VOPT_ARGS"] = "-voptargs=-O0"
    # 顶层模块名由 VPlan 项目决定；`--rtl` 路径同样要传 —— 不然 front/n_design
    # 只能从多文件 RTL 里猜顶层（实测 6 个文件选中了 cmd_int_perf）。
    os.environ["SIGNOFFAI_DESIGN_NAME"] = proj.module
    if from_spec:
        os.environ["SIGNOFFAI_SPEC_LLM"] = "1"
    try:
        from src.app.services import run_verify_async

        return asyncio.run(run_verify_async(
            spec_file="", spec_text=spec_text, output_root=str(out),
            target=95.0, max_rounds=int(max_rounds),
            bypass_design_model=not from_spec,
            rtl_dir="" if from_spec else str(rtl_dir),
            vplan=str(proj.root),
            sim_modes=list(sim_modes) or ["cov"],
            manual_gate=False, approval="auto", checkpointing=False,
            origin="vplan"))
    finally:
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _finalize_run(proj, result, clean_legacy) -> dict:
    extra = {}
    if not (isinstance(result, dict) and result.get("output_root")):
        return extra
    from src.core.runtime.atomic import atomic_write_json, atomic_write_text
    from src.layers.l3_decision.vplan import (
        clean_legacy_dirs, materialize_project_inputs, package_run_assets)
    from src.layers.l3_decision.vplan.build import build_contract_link

    run_root = Path(str(result["output_root"]))
    extra["vplan_inputs"] = materialize_project_inputs(proj, run_root)
    (run_root / "contract").mkdir(parents=True, exist_ok=True)
    (run_root / "docs").mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        run_root / "contract" / "plan_link.yaml",
        yaml.safe_dump(build_contract_link(proj), allow_unicode=True,
                       sort_keys=False))
    atomic_write_json(run_root / "docs" / "vplan_source.json", {
        "schema": "vplan_source_v1", "project_root": str(proj.root),
        "module": proj.module, "dut": proj.dut, "spec_hash": proj.spec_hash,
        "contracts_by_status": proj.status_counts,
        "testpoints_by_status": proj.tp_status_counts,
        "cases_by_status": proj.case_status_counts, "execution": "RUN",
    })
    extra["assets"] = package_run_assets(run_root, proj.module)
    try:
        from src.layers.l3_decision.vplan.uvm_arch import write_uvm_arch

        extra["uvm_arch"] = write_uvm_arch(run_root, proj)
    except Exception as exc:                       # noqa: BLE001 旁路
        extra["uvm_arch_error"] = str(exc)
    # 生成期的 yaml/filelist 是中间输入；执行完只保留 sv/、inputs/vplan、inputs/dplan。
    import shutil as _shutil
    for rel in ("inputs/filelists", "inputs/yaml"):
        _shutil.rmtree(run_root / rel, ignore_errors=True)
    extra["run"] = str(run_root)
    # **sv/ 是唯一交付布局**：run 收尾后删掉内核顶层的 agents/env/bench/build。
    # `sv/` 由 verify 生成期打包；`inputs/filelists/filelist.f` 已消费完毕。
    if clean_legacy and result.get("status") in {"CONVERGED", "PASS",
                                                 "COMPLETED"}:
        try:
            extra["legacy_cleaned"] = clean_legacy_dirs(run_root, apply=True)
        except ValueError as exc:
            extra["legacy_cleaned_error"] = str(exc)
    return extra


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
@click.option("--clean-legacy/--keep-legacy", default=True,
              help="run 成功后删除顶层 agents/bench/env/build，只留 sv/")
@click.option("--from-spec", is_flag=True,
              help="从 spec 生成 RTL（LLM 设计契约 + design/model），不使用现有 rtl/")
@click.option("--rebootstrap", is_flag=True,
              help="从源 spec 重写 docs/specs、data/*.csv、cases/*.yaml（覆盖现有草稿表）")
@click.option("--allow-unreviewed", is_flag=True,
              help="跳过人工审阅门（**仅开发调试**；执行日志会记 warning）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def vplan_execute(project, output, max_rounds, sim_modes, dry_run,
                  low_memory, uvm_layout, clean_legacy, from_spec, rebootstrap,
                  allow_unreviewed, json_output):
    """用 VPlan case/契约 + 执行资产跑现有 verify 内核（UVM/回归/证据）。"""
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.layers.l3_decision.vplan import VPlanError, load_project

    _ensure_project_inputs(project, llm=from_spec, quiet=json_output,
                           force=rebootstrap, assets=not dry_run)
    try:
        proj = load_project(project)
    except VPlanError as exc:
        raise click.ClickException(str(exc)) from exc
    if not dry_run:
        from src.layers.l3_decision.vplan import require_review

        if allow_unreviewed:
            console.print("[yellow]! 已跳过人工审阅门（--allow-unreviewed，"
                          "仅限开发调试）[/yellow]")
        else:
            try:
                require_review(proj)
            except VPlanError as exc:
                raise click.ClickException(str(exc)) from exc
    rtl_dir = _exec_rtl(proj, from_spec)
    spec_text = _exec_spec_text(proj, from_spec)

    out = output or make_output_root(f"output_vplan_{proj.module}")
    summary = {
        "project": str(proj.root), "run": str(out), "rtl": str(rtl_dir),
        "spec": str(proj.spec_path),
        "max_rounds": int(max_rounds), "sim_modes": list(sim_modes) or ["cov"],
        "low_memory": bool(low_memory), "uvm_layout": uvm_layout,
        "from_spec": bool(from_spec),
    }
    if dry_run:
        summary["command"] = _dry_run_command(
            proj, rtl_dir, out, low_memory, uvm_layout, from_spec)
        _print_dry_run(summary, json_output, rtl_dir)
        return

    result = _run_kernel(proj, out, spec_text, rtl_dir,
                         max_rounds, sim_modes, low_memory, uvm_layout,
                         from_spec, exact_output=bool(output),
                         allow_unreviewed=allow_unreviewed)

    summary.update(_finalize_run(proj, result, clean_legacy))
    summary["result"] = result if isinstance(result, dict) else str(result)
    if json_output:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2,
                              default=str))
        return
    console.print(f"[green]✓ VPlan execute[/green] → {summary['run']}")
    if isinstance(result, dict):
        console.print(f"  status={result.get('status', '?')} "
                      f"coverage={result.get('final_coverage', '?')}")
    console.print("  真实证据由现有 verify 内核产出；契约状态仍需 gate 才能从 "
                  "assume 推进")
