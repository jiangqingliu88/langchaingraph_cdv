"""SoC 参考工程适配 CLI —— 薄层，不另造执行引擎。

    vagent soc check  examples/open_npu_soc
    vagent soc golden examples/open_npu_soc
    vagent soc run    examples/open_npu_soc --output output_soc_v01

`run` 复用现有 `InfrastructureManager.run_regression`；`golden` 只是调用工程自带
的 Python 模型；`check` 只读校验输入。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import click

from src.cli.commands import cli, console
from src.cli.output import get_output_adapter

_REQUIRED = (
    "rtl/soc_top.sv",
    "tb/tb_soc_top.sv",
    "filelist.f",
    "golden/gemm_golden.py",
    "regression/regression.yaml",
    "spec/soc_spec.yaml",
)


@cli.group("soc")
def soc_group():
    """SoC 参考工程：检查 / 生成 golden / 跑现有回归"""
    pass


@soc_group.command("check")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def soc_check(project, json_output):
    """检查参考工程的输入是否齐全（不跑 EDA）。"""
    root = Path(project).resolve()
    missing = [rel for rel in _REQUIRED if not (root / rel).is_file()]
    filelist = root / "filelist.f"
    listed, missing_listed = [], []
    if filelist.is_file():
        for line in filelist.read_text(encoding="utf-8", errors="replace").splitlines():
            rel = line.strip()
            if not rel or rel.startswith(("#", "//", "+incdir+")):
                continue
            listed.append(rel)
            if not (root / rel).is_file():
                missing_listed.append(rel)
    result = {
        "project": str(root),
        "ok": not missing and not missing_listed,
        "missing": missing,
        "filelist": listed,
        "filelist_missing": missing_listed,
    }
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["ok"]:
        console.print(f"[green]✓ SoC 工程输入齐全[/green]  {root}")
        console.print(f"  filelist: {len(listed)} 个 RTL/TB 文件")
    else:
        console.print(f"[red]✗ SoC 工程输入不完整[/red]  {root}")
        for rel in missing + missing_listed:
            console.print(f"  - 缺少 {rel}")
    raise SystemExit(0 if result["ok"] else 1)


@soc_group.command("golden")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--size", type=int, default=8, show_default=True)
@click.option("--seed", type=int, default=20261031, show_default=True)
def soc_golden(project, size, seed):
    """生成 golden 向量（固定 seed，可复现）。"""
    root = Path(project).resolve()
    script = root / "golden" / "gemm_golden.py"
    if not script.is_file():
        raise click.ClickException(f"找不到 golden 模型：{script}")
    proc = subprocess.run(
        [sys.executable, str(script), "--out", str(root / "vectors"),
         "--size", str(size), "--seed", str(seed)],
        cwd=str(root), text=True, capture_output=True)
    if proc.returncode != 0:
        raise click.ClickException(proc.stderr.strip() or "golden 生成失败")
    console.print(proc.stdout.strip())


@soc_group.command("run")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", "-o", type=click.Path(file_okay=False), default=None,
              help="输出目录（缺省 output_soc_<工程名>）")
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def soc_run(project, output, json_output):
    """用现有回归执行器跑 SoC 工程（需要 vlog/vsim 在 PATH）。"""
    root = Path(project).resolve()
    reg = root / "regression" / "regression.yaml"
    if not reg.is_file():
        raise click.ClickException(f"找不到回归配置：{reg}")
    os.environ["SOC_ROOT"] = str(root)

    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    from src.layers.l1_infrastructure.output_config import make_output_root

    out_root = make_output_root(output or f"output_soc_{root.name}")
    console.print(f"[cyan]SoC 回归[/cyan] {root}")
    console.print(f"  输出：{out_root}")
    infra = InfrastructureManager(out_root)
    result = infra.run_regression(reg_yaml=str(reg), mode="local")
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        status = result.get("status", "?")
        console.print(f"  status={status} passed={result.get('passed', 0)} "
                      f"failed={result.get('failed', 0)} "
                      f"unknown={result.get('unknown', 0)} total={result.get('total', 0)}")
        if result.get("report_path"):
            console.print(f"  report: {result['report_path']}")
        if result.get("error"):
            console.print(f"[red]{result['error']}[/red]")
    raise SystemExit(0 if result.get("status") == "PASS" else 1)
