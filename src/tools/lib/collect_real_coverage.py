"""
真实覆盖率收集 —— 编译 + 仿真 + vcover merge/report

用法:
    python -m src.tools.lib.collect_real_coverage <output_dir> [--top apb_uart_bench_tb_top]
"""
import os, subprocess, json, sys, re
import builtins
from pathlib import Path

from config.settings import questa_exe, questa_home


def print(*args, **kwargs):
    """本模块诊断日志默认写 stderr（stdout 保留给业务输出/--json，不被污染）。"""
    kwargs.setdefault("file", sys.stderr)
    builtins.print(*args, **kwargs)


# ── 铁律三：LLM 只读降采样文本，上限 1KB ──
_LLM_SUMMARY_LIMIT = 1024


def _build_llm_summary(raw: str, limit: int = _LLM_SUMMARY_LIMIT) -> str:
    """把 vcover 报告压成 <1KB 的语义汇总（铁律三）。

    按语义挑行（汇总行优先），而不是按长度粗暴截断——截断会把一行切成两半、
    丢掉总量信息，也没有省略标记。头部记录原始长度，便于审计降采样比例。
    """
    raw = raw or ""
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]

    # 汇总行优先；含 TOTAL 的最优先排到最前——铁律三要的是总量，
    # 不能因为预算被逐条明细挤掉（vcover 报告里 TOTAL 通常在最后一行的情形很常见）。
    def _rank(ln: str) -> int:
        if "TOTAL" in ln:
            return 0
        return 1 if any(k in ln for k in ("Coverage", "Summary")) else 2

    summary_lines = [ln for ln in lines if _rank(ln) < 2]
    picked = sorted(summary_lines, key=_rank) if summary_lines else lines

    header = f"# coverage summary（降采样；原始 {len(raw)} 字符）\n"
    out, used, omitted = [], len(header.encode()), 0
    for i, ln in enumerate(picked):
        cost = len(ln.encode()) + 1
        if used + cost > limit:
            omitted = len(picked) - i
            break
        out.append(ln)
        used += cost

    text = header + "\n".join(out)
    if omitted:
        text += f"\n...（省略 {omitted} 行；完整报告见 coverage_summary.txt）"
    if len(text.encode()) > limit:  # 极端超长单行的兜底
        budget = max(0, limit - len(header.encode()) - 40)
        text = header + "\n".join(out)[:budget] + "\n...（截断）"
    return text


def build_rtl_filelist(output_dir: Path) -> Path:
    """覆盖率编译用的 filelist —— **就用回归那份**（`inputs/filelists/filelist.f`）。

    这里原来自己拼一份（RTL + agents + env + bench），**漏了 UVM 库本身**
    （`uvm_pkg.sv` + `+incdir+.../uvm-1.2/src`）。实测后果：覆盖率编译的第一句就是

        ** Error: Cannot find `include file "uvm_macros.svh" in directories:
           ... env, env\\seqs, env\\tests, bench, F:/questasim64_2024.1/.../ovm-2.1.2/src

    （那串里出现的是 **OVM**，vlog 自己的兜底路径），接着 `uvm_object_utils`
    之类全部未定义、9 个语法错，收集直接失败。而失败又被上层吞成"覆盖率 0%"，
    在界面上看着像"跑完了但确实没覆盖"，与真正的 0% 无从区分。

    回归那条路用的是 `filelist.build_filelist_for_tb`（顺序即依赖：公共包 → UVM
    → agents → RTL → env → bench），一直是好的 —— 所以这里不再自己拼第二份。
    两份清单内容本来就该一模一样，各写一份只会漂。
    """
    fl = output_dir / "inputs" / "filelists" / "filelist.f"
    if fl.exists():
        return fl                              # 回归已经建好了，直接用
    from src.tools.lib.filelist import build_filelist_for_tb, derive_env_name

    agents_dir = output_dir / "agents"
    agents = [{"name": d.name} for d in agents_dir.iterdir() if d.is_dir()] \
        if agents_dir.exists() else []
    return build_filelist_for_tb(output_dir, agents, derive_env_name(output_dir),
                                 "filelist.f")


