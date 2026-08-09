"""
真实覆盖率收集 —— 编译 + 仿真 + vcover merge/report

用法:
    python -m src.tools.lib.collect_real_coverage <output_dir> [--top apb_uart_bench_tb_top]
"""
import os, subprocess, json, sys, re
from pathlib import Path


def _questa():
    questa = os.environ.get("QUESTA_HOME", "f:/questasim64_2024.1/win64")
    if questa and not os.path.exists(os.path.join(questa, "vlog.exe")):
        if not os.path.exists(os.path.join(questa, "win64", "vlog.exe")):
            default = "f:/questasim64_2024.1/win64"
            if os.path.exists(os.path.join(default, "vlog.exe")):
                return default
    return questa


def build_rtl_filelist(output_dir: Path) -> Path:
    """构建包含 RTL + UVM bench + env 的编译 filelist"""
    fl_dir = output_dir / "inputs" / "filelists"
    fl_dir.mkdir(parents=True, exist_ok=True)
    fl = fl_dir / "filelist_coverage.f"

    lines = []
    # RTL files
    rtl_dir = output_dir / "rtl"
    if rtl_dir.exists():
        for sv in sorted(rtl_dir.glob("*.sv")):
            lines.append(str(sv.resolve()))

    # UVM agents
    agents_dir = output_dir / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            name = agent_dir.name
            pkg = agent_dir / f"{name}_pkg.sv"
            iface = agent_dir / f"{name}_interface.sv"
            if iface.exists():
                lines.append(str(iface.resolve()))
            lines.append(f"+incdir+{agent_dir.resolve()}")
            if pkg.exists():
                lines.append(str(pkg.resolve()))

    # UVM env
    env_dir = output_dir / "env"
    if env_dir.exists():
        lines.append(f"+incdir+{env_dir.resolve()}")
        for sv in sorted(env_dir.glob("*_pkg.sv")):
            lines.append(str(sv.resolve()))
        seqs_dir = env_dir / "seqs"
        if seqs_dir.exists():
            lines.append(f"+incdir+{seqs_dir.resolve()}")
            for sv in sorted(seqs_dir.glob("*_pkg.sv")):
                lines.append(str(sv.resolve()))
        tests_dir = env_dir / "tests"
        if tests_dir.exists():
            lines.append(f"+incdir+{tests_dir.resolve()}")
            for sv in sorted(tests_dir.glob("*_pkg.sv")):
                lines.append(str(sv.resolve()))

    # Bench
    bench_dir = output_dir / "bench"
    if bench_dir.exists():
        lines.append(f"+incdir+{bench_dir.resolve()}")

    fl.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    return fl


def compile_with_coverage(output_dir: Path, filelist: Path) -> dict:
    """vlog 编译，启用覆盖率"""
    vlog = os.path.join(_questa(), "vlog.exe")
    if not os.path.exists(vlog):
        vlog = os.path.join(_questa(), "win64", "vlog.exe")
    if not os.path.exists(vlog):
        return {"status": "FAIL", "error": f"vlog not found: {vlog}"}

    work_dir = output_dir / "build" / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        vlog,
        "-work", str(work_dir.resolve()),
        "+cover=bcesf",           # branch/condition/expression/statement/fsm
        "-f", str(filelist.resolve()),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180,
                          cwd=str(output_dir.resolve()))
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "error": "Compile timeout"}

    errors = r.stderr.count("** Error") + r.stdout.count("** Error")
    return {
        "status": "PASS" if errors == 0 else "FAIL",
        "errors": errors,
        "stdout": r.stdout[-2000:],
        "stderr": r.stderr[-1000:],
    }


def simulate_with_coverage(output_dir: Path, top_module: str) -> dict:
    """vsim 仿真，启用覆盖率并保存 ucdb"""
    vsim = os.path.join(_questa(), "vsim.exe")
    if not os.path.exists(vsim):
        vsim = os.path.join(_questa(), "win64", "vsim.exe")
    if not os.path.exists(vsim):
        return {"status": "FAIL", "error": f"vsim not found: {vsim}"}

    work_dir = output_dir / "build" / "work"
    sim_dir = output_dir / "sim" / "coverage"
    sim_dir.mkdir(parents=True, exist_ok=True)

    ucdb = sim_dir / "merged.ucdb"
    cov_do = f"coverage save -onexit {ucdb.as_posix()}; log -r /*; run -all; quit -f"

    questa_home = _questa()
    uvm_dir = questa_home.replace("win64", "") + os.environ.get("UVM_VERSION", "uvm-1.2")

    cmd = [
        vsim, "-c",
        "-sv_lib", f"{uvm_dir}/win64/uvm_dpi",
        "-onfinish", "stop",
        "-coverage",
        "-do", cov_do,
        "-work", str(work_dir.resolve()),
        "-l", str((sim_dir / "sim.log").resolve()),
        top_module,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300,
                          cwd=str(output_dir.resolve()))
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "error": "Sim timeout"}

    uvm_errors = r.stdout.count("UVM_ERROR") + r.stdout.count("UVM_FATAL")
    return {
        "status": "PASS" if uvm_errors == 0 else "FAIL",
        "errors": uvm_errors,
        "ucdb_path": str(ucdb) if ucdb.exists() else "",
        "stdout_tail": r.stdout[-2000:],
    }


