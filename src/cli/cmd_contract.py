"""SignOffAI CLI 命令组：契约（contract）—— Verification OS v3 · M1。

契约是**构建物**：`vagent contract build` 把 `coverage/case_ir.json`（或给定
的 case 模型）编译成 `contract/contract.yaml` + `obligations.json` +
`contract_manifest.json`；`ops` 用 `contract check` 同一套逻辑做前置门禁。
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from src.cli.commands import cli, console


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
@click.option("--config", "-c", "config", default="",
              type=click.Path(dir_okay=False),
              help="case 模型 YAML（没有 case_ir 时现编译）")
@click.option("--module", "-m", "module", default="", help="模块名（缺省取运行目录/模型）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_build(run_dir, config, module, json_output):
    """把 case IR 编译成契约构建物（contract/contract.yaml + 义务 + 清单）

    \b
    示例:
      vagent contract build --run output_xxx
      vagent contract build --run output_xxx --config specs/npu_sched/casemodel.yaml
    """
    from src.tools.checking.verification_os import write_contract

    root = _resolve_run_dir(run_dir)
    case_ir_path = root / "coverage" / "case_ir.json"
    case_ir = {}
    if case_ir_path.is_file():
        try:
            case_ir = json.loads(case_ir_path.read_text(encoding="utf-8"))
        except ValueError:
            case_ir = {}
    if config and not Path(config).is_file():
        click.echo(f"case 模型不存在: {config}", err=True)
        raise SystemExit(2)
    if not case_ir.get("cases") and config:
        from src.tools.generation.casemodel_tools.api import run_testpoints

        payload = run_testpoints(Path(config).read_text(encoding="utf-8"),
                                 env_name=f"{module or root.name}_env",
                                 module_name=module or root.name)
        if payload.get("error"):
            click.echo(f"case 模型编译失败: {payload['error']}", err=True)
            raise SystemExit(2)
        case_ir = payload.get("case_ir") or {}
    if not case_ir.get("cases"):
        click.echo("没有 case IR：先跑 verify，或用 --config 给 case 模型", err=True)
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
    from src.tools.checking.verification_os import check_contract

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


@contract.command("show")
@click.option("--run", "-o", "run_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def contract_show(run_dir, json_output):
    """查看契约与义务清单（按 case 归并）"""
    from src.tools.checking.verification_os import load_contract, read_manifest

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