def compile_with_coverage(output_dir: Path, filelist: Path) -> dict:
    """[DEPRECATED] vlog 编译，启用覆盖率。

    已由 L1 EdaBackend.compile() 取代（统一走 RegressionRunner 编译链，消除重复）。
    保留此函数仅为向后兼容，新代码请用 get_eda_backend().compile()。
    """
    vlog = questa_exe("vlog.exe")
    if not os.path.exists(vlog):
        return {"status": "FAIL", "error": f"vlog not found: {vlog}"}

    work_dir = output_dir / "build" / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # UVM 源文件路径（与 RegressionRunner.compile 保持一致）
    questa_root = questa_home()
    uvm_src_dir = os.path.join(questa_root, "verilog_src", "uvm-1.2", "src")
    uvm_pkg_path = os.path.join(uvm_src_dir, "uvm_pkg.sv")

    cmd = [
        vlog,
        "-work", str(work_dir.resolve()),
        "-sv", "-mfcu", "+acc",
    ]
    if os.path.exists(uvm_pkg_path):
        cmd += ["+incdir+" + uvm_src_dir.replace("\\", "/"),
                uvm_pkg_path.replace("\\", "/")]
    cmd += [
        "-cover", "sbceft",       # statement/branch/condition/expression/fsm/toggle
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


def simulate_with_coverage(output_dir: Path, top_module: str, uvm_test: str = "",
                           seed: int = 0) -> dict:
    """vsim 仿真，启用覆盖率并保存 ucdb + VCD 波形（通用格式，供人工检查）。

    原始证据按 seed 命名（不覆盖）：sim_seed_<seed>.log（日志）+ wave_seed_<seed>.vcd（波形）。
    """
    vsim = questa_exe("vsim.exe")
    if not os.path.exists(vsim):
        return {"status": "FAIL", "error": f"vsim not found: {vsim}"}

    work_dir = output_dir / "build" / "work"
    sim_dir = output_dir / "sim" / "coverage"
    sim_dir.mkdir(parents=True, exist_ok=True)

    # 原始证据按 seed 命名（多轮/扩种不覆盖），波形用通用 VCD 格式
    seed_tag = f"seed_{seed}" if seed else "seed_default"
    ucdb = sim_dir / "merged.ucdb"
    log_path = sim_dir / f"sim_{seed_tag}.log"
    vcd_path = sim_dir / f"wave_{seed_tag}.vcd"

    # VCD 波形（通用格式，GTKWave/Verdi 可开）+ 覆盖率 save + 运行
    # run 0 触发 elaboration 后 vcd add 才能访问信号层级；只记录 DUT 实例（u_ 前缀）
    cov_do = (
        f"vcd file {vcd_path.as_posix()}; run 0; vcd add -r /{top_module}/u_*; "
        f"coverage save -onexit {ucdb.as_posix()}; run -all; quit -f"
    )

    uvm_dir = os.path.join(questa_home(), os.environ.get("UVM_VERSION", "uvm-1.2"))

    # 关键: -work 参数必须用正斜杠（Windows 下反斜杠会被 vsim 解析成 . 分隔符）
    wd = str(work_dir.resolve()).replace("\\", "/")
    cmd = [
        vsim, "-c",
        "-sv_lib", f"{uvm_dir}/win64/uvm_dpi",
        "-onfinish", "stop",
        "-coverage",
        "-do", cov_do,
        "-work", wd,
        "-l", str(log_path.resolve()),
        top_module,
    ]
    # run_test() 需要 +UVM_TESTNAME 才能启动测试，否则 NOCOMP fatal
    if uvm_test:
        cmd += [f"+UVM_TESTNAME={uvm_test}"]
    # 随机种子（扩种闭环：不同 seed → 不同激励 → 覆盖率变化）
    if seed:
        cmd += ["-sv_seed", str(seed)]
    # 不传 +UVM_TIMEOUT，改用 tb_top 的 uvm_root::set_timeout(10ms)，避免 timescale 单位歧义
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
        "log_path": str(log_path) if log_path.exists() else "",
        "vcd_path": str(vcd_path) if vcd_path.exists() else "",
        "stdout_tail": r.stdout[-2000:],
    }


