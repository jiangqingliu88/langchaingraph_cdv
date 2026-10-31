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
from src.cli.soc_adapter import (
    find_wave, load_run_manifest, run_soc_project, verify_soc_evidence,
)

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
    console.print(f"[cyan]SoC 回归[/cyan] {root}")
    run = run_soc_project(root, output)
    result = run.get("result") or {}
    summary = run.get("summary") or {}
    if json_output:
        click.echo(json.dumps(run, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"  输出：{run.get('output_root', '')}")
        status = result.get("status", "?")
        console.print(f"  status={status} passed={result.get('passed', 0)} "
                      f"failed={result.get('failed', 0)} "
                      f"unknown={result.get('unknown', 0)} total={result.get('total', 0)}")
        if result.get("report_path"):
            console.print(f"  report: {result['report_path']}")
        if summary.get("path"):
            console.print(f"  manifest: {summary['path']}")
        if (summary.get("evidence") or {}).get("path"):
            console.print(f"  evidence: {summary['evidence']['path']}")
        for wave in summary.get("waves") or []:
            console.print(f"  wave: {wave['path']}")
        if result.get("error") or run.get("error"):
            console.print(f"[red]{result.get('error') or run.get('error')}[/red]")
    raise SystemExit(0 if result.get("status") == "PASS" else 1)


def _latest_soc_run() -> Path | None:
    here = Path.cwd()
    runs = sorted((p for p in here.glob("output_soc_*") if p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None


@soc_group.command("report")
@click.argument("run", required=False, type=click.Path(exists=True, file_okay=False,
                                                       path_type=Path))
def soc_report(run):
    """打印一次 SoC run 的 `soc/soc_run.json` 摘要。"""
    root = Path(run).resolve() if run else _latest_soc_run()
    if root is None:
        raise click.ClickException("找不到 output_soc_*；先跑 `vagent soc run`")
    doc = load_run_manifest(root)
    if not doc:
        raise click.ClickException(f"{root} 没有 soc/soc_run.json；先跑 `vagent soc run`")
    reg = doc.get("regression") or {}
    console.print(f"[cyan]SoC run[/cyan] {root.name}")
    console.print(f"  project={doc.get('project', {}).get('name')} "
                  f"rtl_hash={str(doc.get('project', {}).get('rtl_hash'))[:12]}…")
    console.print(f"  status={reg.get('status')} passed={reg.get('passed')} "
                  f"failed={reg.get('failed')} total={reg.get('total')}")
    evidence = root / "signoff_evidence" / "manifest.json"
    if evidence.is_file():
        console.print(f"  evidence: {evidence}")
    for wave in doc.get("waves") or []:
        console.print(f"  wave: {wave.get('path')}")


@soc_group.command("evidence")
@click.argument("run", required=False, type=click.Path(exists=True, file_okay=False,
                                                       path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def soc_evidence(run, json_output):
    """校验一次 SoC run 的证据包（逐文件哈希 + package_hash）。"""
    root = Path(run).resolve() if run else _latest_soc_run()
    if root is None:
        raise click.ClickException("找不到 output_soc_*；先跑 `vagent soc run`")
    result = verify_soc_evidence(root)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        mark = "✓" if result["ok"] else "✗"
        console.print(f"{mark} SoC 证据包 {result['files']} 个文件 · "
                      f"package_hash {str(result.get('package_hash'))[:16]}…")
        for issue in result.get("issues") or []:
            console.print(f"  [red]{issue}[/red]")
    raise SystemExit(0 if result["ok"] else 1)


@soc_group.command("wave")
@click.argument("run", required=False, type=click.Path(exists=True, file_okay=False,
                                                       path_type=Path))
@click.option("--list", "list_only", is_flag=True, help="只打印波形路径，不打开")
def soc_wave(run, list_only):
    """打开最近一次 SoC run 的波形（qwave.db → Visualizer）。"""
    root = Path(run).resolve() if run else _latest_soc_run()
    if root is None:
        raise click.ClickException("找不到 output_soc_*；先跑 `vagent soc run`")
    wave = find_wave(root)
    if wave is None:
        raise click.ClickException(
            f"{root} 没有波形；确认 regression.yaml 的 `-qwavedb` 已启用")
    console.print(f"wave: {wave}")
    if list_only or not wave.is_file():
        return
    import subprocess
    from config.settings import questa_exe

    if wave.suffix.lower() == ".wlf":
        exe = questa_exe("vsim.exe")
        args = ["-view", str(wave), "-do", "add wave -r /*"]
    else:
        exe = questa_exe("visualizer.exe")
        args = ["-wavefile", str(wave)]
    if not os.path.exists(exe):
        raise click.ClickException(f"找不到打开波形的程序：{exe}")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008     # DETACHED_PROCESS
    try:
        subprocess.Popen([exe, *args], **kwargs)
    except OSError as exc:
        raise click.ClickException(f"打开波形失败：{exc}")
    console.print("已打开 Questa Visualizer" if wave.suffix.lower() != ".wlf"
                  else "已打开 vsim -view")
