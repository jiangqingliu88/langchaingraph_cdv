"""SignOffAI CLI 命令组：契约（contract）—— Verification OS v3 · M1。

契约是**构建物**：`vagent contract build` 把 `coverage/case_ir.json`（或给定
的 case 模型）编译成 `contract/contract.yaml` + `obligations.json` +
`contract_manifest.json`；`ops` 用 `contract check` 同一套逻辑做前置门禁。
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.cli.commands import cli, console


@cli.group()
def contract():
    """验证契约（构建物）：编译 / 校验 / 查看"""
    pass


def _resolve_run_dir(path: str) -> Path:
    p = Path(path)
    return p.parent if p.name in ("coverage", "contract") else p


@contract.command("build")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--vplan", "vplan_dir", default="",
              type=click.Path(file_okay=False),
              help="VPlan 项目根（没有 case_ir 时现投影）")
@click.option("--module", "-m", "module", default="", help="模块名（缺省取运行目录/项目）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_build(run_dir, vplan_dir, module, json_output):
    """把 case IR 编译成契约构建物（contract/contract.yaml + 义务 + 清单）

    \b
    示例:
      vagent contract build --run output_xxx
      vagent contract build --run output_xxx --vplan specs/npu_sched
    """
    from src.ir_plane.contract import write_contract

    root = _resolve_run_dir(run_dir)
    case_ir_path = root / "coverage" / "case_ir.json"
    case_ir = {}
    if case_ir_path.is_file():
        try:
            case_ir = json.loads(case_ir_path.read_text(encoding="utf-8"))
        except ValueError:
            case_ir = {}
    if vplan_dir and not Path(vplan_dir).is_dir():
        click.echo(f"VPlan 项目不存在: {vplan_dir}", err=True)
        raise SystemExit(2)
    if not case_ir.get("cases") and vplan_dir:
        from src.ir_plane.vplan import engine

        payload = engine.run_testpoints(
            engine.load_project_from(vplan_dir),
            env_name=f"{module or root.name}_env",
            module_name=module or root.name)
        if payload.get("error"):
            click.echo(f"VPlan 投影失败: {payload['error']}", err=True)
            raise SystemExit(2)
        case_ir = payload.get("case_ir") or {}
    if not case_ir.get("cases"):
        click.echo("没有 case IR：先跑 verify，或用 --vplan 给项目根", err=True)
        raise SystemExit(2)

    manifest = write_contract(root, case_ir, module=module or root.name)
    if json_output:
        click.echo(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    console.print(f"[bold]契约[/bold] {manifest['contract_id']}")
    console.print(f"  用例 {manifest['cases']} · 义务 {manifest['obligations']}")
    console.print(f"  hash {manifest['contract_hash']}")
    console.print(f"  → {root / 'contract'}")


@contract.command("check")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_check(run_dir, json_output):
    """校验契约自洽（存在 / 哈希 / 义务数）—— ops 的前置门禁同一套逻辑"""
    from src.ir_plane.contract import check_contract

    result = check_contract(_resolve_run_dir(run_dir))
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("ok"):
        console.print(f"[bold]契约 ok[/bold] {result.get('contract_id')} · "
                      f"{result.get('obligations')} 条义务")
    if not json_output and not result.get("ok"):
        click.echo(f"契约不可用: {result.get('reason')}", err=True)
    if not result.get("ok"):
        raise SystemExit(1)


@contract.command("why")
@click.argument("obligation_id")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_why(obligation_id, run_dir, json_output):
    """一条义务为什么是这个状态：谓词 → 事实 → 状态 → 还差什么

    \b
    示例:
      vagent contract why OBL-GROUP-CASE-D_DEP-CG-D_DEP-FUNCTIONAL --run output_xxx
    """
    from src.ir_plane.contract import explain

    data = explain(_resolve_run_dir(run_dir), obligation_id)
    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not data.get("available"):
        click.echo(f"查不了：{data.get('reason')}", err=True)
        raise SystemExit(2)
    console.print(f"[bold]{data['obligation_id']}[/bold]  →  {data['status']}")
    pred = data["predicate"]
    console.print(f"  判据：{pred['fact_type']} / {pred['op']}  {pred['where']}")
    console.print(f"  事实：{data['facts_total']} 条")
    for fact in data["facts"][:3]:
        console.print(f"    {fact['type']} {fact['subject']} → {fact['value']}")
    missing = data.get("missing")
    if missing:
        console.print(f"  还差：{missing['fact_type']}")
        for run in missing.get("suggested_runs") or []:
            console.print(f"    跑 {run.get('test')} seed={run.get('seeds')} "
                          f"（TP {run.get('tp_id')}）")
    if data["status"] != "PROVEN":
        raise SystemExit(1)


@contract.command("worklist")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_worklist(run_dir, json_output):
    """未清偿义务 → 需要重跑的回归 test 清单（义务驱动执行）"""
    from src.ir_plane.contract.worklist import write_worklist

    data = write_worklist(_resolve_run_dir(run_dir))
    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not data.get("available"):
        click.echo(f"清单不可用（{data.get('reason')}）—— 跑全量", err=True)
        return
    console.print(f"[bold]未清偿 {data['open']}/{data['obligations']} 条义务[/bold] "
                  f"→ {data['count']} 条 test")
    for item in data["items"][:20]:
        console.print(f"  {item['test']}（{item.get('stage') or '-'}）"
                      f" TP {len(item['tp_ids'])} · 义务 {len(item['obligations'])}")
    if data.get("skipped_no_test"):
        console.print(f"  映射不到回归 test：{len(data['skipped_no_test'])} 条"
                      f"（见 status/worklist.json）")


@contract.command("seeds")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_seeds(run_dir, json_output):
    """种子索引：哪个 seed 清偿了哪些义务（可复现证据）"""
    from src.ir_plane.contract.seeds import write_seed_index

    data = write_seed_index(_resolve_run_dir(run_dir))
    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not data.get("available"):
        click.echo(f"索引不可用（{data.get('reason')}）", err=True)
        raise SystemExit(2)
    counts = data.get("counts") or {}
    console.print(f"[bold]种子索引[/bold] {counts.get('seeds', 0)} 颗 seed · "
                  f"{counts.get('runs', 0)} 次执行 · 清偿 {counts.get('discharged_total', 0)} 条义务")
    for seed, slot in list((data.get("by_seed") or {}).items())[:20]:
        console.print(f"  seed {seed}: 清偿 {slot.get('count', 0)} 条"
                      f"（{slot.get('runs', 0)} 次执行）")


@contract.command("status")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_status(run_dir, json_output):
    """OS 视图：契约 / 账本 / case 与 TP 两级影子对账"""
    from src.ir_plane.contract import status_summary

    data = status_summary(_resolve_run_dir(run_dir))
    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    contract = data.get("contract") or {}
    console.print(f"[bold]{data['run']}[/bold]")
    console.print(f"  契约：{'ok' if contract.get('ok') else contract.get('reason')}"
                  f"（{contract.get('obligations', 0)} 条义务）")
    console.print(f"  账本：{data['ledger']['facts']} 条事实 · head "
                  f"{data['ledger']['head']}")
    for key, label in (("case_shadow", "case 对账"), ("tp_shadow", "TP 对账")):
        shadow = data.get(key) or {}
        console.print(f"  {label}：{'一致' if shadow.get('ok') else '有差异'}"
                      f"（mismatched={shadow.get('mismatched')}）")
    if (data.get("case_shadow") or {}).get("stale_facts"):
        console.print(f"  stale 事实：{data['case_shadow']['stale_facts']} 条"
                      f"（契约换版前采集的，不参与推导）")


@contract.command("show")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_show(run_dir, json_output):
    """查看契约与义务清单（按 case 归并）"""
    from src.ir_plane.contract import load_contract, read_manifest

    root = _resolve_run_dir(run_dir)
    manifest = read_manifest(root)
    model = load_contract(root)
    if model is None:
        click.echo("契约不存在或不完整（先 `vagent contract build`）", err=True)
        raise SystemExit(2)
    if json_output:
        click.echo(json.dumps({"manifest": manifest,
                               "contract": model.model_dump(by_alias=True)},
                              ensure_ascii=False, indent=2))
        return
    console.print(f"[bold]{manifest.get('contract_id')}[/bold] · "
                  f"{manifest.get('obligations')} 条义务")
    for case in model.cases:
        console.print(f"  {case.id}: 组 {len(case.groups)} · "
                      f"SVA {len(case.sva)} · SB {len(case.scb)}")
