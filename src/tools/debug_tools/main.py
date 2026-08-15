"""
调试工具集 — 真实实现（非 mock）

  collect_sim_log      解析 vsim 仿真日志 → 结构化错误树
  collect_compile_log  解析 vlog 编译错误 → 文件:行号:消息
  collect_waveform     解析 WLF 波形 → 关键信号时间线
  fingerprint_error    错误去重指纹
  bisect_test          二分法定位失败测试
  auto_fix             模板匹配 → 自动修复 → 应用 patch
  rerun_failed_test    重跑失败 case 验证修复
"""
import json, re, os, subprocess, time, hashlib
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

from langchain.tools import tool


# ═══════════════════════════════════════════════════════════════
# 错误分类模式（12 类精细分类）
# ═══════════════════════════════════════════════════════════════

ERROR_CATEGORIES = {
    # UVM 环境 (5 子类)
    "uvm_config": {
        "patterns": [r"config_db", r"set\s*\(|get\s*\(", r"virtual\s+interface",
                     r"NOVIF", r"VIF\s*not", r"resource\s+not\s+found"],
        "fix_agent": "uvm",
    },
    "uvm_phase": {
        "patterns": [r"phase.*objection", r"drain_time", r"timeout.*\d+\s*(ns|us|ms)",
                     r"Objection.*raised", r"run_phase.*timeout", r"main_phase"],
        "fix_agent": "uvm",
    },
    "uvm_factory": {
        "patterns": [r"factory.*override", r"type_id::create", r"type\s+not\s+registered",
                     r"factory.*not\s+found", r"override.*failed"],
        "fix_agent": "uvm",
    },
    "uvm_sequencer": {
        "patterns": [r"sequencer.*not\s+found", r"start_item", r"finish_item",
                     r"sequence.*error", r"seq_item_port", r"get_next_item"],
        "fix_agent": "uvm",
    },
    "uvm_tlm": {
        "patterns": [r"TLM.*port", r"export.*not\s+connected", r"analysis.*port",
                     r"imp.*not\s+found", r"put_port|get_port|write\s*\(\)"],
        "fix_agent": "uvm",
    },

    # RTL 设计 (4 子类)
    "rtl_xz": {
        "patterns": [r"\bX\b.*detected", r"\bZ\b.*detected", r"unknown.*state",
                     r"high.impedance", r"uninitialized", r"metastability"],
        "fix_agent": "rtl",
    },
    "rtl_timing": {
        "patterns": [r"setup.*violation", r"hold.*violation", r"recovery.*violation",
                     r"removal.*violation", r"slack.*negative", r"timing.*violation",
                     r"vsim-\d+.*timing"],
        "fix_agent": "rtl",
    },
    "rtl_width": {
        "patterns": [r"width.*mismatch", r"truncat", r"extend.*sign",
                     r"size.*mismatch", r"bit.*width", r"port.*size"],
        "fix_agent": "rtl",
    },
    "rtl_syntax": {
        "patterns": [r"already\s+declared", r"not\s+defined", r"syntax\s+error",
                     r"undeclared.*signal", r"implicit.*net", r"multiple.*driver"],
        "fix_agent": "rtl",
    },

    # 编译 (2 子类)
    "compile_syntax": {
        "patterns": [r"\*\*\s+Error:", r"vlog-", r"near\s+\"", r"syntax\s+error",
                     r"unexpected\s+token", r"expecting\s+\"", r"missing\s+\""],
        "fix_agent": "uvm",
    },
    "compile_elab": {
        "patterns": [r"vopt-", r"elaborat", r"unresolved\s+reference",
                     r"multiple\s+definition", r"library\s+not\s+found",
                     r"Module\s+\".*\"\s+not\s+defined"],
        "fix_agent": "uvm",
    },

    # 模型比对
    "model_mismatch": {
        "patterns": [r"predictor.*mismatch", r"golden.*mismatch", r"expected.*!=.*actual",
                     r"scoreboard.*mismatch", r"reference.*model.*fail", r"cmp.*mismatch"],
        "fix_agent": "model",
    },
}


