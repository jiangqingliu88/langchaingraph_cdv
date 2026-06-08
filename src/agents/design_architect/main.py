"""
设计架构师 Agent —— 模块 Spec → function_hier(代码风格) + 寄存器 + RTL hierarchy

Output: 函数模块声明 + 寄存器 map + RTL 例化层次 + signoff checklist
"""
from typing import Dict, List, Any
from datetime import datetime as dt
from pathlib import Path
import json, re

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent


@register_agent("design_architect")
class DesignArchitect(BaseAgent):
    """设计架构师 —— function + register + RTL hierarchy 代码生成"""

    task_type = "code_generation"
    consumes = ["spec"]
    produces = "design_arch"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="design_architect", display_name="设计架构师",
            description="模块 Spec → function hierarchy + register map + RTL hierarchy",
            config=config or {})
        self.min_score = 50

    async def _setup(self): pass
    async def _get_prompt_template(self): return None
    async def _get_tools(self) -> List: return []
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        return {"output": "use bypass mode"}

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            ctx = task.get("ctx", {}) if isinstance(task, dict) else {}
            if ctx.get("spec"):
                task["bypass"] = True
            else:
                return await super().execute_task(task)
        start = dt.now()
        try:
            spec_text = task.get("input", str(task))
            module_name = _extract_module(spec_text)

            # 根据模块名选择生成器
            if module_name == 'alu':
                func_hier = _gen_alu_function_hierarchy()
                registers = _gen_alu_register_map()
            else:
                func_hier  = _gen_function_hierarchy(module_name, spec_text)
                registers  = _gen_register_map(module_name, spec_text)
            rtl_hier   = _gen_rtl_hierarchy(module_name, func_hier)
            signoff    = _gen_signoff(module_name, func_hier, registers)

            doc_code = _render_code(module_name, func_hier, registers, rtl_hier, signoff)
            synth_rtl = _render_synth_rtl(module_name, func_hier, registers)

            result = {
                "module_name": module_name,
                "function_hier": func_hier,
                "registers": registers,
                "rtl_hier": rtl_hier,
                "signoff_checklist": signoff,
                "register_count": len(registers),
                "function_count": _count_leaves(func_hier),
                "code": doc_code,
            }
            # ── Write RTL to disk ──
            output_dir = task.get("output_dir", "generated/alu") if isinstance(task, dict) else "generated/alu"
            rtl_dir = Path(output_dir) / "rtl"
            rtl_dir.mkdir(parents=True, exist_ok=True)
            rtl_path = rtl_dir / f"{module_name}.v"
            rtl_path.write_text(synth_rtl, encoding="utf-8")
            result["rtl_file"] = str(rtl_path)
            result["rtl_type"] = "synthesizable"

            elapsed = (dt.now() - start).total_seconds()
            fc = result.get("function_count", 0)
            rc = result.get("register_count", 0)
            score = min(5 * fc + 8 * rc, 90)
            return AgentResult(success=True, data={
                "output": doc_code, "design_arch": result, "score": score,
            }, execution_time=elapsed)
        except Exception as e:
            return AgentResult(success=False, error=str(e))


# ═══════════════════════════════════════════════════════════
# 模块名提取
# ═══════════════════════════════════════════════════════════
def _extract_module(spec: str) -> str:
    for kw in ['alu', 'uart', 'spi', 'i2c', 'usb', 'pcie', 'dma', 'ethernet', 'ahb', 'apb', 'axi']:
        if kw in spec.lower(): return kw
    return "module_top"


