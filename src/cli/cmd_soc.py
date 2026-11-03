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
from src.app.services.soc_service import (
    build_ip_release, find_design, find_wave, ip_plan, ip_status,
    list_c_cases, load_run_manifest, run_c_project, run_ip_regression,
    run_soc_project, soc_ip_binding, soc_ip_release_matrix,
    verify_ip_release, verify_soc_evidence, write_ip_evidence,
)

_REQUIRED = (
    "npu/soc_top.sv",
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
    runs = [p for p in here.glob("output_*")
            if p.is_dir() and ((p / "soc" / "soc_run.json").is_file()
                               or (p / "c_run.json").is_file())]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None


@soc_group.command("c-cases")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def soc_c_cases(project, json_output):
    """列出 SoC 的 C 用例（CPU/NICE 驱动 IP）。"""
    cases = list_c_cases(project)
    if json_output:
        click.echo(json.dumps(cases, indent=2, ensure_ascii=False))
        return
    for case in cases:
        console.print(f"{case.get('id')} · {case.get('name')} · "
                      f"IPs={'、'.join(case.get('ips') or [])}")


@soc_group.command("c-run")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--case", "case_id", required=True, help="C 用例 id（如 C-GEMM-8X8）")
@click.option("--output", "-o", default=None)
@click.option("--json", "json_output", is_flag=True)
def soc_c_run(project, case_id, output, json_output):
    """编译并运行 E203 bare-metal C 用例（需要 RISC-V 工具链 + Questa）。"""
    result = run_c_project(project, case_id, output)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"C 用例 {case_id} · {result.get('status')} · "
                      f"{result.get('output_root')}")
        if result.get("error"):
            console.print(f"[red]{result['error']}[/red]")
    raise SystemExit(0 if result.get("status") == "PASS" else 1)


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


@cli.group("ip")
def ip_group():
    """IP 团队：清单 / 验证状态 / 发布检查 / IP 级回归"""
    pass


@ip_group.command("list")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def ip_list(project, json_output):
    """列出 IP 与 team/owner/status。"""
    from src.cli.soc_adapter import list_ips
    ips = list_ips(project)
    if json_output:
        click.echo(json.dumps(ips, indent=2, ensure_ascii=False))
        return
    for ip in ips:
        console.print(f"{ip.get('id')} · {ip.get('name')} · {ip.get('team')} · "
                      f"{ip.get('owner')} · {ip.get('status')}")


@ip_group.command("status")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ip", "ip_id", required=True, help="IP id")
@click.option("--run", "run_root", default="", help="SoC run 目录（缺省最新）")
@click.option("--json", "json_output", is_flag=True)
def ip_status_cmd(project, ip_id, run_root, json_output):
    """IP 的 TP 状态与发布就绪度。"""
    result = ip_status(project, ip_id, run_root)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    console.print(f"{ip_id} · {result.get('status')} · release_ready="
                  f"{result.get('release_ready')} · source={result.get('source_run')}")
    for tp in result.get("testpoints") or []:
        console.print(f"  {tp.get('tp_id')}: {tp.get('status')}")


@ip_group.command("evidence")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ip", "ip_id", required=True)
@click.option("--run", "run_root", default="")
def ip_evidence(project, ip_id, run_root):
    """生成 IP 级证据（引用来源 SoC run）。"""
    result = write_ip_evidence(project, ip_id, run_root)
    if not result:
        raise click.ClickException("没有可用的 SoC run")
    console.print(f"✓ IP 证据 {result['path']} · {result['status']} · "
                  f"release_ready={result['release_ready']}")


@ip_group.command("release")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--run", "run_root", default="")
@click.option("--json", "json_output", is_flag=True)
def ip_release(project, run_root, json_output):
    """SoC 团队消费的 IP release matrix。"""
    rows = soc_ip_release_matrix(project, run_root)
    if json_output:
        click.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for row in rows:
        ip = row.get("ip") or {}
        console.print(f"{ip.get('id')} · {row.get('status')} · "
                      f"release={'✓' if row.get('release_ready') else '✗'} · "
                      f"owner={ip.get('owner')}")


@ip_group.command("release-build")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ip", "ip_id", required=True)
@click.option("--run", "run_root", default="",
              help="来源 run（缺省用该 IP 最近一次 IP run）")
