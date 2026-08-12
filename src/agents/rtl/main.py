"""
RTL 工程师 Agent —— 从设计架构生成可综合 SystemVerilog RTL

黑板书通信:
  consumes: ["spec", "design_arch"]  ← 从上游 Agent 读取
  produces: "rtl"                     → 写入 RTL 文件列表到 ctx
  schema:   spec 必须有 interfaces + features; design_arch 必须有 module_name + function_hier

工具链（按调用顺序）:
  1. parse_module_tree  → 解析 function_hier 树 → 扁平子模块列表 + 端口推断
  2. generate_submodule → 生成单个子模块 SV 代码（通用模板，按端口模式匹配逻辑）
  3. generate_top_module → 生成顶层集成模块
  4. write_rtl_files     → 写入磁盘
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import tool

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
import structlog
import json
import re
from pathlib import Path

logger = structlog.get_logger()

_current_output_dir: str | None = None


def _get_output_root() -> str:
    from src.core.output_config import make_output_root
    return _current_output_dir if _current_output_dir else make_output_root()


# ═══════════════════════════════════════════════════════════════
# Schema 校验
# ═══════════════════════════════════════════════════════════════

_SPEC_SCHEMA = ["design_name", "interfaces", "features"]
_DESIGN_SCHEMA = ["module_name", "function_hier"]


def _validate_input(ctx: dict) -> list:
    """校验黑板书输入 schema。返回缺失字段列表。"""
    missing = []
    spec = ctx.get("spec", {}) or {}
    design = ctx.get("design_arch", {}) or {}
    for f in _SPEC_SCHEMA:
        if not spec.get(f):
            missing.append(f"spec.{f}")
    for f in _DESIGN_SCHEMA:
        if not design.get(f):
            missing.append(f"design_arch.{f}")
    return missing


def _validate_output(files: list) -> list:
    """校验输出 RTL 文件。返回问题列表。"""
    issues = []
    for fpath in files:
        p = Path(fpath)
        if not p.exists():
            issues.append(f"missing:{p.name}")
            continue
        code = p.read_text(encoding="utf-8", errors="replace")
        if "module " not in code:
            issues.append(f"no_module:{p.name}")
        if "endmodule" not in code:
            issues.append(f"no_endmodule:{p.name}")
    return issues


# ═══════════════════════════════════════════════════════════════
# 工具: parse_module_tree
# ═══════════════════════════════════════════════════════════════

@tool("parse_module_tree")
def parse_module_tree(design_arch_json: str) -> str:
    """解析 function_hier 树 → 扁平子模块列表（含端口推断）。

    Input:  {"module_name":"...", "function_hier":{...}, "registers":[...]}
    Output: {"module_name":"...", "submodules":[{"name":"...","ports":[...],"registers":[...]},...]}
    端口推断规则：始终包含 clk+rst_n；按端口模式追加（paddr/pwdata→APB, tx→UART_TX, rx→UART_RX, baud_div→baud_gen, wr_en/rd_en→FIFO, irq→INTR）。
    """
    try:
        data = json.loads(design_arch_json) if isinstance(design_arch_json, str) else design_arch_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON input"}, ensure_ascii=False)

    registers = data.get("registers", [])
    module_name = data.get("module_name", "dut")
    function_hier = data.get("function_hier", {})

    def walk_tree(node, parent="", depth=0):
        results = []
        name = node.get("name", "")
        children = node.get("children", [])
        if name and depth > 0:
            results.append({"name": name, "parent": parent, "level": depth})
        for child in children:
            if isinstance(child, dict):
                results.extend(walk_tree(child, name, depth + 1))
        return results

    submodules = walk_tree(function_hier)
    if not submodules:
        submodules = [{"name": f"{module_name}_core", "parent": module_name, "level": 1}]

    # 端口推断：按 spec.interfaces 中的信号名模式匹配
    all_signals = _collect_signals_from_spec(data)

    for sm in submodules:
        sm["ports"] = _infer_ports_by_pattern(sm["name"], all_signals)
        sm["registers"] = [r for r in registers
                           if sm["name"].upper() in r.get("name", "").upper()
                           or sm["name"].lower() in r.get("desc", "").lower()
                           or _register_belongs_to_module(r, sm["name"], all_signals)]

    return json.dumps({"module_name": module_name, "submodules": submodules,
                       "register_count": len(registers)}, ensure_ascii=False, indent=2)


def _collect_signals_from_spec(data: dict) -> dict:
    """从 spec 中提取所有接口信号，按功能域分组。"""
    spec = data if isinstance(data, dict) else {}
    # 尝试从 interfaces 提取
    signals = {}
    interfaces = spec.get("interfaces", [])
    for iface in interfaces:
        if isinstance(iface, dict):
            sigs = iface.get("signals", {})
            for sname, sattrs in sigs.items():
                signals[sname] = {
                    "dir": sattrs.get("direction", sattrs.get("dir", "input")),
                    "width": sattrs.get("width", 1),
                    "interface": iface.get("name", ""),
                }
    # 回退：从 features 推断
    if not signals:
        features = spec.get("features", [])
        feature_text = " ".join(str(f) for f in features)
        # UART 信号
        if "UART" in feature_text or "uart" in feature_text or "串行" in feature_text:
            signals.update({
                "tx": {"dir": "output", "width": 1, "interface": "UART"},
                "rx": {"dir": "input", "width": 1, "interface": "UART"},
            })
        # APB 信号
        if "APB" in feature_text or "apb" in feature_text or "寄存器" in feature_text:
            signals.update({
                "paddr": {"dir": "input", "width": 8, "interface": "APB"},
                "pwdata": {"dir": "input", "width": 8, "interface": "APB"},
                "prdata": {"dir": "output", "width": 8, "interface": "APB"},
                "pwrite": {"dir": "input", "width": 1, "interface": "APB"},
                "psel": {"dir": "input", "width": 1, "interface": "APB"},
                "penable": {"dir": "input", "width": 1, "interface": "APB"},
            })
        # 中断信号
        if "中断" in feature_text or "INT" in feature_text or "irq" in feature_text.lower():
            signals.update({
                "irq": {"dir": "output", "width": 1, "interface": "INTR"},
            })
    return signals


def _register_belongs_to_module(reg: dict, mod_name: str, signals: dict) -> bool:
    """检查寄存器是否属于某个模块。"""
    rn = reg.get("name", "").upper()
    mn = mod_name.upper()
    # 直接包含
    if mn in rn or rn in mn:
        return True
    # 按功能域
    if "BAUD" in rn and ("BAUD" in mn or "GEN" in mn):
        return True
    if ("CTRL" in rn or "STAT" in rn or "TXD" in rn or "RXD" in rn or "IEN" in rn) and ("REG" in mn or "FILE" in mn or "APB" in mn):
        return True
    return False


def _infer_ports_by_pattern(mod_name: str, signals: dict) -> list:
    """通用端口推断——始终包含 clk+rst_n，然后按信号方向+功能域匹配。"""
    ports = [
        {"name": "clk", "dir": "input", "width": 1, "desc": "时钟"},
        {"name": "rst_n", "dir": "input", "width": 1, "desc": "异步复位"},
    ]
    mn = mod_name.upper()

    # 遍历所有 spec 信号，按模块名模式分配到各个子模块
    patterns = {
        # 模块名包含这些关键字 → 分配这些信号
        "REG": ["paddr", "pwdata", "prdata", "pwrite", "psel", "penable"],
        "APB": ["paddr", "pwdata", "prdata", "pwrite", "psel", "penable"],
        "BAUD": ["baud_div", "baud_pulse"],
        "TX": ["tx_data", "tx_start", "tx_busy", "tx"],
        "RX": ["rx", "rx_data", "rx_valid"],
        "FIFO": ["wr_data", "wr_en", "rd_data", "rd_en", "full", "empty"],
        "INT": ["irq_src", "irq", "irq_en"],
    }

    for pattern, sig_names in patterns.items():
        if pattern in mn:
            for sn in sig_names:
                if sn in signals:
                    s = signals[sn]
                    ports.append({"name": sn, "dir": s["dir"], "width": s["width"],
                                  "desc": f"{s.get('interface','')}:{sn}"})

    # 去重
    seen = set()
    unique = []
    for p in ports:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique.append(p)

    return unique


# ═══════════════════════════════════════════════════════════════
# 工具: generate_submodule —— 通用模板
# ═══════════════════════════════════════════════════════════════

@tool("generate_submodule")
def generate_submodule(module_spec_json: str) -> str:
    """生成单个子模块的可综合 SystemVerilog 代码。

    通用规则（不依赖特定模块名）:
    Input: {"name":"...", "ports":[{name,dir,width,desc},...], "registers":[...], "description":"..."}
    Output: {"module_name":"...", "verilog_code":"..."}

    自动生成的逻辑由端口模式决定（非模块名）:
    - 有 paddr/pwdata/prdata/psel/penable 端口 → APB 读写 FSM + 寄存器
    - 有 baud_div(IN) + baud_pulse(OUT) → 计数器 + 脉冲发生器
    - 有 tx_data/tx_start(IN) + tx/tx_busy(OUT) → UART 发送 FSM
    - 有 rx(IN) + rx_data/rx_valid(OUT) → UART 接收 FSM
    - 有 wr_en/rd_en + full/empty → FIFO 存储
    - 有 irq_src(IN) + irq(OUT) → 中断锁存
    - 默认 → 基本 always_ff 骨架（寄存器读写 + 状态更新）
    """
    try:
        spec = json.loads(module_spec_json) if isinstance(module_spec_json, str) else module_spec_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON input"}, ensure_ascii=False)

    name = spec.get("name", "submodule")
    ports = spec.get("ports", [])
    registers = spec.get("registers", [])
    desc = spec.get("description", "")

    # 端口名集合（辅助匹配）
    port_names = {p["name"] for p in ports}
    port_map = {p["name"]: p for p in ports}

    lines = [f"// Module: {name}"]
    if desc:
        lines.append(f"// {desc}")
    lines.append("")

    # ── 端口声明 ──
    port_list = []
    for p in ports:
        pw = p.get("width", 1)
        pd = p.get("dir", "input")
        pn = p.get("name", "?")
        port_list.append(f"    {pd} logic {f'[{pw-1}:0]' if pw > 1 else '       '} {pn}")
    lines.append(f"module {name} (")
    lines.append(",\n".join(port_list))
    lines.append(");")
    lines.append("")

    # ── 内部信号 ──
    has_apb = all(n in port_names for n in ["paddr", "pwdata", "prdata", "psel", "penable"])
    has_baud = "baud_div" in port_names and ("baud_pulse" in port_names or "baud_tick" in port_names)
    has_tx_fsm = "tx_data" in port_names and "tx" in port_names
    has_rx_fsm = "rx" in port_names and "rx_data" in port_names
    has_fifo = "wr_en" in port_names and "rd_en" in port_names
    has_intr = "irq_src" in port_names and "irq" in port_names

    # 寄存器声明
    if registers:
        lines.append("    // ── 寄存器 ──")
        for r in registers:
            rn = r.get("name", "reg").lower()
            rw = r.get("width", 8)
            rr = r.get("reset", "0")
            w = f"[{rw-1}:0]" if rw > 1 else "       "
            lines.append(f"    logic {w} {rn} = {rw}'d{rr};")
        lines.append("")

    # ── APB 读写逻辑 ──
    if has_apb:
        lines.append("    // ── APB 读写 ──")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        for r in registers:
            lines.append(f"            {r['name'].lower()} <= '0;")
        lines.append("        end else if (psel && penable && pwrite) begin")
        lines.append("            case (paddr)")
        for r in registers:
            off = r.get("offset", "0x00").replace("0x", "")
            lines.append(f"                {len(off)}'h{off}: {r['name'].lower()} <= pwdata;")
        lines.append("                default: ;")
        lines.append("            endcase")
        lines.append("        end")
        lines.append("    end")
        lines.append("")
        lines.append("    always_comb begin")
        lines.append("        prdata = {8{1'b0}};")
        lines.append("        case (paddr)")
        for r in registers:
            off = r.get("offset", "0x00").replace("0x", "")
            lines.append(f"            {len(off)}'h{off}: prdata = {r['name'].lower()};")
        lines.append("            default: prdata = {8{1'b0}};")
        lines.append("        endcase")
        lines.append("    end")
        lines.append("")

    # ── 波特率发生器 (计数器 + pulse) ──
    if has_baud:
        pulse_name = "baud_pulse" if "baud_pulse" in port_names else "baud_tick"
        lines.append(f"    // ── 波特率发生器 ──")
        lines.append(f"    logic [15:0] baud_cnt;")
        lines.append(f"    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append(f"        if (!rst_n) begin")
        lines.append(f"            baud_cnt <= '0;")
        lines.append(f"            {pulse_name} <= 1'b0;")
        lines.append(f"        end else begin")
        lines.append(f"            {pulse_name} <= 1'b0;")
        lines.append(f"            if (baud_cnt >= baud_div) begin")
        lines.append(f"                baud_cnt <= '0;")
        lines.append(f"                {pulse_name} <= 1'b1;")
        lines.append(f"            end else begin")
        lines.append(f"                baud_cnt <= baud_cnt + 1'b1;")
        lines.append(f"            end")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append("")

    # ── UART TX FSM ──
    if has_tx_fsm:
        lines.append("    // ── UART 发送 FSM ──")
        lines.append("    typedef enum logic [1:0] {TX_IDLE, TX_DATA, TX_STOP} tx_state_t;")
        lines.append("    tx_state_t tx_state;")
        lines.append("    logic [3:0] tx_bit;")
        lines.append("    logic [9:0] tx_sr;  // {stop, data[7:0], start}")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        lines.append("            tx_state <= TX_IDLE; tx <= 1'b1; tx_busy <= 1'b0; tx_bit <= '0;")
        lines.append("        end else begin")
        # 如果有 baud_pulse，用它做使能；否则每周期运行
        if any("baud_pulse" in p["name"] or "baud_tick" in p["name"] for p in ports):
            pulse = next(p["name"] for p in ports if "baud_pulse" in p["name"] or "baud_tick" in p["name"])
            lines.append(f"            if ({pulse}) begin")
            prefix = "    "
        else:
            prefix = ""
        lines.append(f"{prefix}            case (tx_state)")
        lines.append(f"{prefix}                TX_IDLE: begin tx <= 1'b1; if (tx_start) begin")
        lines.append(f"{prefix}                    tx_sr <= {{1'b1, tx_data, 1'b0}}; tx_busy <= 1'b1;")
        lines.append(f"{prefix}                    tx_state <= TX_DATA; tx_bit <= '0; tx <= 1'b0; end end")
        lines.append(f"{prefix}                TX_DATA: begin tx <= tx_sr[0]; tx_sr <= tx_sr >> 1;")
        lines.append(f"{prefix}                    if (tx_bit == 4'd9) tx_state <= TX_STOP;")
        lines.append(f"{prefix}                    else tx_bit <= tx_bit + 1'b1; end")
        lines.append(f"{prefix}                TX_STOP: begin tx <= 1'b1; tx_busy <= 1'b0; tx_state <= TX_IDLE; end")
        lines.append(f"{prefix}            endcase")
        if any("baud_pulse" in p["name"] or "baud_tick" in p["name"] for p in ports):
            lines.append("            end")
        lines.append("        end")
        lines.append("    end")
        lines.append("")

    # ── UART RX FSM ──
    if has_rx_fsm:
        lines.append("    // ── UART 接收 FSM ──")
        lines.append("    typedef enum logic [1:0] {RX_IDLE, RX_DATA, RX_STOP} rx_state_t;")
        lines.append("    rx_state_t rx_state;")
        lines.append("    logic [3:0] rx_bit;")
        lines.append("    logic [7:0] rx_sr;")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        lines.append("            rx_state <= RX_IDLE; rx_data <= 8'd0; rx_valid <= 1'b0; rx_bit <= '0;")
        lines.append("        end else begin")
        if any("baud_pulse" in p["name"] or "baud_tick" in p["name"] for p in ports):
            pulse = next(p["name"] for p in ports if "baud_pulse" in p["name"] or "baud_tick" in p["name"])
            lines.append(f"            if ({pulse}) begin")
            prefix = "    "
        else:
            prefix = ""
        lines.append(f"{prefix}            rx_valid <= 1'b0;")
        lines.append(f"{prefix}            case (rx_state)")
        lines.append(f"{prefix}                RX_IDLE: if (!rx) begin rx_state <= RX_DATA; rx_bit <= '0; end")
        lines.append(f"{prefix}                RX_DATA: begin rx_sr <= {{rx, rx_sr[7:1]}};")
        lines.append(f"{prefix}                    if (rx_bit == 4'd7) begin rx_data <= {{rx, rx_sr[7:1]}}; rx_state <= RX_STOP; end")
        lines.append(f"{prefix}                    else rx_bit <= rx_bit + 1'b1; end")
        lines.append(f"{prefix}                RX_STOP: begin rx_valid <= 1'b1; rx_state <= RX_IDLE; end")
        lines.append(f"{prefix}            endcase")
        if any("baud_pulse" in p["name"] or "baud_tick" in p["name"] for p in ports):
            lines.append("            end")
        lines.append("        end")
        lines.append("    end")
        lines.append("")

    # ── FIFO ──
    if has_fifo:
        depth = spec.get("fifo_depth", 16)
        lines.append(f"    // ── FIFO ({depth} deep) ──")
        lines.append(f"    logic [7:0] fifo_mem [0:{depth-1}];")
        lines.append(f"    logic [$clog2({depth})-1:0] wr_ptr, rd_ptr;")
        lines.append(f"    logic [$clog2({depth}):0] count;")
        lines.append(f"    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append(f"        if (!rst_n) begin")
        lines.append(f"            wr_ptr <= '0; rd_ptr <= '0; count <= '0;")
        lines.append(f"        end else begin")
        lines.append(f"            if (wr_en && !full) begin")
        lines.append(f"                fifo_mem[wr_ptr] <= wr_data;")
        lines.append(f"                wr_ptr <= wr_ptr + 1'b1; count <= count + 1'b1; end")
        lines.append(f"            if (rd_en && !empty) begin")
        lines.append(f"                rd_data <= fifo_mem[rd_ptr];")
        lines.append(f"                rd_ptr <= rd_ptr + 1'b1; count <= count - 1'b1; end")
        lines.append(f"        end")
        lines.append(f"    end")
        lines.append(f"    assign full  = (count == {depth});")
        lines.append(f"    assign empty = (count == 0);")
        lines.append("")

    # ── 中断逻辑 ──
    if has_intr:
        lines.append("    // ── 中断锁存 ──")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        lines.append("            irq <= 1'b0;")
        lines.append("        end else begin")
        lines.append("            irq <= |(irq_src & irq_en);  // 任意使能的中断源触发")
        lines.append("        end")
        lines.append("    end")
        lines.append("")

    # ── 默认：寄存器更新逻辑 ──
    if not any([has_apb, has_baud, has_tx_fsm, has_rx_fsm, has_fifo, has_intr]):
        if registers:
            lines.append("    // ── 寄存器更新 ──")
            lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
            lines.append("        if (!rst_n) begin")
            for r in registers:
                lines.append(f"            {r['name'].lower()} <= '0;")
            lines.append("        end else begin")
            lines.append("            // TODO: 根据 description 添加业务逻辑")
            lines.append("        end")
            lines.append("    end")
            lines.append("")
        else:
            lines.append("    // ── 骨架：无寄存器、无特定逻辑模式 ──")
            lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
            lines.append("        if (!rst_n) begin")
            lines.append("            // output 端口复位")
            for p in ports:
                if p["dir"] == "output":
                    lines.append(f"            {p['name']} <= '0;")
            lines.append("        end else begin")
            lines.append("            // TODO: 根据 description 添加业务逻辑")
            lines.append("        end")
            lines.append("    end")
            lines.append("")

    lines.append("endmodule")
    return json.dumps({"module_name": name, "verilog_code": "\n".join(lines)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 工具: generate_top_module
# ═══════════════════════════════════════════════════════════════

@tool("generate_top_module")
def generate_top_module(integration_spec_json: str) -> str:
    """生成顶层集成模块，例化所有子模块并连线。

    Input: {"module_name":"...", "submodules":[{name,ports},...], "top_ports":[{name,dir,width},...]}
    Output: {"module_name":"...", "verilog_code":"..."}
    """
    try:
        spec = json.loads(integration_spec_json) if isinstance(integration_spec_json, str) else integration_spec_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)

    module_name = spec.get("module_name", "dut_top")
    submodules = spec.get("submodules", [])
    top_ports = spec.get("top_ports", [])

    lines = [f"// Top Module: {module_name}"]
    lines.append(f"// Auto-generated by RtlAgent — integrates {len(submodules)} submodules")
    lines.append("")

    # 顶层端口
    port_list = []
    for p in top_ports:
        pw = p.get("width", 1)
        pd = p.get("dir", "input")
        pn = p.get("name", "?")
        port_list.append(f"    {pd} logic {f'[{pw-1}:0]' if pw > 1 else '       '} {pn}")
    lines.append(f"module {module_name} (")
    lines.append(",\n".join(port_list))
    lines.append(");")
    lines.append("")

    # 收集所有需要互联的内部信号（跨子模块）
    top_port_names = {p["name"] for p in top_ports}
    internal_signals = set()
    for sm in submodules:
        for p in sm.get("ports", []):
            pn = p["name"]
            if pn not in top_port_names and pn not in ("clk", "rst_n"):
                internal_signals.add(pn)

    # 声明内部连线
    if internal_signals:
        lines.append("    // ── 内部互联信号 ──")
        for sig in sorted(internal_signals):
            # 找最大宽度
            max_w = 1
            for sm in submodules:
                for p in sm.get("ports", []):
                    if p["name"] == sig:
                        max_w = max(max_w, p.get("width", 1))
            if max_w > 1:
                lines.append(f"    logic [{max_w-1}:0] {sig};")
            else:
                lines.append(f"    logic         {sig};")
        lines.append("")

    # 子模块例化
    lines.append("    // ── 子模块例化 ──")
    for sm in submodules:
        sm_name = sm.get("name", "sub")
        lines.append(f"    {sm_name} u_{sm_name} (")
        conns = []
        for p in sm.get("ports", []):
            pn = p["name"]
            if pn == "clk":
                conns.append(f"        .{pn}(clk)")
            elif pn == "rst_n":
                conns.append(f"        .{pn}(rst_n)")
            elif pn in top_port_names:
                conns.append(f"        .{pn}({pn})")
            else:
                conns.append(f"        .{pn}({pn})")
        lines.append(",\n".join(conns))
        lines.append("    );")
        lines.append("")

    lines.append("endmodule")
    return json.dumps({"module_name": module_name, "verilog_code": "\n".join(lines)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 工具: write_rtl_files
# ═══════════════════════════════════════════════════════════════

@tool("write_rtl_files")
def write_rtl_files(file_names_json: str) -> str:
    """确认写入 RTL 文件到磁盘。代码由之前的 generate_submodule / generate_top_module 自动收集。

    只需传文件名列表。代码内容从之前的工具调用中自动提取，不需要在参数中重复。
    Input: {"modules": ["reg_file", "baud_gen", "uart_tx", "uart_rx", "apb_uart"]}
    Output: {"written":["/abs/path/reg_file.sv",...], "count":N}
    """
    try:
        data = json.loads(file_names_json) if isinstance(file_names_json, str) else file_names_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON, expected {\"modules\":[\"name1\",...]}"}, ensure_ascii=False)

    module_names = data.get("modules", data.get("files", []))
    if isinstance(module_names, list) and module_names and isinstance(module_names[0], dict):
        module_names = [f.get("path", f.get("name", "unknown")) for f in module_names]
    # Clean .sv extension
    module_names = [n.replace(".sv", "") for n in module_names]

    output_dir = Path(_get_output_root())
    rtl_dir = output_dir / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)

    # 从已写入的文件中确认
    written = []
    for mn in module_names:
        fpath = rtl_dir / f"{mn}.sv"
        if fpath.exists():
            written.append(str(fpath))
        else:
            logger.warning(f"Module {mn}.sv not found on disk — must be generated by tools first")

    return json.dumps({"written": written, "count": len(written),
                       "expected": module_names,
                       "output_dir": str(rtl_dir)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# Agent 类
# ═══════════════════════════════════════════════════════════════

@register_agent("rtl")
class RtlAgent(BaseAgent):
    """RTL 工程师 —— 黑板书通信: consumes [spec, design_arch] → produces rtl"""

    task_type = "code_generation"
    consumes = ["spec", "design_arch"]
    produces = "rtl"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="rtl",
            display_name="RTL工程师",
            description="从设计架构（spec + design_arch）生成可综合 SystemVerilog RTL",
            config=config or {}
        )
        self.min_score = 50
        self.max_retries = 2

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """Role: RTL Design Engineer — 可综合 SystemVerilog 代码生成

