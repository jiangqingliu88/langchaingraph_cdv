"""
RTL 工程师 Agent —— 按 design_architect 输出的模块层次生成可综合 SystemVerilog RTL

工作流程:
  1. parse_module_tree: 从 design_arch.function_hier 解析模块树
  2. generate_submodule: 逐个生成子模块 .sv 代码
  3. generate_top_module: 集成所有子模块为顶层模块
  4. write_rtl_files: 将 RTL 代码写入磁盘

LLM 根据 spec（接口信号、功能需求）和 design_arch（模块层次、寄存器表）
生成符合可综合风格的 SystemVerilog 代码。
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

# ── 模块级工具函数 ──

@tool("parse_module_tree")
def parse_module_tree(design_arch_json: str) -> str:
    """Parse design_architect function_hier tree into flat submodule list with port inference.
    Input: design_arch JSON string with function_hier (nested tree) and registers (list).
    Returns JSON with module_name, submodules list (each with name, parent, ports, registers)."""
    try:
        data = json.loads(design_arch_json) if isinstance(design_arch_json, str) else design_arch_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON input"}, ensure_ascii=False)

    registers = data.get("registers", [])
    module_name = data.get("module_name", "dut")
    function_hier = data.get("function_hier", {})

    def walk_tree(node, parent="", depth=0):
        """递归遍历 function_hier 树，收集所有子模块"""
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

    # 为每个子模块推断接口信号
    for sm in submodules:
        sm["ports"] = _infer_ports(sm["name"], data)
        sm["registers"] = [r for r in registers if sm["name"].upper() in r.get("name", "").upper() or
                           sm["name"].lower() in r.get("desc", "").lower()]

    return json.dumps({"module_name": module_name, "submodules": submodules,
                       "register_count": len(registers)}, ensure_ascii=False, indent=2)


def _infer_ports(sub_name: str, data: dict) -> list:
    """根据子模块名和 spec 数据推断端口信号"""
    ports = [
        {"name": "clk", "dir": "input", "width": 1, "desc": "系统时钟"},
        {"name": "rst_n", "dir": "input", "width": 1, "desc": "异步复位低有效"},
    ]
    name_upper = sub_name.upper()
    if "REG" in name_upper or "APB" in name_upper:
        ports.extend([
            {"name": "paddr", "dir": "input", "width": 8, "desc": "APB 地址"},
            {"name": "pwdata", "dir": "input", "width": 8, "desc": "APB 写数据"},
            {"name": "prdata", "dir": "output", "width": 8, "desc": "APB 读数据"},
            {"name": "pwrite", "dir": "input", "width": 1, "desc": "APB 写使能"},
            {"name": "psel", "dir": "input", "width": 1, "desc": "APB 片选"},
            {"name": "penable", "dir": "input", "width": 1, "desc": "APB 使能"},
        ])
    if "TX" in name_upper:
        ports.extend([
            {"name": "tx_data", "dir": "input", "width": 8, "desc": "发送数据"},
            {"name": "tx_start", "dir": "input", "width": 1, "desc": "启动发送"},
            {"name": "tx_busy", "dir": "output", "width": 1, "desc": "发送忙"},
            {"name": "tx", "dir": "output", "width": 1, "desc": "串行发送"},
        ])
    if "RX" in name_upper:
        ports.extend([
            {"name": "rx", "dir": "input", "width": 1, "desc": "串行接收"},
            {"name": "rx_data", "dir": "output", "width": 8, "desc": "接收数据"},
            {"name": "rx_valid", "dir": "output", "width": 1, "desc": "接收有效"},
        ])
    if "FIFO" in name_upper:
        ports.extend([
            {"name": "wr_data", "dir": "input", "width": 8, "desc": "写数据"},
            {"name": "wr_en", "dir": "input", "width": 1, "desc": "写使能"},
            {"name": "rd_data", "dir": "output", "width": 8, "desc": "读数据"},
            {"name": "rd_en", "dir": "input", "width": 1, "desc": "读使能"},
            {"name": "full", "dir": "output", "width": 1, "desc": "FIFO 满"},
            {"name": "empty", "dir": "output", "width": 1, "desc": "FIFO 空"},
        ])
    if "INT" in name_upper:
        ports.extend([
            {"name": "irq_src", "dir": "input", "width": 4, "desc": "中断源"},
            {"name": "irq", "dir": "output", "width": 1, "desc": "中断输出"},
            {"name": "irq_en", "dir": "input", "width": 4, "desc": "中断使能"},
        ])
    return ports


@tool("generate_submodule")
def generate_submodule(module_spec_json: str) -> str:
    """Generate synthesizable SystemVerilog RTL for a single submodule.
    Input JSON keys: name, ports (list of name/dir/width/desc dicts), registers (list), description.
    Returns JSON with module_name and verilog_code."""
    try:
        spec = json.loads(module_spec_json) if isinstance(module_spec_json, str) else module_spec_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)

    name = spec.get("name", "submodule")
    ports = spec.get("ports", [])
    registers = spec.get("registers", [])
    desc = spec.get("description", "")

    # 生成模块声明
    lines = [f"// Module: {name}"]
    if desc:
        lines.append(f"// Description: {desc}")
    lines.append(f"// Auto-generated by WriteRTL Agent")
    lines.append("")

    # 端口列表
    port_list = []
    for p in ports:
        pw = p.get("width", 1)
        pd = p.get("dir", "input")
        pn = p.get("name", "?")
        if pw > 1:
            port_list.append(f"    {pd} logic [{pw-1}:0] {pn}")
        else:
            port_list.append(f"    {pd} logic        {pn}")
    lines.append(f"module {name} (")
    lines.append(",\n".join(port_list))
    lines.append(");")
    lines.append("")

    # 寄存器定义
    if registers:
        lines.append("    // ── 寄存器 ──")
        for r in registers:
            rname = r.get("name", "reg")
            rw = r.get("width", 8)
            rreset = r.get("reset", "0")
            if rw > 1:
                lines.append(f"    logic [{rw-1}:0] {rname.lower()}_reg = {rw}'d{rreset};")
            else:
                lines.append(f"    logic            {rname.lower()}_reg = 1'b{rreset};")
        lines.append("")

    # APB 读写逻辑
    has_apb = any("paddr" in p.get("name", "") for p in ports)
    if has_apb and registers:
        lines.append("    // ── APB 读写逻辑 ──")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        for r in registers:
            lines.append(f"            {r['name'].lower()}_reg <= '0;")
        lines.append("        end else if (psel && penable && pwrite) begin")
        lines.append("            case (paddr)")
        for i, r in enumerate(registers):
            offset = r.get("offset", f"0x{i:02x}")
            lines.append(f"                8'h{offset.replace('0x','')}: {r['name'].lower()}_reg <= pwdata;")
        lines.append("                default: ;")
        lines.append("            endcase")
        lines.append("        end")
        lines.append("    end")
        lines.append("")
        # 读逻辑
        lines.append("    // ── APB 读逻辑 ──")
        lines.append("    always_comb begin")
        lines.append("        prdata = 8'd0;")
        lines.append("        case (paddr)")
        for i, r in enumerate(registers):
            offset = r.get("offset", f"0x{i:02x}")
            lines.append(f"            8'h{offset.replace('0x','')}: prdata = {r['name'].lower()}_reg;")
        lines.append("            default: prdata = 8'd0;")
        lines.append("        endcase")
        lines.append("    end")
        lines.append("")

    # TX 逻辑
    if any("tx" in p.get("name", "").lower() for p in ports) and "TX" in name.upper():
        lines.append("    // ── UART 发送状态机 ──")
        lines.append("    logic [3:0] tx_bit_cnt;")
        lines.append("    logic [9:0] tx_shift_reg;  // start + 8 data + stop")
        lines.append("    typedef enum logic [1:0] {TX_IDLE, TX_START, TX_DATA, TX_STOP} tx_state_t;")
        lines.append("    tx_state_t tx_state;")
        lines.append("")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        lines.append("            tx_state <= TX_IDLE;")
        lines.append("            tx <= 1'b1;")
        lines.append("            tx_busy <= 1'b0;")
        lines.append("            tx_bit_cnt <= '0;")
        lines.append("        end else begin")
        lines.append("            case (tx_state)")
        lines.append("                TX_IDLE: if (tx_start) begin")
        lines.append("                    tx_shift_reg <= {1'b0, tx_data, 1'b1};")
        lines.append("                    tx_busy <= 1'b1;")
        lines.append("                    tx_state <= TX_DATA;")
        lines.append("                    tx_bit_cnt <= '0;")
        lines.append("                    tx <= 1'b0;  // start bit")
        lines.append("                end")
        lines.append("                TX_DATA: begin")
        lines.append("                    tx <= tx_shift_reg[0];")
        lines.append("                    tx_shift_reg <= tx_shift_reg >> 1;")
        lines.append("                    if (tx_bit_cnt == 4'd9)")
        lines.append("                        tx_state <= TX_STOP;")
        lines.append("                    else")
        lines.append("                        tx_bit_cnt <= tx_bit_cnt + 1;")
        lines.append("                end")
        lines.append("                TX_STOP: begin")
        lines.append("                    tx <= 1'b1;")
        lines.append("                    tx_busy <= 1'b0;")
        lines.append("                    tx_state <= TX_IDLE;")
        lines.append("                end")
        lines.append("            endcase")
        lines.append("        end")
        lines.append("    end")
        lines.append("")

    # RX 逻辑
    if any("rx" in p.get("name", "").lower() for p in ports) and "RX" in name.upper():
        lines.append("    // ── UART 接收采样 ──")
        lines.append("    logic [3:0] rx_bit_cnt;")
        lines.append("    logic [7:0] rx_shift_reg;")
        lines.append("    typedef enum logic [1:0] {RX_IDLE, RX_START, RX_DATA, RX_STOP} rx_state_t;")
        lines.append("    rx_state_t rx_state;")
        lines.append("")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        lines.append("            rx_state <= RX_IDLE;")
        lines.append("            rx_data <= 8'd0;")
        lines.append("            rx_valid <= 1'b0;")
        lines.append("            rx_bit_cnt <= '0;")
        lines.append("        end else begin")
        lines.append("            rx_valid <= 1'b0;")
        lines.append("            case (rx_state)")
        lines.append("                RX_IDLE: if (!rx) begin  // start bit detected")
        lines.append("                    rx_state <= RX_DATA;")
        lines.append("                    rx_bit_cnt <= '0;")
        lines.append("                end")
        lines.append("                RX_DATA: begin")
        lines.append("                    rx_shift_reg <= {rx, rx_shift_reg[7:1]};")
        lines.append("                    if (rx_bit_cnt == 4'd7) begin")
        lines.append("                        rx_data <= {rx, rx_shift_reg[7:1]};")
        lines.append("                        rx_state <= RX_STOP;")
        lines.append("                    end else")
        lines.append("                        rx_bit_cnt <= rx_bit_cnt + 1;")
        lines.append("                end")
        lines.append("                RX_STOP: begin")
        lines.append("                    rx_valid <= 1'b1;")
        lines.append("                    rx_state <= RX_IDLE;")
        lines.append("                end")
        lines.append("            endcase")
        lines.append("        end")
        lines.append("    end")
        lines.append("")

    # FIFO 逻辑
    if "FIFO" in name.upper():
        lines.append("    // ── FIFO 存储 ──")
        depth = spec.get("fifo_depth", 16)
        lines.append(f"    parameter int DEPTH = {depth};")
        lines.append(f"    logic [7:0] fifo_mem [0:DEPTH-1];")
        lines.append("    logic [$clog2(DEPTH)-1:0] wr_ptr, rd_ptr;")
        lines.append("    logic [$clog2(DEPTH):0] count;")
        lines.append("")
        lines.append("    always_ff @(posedge clk or negedge rst_n) begin")
        lines.append("        if (!rst_n) begin")
        lines.append("            wr_ptr <= '0; rd_ptr <= '0; count <= '0;")
        lines.append("        end else begin")
        lines.append("            if (wr_en && !full) begin")
        lines.append("                fifo_mem[wr_ptr] <= wr_data;")
        lines.append("                wr_ptr <= wr_ptr + 1;")
        lines.append("                count <= count + 1;")
        lines.append("            end")
        lines.append("            if (rd_en && !empty) begin")
        lines.append("                rd_data <= fifo_mem[rd_ptr];")
        lines.append("                rd_ptr <= rd_ptr + 1;")
        lines.append("                count <= count - 1;")
        lines.append("            end")
        lines.append("        end")
        lines.append("    end")
        lines.append("    assign full  = (count == DEPTH);")
        lines.append("    assign empty = (count == 0);")
        lines.append("")

    lines.append("endmodule")
    return json.dumps({"module_name": name, "verilog_code": "\n".join(lines)}, ensure_ascii=False)


@tool("generate_top_module")
def generate_top_module(integration_spec_json: str) -> str:
    """Generate top-level module that instantiates all submodules.
    Input JSON keys: module_name, submodules (list of name/ports dicts), top_ports (list).
    Returns JSON with module_name and verilog_code."""
    try:
        spec = json.loads(integration_spec_json) if isinstance(integration_spec_json, str) else integration_spec_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)

    module_name = spec.get("module_name", "dut_top")
    submodules = spec.get("submodules", [])
    top_ports = spec.get("top_ports", [
        {"name": "clk", "dir": "input", "width": 1},
        {"name": "rst_n", "dir": "input", "width": 1},
        {"name": "paddr", "dir": "input", "width": 8},
        {"name": "pwdata", "dir": "input", "width": 8},
        {"name": "prdata", "dir": "output", "width": 8},
        {"name": "pwrite", "dir": "input", "width": 1},
        {"name": "psel", "dir": "input", "width": 1},
        {"name": "penable", "dir": "input", "width": 1},
        {"name": "tx", "dir": "output", "width": 1},
        {"name": "rx", "dir": "input", "width": 1},
        {"name": "irq", "dir": "output", "width": 1},
    ])

    lines = [f"// Top Module: {module_name}"]
    lines.append(f"// Auto-generated by WriteRTL Agent — integrates {len(submodules)} submodules")
    lines.append("")

    # 端口声明
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

    # 内部连线
    lines.append("    // ── 内部互联信号 ──")
    for sm in submodules:
        name = sm.get("name", "sub")
        for p in sm.get("ports", []):
            if p.get("name", "") in ("clk", "rst_n"):
                continue
            pw = p.get("width", 1)
            lines.append(f"    logic {f'[{pw-1}:0]' if pw > 1 else '       '} {name}_{p['name']};")
    lines.append("")

    # 子模块例化
    lines.append("    // ── 子模块例化 ──")
    for sm in submodules:
        name = sm.get("name", "sub")
        lines.append(f"    {name} u_{name} (")
        conns = []
        for p in sm.get("ports", []):
            pn = p.get("name", "?")
            if pn == "clk":
                conns.append(f"        .{pn}(clk)")
            elif pn == "rst_n":
                conns.append(f"        .{pn}(rst_n)")
            elif pn in ("tx", "rx", "irq", "paddr", "pwdata", "prdata", "pwrite", "psel", "penable"):
                conns.append(f"        .{pn}({pn})")
            else:
                conns.append(f"        .{pn}({name}_{pn})")
        lines.append(",\n".join(conns))
        lines.append("    );")
        lines.append("")

    lines.append("endmodule")
    return json.dumps({"module_name": module_name, "verilog_code": "\n".join(lines)}, ensure_ascii=False)


@tool("write_rtl_files")
def write_rtl_files(files_json: str) -> str:
    """Write generated RTL SystemVerilog files to disk.
    Input JSON keys: output_dir (string path), files (list of path/content dicts).
    Returns JSON with written file paths list and count."""
    try:
        data = json.loads(files_json) if isinstance(files_json, str) else files_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON input"}, ensure_ascii=False)

    output_dir = Path(data.get("output_dir", "output"))
    files = data.get("files", [])
    rtl_dir = output_dir / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for f in files:
        path = f.get("path", "")
        content = f.get("content", f.get("verilog_code", ""))
        if not content:
            continue
        target = rtl_dir / Path(path).name if path else rtl_dir / "unnamed.sv"
        target.write_text(content, encoding="utf-8", errors="replace")
        written.append(str(target))

    return json.dumps({"written": written, "count": len(written), "output_dir": str(rtl_dir)},
                      ensure_ascii=False)


# ── Agent 类 ──

@register_agent("write_rtl")
class WriteRTL(BaseAgent):
    """RTL 工程师 —— 根据设计架构生成可综合 SystemVerilog RTL"""

    task_type = "code_generation"
    consumes = ["spec", "design_arch"]
    produces = "rtl"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="write_rtl",
            display_name="RTL 工程师",
            description="根据设计架构的模块层次和寄存器表，分模块生成可综合的 SystemVerilog RTL 代码并集成",
            config=config or {}
        )
        self.min_score = 50
        self.max_retries = 2

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """Role: RTL Design Engineer — SystemVerilog Code Generator