# ═══════════════════════════════════════════════════════════
# Function Hierarchy — 模块声明风格
# ═══════════════════════════════════════════════════════════
def _gen_function_hierarchy(name: str, spec: str) -> dict:
    """生成功能层级，每个节点是代码风格的模块声明"""
    N = name.upper()
    return {
        "name": f"{N}_TOP",
        "comment": f"// === {N} Top Module === //",
        "ports": [
            {"dir": "input",  "name": "clk",     "width": 1,  "desc": "System clock"},
            {"dir": "input",  "name": "rst_n",   "width": 1,  "desc": "Async reset, active low"},
            {"dir": "input",  "name": "rx",       "width": 1,  "desc": "Serial input"},
            {"dir": "output", "name": "tx",       "width": 1,  "desc": "Serial output"},
            {"dir": "input",  "name": "paddr",    "width": 8,  "desc": "APB address"},
            {"dir": "input",  "name": "pwdata",   "width": 8,  "desc": "APB write data"},
            {"dir": "output", "name": "prdata",   "width": 8,  "desc": "APB read data"},
            {"dir": "input",  "name": "pwrite",   "width": 1,  "desc": "APB write enable"},
            {"dir": "input",  "name": "psel",     "width": 1,  "desc": "APB select"},
            {"dir": "input",  "name": "penable",  "width": 1,  "desc": "APB enable"},
            {"dir": "output", "name": "intr",     "width": 1,  "desc": "Interrupt output"},
        ],
        "children": [
            {
                "name": f"{N}_TX_PATH",
                "comment": f"// === TX Data Path === //",
                "ports": [
                    {"dir": "input",  "name": "tx_data_i",   "width": 8, "desc": "TX parallel data in"},
                    {"dir": "input",  "name": "tx_start_i",  "width": 1, "desc": "Start TX"},
                    {"dir": "output", "name": "tx_busy_o",   "width": 1, "desc": "TX busy flag"},
                    {"dir": "output", "name": "tx_done_o",   "width": 1, "desc": "TX done pulse"},
                ],
                "children": [
                    {"name": "tx_fifo_16x8", "comment": "// TX FIFO: 16 entries x 8bit, wptr/rptr //",
                     "ports": [
                         {"dir": "input", "name": "wr_data_i", "width": 8, "desc": "Write data"},
                         {"dir": "input", "name": "wr_en_i",   "width": 1, "desc": "Write enable"},
                         {"dir": "input", "name": "rd_en_i",   "width": 1, "desc": "Read enable"},
                         {"dir": "output","name": "rd_data_o", "width": 8, "desc": "Read data"},
                         {"dir": "output","name": "full_o",    "width": 1, "desc": "FIFO full"},
                         {"dir": "output","name": "empty_o",   "width": 1, "desc": "FIFO empty"},
                     ], "children": []},
                    {"name": "tx_shift_reg", "comment": "// TX Shift Register: parallel→serial //",
                     "ports": [
                         {"dir": "input", "name": "load_data_i","width": 8,  "desc": "Parallel load data"},
                         {"dir": "input", "name": "load_i",     "width": 1,  "desc": "Load strobe"},
                         {"dir": "input", "name": "shift_en_i", "width": 1,  "desc": "Shift enable"},
                         {"dir": "output","name": "tx_o",       "width": 1,  "desc": "Serial out"},
                     ], "children": []},
                    {"name": "tx_fsm", "comment": "// TX FSM: IDLE→START→DATA→PARITY→STOP //",
                     "ports": [
                         {"dir": "input", "name": "start_i",       "width": 1, "desc": "Start TX"},
                         {"dir": "input", "name": "data_done_i",   "width": 1, "desc": "All bits shifted"},
                         {"dir": "input", "name": "parity_en_i",   "width": 1, "desc": "Parity enabled"},
                         {"dir": "output","name": "load_o",        "width": 1, "desc": "Load shift reg"},
                         {"dir": "output","name": "shift_en_o",    "width": 1, "desc": "Shift enable"},
                         {"dir": "output","name": "tx_done_o",     "width": 1, "desc": "TX complete"},
                     ], "children": []},
                ]
            },
            {
                "name": f"{N}_RX_PATH",
                "comment": f"// === RX Data Path === //",
                "ports": [
                    {"dir": "input",  "name": "rx_i",        "width": 1, "desc": "Serial input"},
                    {"dir": "output", "name": "rx_data_o",   "width": 8, "desc": "RX parallel data out"},
                    {"dir": "output", "name": "rx_ready_o",  "width": 1, "desc": "RX data ready"},
                    {"dir": "output", "name": "rx_err_o",    "width": 1, "desc": "RX error flag"},
                ],
                "children": [
                    {"name": "rx_sampler", "comment": "// RX Sampler: 16x oversampling, majority vote //",
                     "ports": [
                         {"dir": "input", "name": "rx_i",        "width": 1, "desc": "Serial in"},
                         {"dir": "input", "name": "sample_tick_i","width":1, "desc": "Sample tick (16x baud)"},
                         {"dir": "output","name": "bit_o",       "width": 1, "desc": "Sampled bit"},
                     ], "children": []},
                    {"name": "rx_shift_reg", "comment": "// RX Shift Register: serial→parallel //",
                     "ports": [
                         {"dir": "input", "name": "bit_i",       "width": 1, "desc": "Serial bit in"},
                         {"dir": "input", "name": "shift_en_i",  "width": 1, "desc": "Shift enable"},
                         {"dir": "output","name": "data_o",      "width": 8, "desc": "Parallel data out"},
                         {"dir": "output","name": "done_o",      "width": 1, "desc": "Byte complete"},
                     ], "children": []},
                    {"name": "rx_parity_check", "comment": "// RX Parity Check: NONE/ODD/EVEN //",
                     "ports": [
                         {"dir": "input", "name": "data_i",      "width": 8, "desc": "Data byte"},
                         {"dir": "input", "name": "parity_bit_i","width": 1, "desc": "Received parity bit"},
                         {"dir": "input", "name": "mode_i",      "width": 2, "desc": "00=None 01=Odd 10=Even"},
                         {"dir": "output","name": "err_o",       "width": 1, "desc": "Parity error"},
                     ], "children": []},
                ]
            },
            {
                "name": f"{N}_BAUD_GEN",
                "comment": f"// === Baud Rate Generator === //",
                "ports": [
                    {"dir": "input",  "name": "divisor_i",    "width": 16, "desc": "Baud divisor = PCLK/(baud*16)"},
                    {"dir": "output", "name": "tick_o",       "width": 1,  "desc": "16x baud tick"},
                ],
                "children": [
                    {"name": "baud_counter", "comment": "// Baud Counter: cnt=divisor → tick pulse //",
                     "ports": [
                         {"dir": "input","name":"divisor_i","width":16,"desc":"Division ratio"},
                         {"dir": "output","name":"tick_o","width":1,"desc":"16x baud rate tick"},
                     ], "children": []},
                ]
            },
            {
                "name": f"{N}_REG_FILE",
                "comment": f"// === APB Register File === //",
                "ports": [
                    {"dir": "input",  "name": "paddr_i",   "width": 8,  "desc": "APB address"},
                    {"dir": "input",  "name": "pwdata_i",  "width": 8,  "desc": "APB write data"},
                    {"dir": "output", "name": "prdata_o",  "width": 8,  "desc": "APB read data"},
                    {"dir": "input",  "name": "pwrite_i",  "width": 1,  "desc": "APB write"},
                    {"dir": "input",  "name": "psel_i",    "width": 1,  "desc": "APB select"},
                    {"dir": "input",  "name": "penable_i", "width": 1,  "desc": "APB enable"},
                    {"dir": "output", "name": "ctrl_o",    "width": 8,  "desc": "Control register out"},
                    {"dir": "output", "name": "baud_o",    "width": 16, "desc": "Baud divisor out"},
                    {"dir": "output", "name": "cfg_o",     "width": 8,  "desc": "Config register out"},
                    {"dir": "output", "name": "int_mask_o","width": 4,  "desc": "Interrupt mask out"},
                    {"dir": "input",  "name": "status_i",  "width": 8,  "desc": "Status register in"},
                    {"dir": "input",  "name": "rx_data_i", "width": 8,  "desc": "RX data in"},
                ],
                "children": []
            },
            {
                "name": f"{N}_INTR_CTRL",
                "comment": f"// === Interrupt Controller === //",
                "ports": [
                    {"dir": "input",  "name": "status_i",    "width": 8, "desc": "Status flags"},
                    {"dir": "input",  "name": "mask_i",      "width": 4, "desc": "Interrupt mask"},
                    {"dir": "output", "name": "intr_o",      "width": 1, "desc": "Interrupt output"},
                ],
                "children": []
            },
        ]
    }