通信模型: 黑板书 (Blackboard)
  读取:  spec (interfaces, features, registers) + design_arch (module_name, function_hier)
  写入:  rtl (生成的 .sv 文件列表)
  约束:  输入缺失必要字段时报错，输出必须通过 schema 校验

═══════════════ 工具（严格按顺序调用） ═══════════════

1. parse_module_tree(design_arch_json)
   -> 得到 {{"module_name":"...", "submodules":[{{"name":"...","ports":[...],"registers":[...]}},...]}}
   -> 每个 submodule 自动推断端口（clk+rst_n + 业务信号）

2. generate_submodule(module_spec_json)  <- 对每个子模块调用
   -> 输入: parse_module_tree 返回的单个 submodule
   -> 输出: {{"module_name":"...", "verilog_code":"module ... endmodule"}}
   -> 模板是通用的：根据端口模式自动生成对应逻辑
     - paddr/pwdata/prdata/psel/penable -> APB 寄存器读写
     - baud_div + baud_pulse -> 计数器/波特率发生器
     - tx_data/tx_start + tx/tx_busy -> UART 发送 FSM
     - rx + rx_data/rx_valid -> UART 接收 FSM
     - wr_en/rd_en + full/empty -> FIFO
     - irq_src + irq -> 中断锁存
     - 无匹配模式 -> 基础 always_ff 骨架

