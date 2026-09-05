#!/usr/bin/env python3
"""tool_testrun —— 测试点回归执行器（testpoint 闭环 ④⑤）。

输入: regression_plan.yaml（tool_testgen 产物）+ 生成输出目录
流程:
  ① 编译: vlog -sv -f env/{module}_pkg_filelist.f（Questar）或 vcs
  ② 逐用例 × 种子仿真: +UVM_TESTNAME=<tc> +SEED=<s> (+POLICY_MODE= / +NUM_TRANS=)
  ③ 解析日志 → results.json + test_run_results.md
  ④ 回写 testpoint xlsx（execution sheet: exec_status/exec_comment）
仿真器缺失 → 全部 SKIP（记录原因，不报错；装好 vlog/vcs 后同一命令跑真流程）。

用法:
  python -m src.tools.uvm_tools.tool_testrun.main -p generated/regression_plan.yaml -d generated
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__version__ = "0.1.0"

try:
    from ..tool_uvm.gen_uvm import _detect_simulator
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tool_uvm"))
    from gen_uvm import _detect_simulator

SIM_TIMEOUT_S = 300


def _load_plan(plan_path: Path) -> Dict[str, Any]:
    import yaml as _yaml
    data = _yaml.safe_load(plan_path.read_text(encoding="utf-8", errors="replace")) or {}
    reg = data.get("regression") or {}
    if not reg.get("module"):
        raise SystemExit(f"regression_plan 缺 module: {plan_path}")
    return reg


def _compile(sim: str, dest: Path, module: str, log) -> Optional[str]:
    """整环境编译。成功返回 None，失败返回错误描述。"""
    filelist = dest / "env" / f"{module}_pkg_filelist.f"
    if not filelist.is_file():
        return f"filelist not found: {filelist}"
    work = dest / "build"
    work.mkdir(parents=True, exist_ok=True)
    if sim == "vlog":
        cmds = [["vlog", "-sv", "-work", str(work), "-f", str(filelist),
                 "-l", str(work / "compile.log")]]
    else:
        cmds = [["vcs", "-sverilog", "-f", str(filelist),
                 "-l", str(work / "compile.log"), "-o", str(work / "simv")]]
    for cmd in cmds:
        try:
            proc = subprocess.run(cmd, cwd=str(dest), capture_output=True,
                                  text=True, timeout=600)
        except Exception as exc:
            return f"compile exception: {exc}"
        if proc.returncode != 0:
            log.write_text((proc.stdout or "") + (proc.stderr or ""),
                           encoding="utf-8", errors="replace")
            return f"compile failed (see {work / 'compile.log'})"
    return None


def _run_one(sim: str, dest: Path, work: Path, tc_name: str, seed: int,
             plusargs: List[str], log_dir: Path) -> Tuple[str, str]:
    """跑一个用例×种子 → (status, log_path)。status ∈ pass/fail/timeout/error/skip。"""
    log_path = log_dir / f"{tc_name}_seed{seed}.log"
    common = [f"+UVM_TESTNAME={tc_name}", f"+SEED={seed}"] + plusargs
    if sim == "vlog":
        # 顶层模块 = bench 目录下 *_tb_top.sv（filelist 约定）
        tb_top = next((p.name for p in (dest / "bench").glob("*_tb_top.sv")
                       if p.is_file()), None)
        if tb_top is None:
            return "error", f"no *_tb_top.sv found in {dest / 'bench'}"
        cmd = ["vsim", "-c", "-l", str(log_path),
               "-do", "run -all; quit -f", "-lib", str(work),
               tb_top[:-3]] + common
    else:
        cmd = [str(work / "simv"), "-l", str(log_path)] + common
    try:
        proc = subprocess.run(cmd, cwd=str(dest), capture_output=True,
                              text=True, timeout=SIM_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return "timeout", str(log_path)
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"

    log_text = ""
    if log_path.is_file():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    log_text += (proc.stdout or "") + (proc.stderr or "")

    if "UVM_FATAL" in log_text or "UVM_ERROR" in log_text or "TEST FAILED" in log_text:
        return "fail", str(log_path)
    if "TEST PASSED" in log_text or "PASSED" in log_text:
        return "pass", str(log_path)
    if proc.returncode != 0:
        return "fail", str(log_path)
    return "unknown", str(log_path)


def _writeback_xlsx(plan: Dict[str, Any], results: List[Dict[str, str]]) -> Optional[str]:
    """④ 执行结果回写 testpoint xlsx（新增 execution sheet）。"""
    xlsx_path = plan.get("source_xlsx")
    if not xlsx_path or not Path(xlsx_path).is_file():
        return None
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path)
    if "execution" in wb.sheetnames:
        del wb["execution"]
    ws = wb.create_sheet("execution")
    ws.append(["id", "tc_name", "seed", "status", "log"])
    for r in results:
        ws.append([r.get("id", "-"), r.get("tc_name", "-"), r.get("seed", "-"),
                   r.get("status", "-"), r.get("log", "-")])
    try:
        wb.save(xlsx_path)
        return xlsx_path
    except PermissionError:
        # 源 xlsx 被 Excel 占用：落一份带执行结果的副本
        alt = Path(xlsx_path).with_name(Path(xlsx_path).stem + "_execution.xlsx")
        wb.save(alt)
        return f"{alt}（源文件被占用，结果写入副本）"


def _render_results_md(plan: Dict[str, Any], results: List[Dict[str, str]]) -> str:
    lines = [
        f"# Test Run Results — {plan.get('module', '-')}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| id | tc_name | seed | status | log |",
        "|----|---------|------|--------|-----|",
    ]
    for r in results:
        lines.append(f"| {r.get('id', '-')} | `{r.get('tc_name', '-')}` "
                     f"| {r.get('seed', '-')} | {r.get('status', '-')} "
                     f"| {r.get('log', '-')} |")
    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] in ("fail", "timeout", "error", "unknown"))
    lines += ["", f"**Summary: {n_pass} pass / {n_fail} fail / "
                  f"{len(results) - n_pass - n_fail} skip/other**", ""]
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_signoff_package(dest: Path, plan: Dict[str, Any],
                          results: List[Dict[str, str]],
                          extra_inputs: List[str]) -> Path:
    """签核证据包（项目愿景 Phase 2）：输入/输出 hash 清单 + 证据副本 + 汇总文档。"""
    module = plan.get("module", "module")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pkg_dir = dest / "signoff" / f"{module}_signoff_{ts}"
    (pkg_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (pkg_dir / "evidence").mkdir(parents=True, exist_ok=True)

    # 收集输入文件（report json inputs + source_xlsx + --inputs；目录展开为 YAML）
    inputs: List[Path] = []
    raw_inputs: List[str] = []
    gen_report = dest / "generation_report.json"
    if gen_report.is_file():
        try:
            gr = json.load(open(gen_report, encoding="utf-8"))
            raw_inputs += [str(p) for p in gr.get("inputs", [])]
        except Exception:
            pass
    raw_inputs += [plan.get("source_xlsx", "")] + list(extra_inputs)
    for p in raw_inputs:
        if not p:
            continue
        pp = Path(p)
        if pp.is_dir():
            inputs += sorted(list(pp.rglob("*.yaml")) + list(pp.rglob("*.yml")))
        elif pp.is_file() and pp not in inputs:
            inputs.append(pp)
    inputs = list(dict.fromkeys(inputs))   # 去重保序

    manifest_inputs = []
    for p in inputs:
        copy = pkg_dir / "inputs" / p.name
        shutil.copy2(p, copy)
        manifest_inputs.append({"file": str(p), "sha256": _sha256(p)})

    # 证据文件副本
    evidence_files = ["test_run_results.json", "test_run_results.md",
                      "generation_report.json", "validation_report.txt",
                      "testpoint_trace.md", "regression_plan.yaml"]
    manifest_outputs = []
    for name in evidence_files:
        src = dest / name
        if src.is_file():
            shutil.copy2(src, pkg_dir / "evidence" / name)
            manifest_outputs.append({"file": name, "sha256": _sha256(src)})

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] in ("fail", "timeout", "error"))
    manifest = {
        "module": module,
        "packaged_at": ts,
        "inputs": manifest_inputs,
        "outputs": manifest_outputs,
        "results_summary": {
            "total": len(results), "pass": n_pass,
            "fail": n_fail, "other": len(results) - n_pass - n_fail,
        },
    }
    (pkg_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 汇总文档
    lines = [
        f"# 签核证据包 — {module}",
        "",
        f"- 打包时间: {ts}",
        f"- 用例结果: {manifest['results_summary']['total']} 次执行，"
        f"{n_pass} pass / {n_fail} fail / "
        f"{len(results) - n_pass - n_fail} skip/other",
        f"- 输入文件: {len(manifest_inputs)} 个（YAML/xlsx，hash 见 manifest.json）",
        f"- 证据文件: {len(manifest_outputs)} 个（结果/校验/追溯，hash 见 manifest.json）",
        "",
        "## 执行结果",
        "",
    ]
    for r in results:
        lines.append(f"- `{r.get('tc_name', '-')}` seed={r.get('seed', '-')}: "
                     f"**{r.get('status', '-')}**")
    lines += [
        "",
        "## 校验警告",
        "",
    ]
    val_report = dest / "validation_report.txt"
    if val_report.is_file():
        for line in val_report.read_text(encoding="utf-8", errors="replace").splitlines():
            if "WARNING" in line or "ERROR" in line:
                lines.append(f"- {line}")
    if not any(l.startswith("- [") for l in lines):
        lines.append("- 无校验警告")
    lines += [
        "",
        "## 追溯与证据",
        "",
        "- 测试点 ↔ 用例 ↔ 约束/覆盖率映射: `evidence/testpoint_trace.md`",
        "- 机器可读结果: `evidence/test_run_results.json`",
        "- 生成/校验/merge/gate 报告: `evidence/generation_report.json`",
        "",
        "完整 hash 清单见 `manifest.json`，任何文件被篡改均可在签核时检出。",
        "",
    ]
    (pkg_dir / "signoff_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return pkg_dir


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tool_testrun",
        description="测试点回归执行器（编译 + 逐用例×种子仿真 + 结果回写 xlsx/trace）。")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s (tool_testrun) {__version__}")
    parser.add_argument("-p", "--plan", help="regression_plan.yaml 路径")
    parser.add_argument("-d", "--dest_dir", default="generated",
                        help="生成输出目录（filelist/bench 所在根）")
    parser.add_argument("-s", "--sim", choices=("vlog", "vcs"),
                        help="仿真器（缺省自动探测 vlog/vcs）")
    parser.add_argument("--seed-start", type=int, default=1,
                        help="起始种子（缺省 1）")
    parser.add_argument("--seed-count", type=int, default=3,
                        help="每用例种子数（缺省 3，取 plan 内 seeds 前 N 个）")
    parser.add_argument("--signoff-package", action="store_true",
                        help="生成签核证据包（manifest.json + 输入/证据副本 + 汇总文档）")
    parser.add_argument("--inputs", nargs="+",
                        help="额外输入文件（YAML/xlsx，随证据包归档）")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg)

    if not args.plan:
        parser.error("需要 -p <regression_plan.yaml>")
    plan_path = Path(args.plan).expanduser()
    dest = Path(args.dest_dir).expanduser()
    plan = _load_plan(plan_path)

    sim = args.sim or _detect_simulator()
    module = plan["module"]
    work = dest / "build"
    log_dir = dest / "sim_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, str]] = []

    if sim is None:
        # 无仿真器：全部 SKIP，但仍生成报告结构（诚实记录）
        log("No UVM simulator (vlog/vcs) found — all tests SKIP")
        seeds = list(plan.get("seeds", []))[:args.seed_count]
        for t in plan.get("tests", []):
            for s in seeds:
                results.append({"id": t.get("id", "-"), "tc_name": t.get("tc_name", "-"),
                                "seed": str(s), "status": "skip",
                                "log": "no simulator"})
    else:
        # ① 编译
        compile_log = work / "compile.log"
        err = _compile(sim, dest, module, compile_log)
        if err:
            log(f"Compile: FAILED — {err}")
            for t in plan.get("tests", []):
                results.append({"id": t.get("id", "-"), "tc_name": t.get("tc_name", "-"),
                                "seed": "-", "status": "error", "log": err})
        else:
            log("Compile: OK")
            seeds = list(plan.get("seeds", []))[:args.seed_count] or [1]
            for t in plan.get("tests", []):
                plusargs = []
                if t.get("policy"):
                    plusargs.append(f"+{t['policy']}")
                if t.get("iterations"):
                    plusargs.append(f"+NUM_TRANS={t['iterations']}")
                for s in seeds:
                    status, logf = _run_one(sim, dest, work, t.get("tc_name", "-"),
                                            s, plusargs, log_dir)
                    results.append({"id": t.get("id", "-"),
                                    "tc_name": t.get("tc_name", "-"),
                                    "seed": str(s), "status": status, "log": logf})
                    log(f"  [{status.upper()}] {t.get('tc_name', '-')} seed={s}")

    # ③ 结果文件
    (dest / "test_run_results.json").write_text(
        json.dumps({"module": module, "sim": sim or "none",
                    "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "test_run_results.md").write_text(
        _render_results_md(plan, results), encoding="utf-8")

    # ④ 回写 xlsx
    xlsx_back = _writeback_xlsx(plan, results)
    if xlsx_back:
        log(f"Execution results written back to: {xlsx_back}")

    # ⑤ 签核证据包（项目愿景 Phase 2）
    if args.signoff_package:
        pkg_dir = _make_signoff_package(dest, plan, results, args.inputs or [])
        log(f"Signoff package: {pkg_dir}")

    n_pass = sum(1 for r in results if r["status"] == "pass")
    log(f"Done: {n_pass} pass / {len(results) - n_pass} other — see "
        f"{dest / 'test_run_results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