def parse_coverage_report(output_dir: Path) -> dict:
    """运行 vcover report 并解析覆盖率数据"""
    vcover = os.path.join(_questa(), "vcover.exe")
    if not os.path.exists(vcover):
        vcover = os.path.join(_questa(), "win64", "vcover.exe")
    if not os.path.exists(vcover):
        return {"error": "vcover not found"}

    ucdb = output_dir / "sim" / "coverage" / "merged.ucdb"
    if not ucdb.exists():
        return {"error": f"ucdb not found: {ucdb}"}

    report_dir = output_dir / "sim" / "coverage" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    # 生成详细覆盖率报告
    cmd = [
        vcover, "report",
        "-details",
        "-html",
        "-output", str(report_dir.resolve()),
        str(ucdb.resolve()),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=120,
                      cwd=str(output_dir.resolve()))
    except subprocess.TimeoutExpired:
        pass

    # 生成文本报告供解析
    txt_report = report_dir / "coverage_summary.txt"
    cmd2 = [vcover, "report", "-c", str(ucdb.resolve())]
    try:
        r = subprocess.run(cmd2, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60,
                          cwd=str(output_dir.resolve()))
        txt_report.write_text(r.stdout, encoding="utf-8", errors="replace")
        raw_text = r.stdout
    except subprocess.TimeoutExpired:
        raw_text = ""

    # 解析覆盖率数据
    coverage = _parse_vcover_text(raw_text)
    coverage["ucdb_path"] = str(ucdb)
    coverage["report_dir"] = str(report_dir)
    return coverage


def _parse_vcover_text(text: str) -> dict:
    """从 vcover report 文本中提取覆盖率指标"""
    result = {
        "line_pct": 0.0,
        "branch_pct": 0.0,
        "toggle_pct": 0.0,
        "fsm_pct": 0.0,
        "statement_pct": 0.0,
        "condition_pct": 0.0,
        "overall_pct": 0.0,
    }
    patterns = {
        "line_pct": r"Line[:\s]+(\d+\.?\d*)\s*%",
        "branch_pct": r"Branch[:\s]+(\d+\.?\d*)\s*%",
        "toggle_pct": r"Toggle[:\s]+(\d+\.?\d*)\s*%",
        "fsm_pct": r"FSM[:\s]+(\d+\.?\d*)\s*%",
        "statement_pct": r"Statement[:\s]+(\d+\.?\d*)\s*%",
        "condition_pct": r"Condition[:\s]+(\d+\.?\d*)\s*%",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result[key] = float(m.group(1))

    # 计算总体覆盖率
    vals = [v for k, v in result.items() if k.endswith("_pct") and v > 0]
    result["overall_pct"] = round(sum(vals) / len(vals), 1) if vals else 0.0
    return result


def run(output_dir: str, top_module: str = "") -> dict:
    """一站式收集覆盖率"""
    od = Path(output_dir).resolve()
    if not od.exists():
        return {"status": "FAIL", "error": f"Output dir not found: {od}"}

    # 查找 top module
    if not top_module:
        bench_dir = od / "bench"
        sv_files = list(bench_dir.glob("*_tb_top.sv")) if bench_dir.exists() else []
        if sv_files:
            top_module = sv_files[0].stem
        else:
            return {"status": "FAIL", "error": "No bench top module found"}

    result = {"output_dir": str(od), "top_module": top_module}

    # 1. 构建 filelist
    print(f"[coverage] Building filelist with RTL + UVM for top={top_module}")
    fl = build_rtl_filelist(od)
    result["filelist"] = str(fl)

    # 2. 编译
    print(f"[coverage] Compiling with +cover=bcesf...")
    compile_result = compile_with_coverage(od, fl)
    result["compile"] = compile_result
    if compile_result["status"] != "PASS":
        result["status"] = "FAIL"
        result["error"] = f"Compile failed: {compile_result.get('error') or compile_result.get('stderr','')[-300:]}"
        return result

    # 3. 仿真
    print(f"[coverage] Running simulation with coverage...")
    sim_result = simulate_with_coverage(od, top_module)
    result["simulation"] = sim_result

    # 4. 解析覆盖率
    if sim_result.get("ucdb_path"):
        print(f"[coverage] Parsing coverage data...")
        coverage = parse_coverage_report(od)
        result["coverage"] = coverage
        result["status"] = "PASS"
    else:
        result["status"] = sim_result.get("status", "FAIL")

    # 保存结果
    cov_json = od / "sim" / "coverage" / "coverage_result.json"
    cov_json.parent.mkdir(parents=True, exist_ok=True)
    cov_json.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8", errors="replace")
    print(f"[coverage] Results saved to {cov_json}")
    return result


if __name__ == "__main__":
    od = sys.argv[1] if len(sys.argv) > 1 else "output/demo_apb_uart"
    top = sys.argv[2] if len(sys.argv) > 2 else ""
    result = run(od, top)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
