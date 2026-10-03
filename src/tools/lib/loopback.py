"""
闭环检查 —— 单 agent 编译 + vsim 仿真 + 日志解析 + 自动修复

用法:
    from src.tools.lib.loopback import run_agent_loopback, run_loopback_check
    r = run_agent_loopback(output_dir, "alu_in")
    results = run_loopback_check(output_dir, agents, "dut_env")
"""
import re, os, subprocess, time
from pathlib import Path

from src.tools.lib.uvm_context import ctx
from src.tools.lib.filelist import build_loopback_filelist
from src.tools.lib.sim_log import parse_sim_log
from src.tools.regression_tools.regression_framework.adapters.regression_runner import RegressionRunner


def _try_autofix_loopback(output_dir: Path, agent_name: str, compile_log: str) -> bool:
    """自动修复常见模板问题：base_seq→random_seq、qualifier gate、exp copy、TLM 连线。"""
    fixed_any = False
    agent_dir = output_dir / "agents" / agent_name
    test_file = agent_dir / "loopback" / f"{agent_name}_loopback_test.sv"
    driver_file = agent_dir / f"{agent_name}_driver.sv"
    monitor_file = agent_dir / f"{agent_name}_monitor.sv"
    env_file = agent_dir / "loopback" / f"{agent_name}_loopback_env.sv"

    # Fix 1: base_seq → random_seq
    if test_file.exists():
        content = test_file.read_text(encoding="utf-8", errors="replace")
        if f"{agent_name}_base_seq" in content and f"{agent_name}_random_seq" not in content:
            content = content.replace(f"{agent_name}_base_seq", f"{agent_name}_random_seq")
            if "num_transactions" not in content and "seq.start" in content:
                content = content.replace(
                    "seq.start(env_h.agent_h.sqr);",
                    "seq.num_transactions = num_items;\n    seq.delay_min = 0;\n    seq.delay_max = 3;\n    seq.start(env_h.agent_h.sqr);")
            test_file.write_text(content, encoding="utf-8", errors="replace")
            fixed_any = True
        elif "#200ns" not in content and "raise_objection" in content:
            content = content.replace(
                "phase.raise_objection(this);",
                "phase.raise_objection(this);\n    #200ns; // wait for reset release")
            test_file.write_text(content, encoding="utf-8", errors="replace")
            fixed_any = True

    # Fix 2: compile errors — field not found
    if "could not find field" in compile_log or "Failed to find" in compile_log:
        for sv_file in [test_file, driver_file, monitor_file]:
            if not sv_file or not sv_file.exists():
                continue
            fc = sv_file.read_text(encoding="utf-8", errors="replace")
            modified = False
            for line in compile_log.split("\n"):
                m = re.search(r"field\s+'(\w+)'\s+in", line, re.IGNORECASE)
                if m:
                    bad = m.group(1)
                    if f".{bad}" in fc:
                        fc = fc.replace(f".{bad}", f"//.{bad} // auto-removed")
                        modified = True
            if modified:
                sv_file.write_text(fc, encoding="utf-8", errors="replace")
                fixed_any = True

    # Fix 3: monitor qualifier gate
    if monitor_file.exists():
        mc = monitor_file.read_text(encoding="utf-8", errors="replace")
        sample_fn = _extract_method_body(mc, "sample_transaction")
        if sample_fn:
            has_qualifier = bool(re.search(
                r'\bif\s*\(|case\s*\(|&\s*vif\.|vif\.\w+\s*==|vif\.\w+\s*!=', sample_fn))
            if not has_qualifier:
                interface_file = agent_dir / f"{agent_name}_interface.sv"
                qualifier_signal = None
                if interface_file.exists():
                    ifc = interface_file.read_text(encoding="utf-8", errors="replace")
                    for candidate in ["valid", "strobe", "psel", "penable", "enable", "ready"]:
                        if re.search(rf'\b{candidate}\b', ifc):
                            qualifier_signal = candidate
                            break
                if qualifier_signal and "item." in sample_fn:
                    sample_lines = sample_fn.strip().split("\n")
                    item_lines = [l for l in sample_lines if "item." in l and "vif." in l]
                    if item_lines:
                        indented = "\n".join("    " + l.strip() for l in item_lines)
                        new_block = f"if (vif.{qualifier_signal}) begin\n{indented};\n  end"
                        old_block = "\n".join(item_lines)
                        mc = mc.replace(old_block, new_block)
                        monitor_file.write_text(mc, encoding="utf-8", errors="replace")
                        fixed_any = True

    # Fix 4: driver exp copy
    if driver_file.exists():
        dc = driver_file.read_text(encoding="utf-8", errors="replace")
        drive_fn = _extract_method_body(dc, "drive_transaction")
        if drive_fn and "exp." not in drive_fn and "expected_port.write" in drive_fn:
            txn_file = agent_dir / f"{agent_name}_transaction.sv"
            txn_fields = set()
            if txn_file.exists():
                tc = txn_file.read_text(encoding="utf-8", errors="replace")
                txn_fields = set(re.findall(r'rand\s+\S+\s+(\w+)\s*;', tc))
                txn_fields.update(["req_id", "tag", "error", "begin_time"])
            valid_ports = [p for p in re.findall(r'vif\.cb\.(\w+)\s*<=', drive_fn) if p in txn_fields]
            if valid_ports:
                exp_lines = "\n".join(f"    exp.{p} = req.{p};" for p in valid_ports)
                dc = dc.replace("expected_port.write(exp);", f"{exp_lines}\n    expected_port.write(exp);")
                driver_file.write_text(dc, encoding="utf-8", errors="replace")
                fixed_any = True

    # Fix 5: env TLM connections
    if env_file.exists():
        ec = env_file.read_text(encoding="utf-8", errors="replace")
        if "drv.expected_port.connect" not in ec:
            ec = ec.replace(
                "super.connect_phase(phase);",
                "super.connect_phase(phase);\n    agent_h.drv.expected_port.connect(scb_h.expected_export);\n    agent_h.mon.item_collected_port.connect(scb_h.actual_export);")
            env_file.write_text(ec, encoding="utf-8", errors="replace")
            fixed_any = True

    return fixed_any