def _classify_error(text: str) -> dict:
    """将错误文本分类到 12 个细粒度类别。"""
    scores = {}
    for cat, info in ERROR_CATEGORIES.items():
        hits = sum(1 for p in info["patterns"] if re.search(p, text, re.IGNORECASE))
        if hits > 0:
            scores[cat] = hits

    if not scores:
        return {"category": "unknown", "fix_agent": "none", "confidence": 0.0,
                "details": {}}

    primary = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = min(scores[primary] / total * 100, 100) if total > 0 else 0

    return {
        "category": primary,
        "fix_agent": ERROR_CATEGORIES[primary]["fix_agent"],
        "confidence": round(confidence, 1),
        "details": {cat: count for cat, count in sorted(scores.items(), key=lambda x: -x[1])},
    }


# ═══════════════════════════════════════════════════════════════
# 错误指纹 — 相同根因的错误去重
# ═══════════════════════════════════════════════════════════════

def _fingerprint(text: str) -> str:
    """生成错误指纹：归一化后对错误消息做 hash，用于去重。

    归一化顺序很重要: 先替换特定模式，再处理通用数字。
    """
    # 1. 先归一化 0xHEX (避免被后续数字替换破坏)
    normalized = re.sub(r'0x[0-9a-fA-F]+', 'HEX', text)
    # 2. 时间单位 (必须在通用数字替换之前)
    normalized = re.sub(r'\d+\.?\d*\s*(?:ns|us|ms|ps)', 'TIME', normalized)
    # 3. 文件路径
    normalized = re.sub(r'(?:\S+/)?\w+\.sv[a-z]*\(\d+\)', 'FILE(LINE)', normalized)
    # 4. 剩余数字
    normalized = re.sub(r'\d+', 'N', normalized)
    # 5. 空白归一化
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def _lookup_mature_experience(fp: str) -> dict:
    """L5 进化：查成熟调试经验（fingerprint 命中且稳定通过 N 次）。

    返回经验 dict 或 {}。这是"经验 → 能力"的蒸馏通道——同一类错误
    第二次出现时，不重新模板匹配/LLM 分析，直接从经验库命中修复。
    """
    try:
        from src.core.debug_experience import get_debug_experience_store
        exp = get_debug_experience_store().lookup(fp)
        # lookup 默认 confidence>=0.8 才返回；再要求 success_count>0（验证过）
        if exp and exp.get("success_count", 0) > 0:
            return exp
    except Exception:
        pass
    return {}


# ═══════════════════════════════════════════════════════════════
# Tool 1: collect_sim_log — 真实仿真日志解析
# ═══════════════════════════════════════════════════════════════

