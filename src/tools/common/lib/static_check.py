"""
静态检查 —— 验证所有预期的 UVM 文件是否存在

用法:
    from src.tools.common.lib.static_check import run_static_check, analyze_static
    r = run_static_check(output_dir, agents)
"""
from pathlib import Path


def run_static_check(output_dir: Path, agents: list) -> dict:
    """检查每个 agent 的 8 个预期文件是否都存在。"""
    missing = []
    present = []
    for a in agents:
        name = a["name"]
        agent_dir = output_dir / "agents" / name
        expected = [f"{name}_pkg.sv", f"{name}_interface.sv", f"{name}_agent.sv",
                    f"{name}_driver.sv", f"{name}_monitor.sv", f"{name}_sequencer.sv",
                    f"{name}_config.sv", f"{name}_transaction.sv"]
        for f in expected:
            if (agent_dir / f).exists():
                present.append(f"{name}/{f}")
            else:
                missing.append(f"{name}/{f}")
    passed = len(missing) == 0
    score = 25 if passed else max(0, 25 - len(missing) * 5)
    return {"present": len(present), "missing": len(missing), "missing_files": missing,
            "score": score, "status": "PASS" if passed else "FAIL", "passed": passed}


def analyze_static(output_dir: Path, agents: list) -> dict:
    """同 run_static_check，用于日志分析管道。"""
    return run_static_check(output_dir, agents)