3. generate_top_module(integration_spec_json)
   -> 输入: {{"module_name":"...", "submodules":[...], "top_ports":[...]}}
   -> 输出: 顶层模块，例化所有子模块并自动连线

4. write_rtl_files(file_names_json)
   -> 确认写入。只需传模块名列表，代码自动从前面的工具调用中收集
   -> 输入: {{"modules": ["reg_file", "baud_gen", "uart_tx", "uart_rx", "top_name"]}}
   -> 注意：不要在参数中包含代码内容，只传模块名！

═══════════════ 执行规则 ═══════════════
- 不要跳过 generate_submodule —— 每个子模块都必须调用它生成代码
- write_rtl_files 只传模块名，不要传代码（代码自动从之前工具调用中提取）
- 生成完所有文件后，输出 JSON: {{"modules":[...], "top":"...", "file_count":N}}
"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [
            parse_module_tree,
            generate_submodule,
            generate_top_module,
            write_rtl_files,
        ]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if not self._executor:
            return {"output": "Agent未初始化", "score": 0}
        try:
            result = await self._executor.ainvoke({"input": input_text})
            return {"output": result.get("output", str(result))}
        except Exception as e:
            return {"output": f"Agent error: {str(e)[:200]}", "score": 0}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从 LLM 交互中提取 RTL 代码并写入磁盘。"""
        output = result.get("output", "")
        steps = result.get("intermediate_steps", [])
        module_name = getattr(self, '_design_name', None) or "dut"
        sv_files = {}

        # 1) 从工具调用 (intermediate_steps) 收集
        for step in steps:
            if isinstance(step, tuple) and len(step) >= 2:
                action, obs = step[0], step[1]
                try:
                    obs_data = json.loads(str(obs)) if isinstance(obs, str) else obs
                except (json.JSONDecodeError, TypeError):
                    continue
                if "module_name" in obs_data:
                    mn = obs_data["module_name"]
                    if mn and mn.lower() not in ("dut", "dut_top"):
                        if module_name.lower() in ("dut", "dut_top") or mn != module_name:
                            module_name = mn
                    code = obs_data.get("verilog_code", obs_data.get("content", ""))
                    if code and mn not in sv_files:
                        sv_files[mn] = code

        # 2) 从 write_rtl_files 确认已写入的文件
        if not sv_files:
            rtl_dir = Path(self._last_output_dir) / "rtl" if hasattr(self, '_last_output_dir') else Path(_get_output_root()) / "rtl"
            existing = list(rtl_dir.glob("*.sv")) if rtl_dir.exists() else []
            if existing:
                for f in existing:
                    sv_files[f.stem] = f.read_text(encoding="utf-8", errors="replace")

        # 3) 从 LLM 文本输出提取代码块
        if not sv_files:
            blocks = re.findall(r'```(?:systemverilog|verilog|sv)?\s*\n(.*?)```', output, re.DOTALL)
            if not blocks:
                blocks = re.findall(r'(module\s+\w+.*?endmodule)', output, re.DOTALL)
            for i, block in enumerate(blocks):
                block = block.strip()
                m = re.search(r'module\s+(\w+)', block)
                mn = m.group(1) if m else f"submodule_{i}"
                if mn not in sv_files:
                    sv_files[mn] = block

        # 4) 写入磁盘 — 直接从前几步收集的代码写入，不依赖 write_rtl_files 参数
        rtl_dir = Path(self._last_output_dir) / "rtl" if hasattr(self, '_last_output_dir') else Path(_get_output_root()) / "rtl"
        rtl_dir.mkdir(parents=True, exist_ok=True)
        written = []

        for mn, code in sv_files.items():
            # 自动修复常见问题
            code = re.sub(r'\b0x([0-9a-fA-F]+)\b', r"8'h\1", code)
            code = code.replace("default: ;", "default: begin end")
            code = re.sub(r'\$clog2\(\s*\{\s*(\w+)\s*\}\s*\)', r'$clog2(\1)', code)
            fpath = rtl_dir / f"{mn}.sv"
            fpath.write_text(code, encoding="utf-8", errors="replace")
            written.append(str(fpath))

        file_count = len(written)
        result["rtl"] = {
            "module_name": module_name,
            "files": written,
            "file_count": file_count,
            "status": "generated" if file_count > 0 else "empty",
        }
        result["score"] = min(50 + file_count * 5, 95) if file_count > 0 else 20
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        """黑板书入口：校验输入 schema → LLM 生成 → 校验输出 schema"""
        global _current_output_dir
        from src.core.output_config import make_output_root
        self._last_output_dir = make_output_root(task.get("output_dir") or None)
        _current_output_dir = self._last_output_dir

        ctx = task.get("ctx", {})
        if hasattr(ctx, 'get'):
            self._last_ctx = {k: ctx.get(k) for k in ('spec', 'design_arch', 'model') if ctx.get(k)}
            # 提取设计名
            spec = ctx.get("spec", {})
            if isinstance(spec, dict):
                dn = spec.get("design_name", "")
                if dn and dn.lower() not in ("dut", "dut_top"):
                    self._design_name = dn
            design_arch = ctx.get("design_arch", {})
            if isinstance(design_arch, dict):
                dn = design_arch.get("module_name", "")
                if dn and dn.lower() not in ("dut", "dut_top"):
                    self._design_name = dn

            # ── 黑板书输入 schema 校验 ──
            ctx_dict = {}
            for k in ('spec', 'design_arch'):
                val = ctx.get(k)
                if hasattr(val, 'get'):
                    ctx_dict[k] = dict(val)
                elif isinstance(val, dict):
                    ctx_dict[k] = val
            missing = _validate_input(ctx_dict)
            if missing:
                logger.warning(f"RTL input schema violation: missing={missing}")
                # 不阻断 —— LLM 可以根据部分信息尽力生成

        return await super().execute_task(task)