def _extract_method_body(file_content: str, method_name: str) -> str:
    """从 SV 文件中提取 task/function 方法体。"""
    patterns = [
        rf'(?:virtual\s+)?task\s+(?:automatic\s+)?{method_name}\b.*?endtask',
        rf'(?:virtual\s+)?function\s+\S+\s+{method_name}\b.*?endfunction',
    ]
    for pat in patterns:
        m = re.search(pat, file_content, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


def run_agent_loopback(output_dir: Path, agent_name: str) -> dict:
    """单 agent loopback: 编译 + vsim 仿真 + 日志解析。"""
    import structlog
    logger = structlog.get_logger()

    from src.tools.lib.regress_dir import get_compile_dir, get_sim_dir
    compile_dir = get_compile_dir(output_dir)
    sim_dir = get_sim_dir(output_dir)

    fl = build_loopback_filelist(output_dir, agent_name)
    top = f"{agent_name}_loopback_tb"

    from config.settings import questa_exe, questa_home
    vsim = questa_exe("vsim.exe")
    _uvm_dpi = os.path.join(questa_home(), os.environ.get("UVM_VERSION", "uvm-1.2"),
                            "win64", "uvm_dpi")

    t0 = time.time()
    runner = RegressionRunner(
        env_output_dir=str(output_dir), filelist=str(fl.resolve()),
        top_module=top, coverage=False,
        compile_dir=compile_dir, sim_dir=sim_dir)
    compile_result = runner.compile()
    compile_ok = compile_result["status"] == "PASS"
    compile_errs = compile_result.get("errors", 0)
    compile_time = round(time.time() - t0, 1)

    fixed = False
    if not compile_ok:
        fixed = _try_autofix_loopback(output_dir, agent_name, compile_result.get("stderr", ""))
        if fixed:
            fl = build_loopback_filelist(output_dir, agent_name)
            runner = RegressionRunner(
                env_output_dir=str(output_dir), filelist=str(fl.resolve()),
                top_module=top, coverage=False,
                compile_dir=compile_dir, sim_dir=sim_dir)
            compile_result = runner.compile()
            compile_ok = compile_result["status"] == "PASS"
            compile_errs = compile_result.get("errors", 0)
            compile_time = round(time.time() - t0, 1)
        if not compile_ok:
            return {"compile": "FAIL", "errors": compile_errs, "time_s": compile_time,
                    "sim": "SKIPPED", "score": 0, "passed": False, "autofix_attempted": bool(fixed)}

    compile_base = output_dir / compile_dir if compile_dir else output_dir
    wd = (compile_base / "build" / "work").resolve()
    wd_str = str(wd).replace("\\", "/")
    sim_agent_dir = (output_dir / "sim" / "agent").resolve()
    sim_agent_dir.mkdir(parents=True, exist_ok=True)
    sim_agent_str = str(sim_agent_dir).replace("\\", "/")
    log_path = sim_agent_dir / f"sim_{agent_name}_lb.log"

    if log_path.exists():
        log_path.unlink()

    r2 = subprocess.run([
        vsim, "-c", "-sv_lib", _uvm_dpi,
        "-onfinish", "stop", "-do", "log -r /*; run -all; quit -f",
        "-wlf", f"{sim_agent_str}/wave_{agent_name}_lb.wlf",
        "-work", wd_str, "-l", f"{sim_agent_str}/sim_{agent_name}_lb.log",
        top, f"+UVM_TESTNAME={agent_name}_loopback_test", "+UVM_TIMEOUT=100000",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
       cwd=str(output_dir.resolve()))

    sim_time = round(time.time() - t0 - compile_time, 1)
    parsed = parse_sim_log(r2.stdout)

    MAX_SIM_RETRIES = 3
    for retry in range(MAX_SIM_RETRIES):
        if parsed["passed"] or parsed["errors"] == 0:
            break
        fixed = _try_autofix_loopback(output_dir, agent_name, r2.stdout)
        if not fixed:
            break
        r2 = subprocess.run([
            vsim, "-c", "-sv_lib", _uvm_dpi,
            "-onfinish", "stop", "-do", "log -r /*; run -all; quit -f",
            "-wlf", f"{sim_agent_str}/wave_{agent_name}_lb.wlf",
            "-work", wd_str, top,
            f"+UVM_TESTNAME={agent_name}_loopback_test", "+UVM_TIMEOUT=100000",
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
           cwd=str(output_dir.resolve()))
        parsed = parse_sim_log(r2.stdout)
        sim_time = round(time.time() - t0 - compile_time, 1)
        if parsed["passed"] and parsed["errors"] == 0:
            break

    sim_ok = parsed["passed"] and parsed["errors"] == 0
    passed = sim_ok and parsed.get("matched", 0) > 0
    score = 25 if passed else (15 if sim_ok else (10 if parsed.get("driven", 0) > 0 and parsed.get("matched", 0) > 0 else 0))

    return {
        "agent": agent_name, "compile": "PASS" if compile_ok else "FAIL",
        "compile_errors": compile_errs, "compile_time_s": compile_time,
        "sim_time_s": sim_time, "sim_passed": parsed["passed"],
        "sim_errors": parsed["errors"], "matched": parsed.get("matched", 0),
        "mismatched": parsed.get("mismatched", 0), "driven": parsed.get("driven", 0),
        "errors": parsed["errors"], "timeout": parsed.get("timeout", False),
        "score": score, "passed": passed, "compile_log": "",
        "sim_log": r2.stdout if 'r2' in dir() else "",
    }


def run_loopback_check(output_dir: Path, agents: list, env_name: str) -> dict:
    """对所有 agent 运行闭环检查。"""
    results = []
    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        r = run_agent_loopback(output_dir, name)
        results.append(r)

    total_score = sum(r["score"] for r in results)
    all_passed = all(r["compile"] == "PASS" and r.get("matched", 0) > 0 for r in results)
    score = 25 if all_passed else max(0, 25 - sum(1 for r in results if r.get("matched", 0) == 0) * 8)

    return {
        "agents": results,
        "all_compile_pass": all(r["compile"] == "PASS" for r in results),
        "all_passed": all_passed, "passed": all_passed,
        "total_score": f"{score}/25", "score": score,
    }