@tool("collect_sim_log")
def collect_sim_log(output_dir: str = "") -> str:
    """解析仿真日志 (vsim)，返回结构化错误树。

    扫描: output_dir/<regress_dir>/sim/**/sim_*.log
    提取: UVM_ERROR/FATAL/WARNING + 时间戳 + 文件:行号 + 上下文
    """
    od = Path(output_dir) if output_dir else Path("output")
    if not od.exists():
        return json.dumps({"error": f"output_dir not found: {od}", "logs": []}, ensure_ascii=False)

    from src.tools.lib.regress_dir import get_sim_dir
    sim_dir_name = get_sim_dir(od)
    sim_base = od / sim_dir_name / "sim" if sim_dir_name else od / "sim"

    all_errors = []
    log_files_searched = []

    # 搜索所有 sim 子目录
    search_dirs = [sim_base] if sim_base.exists() else []
    search_dirs += list(od.glob("**/sim_*.log"))  # fallback: recursive

    seen = set()
    for log_file in od.rglob("sim_*.log"):
        if str(log_file) in seen:
            continue
        seen.add(str(log_file))
        log_files_searched.append(str(log_file))

        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        lines = content.split("\n")
        errors_in_log = []

        for i, line in enumerate(lines):
            # 匹配 UVM_ERROR, UVM_FATAL, ** Error, ** Warning
            if not any(kw in line for kw in
                       ["UVM_ERROR", "UVM_FATAL", "** Error", "** Warning",
                        "Error:", "FATAL:", "FAIL", "mismatch"]):
                continue

            # 提取时间戳
            ts_match = re.search(r'(\d+\.?\d*\s*(?:ns|us|ms|ps))', line)
            timestamp = ts_match.group(1) if ts_match else ""

            # 提取文件:行号
            file_match = re.search(r'((?:/\S+)?\w+\.sv[a-z]*)\((\d+)\)', line)
            source_file = file_match.group(1) if file_match else ""
            source_line = int(file_match.group(2)) if file_match else 0

            # 提取上下文 (±3 行)
            ctx_start = max(0, i - 3)
            ctx_end = min(len(lines), i + 4)
            context = [f"  L{j}: {lines[j].strip()}" for j in range(ctx_start, ctx_end)]

            classification = _classify_error(line)

            errors_in_log.append({
                "timestamp": timestamp,
                "file": source_file,
                "line": source_line,
                "message": line.strip()[:300],
                "context": context,
                "fingerprint": _fingerprint(line),
                "classification": classification,
            })

        if errors_in_log:
            all_errors.append({
                "log_file": str(log_file),
                "error_count": len(errors_in_log),
                "errors": errors_in_log,
            })

    # 聚合统计
    by_category = {}
    by_fingerprint = {}
    for log_entry in all_errors:
        for err in log_entry["errors"]:
            cat = err["classification"]["category"]
            by_category[cat] = by_category.get(cat, 0) + 1
            fp = err["fingerprint"]
            if fp not in by_fingerprint:
                by_fingerprint[fp] = err

    return json.dumps({
        "logs_scanned": len(log_files_searched),
        "logs_with_errors": len(all_errors),
        "total_errors": sum(len(e["errors"]) for e in all_errors),
        "unique_errors": len(by_fingerprint),
        "by_category": by_category,
        "by_fingerprint": {fp: {"message": e["message"][:150],
                                "category": e["classification"]["category"]}
                           for fp, e in list(by_fingerprint.items())[:20]},
        "errors": all_errors,
    }, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# Tool 2: collect_compile_log — 真实编译错误解析
# ═══════════════════════════════════════════════════════════════

@tool("collect_compile_log")
def collect_compile_log(output_dir: str = "") -> str:
    """解析编译日志 (vlog/vopt)，返回结构化编译错误。

    扫描: output_dir/<regress_dir>/sim/agent/compile_*.log
          output_dir/build/**/*.log
    提取: 文件:行号:错误消息，按严重性分组
    """
    od = Path(output_dir) if output_dir else Path("output")
    if not od.exists():
        return json.dumps({"error": f"output_dir not found: {od}", "compile_errors": []}, ensure_ascii=False)

    all_errors = []
    logs_scanned = 0

    # 搜索编译日志
    search_patterns = [
        "**/compile_*.log",
        "**/sim/agent/compile_*.log",
        "**/build/**/*.log",
        "**/vlog*.log",
    ]

    seen = set()
    for pattern in search_patterns:
        for log_file in od.rglob(pattern.split("/")[-1]):
            if str(log_file) in seen:
                continue
            seen.add(str(log_file))
            logs_scanned += 1

            try:
                content = log_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            errors = []
            for line in content.split("\n"):
                # QuestaSim 编译错误格式:
                #   ** Error: path/to/file.sv(123): message
                #   ** Warning: path/to/file.sv(456): message
                m = re.match(r'\*\*\s+(Error|Warning|Note)\s*:\s*(\S+\.sv[a-z]*)\((\d+)\)\s*:\s*(.*)', line)
                if m:
                    severity, sv_file, sv_line, msg = m.groups()
                    errors.append({
                        "severity": severity.lower(),
                        "file": sv_file.split("/")[-1] if "/" in sv_file else sv_file,
                        "file_full": sv_file,
                        "line": int(sv_line),
                        "message": msg.strip()[:300],
                        "fingerprint": _fingerprint(f"{sv_file}:{sv_line}:{msg}"),
                    })
                    continue

                # 备用: ** Error: (without file:line)
                m2 = re.match(r'\*\*\s+(Error|Warning)\s*:\s*(.*)', line)
                if m2 and not errors:
                    severity, msg = m2.groups()
                    errors.append({
                        "severity": severity.lower(),
                        "file": "",
                        "line": 0,
                        "message": msg.strip()[:300],
                        "fingerprint": _fingerprint(msg),
                    })

            if errors:
                all_errors.append({"log_file": str(log_file), "errors": errors})

    errors_list = [e for entry in all_errors for e in entry["errors"]]
    error_count = sum(1 for e in errors_list if e["severity"] == "error")
    warning_count = sum(1 for e in errors_list if e["severity"] == "warning")

    # 按文件分组
    by_file = {}
    for e in errors_list:
        f = e["file"] or "(unknown)"
        by_file.setdefault(f, []).append(e)

    return json.dumps({
        "logs_scanned": logs_scanned,
        "logs_with_errors": len(all_errors),
        "error_count": error_count,
        "warning_count": warning_count,
        "by_file": {f: len(errs) for f, errs in sorted(by_file.items())},
        "errors": errors_list[:50],  # top 50
    }, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# Tool 3: collect_waveform — 真实波形解析
# ═══════════════════════════════════════════════════════════════

@tool("collect_waveform")
def collect_waveform(input_json: str = "") -> str:
    """解析波形文件 (WLF)，提取关键信号时间线（结构化，值转 int）。

    输入: {"output_dir": "...", "signals": "clk,rst_n,result"}
    扫描: output_dir/**/*.wlf
    用 wlf2log 转文本 → parse_wlf_text 解析成 {signal: [(time_ns, value_int)]}
    """
    try:
        data = json.loads(input_json)
    except (json.JSONDecodeError, TypeError):
        data = {}
    output_dir = data.get("output_dir", "output")
    signals_str = data.get("signals", "")
    od = Path(output_dir)
    if not od.exists():
        return json.dumps({"error": f"output_dir not found: {od}", "signals": []}, ensure_ascii=False)

    wlf_files = list(od.rglob("*.wlf"))

    if not wlf_files:
        return json.dumps({"waveforms_found": 0, "signals": [],
                          "note": "No WLF files found"}, ensure_ascii=False)

    signal_list = [s.strip() for s in signals_str.split(",") if s.strip()] if signals_str else []

    from src.tools.debug_tools.waveform import extract_signal_trace
    results = []
    for wlf in wlf_files[:5]:  # 最多分析 5 个波形文件
        traces = extract_signal_trace(wlf, signal_list) if signal_list else {}
        results.append({
            "waveform": str(wlf),
            "size_kb": round(wlf.stat().st_size / 1024, 1),
            "signal_traces": {name: trace for name, trace in traces.items()},
        })

    return json.dumps({
        "waveforms_found": len(wlf_files),
        "analyzed": results,
    }, indent=2, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# Tool 4: fingerprint_error — 错误去重指纹
# ═══════════════════════════════════════════════════════════════

@tool("fingerprint_error")
def fingerprint_error(error_text: str) -> str:
    """为错误消息生成指纹，用于去重相同的 bug。

    返回指纹 + 已知相似指纹匹配（如有知识库）。
    """
    if not error_text:
        return json.dumps({"error": "empty input"}, ensure_ascii=False)

    fp = _fingerprint(error_text)
    classification = _classify_error(error_text)

    return json.dumps({
        "fingerprint": fp,
        "classification": classification,
        "normalized": re.sub(r'\d+', 'N',
                     re.sub(r'0x[0-9a-fA-F]+', 'HEX', error_text[:200])),
    }, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# Tool 5: bisect_test — 二分法定位失败测试
# ═══════════════════════════════════════════════════════════════

@tool("bisect_test")
def bisect_test(input_json: str = "") -> str:
    """二分法定位失败测试的最小集合。

    输入: {"output_dir": "...", "failed_tests": ["test_a", "test_b"]}
    返回: 最小失败集合 + 建议隔离方向
    """
    try:
        data = json.loads(input_json)
    except (json.JSONDecodeError, TypeError):
        data = {}
    output_dir = data.get("output_dir", "")
    failed_tests_json = data.get("failed_tests", [])
    failed = []
    if failed_tests_json:
        if isinstance(failed_tests_json, list):
            failed = failed_tests_json
        elif isinstance(failed_tests_json, str):
            failed = [t.strip() for t in failed_tests_json.split(",") if t.strip()]

    if not failed:
        # 尝试从 regression 报告读取
        od = Path(output_dir) if output_dir else Path("output")
        for report in od.rglob("report.json"):
            try:
                rpt = json.loads(report.read_text(encoding="utf-8", errors="replace"))
                failed = [t.get("name", "") for t in rpt.get("tests", [])
                          if t.get("status") == "FAIL"]
                break
            except Exception:
                pass

    if not failed:
        return json.dumps({"error": "no failed tests found", "bisect_plan": []}, ensure_ascii=False)

    # 二分策略：如果 >2 个失败，建议先跑一半
    plan = []
    if len(failed) >= 3:
        half = len(failed) // 2
        plan.append({
            "step": 1,
            "action": "bisect",
            "tests_to_run": failed[:half],
            "reason": f"Run first {half}/{len(failed)} tests to narrow down",
        })
        plan.append({
            "step": 2,
            "action": "bisect",
            "tests_to_run": failed[half:] if len(plan) == 1 else [],
            "reason": "If step 1 passed, run rest; else bisect further",
        })

    # 检查每个 failed test 是否独立（看 log 是否共享相同错误指纹）
    od = Path(output_dir) if output_dir else Path("output")
    fps_per_test = {}
    for test_name in failed:
        for log in od.rglob(f"*{test_name}*.log"):
            try:
                content = log.read_text(encoding="utf-8", errors="replace")
                fps_per_test[test_name] = _fingerprint(content[-5000:])
            except Exception:
                pass

    unique_fps = set(fps_per_test.values())
    shared_root = len(unique_fps) < len(failed) * 0.5

    return json.dumps({
        "total_failed": len(failed),
        "failed_tests": failed,
        "unique_fingerprints": len(unique_fps),
        "shared_root_cause": shared_root,
        "suggestion": ("Multiple tests share same error → likely one root cause. Debug first test."
                       if shared_root else
                       "Different error patterns → may be independent bugs. Debug separately."),
        "bisect_plan": plan,
        "test_fingerprints": {t: fp[:8] for t, fp in fps_per_test.items()},
    }, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# Tool 6: auto_fix — 模板匹配 → 自动修复
# ═══════════════════════════════════════════════════════════════

# 修复模板库
FIX_TEMPLATES = [
    {
        "name": "fix_missing_vif",
        "match": [r"virtual\s+interface\s+not\s+set", r"NOVIF", r"VIF\s*not\s+found"],
        "description": "在 test 的 build_phase 中注入 uvm_config_db::set 设置虚拟接口",
        "fix_type": "inject_config_db",
        "target_file_hint": "_tb_top.sv",  # 优先搜索的文件
        "inject_lines": [
            '    uvm_config_db#(virtual {if_name})::set(this, "*", "{vif_name}", {vif_instance});',
        ],
    },
    {
        "name": "fix_missing_package",
        "match": [r"could\s+not\s+find\s+package", r"import.*not\s+found",
                  r"package\s+\".*\"\s+not\s+found"],
        "description": "检查 filelist 是否包含 package 源文件，或加 +incdir+ 路径",
        "fix_type": "update_filelist",
    },
    {
        "name": "fix_module_not_defined",
        "match": [r"Module\s+\".*\"\s+not\s+defined", r"not\s+defined"],
        "description": "在 filelist 中追加缺失的 .sv 文件，或检查 +incdir+ 路径",
        "fix_type": "update_filelist",
    },
    {
        "name": "fix_double_declare",
        "match": [r"already\s+declared\s+in\s+this\s+scope", r"multiple\s+definition"],
        "description": "删除重复的 import 或 include 语句",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_sequence_timeout",
        "match": [r"sequence.*timeout", r"drain_time", r"Objection"],
        "description": "在 sequence body() 中确保 raise_objection/drop_objection 配对，或增加 drain_time",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_scoreboard_width",
        "match": [r"width.*mismatch", r"size.*mismatch", r"truncat"],
        "description": "在 scoreboard compare 中加入 $size() 检查并对齐位宽",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_xz_in_driver",
        "match": [r"\bX\b.*driver", r"\bZ\b.*driver", r"driver.*\bX\b"],
        "description": "在 driver 的 reset 阶段驱动确定值（非 X），或加 if (vif.rst_n) 检查",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_timing_violation",
        "match": [r"setup.*violation", r"hold.*violation", r"timing.*violation"],
        "description": "调整 input delay / output delay 约束，或在 TB 中插入 #delay 等待",
        "fix_type": "manual_hint",
    },
    # ── 新增 12 个模板 ──
    {
        "name": "fix_unconnected_port",
        "match": [r"Port.*not\s+connected", r"unconnected.*port", r"output.*not\s+driven"],
        "description": "在顶层例化中补全缺失的端口连接",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_interface_clock_mismatch",
        "match": [r"clock.*mismatch", r"interface.*clock.*not\s+found", r"clocking\s+block"],
        "description": "对齐 interface 和 agent 的 clocking block 时钟信号名",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_reset_not_connected",
        "match": [r"reset.*not\s+connected", r"rst_n.*not\s+found", r"preset_n.*not\s+found"],
        "description": "确保所有 agent 的 reset 信号连接到顶层 rst_n",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_factory_override",
        "match": [r"factory.*override.*failed", r"type\s+not\s+registered", r"create.*failed"],
        "description": "在 build_phase 中补全 `uvm_factory::set_type_override_by_name`",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_analysis_port_connect",
        "match": [r"analysis.*port.*not\s+connected", r"write.*function.*not\s+called", r"subscriber"],
        "description": "在 env connect_phase 中连接 monitor.analysis_port 到 scoreboard.analysis_export",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_phase_objection",
        "match": [r"Objection.*not\s+raised", r"UVM_WARNING.*objection", r"run_phase.*no\s+objection"],
        "description": "在 sequence 的 pre_body 或 body 开头补 raise_objection，结束时补 drop_objection",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_randomization_failure",
        "match": [r"randomize.*failed", r"constraint.*conflict", r"rand.*not\s+solved"],
        "description": "放宽约束条件或添加 soft constraint 解决随机化冲突",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_config_db_type_mismatch",
        "match": [r"config_db.*type.*mismatch", r"uvm_config_db.*cast.*failed"],
        "description": "确保 uvm_config_db::set 和 get 的类型参数一致",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_hier_path_error",
        "match": [r"hier.*path.*not\s+found", r"uvm_root.*find", r"path.*does\s+not\s+exist"],
        "description": "修正 config_db 的 hier path（使用通配符 * 替代绝对路径）",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_wire_reg_conflict",
        "match": [r"cannot\s+assign\s+to.*reg", r"reg.*cannot\s+be\s+driven", r"multiple\s+driver"],
        "description": "将 reg 改为 wire 或 logic，或在多驱动处加 tri 解析",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_enum_range_error",
        "match": [r"enum.*value.*out\s+of\s+range", r"enum.*invalid", r"illegal.*enum"],
        "description": "扩展 enum 定义范围或添加 default case 处理异常值",
        "fix_type": "edit_file",
    },
    {
        "name": "fix_overflow_underflow",
        "match": [r"overflow", r"underflow", r"fifo.*full.*write", r"fifo.*empty.*read"],
        "description": "在 FIFO 读写前加 full/empty 检查保护逻辑",
        "fix_type": "edit_file",
    },
]


@tool("auto_fix")
def auto_fix(input_json: str = "") -> str:
    """根据错误消息自动匹配修复模板，生成并应用 patch。

    输入: {"error_text": "...", "output_dir": "..."}
    返回: {matched, fix_name, fix_description, patch_applied, file_modified}
    """
    try:
        data = json.loads(input_json)
    except (json.JSONDecodeError, TypeError):
        data = {"error_text": str(input_json)} if input_json else {}
    error_text = data.get("error_text", data.get("error", str(input_json)))
    output_dir = data.get("output_dir", ".")
    if not error_text:
        return json.dumps({"matched": False, "reason": "no error text provided"}, ensure_ascii=False)

    od = Path(output_dir) if output_dir else Path(".")

    # 0. L5 进化：先查成熟调试经验（fingerprint 命中且稳定通过 N 次），跳过模板/LLM
    fp = _fingerprint(error_text)
    exp_reuse = _lookup_mature_experience(fp)
    if exp_reuse:
        return json.dumps({
            "matched": True,
            "fix_name": exp_reuse.get("fix_name", ""),
            "fix_description": f"复用成熟经验（成功 {exp_reuse.get('success_count', 0)} 次）",
            "fix_type": "experience_reuse",
            "patch_applied": False,
            "source": "experience",
            "root_cause": exp_reuse.get("root_cause", ""),
        }, indent=2, ensure_ascii=False)

    # 1. 匹配修复模板
    matched = None
    for tmpl in FIX_TEMPLATES:
        for pattern in tmpl["match"]:
            if re.search(pattern, error_text, re.IGNORECASE):
                matched = tmpl
                break
        if matched:
            break

    if not matched:
        return json.dumps({
            "matched": False,
            "error_summary": error_text[:200],
            "classification": _classify_error(error_text),
            "hint": "No matching fix template — needs manual analysis",
        }, indent=2, ensure_ascii=False)

    # 2. 按 fix_type 执行修复
    result = {
        "matched": True,
        "fix_name": matched["name"],
        "fix_description": matched["description"],
        "fix_type": matched["fix_type"],
        "patch_applied": False,
        "file_modified": "",
    }

    if matched["fix_type"] == "inject_config_db":
        # 搜索合适的注入位置 (tb_top)
        for sv_file in list(od.rglob("*_tb_top.sv"))[:3]:
            try:
                content = sv_file.read_text(encoding="utf-8", errors="replace")
                # 找到 initial begin 块
                if "initial begin" in content:
                    inject_line = matched["inject_lines"][0].format(
                        if_name="dut_if", vif_name="vif", vif_instance="dut_vif")
                    # 在 initial begin 后第一行插入
                    new_content = re.sub(
                        r'(initial\s+begin\s*\n)',
                        r'\1' + inject_line + '\n',
                        content, count=1)
                    sv_file.write_text(new_content, encoding="utf-8", errors="replace")
                    result["patch_applied"] = True
                    result["file_modified"] = str(sv_file)
                    result["injected_line"] = inject_line
                    break
            except Exception as e:
                result["error"] = str(e)

    elif matched["fix_type"] == "update_filelist":
        # 搜索 filelist 并追加缺失文件
        for fl in list(od.rglob("filelist*.f"))[:5] + list(od.rglob("*.filelist"))[:5]:
            try:
                lines = fl.read_text(encoding="utf-8", errors="replace").split("\n")
                result["filelist_checked"] = str(fl)
                result["current_entries"] = len(lines)
                result["patch_applied"] = False
                result["hint"] = f"Check {fl} — may be missing a .sv file or +incdir+ path"
            except Exception as e:
                result["error"] = str(e)

    elif matched["fix_type"] == "edit_file":
        # 定位错误文件并尝试简单修复
        file_match = re.search(r'(\w+\.sv[a-z]*)\((\d+)\)', error_text)
        if file_match:
            target_file = file_match.group(1)
            target_line = int(file_match.group(2))
            for sv in od.rglob(target_file):
                try:
                    lines = sv.read_text(encoding="utf-8", errors="replace").split("\n")
                    if target_line < len(lines):
                        result["target_file"] = str(sv)
                        result["target_line"] = target_line
                        result["line_content"] = lines[target_line - 1].strip()
                        result["hint"] = f"Edit {sv}:{target_line} — {lines[target_line-1].strip()}"
                except Exception:
                    pass

    elif matched["fix_type"] == "manual_hint":
        result["hint"] = matched["description"]
        result["patch_applied"] = False

    return json.dumps(result, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# Tool 7: rerun_failed_test — 重跑失败 case 验证修复
# ═══════════════════════════════════════════════════════════════

@tool("rerun_failed_test")
def rerun_failed_test(input_json: str = "") -> str:
    """重跑指定的失败测试，验证修复。

    输入: {"output_dir": "...", "test_name": "test_smoke_test"}
    返回: {status, stdout_tail, stderr_tail}
    """
    try:
        data = json.loads(input_json)
    except (json.JSONDecodeError, TypeError):
        data = {}
    output_dir = data.get("output_dir", "output")
    test_name = data.get("test_name", "")
    if not test_name:
        return json.dumps({"error": "test_name required"}, ensure_ascii=False)

    od = Path(output_dir) if output_dir else Path("output")

    # 查找 run.sh
    run_script = None
    for candidate in od.rglob(f"**/test_{test_name}/run.sh"):
        run_script = candidate
        break
    if not run_script:
        for candidate in od.rglob(f"**/{test_name}*/run.sh"):
            run_script = candidate
            break

    if not run_script:
        return json.dumps({
            "error": f"No run.sh found for test '{test_name}'",
            "searched_in": str(od),
        }, ensure_ascii=False)

    try:
        r = subprocess.run(
            ["bash", str(run_script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, cwd=str(od.resolve()),
        )
        stdout = r.stdout[-3000:] if r.stdout else ""
        stderr = r.stderr[-1000:] if r.stderr else ""

        passed = "UVM_FATAL" not in stdout and "UVM_ERROR" not in stdout

        return json.dumps({
            "test_name": test_name,
            "status": "PASS" if passed else "FAIL",
            "returncode": r.returncode,
            "stdout_tail": stdout,
            "stderr_tail": stderr,
            "run_script": str(run_script),
        }, indent=2, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"test_name": test_name, "status": "TIMEOUT", "error": "300s timeout"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"test_name": test_name, "status": "ERROR", "error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# DebugTools 类
# ═══════════════════════════════════════════════════════════════

class DebugTools:
    """调试工具集"""

    def get_tools(self):
        return [
            collect_sim_log,
            collect_compile_log,
            collect_waveform,
            fingerprint_error,
            bisect_test,
            auto_fix,
            rerun_failed_test,
        ]

    # 保留旧工具名以兼容
    analyze_simulation_log = staticmethod(lambda log_path="": collect_sim_log(log_path))
    analyze_waveform = staticmethod(lambda waveform_path="", signals="": collect_waveform(waveform_path, signals))
    trace_error_source = staticmethod(lambda error_description="": fingerprint_error(error_description))
    generate_fix_suggestion = staticmethod(lambda root_cause="": auto_fix(root_cause))
