"""
编译检查 —— 通过 RegressionRunner 适配第三方 EDA 工具

用法:
    from src.tools.lib.compile import run_compile_check
    r = run_compile_check(output_dir, agents, "dut_env")
"""
import time
from pathlib import Path

from src.tools.lib.filelist import build_filelist_for_tb
from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner


def run_compile_check(output_dir: Path, agents: list, env_name: str) -> dict:
    """编译 UVM 环境，返回 {status, errors, time_s, score, passed, log_file}。"""
    fl = build_filelist_for_tb(output_dir, agents, env_name)
    top = f"{env_name}_bench_tb_top"

    t0 = time.time()
    runner = RegressionRunner(
        env_output_dir=str(output_dir),
        filelist=str(fl.resolve()),
        top_module=top,
        coverage=False,
    )
    result = runner.compile()
    elapsed = round(time.time() - t0, 1)

    sim_agent_dir = output_dir / "sim" / "agent"
    sim_agent_dir.mkdir(parents=True, exist_ok=True)
    log_path = sim_agent_dir / f"compile_{env_name}.log"

    compile_errs = result.get("errors", 0)
    passed = result["status"] == "PASS" and compile_errs == 0
    log_path.write_text(
        f"status: {result['status']}\nerrors: {compile_errs}\ntime: {elapsed}s\n",
        encoding="utf-8", errors="replace")

    return {
        "status": "PASS" if passed else "FAIL",
        "errors": compile_errs, "time_s": elapsed,
        "score": 25 if passed else max(0, 25 - compile_errs * 5),
        "passed": passed,
        "log_file": str(log_path),
    }
