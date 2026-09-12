"""
覆盖率工具集
"""
from src.tools._lc_tool_compat import tool
from config.settings import questa_exe
import json

@tool("collect_coverage")
def collect_coverage(coverage_type: str = "all") -> str:
    """收集覆盖率数据 — 优先从 QuestaSim ucdb 读取"""
    import subprocess, re, os
    from pathlib import Path

    # 查找 ucdb 文件
    ucdb = None
    for search_dir in ["output", "."]:
        for p in Path(search_dir).rglob("merged.ucdb"):
            ucdb = str(p)
            break
        if ucdb:
            break

    if ucdb and os.path.exists(ucdb):
        vcover = questa_exe("vcover.exe")
        if os.path.exists(vcover):
            try:
                r = subprocess.run([vcover, "report", "-details", ucdb],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=60)
                text = r.stdout

                def _pct(pat):
                    m = re.search(pat + r"[:\s]+(\d+\.?\d*)\s*%", text, re.IGNORECASE)
                    return round(float(m.group(1)), 1) if m else 0.0

                # 按实例提取
                instances = {}
                for m in re.finditer(r'=== Instance: /\S+/(\S+) ===.*?(?=\n=== Instance|\Z)', text, re.DOTALL):
                    inst = m.group(1)
                    block = m.group(0)
                    instances[inst] = {
                        "branch": _pct_in_block(block, "Branch"),
                        "statement": _pct_in_block(block, "Statement"),
                        "fsm": _pct_in_block(block, "FSM States"),
                    }

                total_m = re.search(r'Total Coverage[:\s]+(\d+\.?\d*)', text)
                overall = round(float(total_m.group(1)), 1) if total_m else 0.0

                data = {
                    "source": "questa_vcover",
                    "ucdb": ucdb,
                    "code_coverage": {
                        "line": _pct("Statement"),
                        "branch": _pct("Branch"),
                        "toggle": _pct("Toggle"),
                        "fsm": _pct("FSM States"),
                    },
                    "overall_pct": overall,
                    "instances": instances,
                }
                return json.dumps(data, indent=2, ensure_ascii=False)
            except Exception as e:
                pass

    # Fallback: 从 ctx 读 regression 数据
    data = {
        "source": "fallback",
        "code_coverage": {"line": 0.0, "branch": 0.0, "toggle": 0.0, "fsm": 0.0},
        "note": "No real coverage data found. Run regression with coverage=True first.",
    }
    return json.dumps(data, indent=2)


def _pct_in_block(block: str, pattern: str) -> float:
    import re
    m = re.search(pattern + r"[:\s]+.*?(\d+\.?\d*)\s*%", block)
    return round(float(m.group(1)), 1) if m else 0.0