# ═══════════════════════════════════════════════════════════
# 寄存器 Map — 带 bit field 定义
# ═══════════════════════════════════════════════════════════
def _gen_register_map(name: str, spec: str) -> list:
    N = name.upper()
    return [
        {"name": f"{N}_CTRL",     "offset":"0x00", "width":8, "access":"RW", "reset":"8'h00",
         "desc": "Control Register",
         "fields": [
             {"bits":"[0]",    "name":"TX_EN",     "access":"RW", "reset":"1'b0", "desc":"TX enable"},
             {"bits":"[1]",    "name":"RX_EN",     "access":"RW", "reset":"1'b0", "desc":"RX enable"},
             {"bits":"[2]",    "name":"PARITY_EN", "access":"RW", "reset":"1'b0", "desc":"Parity check enable"},
             {"bits":"[3]",    "name":"LOOPBACK",  "access":"RW", "reset":"1'b0", "desc":"Loopback mode"},
             {"bits":"[4]",    "name":"SLEEP_EN",  "access":"RW", "reset":"1'b0", "desc":"Sleep mode"},
             {"bits":"[7:5]",  "name":"RSVD",      "access":"RO", "reset":"3'b0",  "desc":"Reserved"},
         ]},
        {"name": f"{N}_STATUS",   "offset":"0x04", "width":8, "access":"RO", "reset":"8'h01",
         "desc": "Status Register (read-only, write-1-clear)",
         "fields": [
             {"bits":"[0]",    "name":"TX_BUSY",   "access":"RO", "reset":"1'b0", "desc":"TX is transmitting"},
             {"bits":"[1]",    "name":"TX_DONE",   "access":"W1C","reset":"1'b0", "desc":"TX completed, write 1 to clear"},
             {"bits":"[2]",    "name":"RX_RDY",    "access":"RO", "reset":"1'b0", "desc":"RX data ready in buffer"},
             {"bits":"[3]",    "name":"RX_ERR",    "access":"W1C","reset":"1'b0", "desc":"RX error (parity/frame), write 1 clear"},
             {"bits":"[4]",    "name":"FIFO_FULL", "access":"RO", "reset":"1'b0", "desc":"TX FIFO is full"},
             {"bits":"[5]",    "name":"FIFO_EMPTY","access":"RO", "reset":"1'b1", "desc":"TX FIFO is empty"},
             {"bits":"[7:6]",  "name":"RSVD",      "access":"RO", "reset":"2'b0", "desc":"Reserved"},
         ]},
        {"name": f"{N}_BAUD_DIV", "offset":"0x08", "width":16,"access":"RW", "reset":"16'd326",
         "desc": "Baud Rate Divisor = PCLK_freq / (baud_rate × 16)",
         "fields": [
             {"bits":"[15:0]", "name":"DIVISOR",   "access":"RW", "reset":"16'd326","desc":"divisor value, 326→9600@50MHz"},
         ]},
        {"name": f"{N}_TXDATA",   "offset":"0x0C", "width":8, "access":"WO", "reset":"8'h00",
         "desc": "TX Data Register (write-only, writing triggers TX)",
         "fields": [
             {"bits":"[7:0]",  "name":"TXDATA",    "access":"WO", "reset":"8'h00","desc":"TX data byte"},
         ]},
        {"name": f"{N}_RXDATA",   "offset":"0x10", "width":8, "access":"RO", "reset":"8'h00",
         "desc": "RX Data Register (read-only, reading clears RX_RDY)",
         "fields": [
             {"bits":"[7:0]",  "name":"RXDATA",    "access":"RO", "reset":"8'h00","desc":"Received data byte"},
         ]},
        {"name": f"{N}_CFG",      "offset":"0x14", "width":8, "access":"RW", "reset":"8'h0B",
         "desc": "Configuration Register",
         "fields": [
             {"bits":"[1:0]",  "name":"DATA_BITS",  "access":"RW","reset":"2'b11","desc":"00=5b, 01=6b, 10=7b, 11=8b"},
             {"bits":"[2]",    "name":"STOP_BITS",  "access":"RW","reset":"1'b0", "desc":"0=1 stop, 1=2 stop bits"},
             {"bits":"[4:3]",  "name":"PARITY_SEL", "access":"RW","reset":"2'b00","desc":"00=None, 01=Odd, 10=Even"},
             {"bits":"[7:5]",  "name":"RSVD",       "access":"RO","reset":"3'b0", "desc":"Reserved"},
         ]},
        {"name": f"{N}_INT_MASK", "offset":"0x18", "width":8, "access":"RW", "reset":"8'h00",
         "desc": "Interrupt Mask Register (1=enable interrupt)",
         "fields": [
             {"bits":"[0]",    "name":"MSK_TX_DONE","access":"RW","reset":"1'b0","desc":"TX done interrupt enable"},
             {"bits":"[1]",    "name":"MSK_RX_RDY", "access":"RW","reset":"1'b0","desc":"RX ready interrupt enable"},
             {"bits":"[2]",    "name":"MSK_RX_ERR", "access":"RW","reset":"1'b0","desc":"RX error interrupt enable"},
             {"bits":"[3]",    "name":"MSK_FIFO",   "access":"RW","reset":"1'b0","desc":"FIFO threshold interrupt enable"},
             {"bits":"[7:4]",  "name":"RSVD",       "access":"RO","reset":"4'b0","desc":"Reserved"},
         ]},
        {"name": f"{N}_VERSION",  "offset":"0x1C", "width":8, "access":"RO", "reset":"8'h01",
         "desc": "IP Version Register",
         "fields": [
             {"bits":"[3:0]",  "name":"MINOR_REV", "access":"RO","reset":"4'h1","desc":"Minor revision"},
             {"bits":"[7:4]",  "name":"MAJOR_REV", "access":"RO","reset":"4'h0","desc":"Major revision → v0.1"},
         ]},
    ]