@click.option("--by", "released_by", default="", help="发布人（缺省取 IP owner）")
@click.option("--json", "json_output", is_flag=True)
def ip_release_build(project, ip_id, run_root, released_by, json_output):
    """生成 IP 发布包（spec/ip_releases/<ip>.json）。

    准则没过也照样写盘，但 `released=false` 并列出 blocking —— 发布与否是人的决定。
    """
    result = build_ip_release(project, ip_id, run_root, released_by)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    elif not result.get("ok"):
        click.echo(result.get("error") or "生成失败")
    else:
        console.print(f"{'✓ released' if result['released'] else '✗ blocked'} · "
                      f"{result['path']} · sha256 {result['sha256'][:16]}…")
        for c in result.get("criteria") or []:
            mark = {"pass": "✓", "fail": "✗", "unknown": "?"}.get(c["status"], "?")
            console.print(f"  {mark} {c['id']}"
                          f"（{'必需' if c['required'] else '参考'}）{c['detail']}")
    raise SystemExit(0 if result.get("ok") and result.get("released") else 1)


@ip_group.command("release-check")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ip", "ip_id", required=True)
@click.option("--json", "json_output", is_flag=True)
def ip_release_check(project, ip_id, json_output):
    """校验发布包：自身哈希 / 是否放行 / 与清单 RTL hash 是否还绑得住。"""
    result = verify_ip_release(project, ip_id)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    elif result.get("ok"):
        pkg = result.get("package") or {}
        console.print(f"✓ {ip_id} {pkg.get('version')} · "
                      f"sha256 {str(pkg.get('sha256'))[:16]}…")
    else:
        console.print(f"✗ {ip_id}：{result.get('issues')}")
    raise SystemExit(0 if result.get("ok") else 1)


@ip_group.command("binding")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def ip_binding(project, json_output):
    """SoC 视角：每个 IP 绑的发布包状态（OK / STALE / MISSING / UNRELEASED）。"""
    rows = soc_ip_binding(project)
    if json_output:
        click.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for row in rows:
        console.print(f"{row['ip_id']} · {row['state']} · "
                      f"release={row.get('release_version') or '-'} · "
                      f"manifest={row.get('manifest_version') or '-'}")


@ip_group.command("run")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ip", "ip_id", required=True)
@click.option("--output", "-o", default=None)
@click.option("--json", "json_output", is_flag=True)
def ip_run(project, ip_id, output, json_output):
    """按 IP verification plan 的 tests 跑一次 IP 回归。"""
    result = run_ip_regression(project, ip_id, output)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"IP {ip_id} · {result.get('status')} · "
                      f"{result.get('output_root')} · "
                      f"evidence={(result.get('ip_evidence') or {}).get('path')}")
    raise SystemExit(0 if result.get("status") == "PASS" else 1)


@soc_group.command("wave")
@click.argument("run", required=False, type=click.Path(exists=True, file_okay=False,
                                                       path_type=Path))
@click.option("--list", "list_only", is_flag=True, help="只打印波形路径，不打开")
@click.option("--test", "-t", "test_name", default="",
              help="按用例名筛选（如 gemm_8x8_c）")
def soc_wave(run, list_only, test_name):
    """打开 SoC run / C 用例 run 的波形（qwave.db → Visualizer）。"""
    root = Path(run).resolve() if run else _latest_soc_run()
    if root is None:
        raise click.ClickException("找不到 output_* run；先跑 `vagent soc run` 或 `soc c-run`")
    wave = find_wave(root, test_name)
    if wave is None:
        raise click.ClickException(
            f"{root} 没有波形；确认 regression.yaml 的 `-qwavedb` / c-run 已启用")
    design = find_design(root, wave)
    console.print(f"wave: {wave}")
    if design:
        console.print(f"design: {design}")
    if list_only or not wave.is_file():
        return
    import subprocess
    from config.settings import questa_exe

    if wave.suffix.lower() == ".wlf":
        exe = questa_exe("vsim.exe")
        args = ["-view", str(wave), "-do", "add wave -r /*"]
    else:
        exe = questa_exe("visualizer.exe")
        args = (["-designfile", str(design)] if design else []) + [
            "-wavefile", str(wave)]
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
