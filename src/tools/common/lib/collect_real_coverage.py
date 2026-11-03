"""
真实覆盖率收集 —— 编译 + 仿真 + vcover merge/report

用法:
    python -m src.tools.common.lib.collect_real_coverage <output_dir> [--top apb_uart_bench_tb_top]
"""
import os, subprocess, json, sys, re
import builtins
from typing import Optional
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
    from src.tools.common.lib.filelist import build_filelist_for_tb, derive_env_name

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

    # 功能覆盖率（-cvg **-details** 输出逐 covergroup/coverpoint/cross 的覆盖率）
    #
    # **`-details` 不能省**：只给 `-cvg` 的话输出是一份**只有汇总行**的报表
    # （`Covergroups 3 na na 51.58%`），拿不到任何一个 covergroup 的名字 ——
    # 而证据链的功能覆盖层要的正是逐条的 `{name, goal, actual}`。少了它就只能
    # 产出一个标量计数，`five_layer` 读不到列表，于是永远报「0 covergroups」。
    cvg_txt = report_dir / "coverage_cvg.txt"
    cvg_raw = ""
    cmd3 = [vcover, "report", "-cvg", "-details", str(ucdb.resolve())]
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


def _write_merge_manifest(od: Path, out: Path, stores: list, specs: list,
                          merged: int, errors: list, warnings: list) -> str:
    """把"这次计划覆盖率由哪些库合并而来"落成机器可读清单。

    为什么不能只留 `plan_merged.ucdb`：签核要回答"95.23% 是从哪些用例库
    算出来的"。只有一份最终库，等于把**输入集合**藏了起来 —— 而输入集合
    正是可复现的那一半。清单里记相对路径 + 大小 + mtime + merged ucdb 的
    sha256；不复制库本体（体积大），但足以核对"是不是同一批输入"。
    """
    from src.layers.l1_infrastructure.infrastructure import sha256_file

    path = od / "coverage" / "plan_merge_manifest.json"
    old = []
    try:
        if path.is_file():
            old = (json.loads(path.read_text(encoding="utf-8", errors="replace"))
                   or {}).get("stores") or []
    except (OSError, ValueError):
        old = []
    old_by_rel = {e.get("path"): e for e in old if isinstance(e, dict)}

    entries = []
    for db in stores:
        try:
            rel = db.relative_to(od).as_posix()
        except ValueError:
            rel = str(db)
        try:
            st = db.stat()
            entry = {"path": rel, "size": st.st_size,
                     "mtime": int(st.st_mtime)}
        except OSError:
            entry = {"path": rel, "size": 0, "mtime": 0}
        # 单个 store 的 sha256 很贵（254 个库）。只在缓存里已有同路径同大小
        # 的旧值时复用；没有就留空（空 = 没算，不伪造）。
        prev = old_by_rel.get(rel)
        if prev and prev.get("size") == entry["size"]:
            entry["sha256"] = prev.get("sha256", "")
        else:
            entry["sha256"] = ""
        entries.append(entry)

    payload = {
        "schema": "plan_merge_manifest_v1",
        "store_count": len(stores),
        "merged_stores": merged,
        "stores": entries,
        "specs": list(specs),
        "merged_ucdb": str(out),
        "merged_sha256": sha256_file(out) if out.is_file() else "",
        "errors": errors,
        "warnings": warnings,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError:
        pass
    return str(path)


def merge_regression_coverage(od: Path) -> dict:
    """把**回归逐用例覆盖率库**合并成一份「计划覆盖率」。

    ## 为什么需要它（这是签核口径的问题，不是工具细节）

    原来的签核覆盖率来自覆盖率阶段**单独跑的一条 test**；而回归实际跑了 244 条
    用例，每条都 `-coverstore` 落了一份库。两个数字对不上时，签核用的是"另一条
    测试的覆盖率"—— 既不诚实，也让"补测试"对签核数字没有直接作用。

    这里把 `regression_run/**/cov/*/questa.db` 合并成 `plan_merged.ucdb`，
    并产出一份 `coverage_cvg_plan.txt` 供解析。签核与 TP 矩阵都改用它。

    ## coverstore 的读法（实测）

    - 有 `<test>.data`：`vcover merge "cov/<store>:<test>"`（cwd=用例目录）；
    - 只有 `(null).data`（历史 `-testname` 漏传）：`vcover merge "cov/<store>"`
      —— 带 `:test` 会让 vcover 崩溃。
    - **spec 必须带一层目录**（`cov/...`）；只写 `<store>:<test>` 会被当成目录名。

    合并是增量的（`-append`），244 条约 20 秒。失败**不抛**：返回 `errors`，
    调用方保留单测覆盖率并如实记账。
    """
    # **全部用绝对路径**：`cwd` + `-inputs` 的相对路径混用时，vcover 会把它
    # 当成另一份文件（实测 usage error）；绝对路径与手工验证过的命令一致。
    od = Path(od).resolve()
    reg_root = od / "regression_run"
    if not reg_root.is_dir():
        return {}
    stores = sorted(reg_root.rglob("cov/*/questa.db"))
    if not stores:
        return {}
    out_dir = od / "sim" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "plan_merged.ucdb"
    report_txt = out_dir / "reports" / "coverage_cvg_plan.txt"
    try:
        newest = max(p.stat().st_mtime for p in stores)
        if (out.is_file() and out.stat().st_mtime >= newest
                and report_txt.is_file()):
            # **缓存也要把解析结果带回来** —— 只给路径的话调用方拿不到
            # functional_pct，会误以为"计划覆盖率没生成"。
            detail = _parse_cvg_text(
                report_txt.read_text(encoding="utf-8", errors="replace"))
            manifest = od / "coverage" / "plan_merge_manifest.json"
            return {"ucdb": str(out), "report": str(report_txt),
                    "stores": len(stores), "merged": len(stores),
                    "functional_pct": detail.get("functional_pct", 0.0),
                    "functional_detail": detail, "cached": True,
                    "manifest": str(manifest) if manifest.is_file() else "",
                    "errors": [], "warnings": []}
    except OSError:
        pass

    vcover = questa_exe("vcover.exe")
    if not os.path.exists(vcover):
        return {"error": f"vcover not found: {vcover}", "stores": len(stores)}

    # **一条命令合并全部输入**（而不是逐条 `-append`）。
    #
    # 逐条 append 时 vcover 会在同一个输出文件上反复建/删锁；前一次锁没释放，
    # 下一条就报 "DB file ... in write mode"（实测）。一次给全量输入没有这个问题，
    # 也快得多（244 条约 20 秒）。
    #
    # spec 用**相对运行根**的路径（`regression_run/.../cov/<test>[:<test>]`）：
    # 绝对路径里的盘符冒号会和 coverstore 的 `store:test` 分隔符冲突。
    tmp = out.with_name("plan_merged_build.ucdb")
    # 清掉上一次中断留下的临时库 / 锁（vcover 对残留锁会拒绝写）
    for junk in (tmp, Path(str(tmp) + "._lock"),
                 Path(str(tmp) + ".questatmp")):
        try:
            junk.unlink()
        except OSError:
            pass
    specs = []
    for db in stores:
        store = db.parent
        data = sorted(store.glob("*.data"))
        stem = (data[0].stem if len(data) == 1
                else (store.name if not data else
                      max(data, key=lambda x: x.stat().st_mtime).stem))
        null_test = (not stem) or stem in ("(null)", "null")
        try:
            rel = store.relative_to(od).as_posix()
        except ValueError:
            continue
        specs.append(rel if null_test else f"{rel}:{stem}")
    errors = []
    warnings = []
    merged = 0
    if specs:
        # **用 `-inputs <cmdfile>`**：244 条 spec 直接上命令行会超过 Windows 的
        # 命令行长度上限（实测 `[WinError 206] 文件名或扩展名太长`）。
        cmdfile = out_dir / "plan_merge_inputs.txt"
        try:
            cmdfile.write_text("\n".join(specs) + "\n", encoding="utf-8")
            proc = subprocess.run([vcover, "merge", "-inputs", str(cmdfile), str(tmp)],
                                  cwd=str(od), capture_output=True, text=True,
                                  errors="replace", timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(str(e))
            proc = None
        if proc is not None:
            if proc.returncode != 0 or not tmp.is_file():
                errors.append(((proc.stdout or "") + (proc.stderr or "")).strip()[-300:])
            else:
                merged = len(specs)
                # "Design hierarchy mismatch" 是**代码覆盖率**的合并告警
                # （loopback TB 与 DUT TB 的层次不同，属正常）；功能覆盖照样合并。
                # 不当错误处理，只留在 warnings 里供报告引用。
                tail = ((proc.stdout or "") + (proc.stderr or "")).strip()
                if "Design hierarchy mismatch" in tail:
                    warnings.append("部分用例的代码覆盖层次不同（loopback vs DUT），"
                                    "功能覆盖已合并；代码覆盖按层次跳过")

    if not tmp.is_file():
        return {"stores": len(stores), "merged": merged, "errors": errors}
    tmp.replace(out)

    detail = {}
    try:
        r = subprocess.run([vcover, "report", "-cvg", "-details", str(out)],
                           capture_output=True, text=True, errors="replace",
                           timeout=180)
        report_txt.parent.mkdir(parents=True, exist_ok=True)
        report_txt.write_text(r.stdout or "", encoding="utf-8", errors="replace")
        detail = _parse_cvg_text(r.stdout or "")
    except (OSError, subprocess.SubprocessError) as e:
        errors.append(f"report: {e}")
    manifest = _write_merge_manifest(od, out, stores, specs, merged,
                                     errors, warnings)
    return {"ucdb": str(out), "report": str(report_txt),
            "stores": len(stores), "merged": merged,
            "functional_pct": detail.get("functional_pct", 0.0),
            "functional_detail": detail, "manifest": manifest,
            "errors": errors, "warnings": warnings}


def analyze_seed_diversity(od: Path, max_seeds: int = 5,
                           max_stores_per_seed: int = 400) -> dict:
    """**种子多样性实测** —— 不同 seed 的命中 bin 集合到底一不一样。

    ## 为什么要做

    "换种子 → 换激励 → 换覆盖率"是随机验证的基本假设，但此前没有任何
    证据：`seed_diversity` 一直是 `None`。`None` 不是"中性"，它让
    "可复现"退化成"同一颗种子可复现"，而不是"分布可复现"。

    ## 怎么算（不重跑仿真）

    回归的每个用例目录名里带 seed（`*_seed_<n>`），每个用例都有
    `cov/*/questa.db`。按 seed 分组合并成一份 ucdb，再 `vcover report -cvg
    -details` 取逐 bin 命中数。比较各 seed 的命中集合：

      · `stable_bins`   所有 seed 都命中的 bin（种子无关）
      · `variable_bins` 至少一个 seed 新打中的 bin（种子敏感）
      · `new_bins_per_seed` 每个 seed 相对前序 seed 的新增

    这是**实测**，不是"跑了几颗种子"的计数。代价是每颗种子一次 merge；
    默认最多 5 颗（超过的**记账不静默丢**）。

    ## 失败时

    仍然写一份 JSON（`verdict: UNAVAILABLE/INSUFFICIENT` + 原因），
    绝不返回 `None` —— 签核要能区分"没验证"与"验证过且结果如何"。
    """
    od = Path(od).resolve()
    reg_root = od / "regression_run"
    stores = sorted(reg_root.rglob("cov/*/questa.db")) if reg_root.is_dir() else []
    out_path = od / "coverage" / "seed_diversity.json"

    def _finish(payload: dict) -> dict:
        payload.setdefault("schema", "seed_diversity_v1")
        payload.setdefault("analyzed", False)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        except OSError as e:
            payload.setdefault("notes", []).append(f"落盘失败: {e}")
        return payload

    if not stores:
        return _finish({"verdict": "UNAVAILABLE", "reason": "没有回归覆盖率库",
                        "seeds": []})

    # 缓存：结果比所有 store 都新就直接用
    try:
        newest = max(p.stat().st_mtime for p in stores)
        if out_path.is_file() and out_path.stat().st_mtime >= newest:
            cached = json.loads(out_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(cached, dict):
                cached["cached"] = True
                return cached
    except (OSError, ValueError):
        pass

    # 按 seed 分组（目录名里找 `_seed_<n>` / `seed<n>`）
    groups: dict = {}
    for db in stores:
        rel = db.relative_to(od).as_posix()
        m = re.search(r"(?:^|[_-])seed[_-]?(\d+)", rel, re.IGNORECASE)
        seed = int(m.group(1)) if m else None
        groups.setdefault(seed, []).append(db)

    seeds = sorted(s for s in groups if s is not None)
    notes = []
    if len(seeds) < 2:
        return _finish({
            "verdict": "INSUFFICIENT",
            "reason": f"只找到 {len(seeds)} 个可区分 seed 的用例库"
                      f"（共 {len(stores)} 个 store）—— 需要 ≥2 颗种子才能比对",
            "seeds": seeds,
            "stores": len(stores),
            "notes": notes,
        })
    if len(seeds) > max_seeds:
        notes.append(f"只分析前 {max_seeds} 颗种子（共 {len(seeds)} 颗）："
                     f"{seeds[:max_seeds]}，其余 {len(seeds) - max_seeds} 颗未分析")
        seeds = seeds[:max_seeds]

    vcover = questa_exe("vcover.exe")
    if not os.path.exists(vcover):
        return _finish({"verdict": "UNAVAILABLE",
                        "reason": f"vcover not found: {vcover}",
                        "seeds": seeds, "stores": len(stores)})

    per_seed: dict = {}
    errors: list = []
    all_hit_sets: dict = {}
    for seed in seeds:
        subset = groups[seed][:max_stores_per_seed]
        if len(groups[seed]) > max_stores_per_seed:
            notes.append(f"seed {seed}: 只合并前 {max_stores_per_seed} 个 store"
                         f"（共 {len(groups[seed])} 个）")
        out = od / "sim" / "coverage" / f"seed_{seed}_merged.ucdb"
        out.parent.mkdir(parents=True, exist_ok=True)
        for junk in (out, Path(str(out) + "._lock"), Path(str(out) + ".questatmp")):
            try:
                junk.unlink()
            except OSError:
                pass
        specs = []
        for db in subset:
            store = db.parent
            data = sorted(store.glob("*.data"))
            stem = (data[0].stem if len(data) == 1
                    else (store.name if not data else
                          max(data, key=lambda x: x.stat().st_mtime).stem))
            null_test = (not stem) or stem in ("(null)", "null")
            try:
                rel = store.relative_to(od).as_posix()
            except ValueError:
                continue
            specs.append(rel if null_test else f"{rel}:{stem}")
        if not specs:
            continue
        cmdfile = od / "sim" / "coverage" / f"seed_{seed}_inputs.txt"
        cmdfile.write_text("\n".join(specs) + "\n", encoding="utf-8")
        proc = subprocess.run([vcover, "merge", "-inputs", str(cmdfile), str(out)],
                              cwd=str(od), capture_output=True, text=True,
                              errors="replace", timeout=900)
        if proc.returncode != 0 or not out.is_file():
            errors.append(f"seed {seed}: "
                          f"{((proc.stdout or '') + (proc.stderr or '')).strip()[-200:]}")
            continue
        rep = subprocess.run([vcover, "report", "-cvg", "-details", str(out)],
                             capture_output=True, text=True, errors="replace",
                             timeout=300)
        hits = _parse_cvg_bin_hits(rep.stdout or "")
        hit_set = {f"{cg}.{cp}.{b}"
                   for cg, cps in hits.items()
                   for cp, bins in cps.items()
                   for b, n in bins.items() if n > 0}
        all_hit_sets[seed] = hit_set
        per_seed[str(seed)] = {
            "stores": len(specs),
            "hit_bins": len(hit_set),
            "ucdb": str(out),
        }

    if len(all_hit_sets) < 2:
        return _finish({"verdict": "UNAVAILABLE",
                        "reason": "可用的 seed 合并结果不足 2 份",
                        "seeds": seeds, "per_seed": per_seed,
                        "errors": errors, "notes": notes})

    sets = list(all_hit_sets.values())
    stable = set.intersection(*sets)
    union = set.union(*sets)
    variable = union - stable
    # 每个 seed 相对"前序并集"的新增
    running: set = set()
    new_per_seed: dict = {}
    for seed in sorted(all_hit_sets):
        new_per_seed[str(seed)] = len(all_hit_sets[seed] - running)
        running |= all_hit_sets[seed]
    for seed, info in per_seed.items():
        info["new_bins"] = new_per_seed.get(seed, 0)

    verdict = "DIVERSE" if variable else "IDENTICAL"
    if verdict == "IDENTICAL":
        notes.append("所有种子的命中 bin 集合完全一致 —— 种子没有改变覆盖分布，"
                     "需要检查随机化是否真的生效（约束是否把所有取值钉死了）")
    return _finish({
        "verdict": verdict,
        "seeds": sorted(all_hit_sets),
        "stores": len(stores),
        "per_seed": per_seed,
        "stable_bins": len(stable),
        "variable_bins": len(variable),
        "union_bins": len(union),
        "new_bins_per_seed": new_per_seed,
        "notes": notes,
        "errors": errors,
        "analyzed": True,
    })


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
    result["covergroups"] = _parse_cvg_details(text)
    return result


#: `-cvg -details` 里的三行结构（`Coverpoint` / `Cross` 缩进更深，但都靠行首词认）。
_CG_TYPE_RE = re.compile(r"^\s*TYPE\s+(\S+)\s*$", re.M)
_CG_CP_RE = re.compile(r"^\s*Coverpoint\s+(\S+)\s+(\d+\.?\d*)%", re.M)
_CG_CROSS_RE = re.compile(r"^\s*Cross\s+(\S+)\s+(\d+\.?\d*)%", re.M)
_CG_PCT_RE = re.compile(r"^\s*(\d+\.?\d*)%")


def _parse_cvg_details(text: str) -> list:
    """`vcover report -cvg -details` → `[{name, path, goal, actual, coverpoints,
    crosses, cross_actual}]`。

    形状对齐 `config/evidence_schema.yaml` 的 `functional_coverage_layer`
    `evidence_fields.covergroups`（`name` / `goal` / `actual` / `coverpoints` /
    `crosses`）—— 证据链那边读的就是这几个键，键名对不上就等于没有。

    实测输出长这样（`-cvg` 单独用时**没有**这一段，见上面 cmd3 的注释）：

        TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_apb
                                                       71.42%        100          -    Uncovered
            Coverpoint cp_paddr                                66.66%        100 ...
            Cross cross_all                                    33.33%        100 ...

    `TYPE` 那一行给全路径（**末段才是 covergroup 名**），百分比在**下一行**的首列 ——
    这是 vcover 的排版，不是我们选的。
    """
    if not text:
        return []
    # 只看 `COVERGROUP COVERAGE:` 那一段。`-details` 的输出有**两段**：
    #   ① "Coverage Report by instance with details"  —— 逐实例（含每个 bin 的命中数）
    #   ② "COVERGROUP COVERAGE:"                      —— 逐 **type**
    # 两段的 `TYPE` 行一模一样，照全文抓会把每个 covergroup 收两遍（实测 3 个变 6 个），
    # 而证据链要的是"有几个 covergroup 类型、各自多少" —— 那就是第 ② 段。
    head = text.find("COVERGROUP COVERAGE:")
    seg_text = text[head:] if head >= 0 else text

    out: list = []
    matches = list(_CG_TYPE_RE.finditer(seg_text))
    for i, m in enumerate(matches):
        # 本 covergroup 的段落：从这一行的结尾到下一个 TYPE 的开头
        end = matches[i + 1].start() if i + 1 < len(matches) else len(seg_text)
        seg = seg_text[m.end():end]
        path = m.group(1)
        pct_m = _CG_PCT_RE.search(seg)
        actual = float(pct_m.group(1)) if pct_m else 0.0
        coverpoints = [{"name": n, "actual": float(p)}
                       for n, p in _CG_CP_RE.findall(seg)]
        crosses = [{"name": n, "actual": float(p)}
                   for n, p in _CG_CROSS_RE.findall(seg)]
        # `five_layer` 的 `func_cov_cross` 读的是 `cross_actual`（不是 crosses 列表）。
        # **不给就是默认 100 分**——那会让"一个 cross 都没跑"悄悄通过门禁，
        # 所以这里按最差的那个 cross 如实给。
        cross_actual = min((c["actual"] for c in crosses), default=100.0)
        out.append({
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "goal": 100.0,
            "actual": actual,
            "coverpoints": coverpoints,
            "crosses": crosses,
            "cross_actual": cross_actual,
        })

    # 兜底去重：没有 `COVERGROUP COVERAGE:` 标记时（格式变了）仍按全路径收一遍，
    # 同一个路径只留第一次 —— 宁可少几行，也不要把同一个 covergroup 报两次。
    seen: set = set()
    return [c for c in out if not (c["path"] in seen or seen.add(c["path"]))]


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
            found = set()
            for m in re.finditer(
                r"(Branches|Statements|Toggles|Conditions|Lines|FSM)"
                r"\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%", blk):
                base = metric_base.get(m.group(1))
                if not base:
                    continue
                found.add(base)
                result[f"{base}_bins"] = int(m.group(2))
                result[f"{base}_misses"] = int(m.group(4))
                result[f"{base}_pct"] = float(m.group(5))
            # ⚠️ **只在报告里真出现过的指标上求平均**（`found`），不是"值 > 0 的"。
            #
            # 原来过滤的是 `v > 0`：于是"这次**压根没采**的指标"（编译没开 `-cover l`
            # 就没有 Lines、没采 toggle 就没有 Toggles，它们都是 0）与"采了但确实低"
            # 的指标被一视同仁 —— 前者被排除出分母、后者拉低平均。数字于是变成
            # "碰巧采到的那些指标的均值"，而闭环拿它当收敛目标。
            #
            # 实测：一份只有 Statements/Branches/Conditions 的报告给出 **32.5%**，
            # 同一轮的**功能覆盖率是 64.81%**；两个数都不是"覆盖率"，却都在被当覆盖率用。
            # 现在把"哪些采了/哪些没采"如实报出来（`metrics_present` / `metrics_absent`），
            # 没采的不进分母，也**不该让闭环去补一个量不到的洞**。
            result["metrics_present"] = sorted(found)
            result["metrics_absent"] = sorted(set(metric_base.values()) - found)
            vals = [result[f"{b}_pct"] for b in sorted(found)]
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


def _attach_code_plan(coverage: dict, result: dict, od: Path) -> None:
    """把 DUT 计划代码覆盖率挂到结果上；失败只打印，不拦主流程。"""
    try:
        from src.tools.common.lib.code_coverage_plan import (
            merge_dut_code_coverage)

        code_plan = merge_dut_code_coverage(od)
        if code_plan.get("overall_pct") is None:
            return
        coverage["code_plan"] = code_plan
        result["code_coverage_plan"] = code_plan
        print(f"[coverage] 计划代码覆盖率（DUT，{code_plan.get('merged', 0)}/"
              f"{code_plan.get('stores', 0)} 条合并）："
              f"{code_plan.get('overall_pct')}%"
              f"（单测 {coverage.get('overall_pct')}%）")
    except Exception as e:                          # noqa: BLE001 旁路
        print(f"[coverage] 计划代码覆盖率合并跳过：{e}")


def _attach_evidence(od: Path, result: dict, max_cases: int) -> None:
    """跑证据流水线并把结果并进 `result`（编排在 `evidence_pipeline` 里）。

    旁路：失败只记一句，不拦"度量"这条主流程。
    """
    try:
        from src.tools.checking.coverage_tools.evidence_pipeline import (
            attach_to_result)

        attach_to_result(od, result, max_cases=max_cases)
    except Exception as e:                          # noqa: BLE001 旁路证据
        print(f"[coverage] 证据流水线失败（度量结果不受影响）: {e}")



def run(output_dir: str, top_module: str = "", seed: int = 0,
        case_cov_sample: int = 0) -> dict:
    """一站式收集覆盖率。

    `case_cov_sample > 0` 时逐用例取证超过该条数就采样（**会在
    `case_tp.json.evidence_sampled` 与 `notes` 里说出来**，不静默降级）。
    """
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

        # ── 签核口径：**计划覆盖率**（回归逐用例库合并）──
        #
        # 上面那份是"覆盖率阶段单独跑的一条 test"；签核实际该看的是**回归计划
        # 跑过的全部用例**。两件事必须分开记，不能悄悄换掉：
        #   functional_pct            ← 计划覆盖率（签核门禁用这个）
        #   single_test_functional_pct ← 单测覆盖率（对照用）
        plan = merge_regression_coverage(od)
        if plan.get("ucdb") and plan.get("functional_detail"):
            coverage["single_test_functional_pct"] = coverage.get("functional_pct")
            coverage["single_test_detail"] = coverage.get("functional_detail")
            coverage["functional_pct"] = plan.get("functional_pct", 0.0)
            coverage["functional_detail"] = plan.get("functional_detail") or {}
            coverage["plan_ucdb"] = plan["ucdb"]
            coverage["plan_stores"] = plan.get("stores", 0)
            coverage["plan_merge_errors"] = plan.get("errors") or []
            coverage["tp_report"] = plan.get("report", "")
            result["plan_coverage"] = {
                "functional_pct": plan.get("functional_pct", 0.0),
                "stores": plan.get("stores", 0),
                "merged": plan.get("merged", 0),
                "ucdb": plan["ucdb"],
                "report": plan.get("report", ""),
                "errors": plan.get("errors") or [],
                "warnings": plan.get("warnings") or [],
                "single_test_pct": coverage["single_test_functional_pct"],
                # 合并输入清单 —— 签核证据包里要能回答"这个数字由哪些库算出来"
                "merge_manifest": plan.get("manifest", ""),
            }
            print(f"[coverage] 计划覆盖率（{plan.get('merged', 0)}/"
                  f"{plan.get('stores', 0)} 条用例库合并）："
                  f"{plan.get('functional_pct', 0.0):.2f}%"
                  f"（单测 {coverage['single_test_functional_pct']}%）")
        else:
            coverage["plan_merge_errors"] = plan.get("errors") or plan.get("error") or []
            if plan:
                print(f"[coverage] 计划覆盖率合并未完成："
                      f"{coverage['plan_merge_errors'][:2] or plan}")

        # ── 代码覆盖率的计划口径：只合并 DUT 层次（排除 loopback）──
        # 单测 merged.ucdb 只代表一条 test；回归 266 条库能回答"回归实际覆盖
        # 了 DUT 多少代码"。它是对照口径，不替代签核的功能覆盖率门禁。
        _attach_code_plan(coverage, result, od)
    else:
        result["status"] = sim_result.get("status", "FAIL")

    # ── 种子多样性：**逐 bin 实测**，不是"跑了几颗种子"的计数 ──
    #
    # 放在计划覆盖率之后：它按 seed 分组合并的是同一批回归库，计划合并
    # 已经把 `regression_run/**/cov/*` 扫过一遍，这里只多花 N 次 merge。
    # 失败不拦主流程 —— 但会写一份 `seed_diversity.json` 说明为什么没算成，
    # 签核因此能区分"没验证"与"验证过，结果是 X"。
    try:
        seed_div = analyze_seed_diversity(od)
        if seed_div:
            result["seed_diversity"] = seed_div
    except Exception as e:                       # noqa: BLE001 旁路
        print(f"[coverage] 种子多样性分析失败: {e}")

    # ── 制品清单：覆盖率库与波形的**路径 + 哈希** ──
    #
    # 这两个文件本来就落盘了（`sim/coverage/merged.ucdb`、`wave_<seed>.vcd`），
    # 但**只以"某个目录里有个文件"的形式存在**：`ucdb_path` 埋在
    # `result["coverage"]` 里，哈希算在 `coverage` 执行器的内存返回里
    #（`coverage/main.py` 的 `coverage_db.sha256`）—— 落进 JSON 的一个都没有。
    #
    # 后果是"签核证据包"里这两样是**匿名文件**：人和工具都说不清这一轮的覆盖率
    # 数字对应的是哪一份库，也没法核"后来有没有被换过"。所以显式记下来，
    # 与 `infrastructure.archive_coverage()` 的 `{sha256, size}` 同一套形状。
    result["artifacts"] = _artifact_manifest(sim_result)

    result["artifacts"] = _artifact_manifest(sim_result)

    # ── 测试点矩阵：**覆盖缺口归因到测试点** ──
    #
    # 有 `coverage/testpoints.yaml` 才产（verify 从 case 模型生成）。矩阵回答的
    # 是以前答不出的那个问题："这个 bin 没打中，是哪条测试点没被激励/没跑到？"
    # 没有它时，缺口只按 coverpoint 百分比列出来 —— 而一个 coverpoint 可能对应
    # 十几个测试点，人得自己去猜。
    #
    # **逐用例取证先跑**：每条用例自己的 ucdb → 它名下 TP 的 proof obligation。
    # 合并库只能回答"某条用例打到过"，逐用例才能回答"这条用例证明了这个点"，
    # 而且能接上同目录的波形。
    # 派生物统一走 `evidence_pipeline`（case_cov → tp_matrix → tp_evidence →
    # evd → cell_matrix → case_view → gates）。每步可单独重跑，产物带 manifest。
    _attach_evidence(od, result, case_cov_sample)

    # ── 语义自述：把"绿但空"的中间态写成结构化字段 ──
    #
    # 覆盖率数字好看**不等于**量到了该量的东西：ucdb 落了库而 bin 一个没命中、
    # 约束生成了而策略体是空壳 —— 这些都是"PASS 但没生效"。以前它们只散落在
    # 日志与人的记忆里，audit 门禁看不见。这个块把结论显式化，供门禁判
    # `PASS_WITH_CAVEAT`。见下面那个函数的 docstring。
    result["semantic_validations"] = _semantic_validations(od, result)

    # 保存结果
    cov_json = od / "sim" / "coverage" / "coverage_result.json"
    cov_json.parent.mkdir(parents=True, exist_ok=True)
    cov_json.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8", errors="replace")
    print(f"[coverage] Results saved to {cov_json}")
    return result


# ════════════════════════════════════════════════════════════
# 测试点 × 覆盖仓 矩阵
# ════════════════════════════════════════════════════════════

def _parse_cvg_bin_hits(text: str) -> dict:
    """`vcover -cvg -details` → `{covergroup: {coverpoint: {bin: hits}}}`。

    只扫**第一段**（`COVERGROUP COVERAGE:` 之前）—— 那段的 `TYPE` 行下带着
    逐 bin 的命中数；第二段只有 covergroup 级百分比。两段都扫会把同一个 bin
    收两遍（见 `_parse_cvg_details` 的注释）。
    """
    out: dict = {}
    head = text.find("COVERGROUP COVERAGE:")
    seg = text[:head] if head >= 0 else text
    cg = cp = ""
    for ln in seg.splitlines():
        m = re.match(r"\s*TYPE\s+(\S+)\s*$", ln)
        if m:
            cg = m.group(1).rstrip("/").split("/")[-1]
            out.setdefault(cg, {})
            cp = ""
            continue
        m = re.match(r"\s*Coverpoint\s+(\S+)\s+", ln)
        if m:
            cp = m.group(1)
            if cg:
                out[cg].setdefault(cp, {})
            continue
        m = re.match(r"\s*(?:illegal_)?bin\s+(\S+)\s+(\d+)", ln)
        if m and cg and cp:
            name, hits = m.group(1), int(m.group(2))
            bins = out[cg][cp]
            # 同一 bin 在段内只出现一次；重复时取最大（防御性，不累加）
            bins[name] = max(bins.get(name, 0), hits)
    return out


def _read_testpoints(od: Path) -> list:
    """读 `coverage/testpoints.yaml`（verify 落的测试点 IR）。没有就空。"""
    p = od / "coverage" / "testpoints.yaml"
    try:
        import yaml as _yaml
        doc = _yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError):
        return []
    tps = doc.get("testpoints") if isinstance(doc, dict) else None
    return tps if isinstance(tps, list) else []


def _lookup_hits(hits: dict, cp_name: str, bin_name: str) -> Optional[int]:
    """`(coverpoint, bin)` → 命中数；**报告里根本没有这一格时返回 `None`**。

    `None` 与 `0` 是两件事：
      · `0`      —— 仓声明了、这次没命中（该补激励）；
      · `None`   —— 报告里压根没有这个仓（模型/生成漂了，该修模型或生成器）。
    把后者记成 0 会让人去补一条**打不中**的用例。

    **优先 DUT 探针那个 covergroup**：`cg_dut` 用的是模型声明的仓名；env_cov 的
    事务通道用的是 `v_zero/v_one/v_rest` 这类自动仓。同一个 `cp_<字段>` 两边都有，
    但只有探针那边的 bin 名能和测试点对上 —— 所以先找 `cg_dut`，再全找。
    """
    if not cp_name or not bin_name:
        return None
    order = sorted(hits, key=lambda g: (not g.startswith("cg_dut"), g))
    for cg in order:
        v = (hits[cg].get(cp_name) or {}).get(bin_name)
        if v is not None:
            return v
    return None


def _stage_of(tp: dict) -> str:
    return str((tp.get("execution") or {}).get("stage") or "")


def _status_for(n, kind: str, observe: bool) -> tuple:
    """命中数 → 矩阵状态。`None` = 报告里没这一格（判不了），不是 0。"""
    is_backdoor = kind == "backdoor"
    if n is None:
        return "UNMAPPED", 0, is_backdoor
    if n > 0:
        status = ("BACKDOOR_HIT" if is_backdoor
                  else ("OBSERVED" if observe else "HIT"))
        return status, n, is_backdoor
    status = ("BACKDOOR_MISS" if is_backdoor
              else ("UNOBSERVED" if observe else "MISS"))
    return status, n, is_backdoor


def _behavior_row(tp: dict, cp_name: str, bin_name: str, kind: str,
                  observe: bool, stage: str) -> dict:
    """行为 TP 的矩阵行 —— 没有执行数据，单列 PENDING_BACKEND。"""
    return {
        "tp_id": tp.get("tp_id"),
        "dimension": tp.get("dimension"),
        "value": tp.get("value"),
        "coverpoint": cp_name,
        "bin": bin_name,
        "hits": 0,
        "kind": kind,
        "observe_only": observe,
        "status": "PENDING_BACKEND",
        "requirement": tp.get("requirement"),
        "stage": stage,
        "note": "行为域执行后端未接（P1b）—— 暂不参与覆盖率判定",
    }


def _attribute_rows(rows: list) -> list:
    return [r for r in rows if r.get("stage") != "behavior"]


def _count_stage(rows: list, stage: str) -> int:
    return sum(1 for r in rows if r.get("stage") == stage)


def _row_hits(tp: dict, hits: dict) -> tuple:
    """`(owned_bins, {bin: hits|None}, legacy_hit_count)`。

    多仓 TP 的 legacy 命中数取**最大**（"打到过"）；proof obligation 的
    全部命中判定在逐用例签核那边（`case_cov`），这里不重复。
    """
    cp_name = str(tp.get("coverpoint") or "")
    owned = _owned_bins(tp)
    bin_hits = {b: _lookup_hits(hits, cp_name, b) for b in owned}
    vals = [v for v in bin_hits.values() if v is not None]
    if owned and not vals:
        return owned, bin_hits, None
    return owned, bin_hits, (max(vals) if vals else 0)


def _tp_row(tp: dict, hits: dict, signoff: dict, counts: dict) -> dict:
    """一条测试点 → 矩阵行（合并库 status + 逐用例签核字段）。"""
    cp_name = str(tp.get("coverpoint") or "")
    bin_name = str(tp.get("bin") or "")
    observe = bool(tp.get("observe_only"))
    kind = str((tp.get("realization") or {}).get("kind") or "")
    if not kind:
        kind = "observe" if observe else "stimulus"
    stage = _stage_of(tp)
    if stage == "behavior":
        # 行为域（P1a）：TP 已进 IR，但执行后端（事件序列 → UVM）还没接，
        # 因此**没有覆盖率数据可判**。单列 PENDING_BACKEND，不进
        # drivable 分母、也不算 UNMAPPED（它不是"模型漂了"）。
        counts["PENDING_BACKEND"] = counts.get("PENDING_BACKEND", 0) + 1
        return _behavior_row(tp, cp_name, bin_name, kind, observe, stage)

    owned, bin_hits, n = _row_hits(tp, hits)
    # `_status_for` 对 UNMAPPED 会把 `None` 归成 `0`（"报告里没这一格"与
    # "打中了 0 次"在 **legacy status** 里不区分；逐用例签核那边用
    # `bin_hits` 保留 None，不把模型漂移记成"该补激励"）。
    status, n, is_backdoor = _status_for(n, kind, observe)
    counts[status] = counts.get(status, 0) + 1
    _s = signoff.get(str(tp.get("tp_id") or "")) or {}
    signed = bool(_s.get("signed_off"))
    counts["SIGNED_OFF" if signed else "UNSIGNED"] += 1
    return {
        "tp_id": tp.get("tp_id"),
        "dimension": tp.get("dimension"),
        "value": tp.get("value"),
        "coverpoint": cp_name,
        "bin": bin_name,
        "bins": owned,
        "bin_hits": bin_hits,
        "hits": n,
        "kind": kind,
        "observe_only": observe,
        "status": status,
        "requirement": tp.get("requirement"),
        "stage": ((tp.get("execution") or {}).get("stage") or ""),
        # ── 逐用例签核（与上面的合并库 status 是两回事）──
        "owner_test": (_s.get("owner_test")
                       or ((tp.get("execution") or {}).get("test") or "")),
        "owner_case": _s.get("owner_case", ""),
        "signed_off": signed,
        "signed_off_by": _s.get("signed_off_by", ""),
        "signoff_reasons": _s.get("reasons") or [],
        # 时序（P2）：None = 没声明/没检查，不是"通过"。
        "timing_ok": _s.get("timing_ok"),
        **_tp_contract_fields(tp, _s),
    }


def _tp_contract_fields(tp: dict, summary: dict) -> dict:
    """三集合引用（arch.md）：这条 TP 属于哪些组 / 受哪些 checker 保护。"""
    return {
        "case_id": tp.get("case_id", "") or summary.get("case_id", ""),
        "groups": list(tp.get("groups") or []),
        "sva": list(tp.get("sva") or []),
        "scb": list(tp.get("scb") or []),
        "case_status": summary.get("case_status", ""),
    }


def _matrix_counts(rows: list, counts: dict) -> dict:
    """**三类分开算**：激励 / 后门 / 观测。后门命中不冒充"激励覆盖"。"""
    attr = _attribute_rows(rows)
    out = {"drivable": 0, "drivable_hit": 0, "backdoor": 0,
           "backdoor_hit": 0, "observed": 0, "attr_total": len(attr)}
    for r in attr:
        kind, hits = r["kind"], r["hits"]
        if kind in ("stimulus", "sequence"):
            out["drivable"] += 1
            if hits > 0:
                out["drivable_hit"] += 1
        elif kind == "backdoor":
            out["backdoor"] += 1
            if hits > 0:
                out["backdoor_hit"] += 1
        elif kind == "observe" and hits > 0:
            out["observed"] += 1
    out["observe_only"] = sum(1 for r in rows if r["kind"] == "observe")
    out["signed_off_total"] = counts["SIGNED_OFF"]
    out["unsigned_total"] = counts["UNSIGNED"]
    return out


def _matrix_summary(rows: list, counts: dict, case_index: dict,
                    stats: dict) -> dict:
    drivable, backdoor = stats["drivable"], stats["backdoor"]
    attr_total = stats["attr_total"]
    return {
        "total": len(rows),
        "counts": counts,
        "drivable": drivable,
        "drivable_hit": stats["drivable_hit"],
        "drivable_pct": (round(100.0 * stats["drivable_hit"] / drivable, 2)
                         if drivable else 0.0),
        "backdoor": backdoor,
        "backdoor_hit": stats["backdoor_hit"],
        "backdoor_pct": (round(100.0 * stats["backdoor_hit"] / backdoor, 2)
                         if backdoor else 0.0),
        "observe_only": stats["observe_only"],
        "observed": stats["observed"],
        "behavior_pending": _count_stage(rows, "behavior"),
        # 签核口径（逐用例、逐 seed）
        "signed_off_total": stats["signed_off_total"],
        "unsigned_total": stats["unsigned_total"],
        "signed_off_pct": (round(100.0 * stats["signed_off_total"] / attr_total, 2)
                           if attr_total else 0.0),
        "timing_warn": sum(1 for r in rows
                           if r.get("timing_ok") is False
                           and r.get("kind") == "sequence"),
        "case_evidence": {
            "case_count": case_index.get("case_count", 0),
            "evidence_sampled": bool(case_index.get("evidence_sampled")),
            "counts": case_index.get("counts") or {},
        },
        "missed": [r for r in rows
                   if r["status"] in ("MISS", "UNOBSERVED", "BACKDOOR_MISS")],
        "unsigned": [r for r in rows
                     if not r.get("signed_off") and r.get("stage") != "behavior"],
        "unmapped": [r for r in rows if r["status"] == "UNMAPPED"],
        "rows": rows,
    }


def _tp_matrix(od: Path, coverage: dict, case_index: dict = None,
               *, require_wave: bool = True) -> dict:
    """测试点 × 覆盖仓 → 命中/缺口矩阵 + **逐 TP 签核状态**。

    命中状态（**四态，不把"没激励"混进"没覆盖"**，口径仍是**合并库**）：

        HIT         激励型测试点，它的仓命中了
        MISS        激励型测试点，仓一个都没中
        OBSERVED    观测型测试点，仓命中了（没有激励差异，但状态确实到达过）
        UNOBSERVED  观测型测试点，仓没命中
        UNMAPPED    模型给的 `coverpoint.bin` 在报告里找不到（模型/生成漂了）

    **`status` 回答的是"合并库里有没有"**；`signed_off` 回答的是完全另一个
    问题："有没有**一条用例、同一次 seed** 证明了这个测试点"。两者不能互相
    冒充 —— 合并库里有命中，只能说明某条用例打到过。
    """
    tps = _read_testpoints(od)
    if not tps:
        return {}

    # **优先用计划覆盖率报告**（回归全量用例合并）—— 单测报告只代表一条 test，
    # 拿它给 63 条测试点判命中会把"没跑过的仓"报成 MISS（其实只是那条 test 没打到）。
    report = (Path(str(coverage["tp_report"]))
              if coverage.get("tp_report")
              else Path(str(coverage.get("report_dir") or "")) / "coverage_cvg.txt")
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"error": f"读不到 {report}", "total": len(tps)}

    if case_index is None:
        case_index = _case_cov_matrix(od, require_wave=require_wave)
    signoff = case_index.get("by_tp") or {}
    hits = _parse_cvg_bin_hits(text)
    counts = {"HIT": 0, "MISS": 0, "OBSERVED": 0, "UNOBSERVED": 0,
              "BACKDOOR_HIT": 0, "BACKDOOR_MISS": 0, "UNMAPPED": 0,
              "SIGNED_OFF": 0, "UNSIGNED": 0}
    rows = [_tp_row(tp, hits, signoff, counts)
            for tp in tps if isinstance(tp, dict)]
    return _matrix_summary(rows, counts, case_index,
                           _matrix_counts(rows, counts))


def _write_tp_matrix(od: Path, matrix: dict) -> None:
    """把矩阵落到 `coverage/tp_matrix.json` —— 签核材料的一部分。"""
    p = od / "coverage" / "tp_matrix.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(matrix, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except OSError as e:
        print(f"[coverage] 测试点矩阵落盘失败: {e}")


# ════════════════════════════════════════════════════════════
# 逐用例取证 —— case_cov / case_tp（实现在检查层，解析器复用本模块）
# ════════════════════════════════════════════════════════════
#
# 签核的口径从「合并库里存在这个 bin」改成「**这一条用例自己的 ucdb** 里，
# 该测试点名下的全部覆盖仓命中，且这条用例本身是干净的」。
#
# 实现放在 `tools/checking/coverage_tools/case_cov.py`：那里读 vcover、写
# case_cov / case_tp，但**不复制任何解析器** —— `_parse_cvg_bin_hits` /
# `_lookup_hits` / proof obligation 都还是本模块这一份。


def _owned_bins(tp: dict) -> list:
    """测试点的 **proof obligation**：它名下必须全部命中的仓。

    `bins:`（多仓/交叉）优先；否则单个 `bin:`。空 = 模型没声明（判不了，
    不能当成"通过"）。
    """
    bins = tp.get("bins")
    owned = [str(b) for b in bins if str(b)] if isinstance(bins, list) else []
    if not owned and tp.get("bin"):
        owned = [str(tp["bin"])]
    return owned


def _case_cov_matrix(od: Path, *, max_cases: int = 0,
                     require_wave: bool = True, force: bool = False) -> dict:
    """逐用例解析回归目录 → 覆盖切片 + 用例 ↔ 测试点证据表（委托检查层）。"""
    from src.tools.checking.coverage_tools.case_cov import case_cov_matrix
    return case_cov_matrix(od, max_cases=max_cases, require_wave=require_wave,
                           force=force)


def _semantic_validations(od: Path, result: dict) -> dict:
    """`semantic_validations` —— 「这一步产出的数字到底有没有意义」。

    回答三个此前没人回答的问题，每个都对应一类**看着绿、其实空**的中间态：

        ucdb_nonzero_bins        库落了，可有一个 bin 被命中吗？
        cg_dut_hit_gt_zero       DUT 侧的 covergroup（内部信号/输出端口）真采到了吗？
        constraint_policy_applied 约束生成了，可 `apply()` 真的做事吗？

    ## 三值而不是两值

    `None` = **没测/测不了**，与 `False` = 测了、结论是"没生效"**必须分开**。
    混成一个的话，"这次没跑覆盖率"会被读成"覆盖率是空的"，而前者不是问题、
    后者是。整块读不到时整个键不出现（与 `_artifact_manifest` 同一条纪律）。

    `constraint_policy_applied` **读生成期落下的 `coverage/constraint_status.json`**，
    不去抓仿真日志 —— 策略体落 `default:` 是运行期分支，而那条 `uvm_info` 是
    `UVM_HIGH`，默认 verbosity 下根本不打（`sim.sh` 里也没有 `+UVM_VERBOSITY`）。
    生成期本来就知道答案，抓日志是舍近求远且抓不到。
    """
    notes: list = []
    cov = result.get("coverage") or {}
    cvg = cov.get("functional_detail") or {}

    bin_hits = int(cvg.get("bin_hits") or 0)
    bin_total = int(cvg.get("bin_total") or 0)
    ucdb_nonzero = (bin_hits > 0) if bin_total else None
    if ucdb_nonzero is False:
        notes.append(f"ucdb 落了库但**一个 bin 都没命中**（0/{bin_total}）—— "
                     f"覆盖率数字没有意义，检查仿真是否真跑到 DUT")
    elif ucdb_nonzero is None:
        notes.append("没拿到 bin 命中数（没跑覆盖率或解析失败）—— 判不了")

    # DUT 侧那个 covergroup 单独看：它采的是**内部状态与输出端口**，
    # 事务通道（`cg_<agent>`）采不到那些。它零命中而事务侧有命中，说明
    # bind 探针没接上（覆盖率数字会虚高）。
    cg_dut_actual = None
    for g in (cvg.get("covergroups") or []):
        if "cg_dut" in str(g.get("name") or ""):
            cg_dut_actual = float(g.get("actual") or 0.0)
            break
    if cg_dut_actual is None:
        notes.append("没有 `cg_dut`（这次没用 `sample: dut` 的覆盖点）")
    elif cg_dut_actual <= 0:
        notes.append("`cg_dut` 零命中 —— DUT 探针可能没挂上"
                     "（bind 接口 / config_db 句柄），内部状态与输出端口一个都没采到")

    # 约束：**生成期**的结论，读 verify 落下的状态文件
    cpa = None
    status_file = od / "coverage" / "constraint_status.json"
    if status_file.is_file():
        try:
            st = json.loads(status_file.read_text(encoding="utf-8", errors="replace"))
            cpa = bool(st.get("constraint_policy_applied"))
            if not cpa:
                _backed = st.get("backed_policy_count")
                _total = st.get("policy_count")
                if isinstance(_backed, int) and isinstance(_total, int) and _backed:
                    notes.append(
                        f"约束只部分生效：{_backed}/{_total} 条策略由模型编译出"
                        f"真实赋值，其余 {st.get('unbacked_policy_count', _total - _backed)} "
                        f"条仍落在 `default:` 分支（维度不可驱动）")
                else:
                    notes.append(
                        f"约束未激活：{st.get('unbacked_policy_count', 0)} 条策略的 "
                        f"apply() 落在 `default:` 分支、不做任何事"
                        f"（{st.get('note') or '策略体是空骨架'}）")
        except (OSError, ValueError):
            notes.append("约束状态文件读不出来 —— 判不了")
    else:
        notes.append("没有约束状态文件（这一轮没生成约束模型）")

    # 测试点：**每一个覆盖缺口都能归因到一条 tp_id** 才算"量到了该量的东西"。
    # 没有 TP IR 时是 `None`（这一轮没建模），不是 `False`（建模了但有断点）。
    tp_matrix = result.get("tp_matrix") or {}
    tp_traced = None
    if tp_matrix:
        tp_traced = not bool(tp_matrix.get("unmapped"))
        if tp_matrix.get("unmapped"):
            notes.append(
                f"{len(tp_matrix['unmapped'])} 条测试点的覆盖仓在报告里找不到 —— "
                f"模型与生成的覆盖率模型漂了（见 coverage/tp_matrix.json 的 unmapped）")
        missed = tp_matrix.get("missed") or []
        if missed:
            notes.append(
                f"{len(missed)} 条测试点的仓未命中"
                f"（激励型 {tp_matrix.get('drivable', 0)} 条中命中 "
                f"{tp_matrix.get('drivable_hit', 0)} 条，"
                f"{tp_matrix.get('drivable_pct', 0)}%）—— 逐条见 tp_matrix.json")

    # ── 种子多样性：**做过才给布尔**，没做仍是 `None` ──
    #
    # `None` 与 `False` 的区别很重要：
    #   None  = 没分析（没有 ≥2 颗种子 / vcover 不可用）
    #   False = 分析了，但各种子的命中集合完全一致（随机化没生效）
    #   True  = 分析了，且确实存在种子敏感的 bin
    sd = result.get("seed_diversity") or {}
    seed_verified = None
    if sd.get("analyzed"):
        seed_verified = (sd.get("verdict") == "DIVERSE")
        notes.append(
            f"种子多样性：{sd.get('verdict')}（{len(sd.get('seeds') or [])} 颗种子，"
            f"稳定 {sd.get('stable_bins', 0)} bin / 种子敏感 "
            f"{sd.get('variable_bins', 0)} bin / 并集 {sd.get('union_bins', 0)}）")
    elif sd:
        notes.append(f"种子多样性：{sd.get('verdict')} —— {sd.get('reason', '')}")

    return {
        "ucdb_nonzero_bins": ucdb_nonzero,
        "cg_dut_hit_gt_zero": (cg_dut_actual > 0) if cg_dut_actual is not None else None,
        "constraint_policy_applied": cpa,
        "testpoints_traced": tp_traced,
        "seed_diversity_verified": seed_verified,
        "seed_diversity": sd or None,
        "notes": notes,
    }


def _artifact_manifest(sim_result: dict) -> dict:
    """覆盖率库 / 波形 → `{ucdb: {...}, waveform: {...}}`（路径 + 哈希 + 大小）。

    **哈希不是装饰**：覆盖率数字的意义完全取决于"它出自哪一份库"。一份能被悄悄
    换掉的 ucdb 会让签核回溯失去意义 —— 而 `sim/coverage/` 是回归会反复写的目录，
    换掉它太容易了。记哈希是让"这一轮的数字 = 这一个文件"可核对。

    文件不在就给空串（不伪造）—— 比如这次仿真没落波形，那是事实，不是错误。
    """
    from src.layers.l1_infrastructure.infrastructure import sha256_file

    def _entry(path_str: str, kind: str) -> dict:
        p = Path(path_str) if path_str else None
        if not p or not p.exists():
            return {"path": "", "sha256": "", "size": 0, "kind": kind}
        return {"path": str(p), "sha256": sha256_file(p),
                "size": p.stat().st_size, "kind": kind}

    return {
        "ucdb": _entry(sim_result.get("ucdb_path", ""), "coverage_db"),
        # `.vcd` 是覆盖率后端自己 dump 的那份（`simulate_with_coverage` 的
        # `vcd file ...`），**不是** `sim_modes` 那条 `-qwavedb` 的波形 ——
        # 是两条互不相干的 vsim 命令（见 `sim_modes.py` 与那里的说明）。
        "waveform": _entry(sim_result.get("vcd_path", ""), "waveform"),
    }


if __name__ == "__main__":
    od = sys.argv[1] if len(sys.argv) > 1 else "output/demo_apb_uart"
    top = sys.argv[2] if len(sys.argv) > 2 else ""
    result = run(od, top)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