# ═══════════════════════════════════════════════════════════
# RTL Hierarchy — 模块例化代码
# ═══════════════════════════════════════════════════════════
def _gen_rtl_hierarchy(name: str, func_hier: dict) -> dict:
    """生成 RTL 例化层次"""
    wires = [
        {"name":"tx_data","width":8},  {"name":"tx_start","width":1}, {"name":"tx_busy","width":1},
        {"name":"tx_done","width":1},  {"name":"rx_data","width":8},  {"name":"rx_ready","width":1},
        {"name":"rx_err","width":1},   {"name":"baud_tick","width":1},{"name":"ctrl_reg","width":8},
        {"name":"baud_div","width":16},{"name":"cfg_reg","width":8},  {"name":"int_mask","width":4},
        {"name":"status_reg","width":8},{"name":"intr_wire","width":1},
    ]

    # 递归生成例化代码
    def _inst_module(node, indent=0):
        lines = []
        mod_name = node["name"].lower()
        prefix = "    " * indent
        lines.append(f"{prefix}// {node.get('comment','')}")
        lines.append(f"{prefix}{node['name']} u_{mod_name} (")
        ports = node.get("ports", [])
        for i, p in enumerate(ports):
            wire_name = p["name"].replace("_i","").replace("_o","")
            comma = "," if i < len(ports)-1 else ""
            lines.append(f"{prefix}    .{p['name']:16s}( {wire_name:16s} ){comma}  // {p.get('desc','')}")
        lines.append(f"{prefix});")
        lines.append("")
        for child in node.get("children", []):
            lines.extend(_inst_module(child, indent+1))
        return lines

    inst_lines = _inst_module(func_hier)

    # 生成顶层模块框架
    top_code = [
        f"// ═══════════════════════════════════════════════════════════",
        f"// Module    : {name}_top",
        f"// Language  : SystemVerilog",
        f"// Author    : design_architect (auto-generated)",
        f"// ═══════════════════════════════════════════════════════════",
        f"",
        f"module {name}_top (",
        f"    input  logic        clk,",
        f"    input  logic        rst_n,",
        f"    input  logic        rx,",
        f"    output logic        tx,",
        f"    // APB interface",
        f"    input  logic [7:0]  paddr,",
        f"    input  logic [7:0]  pwdata,",
        f"    output logic [7:0]  prdata,",
        f"    input  logic        pwrite,",
        f"    input  logic        psel,",
        f"    input  logic        penable,",
        f"    output logic        intr",
        f");",
        f"",
        f"    // ── Internal Wires ──",
    ]
    for w in wires:
        width_str = f"[{w['width']-1}:0]" if w["width"] > 1 else ""
        top_code.append(f"    logic {width_str:6s} {w['name']};")

    top_code.append("")
    top_code.append("    // ── Module Instantiations ──")
    top_code.extend(inst_lines)
    top_code.append("")
    top_code.append("endmodule")

    return {
        "top": f"{name}_top",
        "language": "SystemVerilog",
        "code": "\n".join(top_code),
        "wires": wires,
    }