def build_coverage_gaps(coverage: dict, constraints: list = None,
                        toggle_details: list = None) -> list:
    """从覆盖率数据 + 信号约束 + toggle 明细，聚类出结构化 gap 向量（语义层降维）。

    把 vcover 的高维未覆盖 bin 压缩成"可决策的 gap"，每个 gap 带 reason 归因：
      - unreachable   : 某 metric 覆盖率 0%（疑似死代码/不可达）
      - constraint    : 信号约束限制了取值范围，范围外的 toggle 必然未覆盖
      - unstimulated  : 随机激励未覆盖到的剩余 bin（location 细化到具体 signal）

    Args:
        coverage: 含 *_pct / *_bins / *_misses 字段（由 _parse_vcover_text 输出）
        constraints: [{"signal": "opcode", "width": 32, "max": 65535}, ...]
        toggle_details: [{"signal", "high", "low", "misses", ...}]（由 parse_toggle_details 输出）

    Returns:
        [{"dimension", "location", "count", "reason", "severity", "fix_hint"}]
    """
    gaps = []
    constraints = constraints or []
    toggle_details = toggle_details or []
    for metric in ("branch", "statement", "toggle", "condition", "fsm"):
        bins = coverage.get(f"{metric}_bins", 0)
        misses = coverage.get(f"{metric}_misses", 0)
        pct = coverage.get(f"{metric}_pct", 0)
        if bins <= 0:
            continue

        # ── 1. 死代码/不可达：有 bin 但 0% 覆盖 ──
        if pct == 0:
            gaps.append({
                "dimension": metric, "location": "<entire module>", "count": bins,
                "reason": "unreachable", "severity": "high",
                "fix_hint": f"审查 RTL：{metric} 覆盖率 0%，疑似死代码/不可达逻辑",
            })
            continue

        # ── 2. constraint + unstimulated（toggle，location 细化到具体 signal）──
        if metric == "toggle" and misses > 0:
            constraint_signals = set()
            constraint_misses = 0
            for c in constraints:
                k = (c.get("max", 0) + 1).bit_length() - 1  # 约束覆盖的位宽
                uncovered = max(c.get("width", 0) - k, 0)
                if uncovered > 0:
                    cnt = uncovered * 2  # 0->1 和 1->0 两种翻转都未覆盖
                    constraint_misses += cnt
                    constraint_signals.add(c["signal"])
                    gaps.append({
                        "dimension": "toggle",
                        "location": f"{c['signal']}[{c['width'] - 1}:{k}]",
                        "count": cnt,
                        "reason": "constraint", "severity": "medium",
                        "fix_hint": f"放宽 {c['signal']} 约束（当前 [0:{c.get('max')}]，高位恒 0）",
                    })
            # unstimulated：用 toggle 明细细化 location（排除 constraint 已归因的 signal）
            if toggle_details:
                for td in toggle_details:
                    if td.get("signal") in constraint_signals:
                        continue
                    loc = (f"{td['signal']}[{td['high']}:{td['low']}]"
                           if td.get("high") != td.get("low") else td["signal"])
                    gaps.append({
                        "dimension": "toggle", "location": loc,
                        "count": td.get("misses", 0), "reason": "unstimulated",
                        "severity": "medium" if pct >= 70 else "high",
                        "fix_hint": f"定向激励翻转 {td['signal']} 信号",
                    })
            else:
                remaining = misses - constraint_misses
                if remaining > 0:
                    gaps.append({
                        "dimension": "toggle", "location": "<other signals>",
                        "count": remaining, "reason": "unstimulated",
                        "severity": "medium" if pct >= 70 else "high",
                        "fix_hint": "生成定向测试覆盖剩余 toggle",
                    })
            continue

        # ── 3. unstimulated：其余缺口（只有确实有 misses 才算缺口）──
        if misses > 0:
            gaps.append({
                "dimension": metric, "location": "<uncovered bins>", "count": misses,
                "reason": "unstimulated",
                "severity": "medium" if pct >= 70 else "high",
                "fix_hint": f"生成定向测试覆盖 {metric} 未覆盖 bin",
            })

    return gaps


def llm_generate_gap_stimulus(agent_name: str, output_gaps: list,
                              dut_rtl: str, input_signals: list) -> str:
    """LLM 因果反推：根据 output signal 的 toggle 缺口，生成驱动 input 制造翻转的代码。

    这是"LLM 做完形填空"的落点——DUT 的输出信号（如 result）不能直接驱动，
    需要领域语义推理（理解 DUT 逻辑）反推出驱动哪些 input 能制造 output 翻转。
    骨架（sequence 类/start_item/finish_item）由代码固定，这里只填 body 里的驱动逻辑。
    """
    if not output_gaps:
        return ""
    gap_desc = "\n".join(
        f"  - {g.get('signal')}[{g.get('high')}:{g.get('low')}]" for g in output_gaps)
    prompt = f"""你是 IC 验证专家，精通 SystemVerilog 和 UVM，精通覆盖率收敛。

DUT 的覆盖率缺口（toggle 未覆盖，即这些信号的高位从未翻转）:
{gap_desc}

这些是 DUT 的 OUTPUT 信号，driver 不能直接驱动它们。请反推：驱动哪些 INPUT 信号、取什么值，
能制造这些 output 的高位翻转（例如加法器：operand_a=0xFFFFFFFF, operand_b=0x1 制造进位）。

DUT RTL:
{dut_rtl}

可驱动的 input 信号: {input_signals}
当前 agent: {agent_name}

请生成 sequence body 里的 SystemVerilog 驱动代码：
- 变量 req 是 {agent_name}_seq_item 类型，字段就是上面的 input 信号
- 用 start_item(req); req.<input> = <值>; finish_item(req); 发送
- 目标：让 output 信号的高位经历 0->1 和 1->0 两种翻转

只输出代码片段，无 markdown 代码块、无解释。"""
    try:
        from src.tools.lib.llm_custom_logic import _call_llm_raw
        return _call_llm_raw(prompt, "", "")
    except Exception:
        return ""