def parse_coverage_report(output_dir: Path) -> dict:
    """运行 vcover report 并解析覆盖率数据"""
    vcover = questa_exe("vcover.exe")
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

    # 生成文本报告供解析（-codeAll 输出代码覆盖率，-c 是无效选项）
    txt_report = report_dir / "coverage_summary.txt"
    cmd2 = [vcover, "report", "-codeAll", str(ucdb.resolve())]
    try:
        r = subprocess.run(cmd2, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60,
                          cwd=str(output_dir.resolve()))
        txt_report.write_text(r.stdout, encoding="utf-8", errors="replace")
        raw_text = r.stdout
        # 铁律三落地：再产出一份 <1KB 语义降采样，供 LLM 读取。
        # coverage_summary.txt 仍是完整报告（人工/解析用），两者并存。
        (report_dir / "coverage_summary_llm.txt").write_text(
            _build_llm_summary(raw_text), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raw_text = ""

    # 功能覆盖率（-cvg 输出 covergroup bin 命中）
    cvg_txt = report_dir / "coverage_cvg.txt"
    cvg_raw = ""
    cmd3 = [vcover, "report", "-cvg", str(ucdb.resolve())]
    try:
        r3 = subprocess.run(cmd3, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60,
                            cwd=str(output_dir.resolve()))
        cvg_txt.write_text(r3.stdout, encoding="utf-8", errors="replace")
        cvg_raw = r3.stdout
    except subprocess.TimeoutExpired:
        pass

    # 解析覆盖率数据（优先提取 DUT 实例的覆盖率，而非 UVM 包）
    dut_name = _discover_dut_name(output_dir)
    coverage = _parse_vcover_text(raw_text, dut_name)
    # 功能覆盖率（covergroup bin 命中，语义验证目标）
    functional = _parse_cvg_text(cvg_raw)
    coverage["functional_pct"] = functional.get("functional_pct", 0.0)
    coverage["functional_detail"] = functional
    coverage["ucdb_path"] = str(ucdb)
    coverage["report_dir"] = str(report_dir)
    return coverage


def _discover_dut_name(output_dir: Path) -> str:
    """从 rtl/*.sv 推断 DUT module 名。"""
    try:
        rtl_dir = output_dir / "rtl"
        if rtl_dir.exists():
            for sv in sorted(rtl_dir.glob("*.sv")):
                return sv.stem
    except Exception:
        pass
    return ""


def _parse_cvg_text(text: str) -> dict:
    """解析 `vcover report -cvg` 输出，提取功能覆盖率。

    输出长这样（实测）：

        Enabled Coverage              Bins      Hits    Misses  Coverage
        Covergroups                      3        na        na    34.24%
            Coverpoints/Crosses          9        na        na        na
                Covergroup Bins       4360        64      4296     1.46%
        TOTAL COVERGROUP COVERAGE: 34.24%  COVERGROUP TYPES: 3

    两行两个数，含义不同、都要：
      · `Covergroups … 34.24%` —— **covergroup 级**：有多少个 covergroup 被完整覆盖；
      · `Covergroup Bins … 1.46%` —— **bin 级**：4360 个 bin 只命中 64 个。

    `functional_pct` 取**后者**（bin 命中率）—— 那才是"功能盖了多少"，前者只要
    covergroup 里有一个 bin 没中就掉到很低，粗到没有指导意义。

    **不能"把所有百分比抓出来求平均"**（原来是这么写的）：那段文本里同一个数字
    出现三次（Covergroups 行、TOTAL 行、Total By Instance 行），平均下来正好把
    1.46% 那条冲淡 —— 实测报出 26.0%，而真值是 1.46%。`covergroup_count` 同理，
    原来数的是"出现了几个百分号"。
    """
    result = {"functional_pct": 0.0, "covergroup_count": 0, "raw_pcts": [],
              "covergroup_pct": 0.0, "bin_hits": 0, "bin_total": 0}
    if not text:
        return result

    def _counts(label: str):
        """`<label> <bins> <hits> <misses> <pct>%` —— 前三个是计数（可能带千分位逗号，
        也可能是 `na`），最后一个是百分比字符串。"""
        m = re.search(label + r"\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+(\d+\.?\d*)%", text)
        if not m:
            return None
        return (int(m.group(1).replace(",", "")), int(m.group(2).replace(",", "")),
                int(m.group(3).replace(",", "")), float(m.group(4)))

    bins_row = _counts("Covergroup Bins")
    if bins_row:
        total, hits, _misses, pct = bins_row
        result.update(bin_total=total, bin_hits=hits, functional_pct=pct)

    # `Covergroups  3  na  na  34.24%` —— 这行的中间两列是 `na`（没有"bin 数"一说）
    cg_row = re.search(r"Covergroups\s+([\d,]+)\s+\S+\s+\S+\s+(\d+\.?\d*)%", text)
    if cg_row:
        result["covergroup_pct"] = float(cg_row.group(2))
    types = re.search(r"COVERGROUP TYPES:\s*(\d+)", text)
    if types:
        result["covergroup_count"] = int(types.group(1))
    elif cg_row:
        result["covergroup_count"] = int(cg_row.group(1).replace(",", ""))

    result["raw_pcts"] = [float(m) for m in re.findall(r"(\d+\.?\d*)%", text)]
    return result


def _parse_vcover_text(text: str, dut_name: str = "") -> dict:
    """从 vcover -codeAll 文本中提取覆盖率指标（优先 DUT 实例）。

    vcover -codeAll 输出格式（每实例一个 block）:
        === Instance: /tb/u_dut
        === Design Unit: work.dut
            Branches    4   4   0  100.00%
            Statements  4   4   0  100.00%
            Toggles   260 159 101  61.15%
    末尾: Total Coverage By Instance (filtered view): 22.56%
    """
    result = {
        "line_pct": 0.0, "line_bins": 0, "line_misses": 0,
        "branch_pct": 0.0, "branch_bins": 0, "branch_misses": 0,
        "toggle_pct": 0.0, "toggle_bins": 0, "toggle_misses": 0,
        "fsm_pct": 0.0, "fsm_bins": 0, "fsm_misses": 0,
        "statement_pct": 0.0, "statement_bins": 0, "statement_misses": 0,
        "condition_pct": 0.0, "condition_bins": 0, "condition_misses": 0,
        "overall_pct": 0.0,
    }
    metric_base = {
        "Branches": "branch",
        "Statements": "statement",
        "Toggles": "toggle",
        "Conditions": "condition",
        "Lines": "line",
        "FSM": "fsm",
    }
    # 1. 优先提取 DUT 实例的覆盖率（精确匹配 Design Unit，避免误匹配 *_pkg/_interface）
    if dut_name:
        blocks = re.split(r"(?=== Instance:)", text)
        for blk in blocks:
            dm = re.search(r"Design Unit:\s*work\.([\w.]+)", blk)
            if not dm or dm.group(1) != dut_name:
                continue
            for m in re.finditer(
                r"(Branches|Statements|Toggles|Conditions|Lines|FSM)"
                r"\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%", blk):
                base = metric_base.get(m.group(1))
                if not base:
                    continue
                result[f"{base}_bins"] = int(m.group(2))
                result[f"{base}_misses"] = int(m.group(4))
                result[f"{base}_pct"] = float(m.group(5))
            vals = [v for k, v in result.items() if k.endswith("_pct") and v > 0]
            if vals:
                result["overall_pct"] = round(sum(vals) / len(vals), 1)
                return result

    # 2. 回退：用 Total Coverage By Instance 总百分比
    m = re.search(r"Total Coverage By Instance[^\n]*?([\d.]+)%", text)
    if m:
        result["overall_pct"] = float(m.group(1))
    return result


def parse_toggle_details(output_dir: Path) -> list:
    """从 vcover report -code t -details 提取 signal 级 toggle 缺口。

    vcover 明细格式（每 instance 一段）:
        Toggle Coverage for instance /tb/u_dut --
            result[0-31]  0  0  0.00   ← 信号[low-high] 1H->0L 0L->1H coverage%

    返回: [{"signal", "high", "low", "h_to_l", "l_to_h", "misses", "instance"}]
    其中 misses = 未翻转的 bin 数（1H->0L 或 0L->1H 计数为 0 即未覆盖）。
    """
    vcover = questa_exe("vcover.exe")
    if not os.path.exists(vcover):
        return []

    ucdb = output_dir / "sim" / "coverage" / "merged.ucdb"
    if not ucdb.exists():
        return []

    try:
        r = subprocess.run(
            [vcover, "report", "-code", "t", "-details", str(ucdb.resolve())],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, cwd=str(output_dir.resolve()))
    except Exception:
        return []

    details = []
    instance = ""
    for line in r.stdout.splitlines():
        im = re.match(r"Toggle Coverage for instance (\S+) --", line.strip())
        if im:
            instance = im.group(1)
            continue
        # 多 bit 信号: result[0-31]  1H->0L  0L->1H  pct
        m = re.search(r"(\w+)\[(\d+)-(\d+)\]\s+(\d+)\s+(\d+)\s+([\d.]+)", line)
        if m:
            signal, low, high = m.group(1), int(m.group(2)), int(m.group(3))
            h2l, l2h = int(m.group(4)), int(m.group(5))
        else:
            # 单 bit 信号: rst_n  1H->0L  0L->1H  pct
            m = re.search(r"(\w+)\s+(\d+)\s+(\d+)\s+([\d.]+)", line)
            if not m:
                continue
            signal, low, high = m.group(1), 0, 0
            h2l, l2h = int(m.group(2)), int(m.group(3))
        misses = (1 if h2l == 0 else 0) + (1 if l2h == 0 else 0)
        if misses > 0:
            details.append({
                "signal": signal, "high": high, "low": low,
                "h_to_l": h2l, "l_to_h": l2h, "misses": misses,
                "instance": instance,
            })
    return details


def _discover_uvm_test(output_dir: Path, top_module: str) -> str:
    """从 env/tests 发现可运行的 UVM 测试类名（优先 *_random_test / *_directed_test）。"""
    try:
        tests_dir = output_dir / "env" / "tests"
        if not tests_dir.exists():
            return ""
        candidates = []
        for sv in sorted(tests_dir.glob("*.sv")):
            text = sv.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"class\s+(\w+)\s+extends\s+(?:\w+::)?(?:uvm_test|\w+_base_test)", text):
                candidates.append(m.group(1))
        # 优先级：random > directed > base > 其它
        for key in ("random", "directed", "base"):
            for c in candidates:
                if key in c:
                    return c
        return candidates[0] if candidates else ""
    except Exception:
        return ""


def run(output_dir: str, top_module: str = "", seed: int = 0) -> dict:
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

    # 2. 编译（复用 L1 EdaBackend，消除与 RegressionRunner 的重复 vlog 逻辑）
    print(f"[coverage] Compiling with +cover=bcesf...")
    from src.layers.l1_infrastructure.eda_backend import get_eda_backend
    compile_result = get_eda_backend().compile(od, str(fl), coverage=True)
    result["compile"] = compile_result
    if compile_result["status"] != "PASS":
        result["status"] = "FAIL"
        result["error"] = f"Compile failed: {compile_result.get('error') or compile_result.get('stderr','')[-300:]}"
        return result

    # 3. 仿真
    print(f"[coverage] Running simulation with coverage...")
    uvm_test = _discover_uvm_test(od, top_module)
    sim_result = simulate_with_coverage(od, top_module, uvm_test, seed=seed)
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