# ═══════════════════════════════════════════════════════════
# Signoff Checklist — 代码注释风格
# ═══════════════════════════════════════════════════════════
def _gen_signoff(name: str, func_hier: dict, registers: list) -> list:
    items = []
    # Function coverage
    def _walk(node):
        if not node.get("children"):
            items.append({"item": f"// TODO: verify {node['name']} — {node.get('comment','').replace('//','').strip()}",
                          "cat":"function","status":"pending"})
        for c in node.get("children", []): _walk(c)
    _walk(func_hier)
    # Register checks
    for r in registers:
        items.append({"item": f"// TODO: verify reset value of {r['name']} @ {r['offset']} == {r['reset']}",
                      "cat":"register","status":"pending"})
        for f in r.get("fields",[]):
            items.append({"item": f"// TODO: verify field {r['name']}.{f['name']} {f['bits']} access={f['access']}",
                          "cat":"register_field","status":"pending"})
    # Cross checks
    items.extend([
        {"item":"// TODO: CDC check — PCLK → baud_clk synchronizer","cat":"cdc","status":"pending"},
        {"item":"// TODO: reset sequence — assert rst_n ≥ 100ns, de-assert sync to clk","cat":"reset","status":"pending"},
        {"item":"// TODO: APB protocol — no wait states, pslverr on unmapped addr","cat":"interface","status":"pending"},
        {"item":"// TODO: clock gating — gate baud_clk when SLEEP_EN=1","cat":"power","status":"pending"},
        {"item":"// TODO: lint check — all outputs driven, no multi-driver","cat":"lint","status":"pending"},
        {"item":"// TODO: FORMAL: tx_fsm never deadlocks in DATA state","cat":"formal","status":"pending"},
    ])
    return items


# ═══════════════════════════════════════════════════════════
# 可综合 RTL 生成
# ═══════════════════════════════════════════════════════════
def _extract_leaf_ops(func_hier: dict) -> list:
    """Extract operation leaf nodes from function hierarchy."""
    ops = []
    def _walk(node):
        if isinstance(node, dict):
            children = node.get("children", [])
            if not children: ops.append(node)
            for c in children: _walk(c)
        elif isinstance(node, list):
            for item in node: _walk(item)
    _walk(func_hier)
    return ops


def _render_synth_rtl(name: str, func_hier: dict, registers: list) -> str:
    """Generate synthesizable Verilog RTL from design metadata."""
    ops = _extract_leaf_ops(func_hier)
    dw = 32
    OP_MAP = {"adder":"ADD","add":"ADD","sub":"SUB","sub_32":"SUB","mul":"MUL","multiplier":"MUL",
              "booth":"MUL","div":"DIV","restoring":"DIV","divu":"DIVU","and":"AND","or":"OR",
              "xor":"XOR","nor":"NOR","not":"NOT","inv":"NOT","shift":"SLL","sll":"SLL",
              "srl":"SRL","sra":"SRA","barrel":"SLL","slt":"SLT","sltu":"SLTU","compare":"SLT"}
    op_names = []
    for op_node in ops:
        raw = op_node.get("name","").lower()
        for k,v in OP_MAP.items():
            if k in raw and v not in op_names: op_names.append(v); break
    DEFAULT = ["ADD","SUB","MUL","DIV","DIVU","AND","OR","XOR","NOR","NOT","SLL","SRL","SRA","SLT","SLTU"]
    for o in DEFAULT:
        if o not in op_names: op_names.append(o)
    # Deduplicate preserving order
    seen = set(); uniq = []
    for o in op_names:
        if o not in seen: seen.add(o); uniq.append(o)
    op_names = uniq
    ow = max(4, (len(op_names)-1).bit_length())

    lines = [
        f"// Synthesizable RTL — auto-generated by design_architect",
        f"module {name} #(parameter DATA_WIDTH={dw}, OP_WIDTH={ow})(",
        f"  input  wire clk, rst_n,",
        f"  input  wire [DATA_WIDTH-1:0] a, b,",
        f"  input  wire [OP_WIDTH-1:0] op,",
        f"  input  wire valid_in,",
        f"  output reg  ready_out,",
        f"  output reg  [DATA_WIDTH-1:0] result,",
        f"  output reg  [3:0] flags,",
        f"  output reg  valid_out",
        f");",
    ]
    for i, opn in enumerate(op_names[:16]):
        lines.append(f"  localparam {opn:5s} = {ow}'h{i:X};")
    lines.append("")
    lines.extend([
        f"  reg [DATA_WIDTH-1:0] r_comb;",
        f"  reg [3:0] f_comb;",
        f"  always @(*) begin",
        f"    r_comb = 0; f_comb = 0;",
        f"    case (op)",
    ])
    BODIES = {"ADD":"{f_comb[2], r_comb} = a + b;",
              "SUB":"begin {f_comb[2], r_comb} = a - b; f_comb[2] = ~f_comb[2]; end",
              "MUL":"r_comb = a * b;",
              "DIV":"r_comb = (b != 0) ? $signed(a) / $signed(b) : 0;",
              "DIVU":"r_comb = (b != 0) ? a / b : 0;",
              "AND":"r_comb = a & b;", "OR":"r_comb = a | b;", "XOR":"r_comb = a ^ b;",
              "NOR":"r_comb = ~(a | b);", "NOT":"r_comb = ~a;",
              "SLL":"r_comb = a << b[4:0];", "SRL":"r_comb = a >> b[4:0];",
              "SRA":"r_comb = $signed(a) >>> b[4:0];",
              "SLT":"r_comb = ($signed(a) < $signed(b)) ? 1 : 0;",
              "SLTU":"r_comb = (a < b) ? 1 : 0;"}
    for opn in op_names[:16]:
        body = BODIES.get(opn, "r_comb = 0;")
        lines.append(f"      {opn:5s}: {body}")
    lines.append(f"      default: r_comb = 0;")
    lines.append(f"    endcase")
    lines.extend([
        f"    f_comb[3] = r_comb[DATA_WIDTH-1];",
        f"    f_comb[1] = (r_comb == 0);",
        f"    if (op == ADD) f_comb[0] = (a[DATA_WIDTH-1]==b[DATA_WIDTH-1])&&(r_comb[DATA_WIDTH-1]!=a[DATA_WIDTH-1]);",
        f"    else if (op == SUB) f_comb[0] = (a[DATA_WIDTH-1]!=b[DATA_WIDTH-1])&&(r_comb[DATA_WIDTH-1]!=a[DATA_WIDTH-1]);",
        f"    else f_comb[0] = 0;",
        f"  end",
        f"  always @(posedge clk or negedge rst_n) begin",
        f"    if (!rst_n) begin result <= 0; flags <= 0; valid_out <= 0; ready_out <= 0; end",
        f"    else begin result <= r_comb; flags <= f_comb; valid_out <= valid_in; ready_out <= 1; end",
        f"  end",
        f"endmodule",
    ])
    return "\n".join(lines)
