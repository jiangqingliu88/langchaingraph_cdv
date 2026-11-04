"""
编译检查 —— 通过 RegressionRunner 适配第三方 EDA 工具

用法:
    from src.tools.common.lib.compile import run_compile_check
    r = run_compile_check(output_dir, agents, "dut_env")
"""
import time
from pathlib import Path

from src.tools.common.lib.filelist import build_filelist_for_tb


def run_compile_check(output_dir: Path, agents: list, env_name: str,
                      compile_dir: str = None) -> dict:
    """编译 UVM 环境，返回 {status, errors, time_s, score, passed, log_file}。

    compile_dir: None=自动检测(uvm_regress, 共享 work library)
    """
    if compile_dir is None:
        from src.tools.common.lib.regress_dir import get_compile_dir
        compile_dir = get_compile_dir(output_dir)

    fl = build_filelist_for_tb(output_dir, agents, env_name)
    top = f"{env_name}_bench_tb_top"

    t0 = time.time()
    # **按 `RegressionRunner` 的真实签名调。** 这里原来还传了 `compile_dir=...`，
    # 而那个参数在 runner 上不存在（`regression_framework` 现在只剩 sourceless 的
    # `.pyc`，签名是 `(env_output_dir, filelist, top_module, coverage)`）——
    # 于是这个函数每次都是 `TypeError`，编译检查从来没跑起来过。
    # `eda_backend.QuestaEdaBackend.compile` 是同一套调用，它传的就是对的。
    from src.layers.l2_orchestration.regression_tools.regression_framework.adapters.regression_runner import RegressionRunner

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