GOAL: From a design architecture spec (function hierarchy + register map + interface signals),
generate synthesizable SystemVerilog RTL code organized as submodules integrated into a top module.

AVAILABLE TOOLS (call in order):
1. parse_module_tree(design_arch_json) — parse the function hierarchy tree → flat submodule list with port inference
2. generate_submodule(module_spec_json) — generate SV code for ONE submodule (name, ports, registers, description).
3. generate_top_module(integration_spec_json) — generate the top-level module that instantiates all submodules
4. write_rtl_files(files_json) — write generated .sv files to disk under output_dir/rtl/

WORKFLOW:
1. First, examine the input which contains `spec` (interface signals, functional requirements) and `design_arch` (function_hier tree, register map).
2. CALL parse_module_tree with the design_arch JSON to get the submodule list.
3. For EACH submodule, CALL generate_submodule with the module's ports, registers, and description. Generate real synthesizable RTL.
4. CALL generate_top_module with all submodules and top-level ports to create the integration module.
5. CALL write_rtl_files to save everything to disk.

RTL CODING STANDARDS:
- Use always_ff for sequential logic, always_comb for combinational logic
- Include proper reset logic (asynchronous reset, active low rst_n)
- Use SystemVerilog types: logic, typedef enum for state machines
- Generate real state machines for TX, RX, FIFO control
- Include parameter definitions for configurable widths
- Add comments for each functional block
- Use non-blocking assignments (<=) in always_ff
- Name the top module to match the module_name from design_arch