# ═══════════════════════════════════════════════════════════
# 渲染为完整代码文本
# ═══════════════════════════════════════════════════════════
def _render_code(name: str, func_hier: dict, registers: list, rtl_hier: dict, signoff: list) -> str:
    lines = []
    N = name.upper()
    lines.append(f"// ═══════════════════════════════════════════════")
    lines.append(f"// Design Architecture: {N}")
    lines.append(f"// Generated by design_architect agent")
    lines.append(f"// ═══════════════════════════════════════════════")
    lines.append("")

    # ── Function Hierarchy ──
    lines.append("// ═══════════ FUNCTION HIERARCHY ═══════════")
    lines.append("")
    def _walk(node, indent=0):
        pref = "    " * indent
        lines.append(f"{pref}{node.get('comment','')}")
        ports = node.get("ports",[])
        if ports:
            lines.append(f"{pref}module {node['name']} (")
            for p in ports:
                dir_map = {"input":"input ","output":"output","inout":"inout "}
                d = dir_map.get(p["dir"],"")
                w = f"[{p['width']-1}:0] " if p["width"]>1 else "       "
                lines.append(f"{pref}    {d} logic {w} {p['name']:16s}, // {p.get('desc','')}")
            # Remove last comma
            last = lines[-1]
            if last.rstrip().endswith(","):
                lines[-1] = last.rstrip()[:-1] + " "
            lines.append(f"{pref});")
        lines.append("")
        for c in node.get("children",[]): _walk(c, indent+1)
    _walk(func_hier)

    # ── Register Map ──
    lines.append("// ═══════════ REGISTER MAP ═══════════")
    lines.append("")
    lines.append(f"// {'Name':22s} {'Offset':6s} {'Width':5s} {'Access':6s} {'Reset':10s}  Description")
    lines.append(f"// {'─'*22} {'─'*6} {'─'*5} {'─'*6} {'─'*10}  {'─'*40}")
    for r in registers:
        lines.append(f"// {r['name']:22s} {r['offset']:6s} {str(r['width'])+'b':5s} {r['access']:6s} {r['reset']:10s}  {r['desc']}")
        for f in r.get("fields",[]):
            lines.append(f"//    {f['bits']:8s} {f['name']:20s} {f['access']:6s} {f['reset']:10s}  {f['desc']}")
    lines.append("")

    # ── RTL Hierarchy ──
    lines.append("// ═══════════ RTL HIERARCHY ═══════════")
    lines.append("")
    lines.append(rtl_hier.get("code",""))

    # ── Signoff ──
    lines.append("")
    lines.append("// ═══════════ SIGNOFF CHECKLIST ═══════════")
    for s in signoff:
        status = "✓ DONE" if s["status"]=="done" else "○ TODO"
        lines.append(f"{s['item']:70s}  // [{s['cat']}] {status}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# ALU 专用生成器
# ═══════════════════════════════════════════════════════════

def _gen_alu_function_hierarchy() -> dict:
    """ALU function hierarchy — 代码风格模块声明"""
    return {
        "name": "ALU_TOP",
        "comment": "// === ALU Top Module: 16 ops, 32bit, N/Z/C/V flags === //",
        "ports": [
            {"dir":"input", "name":"clk","width":1,"desc":"System clock"},
            {"dir":"input", "name":"rst_n","width":1,"desc":"Async reset, active low"},
            {"dir":"input", "name":"a_i","width":32,"desc":"Operand A"},
            {"dir":"input", "name":"b_i","width":32,"desc":"Operand B"},
            {"dir":"input", "name":"alu_op_i","width":4,"desc":"Operation select [3:0]"},
            {"dir":"output","name":"result_o","width":32,"desc":"Result"},
            {"dir":"output","name":"flags_o","width":4,"desc":"{N,Z,C,V}"},
        ],
        "children": [
            {"name":"ALU_ARITH","comment":"// Arithmetic Unit: ADD/SUB/MUL/DIV/DIVU //",
             "ports":[
                 {"dir":"input","name":"a_i","width":32,"desc":"Operand A"},
                 {"dir":"input","name":"b_i","width":32,"desc":"Operand B"},
                 {"dir":"input","name":"op_i","width":3,"desc":"000=ADD 001=SUB 010=MUL 011=DIV 100=DIVU"},
                 {"dir":"output","name":"result_o","width":32,"desc":"Arithmetic result"},
                 {"dir":"output","name":"flags_o","width":4,"desc":"{N,Z,C,V}"},
             ],
             "children":[
                 {"name":"adder_32b","comment":"// 32bit Carry-Lookahead Adder //",
                  "ports":[
                      {"dir":"input","name":"a_i","width":32,"desc":""},
                      {"dir":"input","name":"b_i","width":32,"desc":""},
                      {"dir":"input","name":"cin_i","width":1,"desc":"Carry in"},
                      {"dir":"output","name":"sum_o","width":32,"desc":"Sum"},
                      {"dir":"output","name":"cout_o","width":1,"desc":"Carry out"},
                  ],"children":[]},
                 {"name":"sub_32b","comment":"// 32bit Subtractor = ADD(~B+1) //",
                  "ports":[
                      {"dir":"input","name":"a_i","width":32,"desc":""},
                      {"dir":"input","name":"b_i","width":32,"desc":""},
                      {"dir":"output","name":"diff_o","width":32,"desc":"Difference"},
                      {"dir":"output","name":"borrow_o","width":1,"desc":"Borrow"},
                  ],"children":[]},
                 {"name":"booth_mul","comment":"// Booth-2 Multiplier: Radix-4 + Wallace Tree //",
                  "ports":[
                      {"dir":"input","name":"a_i","width":32,"desc":"Multiplicand"},
                      {"dir":"input","name":"b_i","width":32,"desc":"Multiplier"},
                      {"dir":"output","name":"prod_o","width":64,"desc":"Product"},
                  ],"children":[]},
                 {"name":"restoring_div","comment":"// Restoring Divider: 32b/32b → quotient + remainder //",
                  "ports":[
                      {"dir":"input","name":"dividend_i","width":32,"desc":""},
                      {"dir":"input","name":"divisor_i","width":32,"desc":""},
                      {"dir":"output","name":"quotient_o","width":32,"desc":""},
                      {"dir":"output","name":"remainder_o","width":32,"desc":""},
                      {"dir":"output","name":"div_zero_o","width":1,"desc":"Divide by zero"},
                  ],"children":[]},
             ]},
            {"name":"ALU_LOGIC","comment":"// Logic Unit: AND/OR/XOR/NOR/NOT //",
             "ports":[
                 {"dir":"input","name":"a_i","width":32,"desc":"Operand A"},
                 {"dir":"input","name":"b_i","width":32,"desc":"Operand B"},
                 {"dir":"input","name":"op_i","width":3,"desc":"000=AND 001=OR 010=XOR 011=NOR 100=NOT"},
                 {"dir":"output","name":"result_o","width":32,"desc":"Logic result"},
             ],
             "children":[
                 {"name":"and32","comment":"// 32bit bitwise AND //","ports":[],"children":[]},
                 {"name":"or32","comment":"// 32bit bitwise OR //","ports":[],"children":[]},
                 {"name":"xor32","comment":"// 32bit bitwise XOR //","ports":[],"children":[]},
             ]},
            {"name":"ALU_SHIFT","comment":"// Shift Unit: SLL/SRL/SRA (barrel shifter) //",
             "ports":[
                 {"dir":"input","name":"data_i","width":32,"desc":"Data input"},
                 {"dir":"input","name":"shamt_i","width":5,"desc":"Shift amount [4:0]"},
                 {"dir":"input","name":"op_i","width":2,"desc":"00=SLL 01=SRL 10=SRA"},
                 {"dir":"output","name":"result_o","width":32,"desc":"Shifted result"},
             ],
             "children":[
                 {"name":"barrel_shifter","comment":"// 32bit Barrel Shifter: single-cycle any-shift //",
                  "ports":[
                      {"dir":"input","name":"data_i","width":32,"desc":""},
                      {"dir":"input","name":"shamt_i","width":5,"desc":""},
                      {"dir":"input","name":"left_i","width":1,"desc":"1=left 0=right"},
                      {"dir":"input","name":"arith_i","width":1,"desc":"1=arithmetic 0=logic"},
                      {"dir":"output","name":"result_o","width":32,"desc":""},
                  ],"children":[]},
             ]},
            {"name":"ALU_FLAGS_GEN","comment":"// Flags Generator: N/Z/C/V from result + overflow detect //",
             "ports":[
                 {"dir":"input","name":"result_i","width":32,"desc":"ALU result"},
                 {"dir":"input","name":"a_sign_i","width":1,"desc":"A[31]"},
                 {"dir":"input","name":"b_sign_i","width":1,"desc":"B[31]"},
                 {"dir":"input","name":"carry_i","width":1,"desc":"Carry from adder"},
                 {"dir":"input","name":"is_logic_i","width":1,"desc":"1=logic op (C=0,V=0)"},
                 {"dir":"output","name":"flags_o","width":4,"desc":"{N,Z,C,V}"},
             ],
             "children":[
                 {"name":"neg_detect","comment":"// N flag = result[31] //","ports":[],"children":[]},
                 {"name":"zero_detect","comment":"// Z flag = (result==0) //","ports":[],"children":[]},
                 {"name":"overflow_detect","comment":"// V = a[31]==b[31] && result[31]!=a[31] //","ports":[],"children":[]},
             ]},
            {"name":"ALU_APB_REG","comment":"// APB Register File: 8 registers (CTRL/OPA/OPB/RESULT/FLAGS/STATUS/CFG/VERSION) //",
             "ports":[
                 {"dir":"input","name":"paddr_i","width":8,"desc":"APB address"},
                 {"dir":"input","name":"pwdata_i","width":32,"desc":"APB write data"},
                 {"dir":"output","name":"prdata_o","width":32,"desc":"APB read data"},
                 {"dir":"input","name":"pwrite_i","width":1,"desc":"APB write"},
                 {"dir":"input","name":"psel_i","width":1,"desc":"APB select"},
                 {"dir":"input","name":"penable_i","width":1,"desc":"APB enable"},
                 {"dir":"output","name":"alu_op_o","width":4,"desc":"ALU operation"},
                 {"dir":"output","name":"start_o","width":1,"desc":"Start pulse"},
                 {"dir":"input","name":"result_i","width":32,"desc":"Result from ALU"},
                 {"dir":"input","name":"flags_i","width":4,"desc":"Flags from ALU"},
             ],"children":[]},
        ]}


def _gen_alu_register_map() -> list:
    """ALU 寄存器 map"""
    return [
        {"name":"ALU_CTRL","offset":"0x00","width":8,"access":"RW","reset":"8'h00","desc":"Control Register",
         "fields":[
             {"bits":"[3:0]","name":"ALU_OP","access":"RW","reset":"4'h0","desc":"0=ADD 1=SUB 2=MUL 3=DIV 4=DIVU 5=AND 6=OR 7=XOR 8=NOR 9=NOT 10=SLL 11=SRL 12=SRA"},
             {"bits":"[4]","name":"START","access":"RW","reset":"1'b0","desc":"Start (multi-cycle mode)"},
             {"bits":"[5]","name":"IRQ_EN","access":"RW","reset":"1'b0","desc":"Interrupt enable"},
             {"bits":"[7:6]","name":"RSVD","access":"RO","reset":"2'b0","desc":"Reserved"},
         ]},
        {"name":"ALU_OPA","offset":"0x04","width":32,"access":"RW","reset":"32'h0","desc":"Operand A"},
        {"name":"ALU_OPB","offset":"0x08","width":32,"access":"RW","reset":"32'h0","desc":"Operand B"},
        {"name":"ALU_RESULT","offset":"0x0C","width":32,"access":"RO","reset":"32'h0","desc":"Result Register",
         "fields":[
             {"bits":"[31:0]","name":"RESULT","access":"RO","reset":"32'h0","desc":"ALU operation result"},
         ]},
        {"name":"ALU_FLAGS","offset":"0x10","width":4,"access":"RO","reset":"4'h0","desc":"Flags Register",
         "fields":[
             {"bits":"[0]","name":"C","access":"RO","reset":"1'b0","desc":"Carry/Borrow"},
             {"bits":"[1]","name":"V","access":"RO","reset":"1'b0","desc":"Overflow"},
             {"bits":"[2]","name":"Z","access":"RO","reset":"1'b0","desc":"Zero"},
             {"bits":"[3]","name":"N","access":"RO","reset":"1'b0","desc":"Negative"},
         ]},
        {"name":"ALU_STATUS","offset":"0x14","width":8,"access":"RO","reset":"8'h01","desc":"Status Register",
         "fields":[
             {"bits":"[0]","name":"READY","access":"RO","reset":"1'b1","desc":"Ready (0=busy)"},
             {"bits":"[1]","name":"DIV_ZERO","access":"RO","reset":"1'b0","desc":"Divide by zero error"},
             {"bits":"[2]","name":"OVERFLOW","access":"RO","reset":"1'b0","desc":"Arithmetic overflow"},
         ]},
        {"name":"ALU_CFG","offset":"0x18","width":8,"access":"RW","reset":"8'h00","desc":"Configuration Register",
         "fields":[
             {"bits":"[0]","name":"SINGLE_CYCLE","access":"RW","reset":"1'b0","desc":"1=single-cycle 0=multi-cycle"},
             {"bits":"[1]","name":"PIPELINE_EN","access":"RW","reset":"1'b0","desc":"Pipeline enable"},
             {"bits":"[3:2]","name":"MUL_MODE","access":"RW","reset":"2'b00","desc":"00=single-cycle 01=Booth 10=Wallace"},
         ]},
        {"name":"ALU_VERSION","offset":"0x1C","width":8,"access":"RO","reset":"8'h01","desc":"IP Version v0.1",
         "fields":[
             {"bits":"[3:0]","name":"MINOR","access":"RO","reset":"4'h1","desc":"Minor revision"},
             {"bits":"[7:4]","name":"MAJOR","access":"RO","reset":"4'h0","desc":"Major revision"},
         ]},
    ]


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════
def _count_leaves(node: dict) -> int:
    if not node.get("children"): return 1
    return sum(_count_leaves(c) for c in node["children"])
