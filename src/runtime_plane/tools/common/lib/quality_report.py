"""
质量报告 —— 从日志文件评分，生成 quality_report.json

用法:
    from src.runtime_plane.tools.common.lib.quality_report import score_from_logs, generate_quality_report
    result = score_from_logs(output_dir, agents, "dut_env")
    report = generate_quality_report(output_dir, agents, "dut_env")
"""
import json
from datetime import datetime
from pathlib import Path
import structlog

from src.runtime_plane.tools.common.lib.static_check import analyze_static
from src.runtime_plane.tools.common.lib.sim_log import analyze_compile_log, analyze_sim_log
from src.runtime_plane.tools.common.lib.compile import run_compile_check
from src.runtime_plane.tools.common.lib.loopback import run_agent_loopback

logger = structlog.get_logger()


def score_from_logs(output_dir: Path, agents: list, env_name: str) -> dict:
    """从日志文件评分：静态 + 编译 + 仿真 → 三项 PASS/FAIL。

    日志位置: {output_dir}/sim/agent/compile_{env_name}.log
              {output_dir}/sim/agent/sim_{agent_name}_lb.log
    """
    # 静态检查
    static_r = analyze_static(output_dir, agents)

    # 编译日志分析
    compile_log_path = output_dir / "sim" / "agent" / f"compile_{env_name}.log"
    if compile_log_path.exists():
        compile_r = analyze_compile_log(compile_log_path.read_text(encoding="utf-8", errors="replace"))
        compile_r["_source"] = "log_file"
    else:
        compile_r = run_compile_check(output_dir, agents, env_name)
        compile_r["_source"] = "self_check"

    # 仿真日志分析（每 agent）
    loopback_results = []
    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        sim_log_path = output_dir / "sim" / "agent" / f"sim_{name}_lb.log"
        if sim_log_path.exists():
            sim_r = analyze_sim_log(sim_log_path.read_text(encoding="utf-8", errors="replace"))
            sim_r["agent"] = name
            sim_r["compile"] = "PASS"
            sim_r["_source"] = "log_file"
        else:
            sim_r = run_agent_loopback(output_dir, name)
            sim_r["_source"] = "self_check"
        loopback_results.append(sim_r)

    all_compile_passed = all(r["compile"] == "PASS" for r in loopback_results)
    all_sim_passed = all(r.get("passed", False) for r in loopback_results)
    loopback_passed = all_compile_passed and all_sim_passed

    total_matched = sum(r.get("matched", 0) for r in loopback_results)
    loopback_score = 25 if loopback_passed else max(0, 25 - sum(1 for r in loopback_results if not r.get("passed", False)) * 8)

    loopback_r = {
        "agents": loopback_results, "all_compile_pass": all_compile_passed,
        "all_passed": loopback_passed, "passed": loopback_passed,
        "matched": total_matched, "score": loopback_score,
        "total_score": f"{loopback_score}/25",
    }

    all_three_passed = static_r["passed"] and compile_r["passed"] and loopback_passed
    total = static_r["score"] + compile_r["score"] + loopback_score

    return {
        "passed": all_three_passed,
        "static_passed": static_r["passed"],
        "compile_passed": compile_r["passed"],
        "loopback_passed": loopback_passed,
        "scores": {
            "static": f"{static_r['score']}/25",
            "compile": f"{compile_r['score']}/25",
            "loopback": f"{loopback_score}/25",
            "total": f"{total}/75",
        },
        "total": total, "max_total": 75,
        "details": {"static": static_r, "compile": compile_r, "loopback": loopback_r},
        "verdict": "READY" if all_three_passed else "NEEDS_FIX",
    }


def generate_quality_report(output_dir: Path, agents: list, env_name: str) -> dict:
    """生成完整质量报告并写入 quality_report.json。"""
    from src.runtime_plane.tools.common.lib.llm_refine import llm_refine_sim_timing

    result = score_from_logs(output_dir, agents, env_name)
    static_r = result["details"]["static"]
    compile_r = result["details"]["compile"]
    loopback_r = result["details"]["loopback"]

    if not result["loopback_passed"] and compile_r["passed"]:
        logger.info("Loopback FAIL, attempting LLM-driven fix...")
        refine_result = llm_refine_sim_timing(output_dir, agents, env_name)
        if refine_result.get("fixed", 0) > 0:
            result = score_from_logs(output_dir, agents, env_name)
            result["_llm_refined"] = True
            result["_llm_fixed_count"] = refine_result["fixed"]
            static_r = result["details"]["static"]
            compile_r = result["details"]["compile"]
            loopback_r = result["details"]["loopback"]

    all_three_passed = result["passed"]
    total = result["total"]
    grade = "A" if total >= 70 else "B" if total >= 50 else "C" if total >= 30 else "D"

    report = {
        "timestamp": datetime.now().isoformat(),
        "agent": "uvm",
        "output_dir": str(output_dir.resolve()),
        "env_name": env_name,
        "scores": result["scores"],
        "grade": grade,
        "passed": all_three_passed,
        "details": {"static": static_r, "compile": compile_r, "loopback": loopback_r},
        "issues": {"errors": compile_r.get("errors", 0),
                   "missing_files": static_r.get("missing_files", [])},
        "verdict": "READY" if all_three_passed else "NEEDS_FIX",
        "recommendations": (
            ["Static check passed"] if result["static_passed"]
            else [f"Missing {len(static_r.get('missing_files', []))} files"]
        ) + ([f"Compile: {compile_r.get('errors', 0)} errors"] if not result["compile_passed"] else ["Compile passed"])
          + (["Loopback passed"] if result["loopback_passed"]
             else [f"Loopback failed — matched={loopback_r.get('matched', 0)}"]),
    }

    report_path = output_dir / "quality_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8", errors="replace")
    return report
