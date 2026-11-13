"""
仿真/编译日志解析 —— 纯文本分析，不跑编译/仿真

用法:
    from src.runtime_plane.tools.common.lib.sim_log import parse_sim_log, analyze_compile_log, analyze_sim_log
    r = parse_sim_log(vsim_stdout)
"""
import re


def parse_sim_log(log_text: str) -> dict:
    """解析 vsim 日志 → {passed, errors, matched, mismatched, driven, timeout}。"""
    err_lines = [l for l in log_text.split("\n")
                 if ("UVM_ERROR" in l or "UVM_FATAL" in l)
                 and "UVM_ERROR :" not in l and "UVM_FATAL :" not in l]
    errors = len(err_lines)
    warnings = len([l for l in log_text.split("\n") if "UVM_WARNING" in l])
    timeout = "LOOPBACK_TIMEOUT" in log_text

    matched = 0
    mismatched = 0
    all_matched = list(re.finditer(r"\[SCB_LOOP\].*?matched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    all_mismatched = list(re.finditer(r"\[SCB_LOOP\].*?mismatched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    if all_matched:
        matched = int(all_matched[-1].group(1))
    if all_mismatched:
        mismatched = int(all_mismatched[-1].group(1))

    driven_m = re.search(r"driven\s*[:=]\s*(\d+)", log_text)
    driven = int(driven_m.group(1)) if driven_m else 0
    passed = errors == 0 and not timeout and driven > 0

    return {"passed": passed, "errors": errors, "warnings": warnings,
            "timeout": timeout, "matched": matched, "mismatched": mismatched,
            "driven": driven}


def analyze_compile_log(log_text: str) -> dict:
    """分析编译日志 → PASS/FAIL（0 错误 = PASS）。"""
    errors = len(re.findall(r"\*\* Error", log_text))
    warnings = len(re.findall(r"\*\* Warning", log_text))
    passed = errors == 0
    score = 25 if passed else max(0, 25 - errors * 5)
    return {
        "passed": passed, "status": "PASS" if passed else "FAIL",
        "errors": errors, "warnings": warnings,
        "score": score, "score_str": f"{score}/25",
    }


def analyze_sim_log(log_text: str) -> dict:
    """分析仿真日志 → PASS/FAIL。"""
    errors = len([l for l in log_text.split("\n")
                  if ("UVM_ERROR" in l or "UVM_FATAL" in l)
                  and "UVM_ERROR :" not in l and "UVM_FATAL :" not in l])
    timeout = "LOOPBACK_TIMEOUT" in log_text
    matched = 0
    mismatched = 0
    all_matched = list(re.finditer(r"\[SCB_LOOP\].*?matched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    all_mismatched = list(re.finditer(r"\[SCB_LOOP\].*?mismatched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    if all_matched:
        matched = int(all_matched[-1].group(1))
    if all_mismatched:
        mismatched = int(all_mismatched[-1].group(1))
    driven_m = re.search(r"driven\s*[:=]\s*(\d+)", log_text)
    driven = int(driven_m.group(1)) if driven_m else 0
    passed = errors == 0 and not timeout and matched > 0
    score = 25 if passed else (15 if errors == 0 and driven > 0 else (10 if driven > 0 else 0))
    return {
        "passed": passed, "status": "PASS" if passed else "FAIL",
        "errors": errors, "timeout": timeout,
        "matched": matched, "mismatched": mismatched, "driven": driven,
        "score": score, "score_str": f"{score}/25",
    }
