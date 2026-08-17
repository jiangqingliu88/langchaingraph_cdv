"""
Tool: check_env_arch —— env 架构自检（验收 UVM env 架构对不对）

两项验收：
  1. check_port_ownership —— 静态检查：每个 DUT 端口恰好被一个 agent 驱动/监控（无孤儿、无双驱）
  2. check_env_loopback   —— 仿真检查：跑 DUT 级回环 case，断言 scoreboard matched==N && mismatched==0

这是「验收 env 架构是对的」的自动化证据链，替代「拍胸脯」。

用法:
    from src.tools.uvm_tools.tool_check_env_arch.main import check_port_ownership, check_env_loopback
    print(check_port_ownership("output/apb_uart_run_xxx"))
    print(check_env_loopback("output/apb_uart_run_xxx"))
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Any, Dict, List


# DUT 端口方向 → agent 端口方向映射
# DUT input（TB 驱动）→ agent output；DUT output（TB 监控）→ agent input
_DUT_INPUT = "output"
_DUT_OUTPUT = "input"
_CLK_RST = {"clock", "reset", "clk", "rst"}


def _load_spec(output_dir: Path) -> Dict:
    p = output_dir / "spec.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _load_agent_ports(output_dir: Path) -> Dict[str, List[Dict]]:
    """加载 agent yamls 的端口，返回 {port_name: [{agent, dir}]}。"""
    result: Dict[str, List[Dict]] = {}
    yaml_dir = output_dir / "inputs" / "yaml" / "uvm"
    if not yaml_dir.exists():
        return result
    for yp in sorted(yaml_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yp.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        # agent yaml 顶层是 interfaces / environment / bench，只取 interfaces 的
        if "interfaces" in data:
            ifaces = data["interfaces"]
            agent_name = ifaces.get("name", yp.stem)
            for p in ifaces.get("ports", []) or []:
                if not isinstance(p, dict) or not p.get("name"):
                    continue
                result.setdefault(p["name"], []).append(
                    {"agent": agent_name, "dir": p.get("dir", "input")})
    return result


def _load_loopbacks(output_dir: Path) -> Dict[str, str]:
    """从 bench tb_top 读回环（assign lhs = rhs），返回 {lhs: rhs}。"""
    loopbacks: Dict[str, str] = {}
    bench_dir = output_dir / "bench"
    if not bench_dir.exists():
        return loopbacks
    for p in bench_dir.glob("*_tb_top.sv"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            m = re.match(r'\s*assign\s+(\w+)\s*=\s*(\w+)\s*;', line)
            if m:
                loopbacks[m.group(1)] = m.group(2)
    return loopbacks


def check_port_ownership(output_dir: str) -> Dict[str, Any]:
    """静态检查：每个 DUT 端口恰好被一个 agent 驱动/监控（回环驱动的端口视为已覆盖）。"""
    od = Path(output_dir)
    spec = _load_spec(od)
    dut_ports = spec.get("interfaces", []) or []
    agent_ports = _load_agent_ports(od)
    loopbacks = _load_loopbacks(od)

    violations = []   # 真问题（冲突 / 真孤儿）
    warnings = []     # 回环驱动的端口（合法，非 agent）
    checked = 0
    for p in dut_ports:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).split("[")[0].strip()
        proto = str(p.get("protocol", "")).lower()
        direction = str(p.get("direction", "")).upper()
        if not name or proto in _CLK_RST:
            continue  # 跳过 clock/reset
        checked += 1
        expected_dir = _DUT_INPUT if direction == "INPUT" else _DUT_OUTPUT
        matches = [a for a in agent_ports.get(name, []) if a["dir"] == expected_dir]
        if len(matches) == 0:
            if name in loopbacks:
                warnings.append(f"{name}({direction}) 由回环驱动（assign {name}={loopbacks[name]}），合法")
            else:
                violations.append(f"孤儿端口 {name}({direction})：无 agent 驱动/监控")
        elif len(matches) > 1:
            agents = [a["agent"] for a in matches]
            violations.append(f"端口冲突 {name}({direction})：被 {len(matches)} 个 agent 驱动/监控 {agents}")

    status = "PASS" if not violations else "FAIL"
    return {
        "check": "port_ownership",
        "status": status,
        "dut_ports": checked,
        "violations": violations,
        "warnings": warnings,
        "message": ("端口归属正确：每个 DUT 端口恰好一个 agent（回环端口另有标注）"
                    if not violations else f"发现 {len(violations)} 个端口归属问题"),
    }


def _resolve_test(output_dir: Path) -> str | None:
    """解析默认测试：loopback_test（双向回环）> directed_test > base_test。"""
    tests_dir = output_dir / "env" / "tests"
    spec = _load_spec(output_dir)
    env_name = f"{spec.get('design_name', 'dut')}_env"
    candidates = ["loopback_test", f"{env_name}_directed_test", f"{env_name}_base_test"]
    for c in candidates:
        if (tests_dir / f"{c}.sv").exists():
            return c
    return None


def check_scoreboard(output_dir: str, test_name: str = None,
                     questasim_uvm: str = "F:/questasim64_2024.1") -> Dict[str, Any]:
    """仿真检查：跑一个定向 case，断言 scoreboard 全部 match（matched==N && mismatched==0）。

    这是「逻辑闭环」的通用验收——适用于所有 DUT（物理回环只是其中一种 test）。
    test_name 为空时自动解析：loopback_test > directed_test > base_test。
    """
    od = Path(output_dir).resolve()  # 绝对路径：vlog/vsim 以 cwd=od 运行时，相对路径会翻倍
    if test_name is None:
        test_name = _resolve_test(od)
    if not test_name:
        return {"check": "scoreboard", "status": "SKIP",
                "message": "未找到可跑的定向测试（env/tests/*.sv）"}
    test_file = (od / "env" / "tests" / f"{test_name}.sv").as_posix()
    if not Path(test_file).exists():
        return {"check": "scoreboard", "status": "SKIP",
                "message": f"未找到测试文件 {test_file}"}

    # ── EDA 可用性前置检查（失败响亮：无 vlog/vsim → EDA_MISSING，而非 WinError）──
    import shutil
    if not (shutil.which("vlog") and shutil.which("vsim")):
        return {"check": "scoreboard", "status": "EDA_MISSING",
                "message": "未检测到 EDA 工具（vlog/vsim），无法执行编译仿真验收。"
                           "请安装 QuestaSim 并加入 PATH。"}

    work = (od / "build" / "work").as_posix()
    filelist = (od / "inputs" / "filelists" / "filelist.f").as_posix()
    uvm_src = f"{questasim_uvm}/verilog_src/uvm-1.2/src"
    uvm_dpi = f"{questasim_uvm}/uvm-1.2/win64/uvm_dpi"

    # 编译（只编 filelist.f：test 类已由 test_pkg.sv include，重复传 test_file 会
    # 把类片段当独立文件编，缺 import uvm_pkg → "uvm_test undefined"）
    compile_cmd = [
        "vlog", "-work", work, "-sv", "-mfcu", "-timescale", "1ns/1ps",
        f"+incdir+{uvm_src}", f"{uvm_src}/uvm_pkg.sv", "-f", filelist,
    ]
    r = subprocess.run(compile_cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(od), timeout=120)
    if r.returncode != 0:
        return {"check": "scoreboard", "status": "FAIL",
                "message": f"编译失败: {r.stdout[-500:]}{r.stderr[-500:]}"}

    # 顶层模块名：从 bench.yaml 读，回退到 <project>_bench_tb_top
    bench_yaml = od / "inputs" / "yaml" / "uvm" / "bench.yaml"
    top = "bench_tb_top"
    if bench_yaml.exists():
        try:
            b = yaml.safe_load(bench_yaml.read_text(encoding="utf-8", errors="replace"))
            top = f"{b['bench']['name']}_tb_top"
        except Exception:
            top = "bench_tb_top"

    # 仿真
    sim_cmd = [
        "vsim", "-c", "-sv_lib", uvm_dpi, "-work", work, top,
        f"+UVM_TESTNAME={test_name}", "-do", "run -all; quit -f",
    ]
    r = subprocess.run(sim_cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(od), timeout=180)
    out = r.stdout + r.stderr

    # 解析 scoreboard 结果: InOrder Scoreboard: total=N matched=M mismatched=K
    m = re.search(r"Scoreboard:\s*total=(\d+)\s*matched=(\d+)\s*mismatched=(\d+)", out)
    if not m:
        return {"check": "scoreboard", "status": "FAIL",
                "message": "未找到 scoreboard 结果（仿真可能超时/崩溃）"}
    total, matched, mismatched = int(m.group(1)), int(m.group(2)), int(m.group(3))
    passed = (mismatched == 0 and matched == total and total > 0)
    return {
        "check": "scoreboard",
        "test_name": test_name,
        "status": "PASS" if passed else "FAIL",
        "total": total, "matched": matched, "mismatched": mismatched,
        "message": f"scoreboard 比对 {'正确' if passed else '有 mismatch'}（{test_name}）："
                   f"total={total} matched={matched} mismatched={mismatched}",
    }


def check_env_loopback(output_dir: str, **kw) -> Dict[str, Any]:
    """双向 DUT 的物理回环 case（写啥读啥），是 check_scoreboard 的便捷封装。"""
    return check_scoreboard(output_dir, test_name="loopback_test", **kw)


def check_env_arch(output_dir: str, test_name: str = None) -> Dict[str, Any]:
    """env 架构验收：端口归属（通用）+ scoreboard 定向 case（通用）。

    test_name 为空时自动解析（loopback > directed > base）。
    任一子检查 EDA_MISSING → 整体 EDA_MISSING（失败响亮，语义化而非 WinError）。
    """
    ownership = check_port_ownership(output_dir)
    scoreboard = check_scoreboard(output_dir, test_name)
    if ownership.get("status") == "EDA_MISSING" or scoreboard.get("status") == "EDA_MISSING":
        status = "EDA_MISSING"
    else:
        status = "PASS" if (ownership["status"] == "PASS" and scoreboard["status"] == "PASS") else "FAIL"
    return {"status": status, "port_ownership": ownership, "scoreboard": scoreboard}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "output"
    import pprint
    pprint.pprint(check_env_arch(d))
