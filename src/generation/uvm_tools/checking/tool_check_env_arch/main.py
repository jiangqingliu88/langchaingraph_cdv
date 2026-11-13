"""
Tool: check_env_arch —— env 架构自检（验收 UVM env 架构对不对）

两项验收：
  1. check_port_ownership —— 静态检查：每个 DUT 端口恰好被一个 agent 驱动/监控（无孤儿、无双驱）
  2. check_env_loopback   —— 仿真检查：跑 DUT 级回环 case，断言 scoreboard matched==N && mismatched==0

这是「验收 env 架构是对的」的自动化证据链，替代「拍胸脯」。

用法:
    from src.generation.uvm_tools.checking.tool_check_env_arch.main import check_port_ownership, check_env_loopback
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

# ── scoreboard 结算报告的解析 ──
#
# 报告是 `in_order_scoreboard.get_report_string()` 打的（base_pkg/scb/），形如：
#
#     ===========================================================
#     Scoreboard: <实例名>
#     ===========================================================
#       Expected items : N
#       Actual items   : N
#       Matches        : N
#       Mismatches     : N
#       Missing        : N
#       Extra          : N
#       Match Rate     : X%
#
# 这里**按它真的打的格式解析**。原先只认一句
# `Scoreboard: total=N matched=M mismatched=K` —— 全仓没有任何 scoreboard 打过这个
# 形状（`grep total=` 在 base_pkg 里一个都搜不到），于是正则永远不命中，
# `env_arch_check` 每一轮都报「未找到 scoreboard 结果（仿真可能超时/崩溃）」：
# 把**解析不上**说成了**仿真崩了**，是最难查的那种误导。
#
# 旧形状仍然认（放前面）—— 外部/自定义 scoreboard 可能按那句打，不能修了这边坏了那边。
_LEGACY_SCB_RE = re.compile(
    r"Scoreboard:\s*total=(\d+)\s*matched=(\d+)\s*mismatched=(\d+)")

#: 报告里的整行字段：`  <标签> : <数字>`。**行首锚定**，否则 `Matches` 会
#: 命中 `Mismatches` 里的那段（`Matches\s*:` 在 "Mismatches     : 0" 上不匹配是
#: 因为大小写，靠大小写挡住太脆 —— 锚行首是把它从"碰巧"变成"构造上不可能"）。
def _report_int(text: str, label: str):
    m = re.search(rf"^[ \t]*{re.escape(label)}[ \t]*:[ \t]*(\d+)[ \t]*$",
                  text, re.MULTILINE)
    return int(m.group(1)) if m else None


def _parse_scoreboard_report(out: str):
    """仿真输出 → `(total, matched, mismatched)`；解析不上给 `None`。

    `matched`/`mismatched` 的口径**照 scoreboard 自己的判据**
    （`in_order_scoreboard.svh`：`mismatches>0 || missing>0 || extra>0` 即 FAILED）：
    少了（missing）和多了（extra）都是比对失败，不能只数 mismatch —— 否则
    "一条都没对上、全被当成 missing" 会被读成 0 mismatch 的满分。
    """
    m = _LEGACY_SCB_RE.search(out)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    matches = _report_int(out, "Matches")
    if matches is None:                      # 连报告都没打出来
        return None
    mismatches = _report_int(out, "Mismatches") or 0
    missing = _report_int(out, "Missing") or 0
    extra = _report_int(out, "Extra") or 0
    expected = _report_int(out, "Expected items") or 0
    actual = _report_int(out, "Actual items") or 0
    # total 取两侧的**大者**：expected 少一条、actual 多一条时，拿 expected 当
    # 分母会把"实际上比对过更多"这件事藏掉；判"有没有比过"用大者更诚实。
    return max(expected, actual), matches, mismatches + missing + extra


def _scoreboard_passed(total: int, matched: int, mismatched: int) -> bool:
    """判据与 `in_order_scoreboard` 自己的 FAILED 条件对齐（见其 `check_phase`）。

    `total > 0` 那条不能省：一条都没比过（用例没产生事务 / scoreboard 没接上）
    不是"零 mismatch 的满分"，是**没比** —— 报 PASS 等于把"什么都没检查"说成
    "检查通过"，正是这类门禁最容易骗过人的地方。
    """
    return mismatched == 0 and matched == total and total > 0


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
        bench_dir = output_dir / "sv" / "tb"
    if not bench_dir.exists():
        return loopbacks
    for p in sorted(bench_dir.glob("*.sv")):
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
        # 跳过 clock/reset —— **必须按名字也判一遍**：`protocol` 这个字段在
        # `--rtl` 路径生成的 spec 里根本不存在，只认它的话 `clk`/`rst_n` 会被
        # 当成"孤儿端口：无 agent 驱动"（它们本由 base 包的 `clk_rst_agent` 驱动），
        # 于是 env 架构验收每轮 0 分。共用判定见 `src/tools/common/lib/ports.py`。
        from src.tools.common.lib.ports import is_clock_or_reset
        if not name or proto in _CLK_RST or is_clock_or_reset(name):
            continue
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
    if not tests_dir.exists():
        tests_dir = output_dir / "sv" / "test"
    spec = _load_spec(output_dir)
    env_name = f"{spec.get('design_name', 'dut')}_env"
    candidates = ["loopback_test", f"{env_name}_directed_test", f"{env_name}_base_test"]
    for c in candidates:
        if (tests_dir / f"{c}.sv").exists():
            return c
    # sv 布局：loopback test 带 agent 前缀，按后缀认。
    for c in ("*_loopback_test.sv", "*_directed_test.sv", "*_base_test.sv"):
        hit = sorted(tests_dir.glob(c))
        if hit:
            return hit[0].stem
    return None


def _env_has_scoreboard(od: Path) -> bool:
    """生成的 env 到底接没接 scoreboard（读 `inputs/yaml/uvm/env.yaml` 的
    `scoreboards:` —— 生成器按 `_ref_mirror_gate` 写进去的那一节）。

    读不到一律按"没有"处理：这一节只用来决定 SKIP 还是 FAIL，判重了不划算。
    """
    p = od / "inputs" / "yaml" / "uvm" / "env.yaml"
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:                                  # noqa: BLE001
        return False
    env = (doc or {}).get("env") or doc
    return bool((env or {}).get("scoreboards"))


def check_scoreboard(output_dir: str, test_name: str = None,
                     questasim_uvm: str = None,
                     sim_modes=None) -> Dict[str, Any]:
    """仿真检查：跑一个定向 case，断言 scoreboard 全部 match（matched==N && mismatched==0）。

    这是「逻辑闭环」的通用验收——适用于所有 DUT（物理回环只是其中一种 test）。
    test_name 为空时自动解析：loopback_test > directed_test > base_test。
    questasim_uvm 为空时由 config.settings.questa_home() 解析。

    ## 两种"不判"（都是 SKIP，不是 FAIL）

    1. **波形模式**（`sim_modes` 含 `wave`）—— 那一轮要的是 qwave.db 而不是判决书，
       仿真侧也已带 `+SCB_OFF`（scoreboard 自己不结算）。这里跟着关，免得同一件事
       在两边给出两种口径。
    2. **这个 env 压根没接 scoreboard** —— 生成器按 `_ref_mirror_gate` **有意**不加
       （判据：这设计得看上去真是个寄存器文件；`apb_uart` 这种 `prdata` 直出 FIFO、
       `registers` 为空的，接上去只会造一批假失败）。没有 scoreboard 是**诚实的**，
       拿"没得比"判 FAIL，等于逼生成器去接一个必然假失败的东西 —— 两害相权，SKIP。
    """
    if not questasim_uvm:
        from config.settings import questa_home
        questasim_uvm = questa_home()
    od = Path(output_dir).resolve()  # 绝对路径：vlog/vsim 以 cwd=od 运行时，相对路径会翻倍

    # ── 波形模式：关掉（见 docstring 的两条"不判"）──
    if any(str(m).lower() == "wave" for m in (sim_modes or [])):
        return {"check": "scoreboard", "status": "SKIP",
                "message": "波形模式：scoreboard 检查关闭（这一轮要的是波形，不是判决）"}

    # ── 这 env 没接 scoreboard：没得比，不是失败 ──
    if not _env_has_scoreboard(od):
        return {"check": "scoreboard", "status": "SKIP",
                "message": "这个 env 没接 scoreboard（生成器按 ref_mirror_gate 有意不加："
                           "设计看不出是寄存器文件时，接上去只会造假失败）—— 没得比，"
                           "不是「比对失败」"}

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

    # 解析 scoreboard 结算报告（格式见 `_parse_scoreboard_report` 的注释）
    parsed = _parse_scoreboard_report(out)
    if parsed is None:
        return {"check": "scoreboard", "status": "FAIL",
                "message": "仿真跑完但没有 scoreboard 结算报告（用例没接 scoreboard，"
                           "或仿真中途崩了）—— 注意这与「比对失败」不是一回事"}
    total, matched, mismatched = parsed
    passed = _scoreboard_passed(total, matched, mismatched)
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


def check_env_arch(output_dir: str, test_name: str = None,
                   sim_modes=None) -> Dict[str, Any]:
    """env 架构验收：端口归属（通用）+ scoreboard 定向 case（通用）。

    test_name 为空时自动解析（loopback > directed > base）。
    任一子检查 EDA_MISSING → 整体 EDA_MISSING（失败响亮，语义化而非 WinError）。

    `SKIP` **不是失败**：那表示"这一项没得判/不适用"（波形模式、或这 env 本就没接
    scoreboard —— 见 `check_scoreboard` 的两条"不判"）。把它当成 FAIL，等于逼着
    生成器去接一个必然假失败的 scoreboard，或者逼着波形模式给出判决书。
    """
    ownership = check_port_ownership(output_dir)
    scoreboard = check_scoreboard(output_dir, test_name, sim_modes=sim_modes)
    _sts = ("PASS", "SKIP")
    if ownership.get("status") == "EDA_MISSING" or scoreboard.get("status") == "EDA_MISSING":
        status = "EDA_MISSING"
    else:
        status = "PASS" if (ownership["status"] in _sts
                            and scoreboard["status"] in _sts) else "FAIL"
    return {"status": status, "port_ownership": ownership, "scoreboard": scoreboard}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "output"
    import pprint
    pprint.pprint(check_env_arch(d))
