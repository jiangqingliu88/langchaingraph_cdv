"""
dvtool — 轻量仿真工具，替代 dvsim
只做三件事: compile → run → report
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import yaml

# ── 默认配置 ──
DEFAULT_CONFIG = {
    "tool": "questa",
    "top": "tb",
    "timescale": "1ns/1ps",
    "uvm": True,
    "build_opts": ["+define+UVM", "+define+SIMULATION"],
    "run_opts": [],
    "pass_pattern": r"TEST PASSED",
    "fail_pattern": r"(UVM_ERROR|UVM_FATAL|TEST FAILED|^\s*\*\*\s*Error)",
    "timeout_s": 300,
}


def load_config(path: str) -> dict:
    """加载 YAML 配置，合并默认值"""
    cfg = dict(DEFAULT_CONFIG)
    if Path(path).exists():
        cfg.update(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    return cfg


def compile(cfg: dict) -> tuple[bool, str]:
    """编译: qrun -f filelist.f -top tb ..."""
    opts = cfg.get("build_opts", [])
    if cfg.get("uvm"):
        opts = ["-uvm"] + opts

    cmd = [
        "qrun", "-optimize",
        "-timescale", cfg["timescale"],
        "-f", cfg["filelist"],
        "-top", cfg["top"],
        "-outdir", str(Path(cfg.get("outdir", "build")) / "qrun.out"),
        "-voptargs=+acc=nr",
    ] + opts

    print(f"[compile] {' '.join(cmd[:6])} ...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.get("timeout_s", 300))
    log = r.stdout + r.stderr
    ok = "Errors: 0" in log or "Errors:   0" in log
    return ok, log


def run_test(cfg: dict, test: dict, seed: int = 1) -> dict:
    """运行一个 test: qrun -simulate +UVM_TESTNAME=..."""
    cmd = [
        "qrun", "-simulate",
        "-f", cfg["filelist"],
        "-top", cfg["top"],
        "-outdir", str(Path(cfg.get("outdir", "build")) / "qrun.out"),
        "-sv_seed", str(seed),
        "+UVM_TESTNAME=" + test["uvm_test"],
    ]
    if "uvm_seq" in test:
        cmd.append("+UVM_TEST_SEQ=" + test["uvm_seq"])

    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=cfg.get("timeout_s", 300))
        elapsed = time.time() - t0
    except subprocess.TimeoutError:
        return {"name": test["name"], "seed": seed, "status": "TIMEOUT",
                "elapsed": cfg["timeout_s"], "log": ""}

    log = r.stdout + r.stderr
    passed = bool(re.search(cfg["pass_pattern"], log))
    failed = bool(re.search(cfg["fail_pattern"], log))
    status = "PASS" if passed and not failed else "FAIL"

    return {
        "name": test["name"],
        "seed": seed,
        "status": status,
        "elapsed": round(elapsed, 1),
        "log": log[-2000:],
    }


def run_all(cfg: dict) -> dict:
    """编译 + 跑所有 tests + 出结果"""
    results = {"tool": cfg["tool"], "tests": [], "passed": 0, "failed": 0, "total": 0}

    # Step 1: 编译
    ok, build_log = compile(cfg)
    if not ok:
        results["build"] = "FAIL"
        results["build_log"] = build_log[-1000:]
        return results
    results["build"] = "PASS"

    # Step 2: 跑 tests
    seeds = cfg.get("seeds", 1)
    for test in cfg.get("tests", []):
        for s in range(seeds):
            r = run_test(cfg, test, seed=s + 1)
            results["tests"].append(r)
            results["total"] += 1
            if r["status"] == "PASS":
                results["passed"] += 1
            else:
                results["failed"] += 1
            print(f"  [{r['status']}] {r['name']} seed={r['seed']} ({r['elapsed']}s)")

    return results


# ── CLI ──
def main():
    if len(sys.argv) < 2:
        print("Usage: python dvtool.py <config.yaml> [--json]")
        print("       python dvtool.py <config.yaml> --compile-only")
        sys.exit(1)

    cfg_path = sys.argv[1]
    cfg = load_config(cfg_path)

    if "--compile-only" in sys.argv:
        ok, log = compile(cfg)
        print(log[-2000:])
        sys.exit(0 if ok else 1)

    results = run_all(cfg)
    summary = {
        "build": results["build"],
        "passed": results["passed"],
        "failed": results["failed"],
        "total": results["total"],
        "tests": results["tests"],
    }

    if "--json" in sys.argv:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"\nBuild: {results['build']}")
        print(f"Tests: {results['passed']}/{results['total']} passed")
        for t in results["tests"]:
            icon = "+" if t["status"] == "PASS" else "X"
            print(f"  [{icon}] {t['name']} s={t['seed']} {t['elapsed']}s")

    # 保存结果
    out = Path(cfg.get("outdir", "build")) / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults: {out}")

    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