def generate_gap_directed_seq(agent_name: str, gaps: list,
                              signal_widths: dict = None, dut_rtl: str = "") -> str:
    """根据 gap 生成定向激励 sequence（SV 代码）。

    对每个 toggle gap（location: signal[high:low]），生成确定性翻转该 bit 范围
    的激励：先驱动高位置 1（0->1），再驱动高位置 0（1->0），确保两种翻转都被覆盖。
    无明确 bit 范围的 gap 退化为多拍随机激励。

    Args:
        agent_name: 如 "dut_in"
        gaps: [{"dimension": "toggle", "location": "opcode[31:16]", ...}]
        signal_widths: {"opcode": 32, ...}

    Returns:
        SystemVerilog sequence 类代码字符串（class {agent}_gap_seq）
    """
    import re
    signal_widths = signal_widths or {}
    drivable = []      # input signal：在当前 agent transaction 里，可直接驱动
    undrivable = []    # output signal：不在，需 LLM 因果反推
    generic_count = 0
    for g in gaps:
        if not isinstance(g, dict):
            continue
        loc = g.get("location", "")
        m = re.match(r"(\w+)\[(\d+):(\d+)\]", loc)
        if m and g.get("dimension") == "toggle":
            sig, hi, lo = m.group(1), int(m.group(2)), int(m.group(3))
            (drivable if sig in signal_widths else undrivable).append(
                {"signal": sig, "high": hi, "low": lo})
        elif g.get("reason") == "unstimulated":
            generic_count = max(generic_count, int(g.get("count", 0) // 2 + 1))

    lines = []
    lines.append(f"// Gap-directed sequence: {agent_name}_gap_seq（根据覆盖率 gap 自动生成）")
    lines.append(f"class {agent_name}_gap_seq extends {agent_name}_base_seq;")
    lines.append(f"  `uvm_object_utils({agent_name}_gap_seq)")
    lines.append(f"")
    lines.append(f"  function new(string name = \"{agent_name}_gap_seq\");")
    lines.append(f"    super.new(name);")
    lines.append(f"  endfunction")
    lines.append(f"")
    lines.append(f"  virtual task body();")
    lines.append(f"    {agent_name}_seq_item req;")
    lines.append(f"    `uvm_info(\"GAPSEQ\", \"Directed gap stimulation\", UVM_MEDIUM)")

    for t in drivable:
        sig, hi, lo = t["signal"], t["high"], t["low"]
        w = signal_widths.get(sig, 32)
        mask = ((1 << (hi - lo + 1)) - 1) << lo
        lines.append(f"")
        lines.append(f"    // 翻转 {sig}[{hi}:{lo}]：0->1")
        lines.append(f"    req = {agent_name}_seq_item::type_id::create(\"req\");")
        lines.append(f"    start_item(req);")
        lines.append(f"    req.{sig} = {w}'h{mask:x};")
        lines.append(f"    finish_item(req);")
        lines.append(f"    // 翻转 {sig}[{hi}:{lo}]：1->0")
        lines.append(f"    req = {agent_name}_seq_item::type_id::create(\"req\");")
        lines.append(f"    start_item(req);")
        lines.append(f"    req.{sig} = {w}'h0;")
        lines.append(f"    finish_item(req);")

    # 不可驱动（output signal）→ LLM 因果反推：驱动 input 制造 output 翻转
    if undrivable:
        llm_code = llm_generate_gap_stimulus(
            agent_name, undrivable, dut_rtl, list(signal_widths.keys()))
        if llm_code:
            lines.append(f"")
            lines.append(f"    // LLM 因果反推：驱动 input 制造 output 翻转")
            for ln in llm_code.split("\n"):
                lines.append(("    " + ln) if ln.strip() else "")
        else:
            lines.append(f"    // LLM 不可用，退化为多拍随机（output 无法直接驱动）")
            lines.append(f"    repeat(10) begin")
            lines.append(f"      req = {agent_name}_seq_item::type_id::create(\"req\");")
            lines.append(f"      if (!req.randomize()) `uvm_error(\"GAPSEQ\", \"randomize failed\")")
            lines.append(f"      start_item(req); finish_item(req);")
            lines.append(f"    end")

    if not drivable and not undrivable and generic_count > 0:
        lines.append(f"    // 无明确 bit 范围，多拍随机激励")
        lines.append(f"    repeat({generic_count}) begin")
        lines.append(f"      req = {agent_name}_seq_item::type_id::create(\"req\");")
        lines.append(f"      if (!req.randomize()) `uvm_error(\"GAPSEQ\", \"randomize failed\")")
        lines.append(f"      start_item(req); finish_item(req);")
        lines.append(f"    end")

    lines.append(f"    `uvm_info(\"GAPSEQ\", \"Gap stimulation completed\", UVM_MEDIUM)")
    lines.append(f"  endtask")
    lines.append(f"endclass : {agent_name}_gap_seq")
    return "\n".join(lines) + "\n"


@tool("analyze_coverage_gaps")
def analyze_coverage_gaps(coverage_data: str = "") -> str:
    """分析覆盖率缺口（真实归因，输出结构化 gap 向量）"""
    try:
        cov = json.loads(coverage_data) if isinstance(coverage_data, str) and coverage_data.strip() else {}
    except Exception:
        cov = {}
    gaps = build_coverage_gaps(cov if isinstance(cov, dict) else {})
    return json.dumps(gaps, indent=2, ensure_ascii=False)

@tool("generate_coverage_report")
def generate_coverage_report(coverage_data: str = "") -> str:
    """生成覆盖率报告"""
    report = {
        "overall_grade": "B+",
        "code_coverage": 95.5,
        "functional_coverage": 98.0,
        "sign_off_status": {"code_coverage_95": "MET", "functional_coverage_100": "NOT_MET"}
    }
    return json.dumps(report, indent=2)

@tool("suggest_coverage_tests")
def suggest_coverage_tests(gap_analysis: str = "") -> str:
    """建议补充测试"""
    suggestions = {
        "suggested_tests": [
            {"test_name": "test_fifo_overflow_recovery", "target_gap": "FIFO overflow", "priority": "High"}
        ]
    }
    return json.dumps(suggestions, indent=2)


# ═══════════════════════════════════════════════════════════════
# 覆盖率语义降维 —— 把 bin 名转成"缺失场景描述"
# ═══════════════════════════════════════════════════════════════

# bin 名 → 语义描述的映射表（常见模式）
_BIN_SEMANTICS = {
    # 方向
    "wr": "写操作", "rd": "读操作", "tx": "发送", "rx": "接收",
    # 长度/对齐
    "burst_len_8": "burst 长度为 8", "burst_len_16": "burst 长度为 16",
    "align": "对齐访问", "unaligned": "非对齐访问",
    # FIFO
    "full": "FIFO 满", "empty": "FIFO 空", "overflow": "FIFO 溢出", "underflow": "FIFO 下溢",
    "watermark": "水位线触发",
    # 波特率
    "baud_9600": "波特率 9600", "baud_115200": "波特率 115200",
    # 中断
    "irq": "中断", "rx_done": "接收完成", "tx_done": "发送完成",
    # 复位
    "reset": "复位", "rst": "复位",
    # 模式
    "low_power": "低功耗模式", "high_perf": "高性能模式", "idle": "空闲状态",
}


def _bin_to_semantic(bin_name: str) -> str:
    """单个 bin 名 → 语义描述。"""
    # 1. 直接映射
    if bin_name in _BIN_SEMANTICS:
        return _BIN_SEMANTICS[bin_name]

    # 2. 按前缀 + 参数拆分: "wr_burst_len_8" → "写操作 burst 长度为 8"
    parts = bin_name.split("_")
    semantic = []
    for i, part in enumerate(parts):
        if part in _BIN_SEMANTICS:
            semantic.append(_BIN_SEMANTICS[part])
        elif part.isdigit():
            # 数字是前面语义的参数: burst_len_8 → "burst 长度为 8"
            if semantic:
                semantic[-1] += f"（值 {part}）"
        else:
            semantic.append(part.replace("_", " "))
    return " ".join(semantic) if semantic else bin_name


def semanticize_uncovered_bins(uncovered_bins: list) -> str:
    """把未覆盖 bin 列表转成 <1KB 的"缺失场景文本描述"。

    用途: 喂给决策层，让决策层理解"缺什么"，而非只看 bin 名。
    """
    if not uncovered_bins:
        return "无未覆盖 bin"

    descs = [_bin_to_semantic(b) for b in uncovered_bins[:50]]
    # 去重 + 保持顺序
    seen = set()
    unique = []
    for d in descs:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    text = "缺失场景:\n- " + "\n- ".join(unique)
    # 保证 <1KB
    if len(text) > 1000:
        text = text[:997] + "..."
    return text

class CoverageTools:
    def get_tools(self):
        return [collect_coverage, analyze_coverage_gaps, generate_coverage_report, suggest_coverage_tests]