OUTPUT: After writing files, output a JSON summary with generated modules, file paths, and line counts.
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
        """通过 LLM Agent 执行 RTL 生成"""
        if not self._executor:
            return {"output": "Agent未初始化", "score": 0}
        try:
            result = await self._executor.ainvoke({"input": input_text})
            return {"output": result.get("output", str(result))}
        except Exception as e:
            return {"output": f"Agent error: {str(e)[:200]}", "score": 0}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从 LLM 输出和 intermediate_steps 提取 RTL 代码，确定性写入磁盘"""
        output = result.get("output", "")
        steps = result.get("intermediate_steps", [])
        module_name = "dut"
        sv_files = {}  # {module_name: verilog_code}

        # 从 intermediate_steps 收集所有生成的 SV 代码
        for step in steps:
            if isinstance(step, tuple) and len(step) >= 2:
                action, obs = step[0], step[1]
                tool_name = getattr(action, 'tool', '') if hasattr(action, 'tool') else str(action)
                try:
                    obs_data = json.loads(str(obs)) if isinstance(obs, str) else obs
                except (json.JSONDecodeError, TypeError):
                    continue
                if "module_name" in obs_data:
                    mn = obs_data["module_name"]
                    if mn != module_name and module_name == "dut":
                        module_name = mn
                    code = obs_data.get("verilog_code", obs_data.get("content", ""))
                    if code and mn not in sv_files:
                        sv_files[mn] = code

        # 回退：从 LLM 输出提取代码块
        if not sv_files:
            code_blocks = re.findall(r'```(?:systemverilog|verilog|sv)?\s*\n(.*?)```', output, re.DOTALL)
            for i, block in enumerate(code_blocks):
                m = re.search(r'module\s+(\w+)', block)
                mn = m.group(1) if m else f"submodule_{i}"
                sv_files[mn] = block.strip()

        # 确定性写入磁盘 + 自动修复 LLM 常见语法错误
        rtl_dir = Path(self._last_output_dir) / "rtl" if hasattr(self, '_last_output_dir') else Path("output") / "rtl"
        rtl_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for mn, code in sv_files.items():
            # Fix 1: C-style hex 0x00 → 8'h00 in case items
            code = re.sub(r'\b0x([0-9a-fA-F]+)\b', r"8'h\1", code)
            # Fix 2: $clog2({depth}) → $clog2(DEPTH) (LLM concatenation bug)
            code = re.sub(r'\$clog2\(\s*\{\s*(\w+)\s*\}\s*\)', r'$clog2(\1)', code)
            code = re.sub(r'\$clog2\(\s*\{\s*(\w+)\s*\}\s*\)', r'$clog2(\1)', code)
            # Fix 3: parameter on same line as logic declaration
            code = re.sub(r'(parameter\s+\w+\s*=\s*\d+;)\s*(\w+)', r'\1\n    \2', code)
            # Fix 4: APB_REG default case syntax
            code = code.replace("default: ;", "default: begin end")
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
        """保存 output_dir 供 post_process 使用"""
        self._last_output_dir = task.get("output_dir", "output")
        return await super().execute_task(task)
