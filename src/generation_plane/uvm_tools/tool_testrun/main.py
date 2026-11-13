#!/usr/bin/env python3
"""tool_testrun —— 回归执行 + xlsx execution 回写 + 签核证据包。

闭环 ④⑤：tool_uvmtestgen（regression_plan.yaml）→ 本工具跑回归 →
回写 testpoint xlsx execution 表 + 生成签核证据包（manifest + summary）。

用法:
    python -m src.generation_plane.uvm_tools.tool_testrun.main \
        -p generated/regression_plan.yaml -d generated/ \
        --signoff-package --inputs <interface.yaml>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _detect_simulator() -> Optional[str]:
    for name in ("vlog", "vcs"):
        if shutil.which(name):
            return name
    return None


def _load_plan(plan_path: Path) -> Dict[str, Any]:
    import yaml
    data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    return data.get("regression", {}) or {}


def _run_one(test: Dict[str, Any], seed: int, sim: Optional[str]) -> Dict[str, Any]:
    """跑一个 test × seed；无仿真器 → skip（失败响亮，不假通过）。"""
    if sim is None:
        return {"test": test.get("tc_name", test.get("id", "?")),
                "id": test.get("id", ""), "seed": seed, "status": "skip",
                "reason": "no UVM simulator (vlog/vcs)"}
    # 有仿真器时：vsim +UVM_TESTNAME=<tc> -seed <seed>（此处为骨架，需 EDA 环境实测）
    return {"test": test.get("tc_name", test.get("id", "?")),
            "id": test.get("id", ""), "seed": seed, "status": "pending",
            "reason": f"simulator {sim} detected; run not implemented (EDA env)"}


def _write_results_json(dest: Path, results: List[Dict[str, Any]]) -> Path:
    path = dest / "test_run_results.json"
    payload = {
        "generated": datetime.now().isoformat(),
        "results": results,
        "summary": {"total": len(results),
                    "passed": sum(1 for r in results if r["status"] == "pass"),
                    "failed": sum(1 for r in results if r["status"] == "fail"),
                    "skipped": sum(1 for r in results if r["status"] == "skip")},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_results_md(dest: Path, results: List[Dict[str, Any]]) -> Path:
    path = dest / "test_run_results.md"
    lines = [f"# Test Run Results", "",
             f"Generated: {datetime.now().isoformat()}", "",
             "| test | id | seed | status | reason |", "|------|----|------|--------|--------|"]
    for r in results:
        lines.append(f"| {r['test']} | {r['id']} | {r['seed']} | {r['status']} | {r['reason']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_xlsx_execution(xlsx_path: Path, results: List[Dict[str, Any]]) -> None:
    """回写 testpoint xlsx 的 execution 表（若存在则覆盖，否则新建）。"""
    if not xlsx_path.is_file():
        return
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path)
    if "execution" in wb.sheetnames:
        ws = wb["execution"]
    else:
        ws = wb.create_sheet("execution")
    # 表头（幂等重写）
    ws.delete_rows(1, ws.max_row)
    ws.append(["id", "test", "seed", "status", "reason"])
    for r in results:
        ws.append([r.get("id", ""), r.get("test", ""), r.get("seed", ""),
                   r.get("status", ""), r.get("reason", "")])
    wb.save(xlsx_path)


def _write_signoff_package(dest: Path, results: List[Dict[str, Any]],
                           inputs: List[Path]) -> Path:
    """生成签核证据包：signoff/<时间戳>/manifest.json + signoff_summary.md。"""
    import time
    pkg_dir = dest / "signoff" / datetime.now().strftime("%Y%m%d_%H%M%S")
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # 输入/输出文件（带 sha256，可追溯）
    outputs = []
    for name in ("test_run_results.json", "test_run_results.md"):
        p = dest / name
        if p.is_file():
            outputs.append({"path": p.name, "sha256": _sha256(p)})
    input_entries = []
    for p in inputs:
        if Path(p).is_file():
            pp = Path(p)
            input_entries.append({"path": str(pp), "sha256": _sha256(pp)})

    manifest = {
        "generated": datetime.now().isoformat(),
        "inputs": input_entries,
        "outputs": outputs,
        "summary": {"total": len(results),
                    "passed": sum(1 for r in results if r["status"] == "pass"),
                    "failed": sum(1 for r in results if r["status"] == "fail"),
                    "skipped": sum(1 for r in results if r["status"] == "skip")},
    }
    (pkg_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = [
        f"# 签核证据包", "",
        f"生成时间: {manifest['generated']}", "",
        f"- 总用例: {manifest['summary']['total']}",
        f"- 通过: {manifest['summary']['passed']}",
        f"- 失败: {manifest['summary']['failed']}",
        f"- 跳过: {manifest['summary']['skipped']}", "",
        "## 输入（sha256 可追溯）", "",
    ]
    for e in input_entries:
        summary.append(f"- `{e['path']}` sha256={e['sha256'][:16]}")
    summary += ["", "## 输出", ""]
    for e in outputs:
        summary.append(f"- `{e['path']}` sha256={e['sha256'][:16]}")
    (pkg_dir / "signoff_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return pkg_dir


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="回归执行 + xlsx 回写 + 签核证据包")
    ap.add_argument("-p", "--plan", required=True, help="regression_plan.yaml 路径")
    ap.add_argument("-d", "--dest_dir", default="generated", help="输出目录")
    ap.add_argument("--signoff-package", action="store_true", help="生成签核证据包")
    ap.add_argument("--inputs", nargs="+", default=[], help="输入文件（写入证据包 sha256）")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    dest = Path(args.dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    plan = _load_plan(Path(args.plan))
    sim = _detect_simulator()

    tests = plan.get("tests", []) or []
    seeds = plan.get("seeds", [1]) or [1]
    results = []
    for t in tests:
        for s in seeds:
            results.append(_run_one(t, s, sim))

    _write_results_json(dest, results)
    _write_results_md(dest, results)
    src_xlsx = plan.get("source_xlsx", "")
    if src_xlsx:
        _write_xlsx_execution(Path(src_xlsx), results)
    if args.signoff_package:
        _write_signoff_package(dest, results, [Path(p) for p in args.inputs])

    if not args.quiet:
        print(f"tool_testrun: {len(results)} runs "
              f"({sum(1 for r in results if r['status']=='pass')} pass, "
              f"{sum(1 for r in results if r['status']=='fail')} fail, "
              f"{sum(1 for r in results if r['status']=='skip')} skip)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
