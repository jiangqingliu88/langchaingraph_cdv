"""
规格与测试规划Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.spec_tools import SpecAnalysisTools
import structlog
import json

logger = structlog.get_logger()

import re


def _build_spec_plan(spec_text: str) -> dict:
    """Build a specification plan dynamically from the input spec text."""
    text = spec_text.lower() if spec_text else ""
    text_orig = spec_text or ""

    # ── Detect design type ──
    is_alu = any(kw in text for kw in ["alu", "arithmetic", "mul", "div",
                "shift", "flags", "sll", "srl", "sra", "apb", "alu_op"])
    is_uart = any(kw in text for kw in ["uart", "baud", "tx", "rx",
                "serial", "parity", "stop bit", "axi"])

    if is_alu:
        return _build_alu_plan(spec_text)
    if is_uart:
        return _build_uart_plan()
    # Generic fallback
    return _build_generic_plan(spec_text)


def _build_alu_plan(spec_text: str) -> dict:
    """Build ALU-specific plan."""
    # Extract data width
    dw_match = re.search(r"(\d+)\s*bit", spec_text)
    data_width = int(dw_match.group(1)) if dw_match else 32
    op_width = 4  # 16 operations

    # Extract operations
    ops = []
    for line in spec_text.split("\n"):
        m = re.match(r"\|\s*4'b(\d+)\s*\|\s*(\w+)", line)
        if m:
            ops.append({"code": int(m.group(1), 2), "name": m.group(2)})

    # Build features from spec
    features = []
    bt_reqs = re.findall(r"\*\*(REQ_ALU_BT_\d+)\*\*:\s*(.+)", spec_text)
    for req_id, desc in bt_reqs:
        features.append({"name": req_id.lower(), "description": desc.strip(),
                         "priority": "P0"})

    # Build registers from APB spec
    registers = []
    for line in spec_text.split("\n"):
        m = re.match(r"\|\s*(\w+)\s*\|\s*(0x[0-9A-Fa-f]+)\s*\|\s*(\d+)\s*\|\s*(\w+)\s*\|.*\|\s*(.+)\s*\|", line)
        if m:
            registers.append({
                "name": m.group(1), "offset": m.group(2),
                "width": int(m.group(3)), "access": m.group(4),
                "description": m.group(5).strip()
            })

    # Build test points
    test_points = []
    current_category = None
    for line in spec_text.split("\n"):
        cat_match = re.match(r"##\s*(?:测试点|Test Points)", line)
        if cat_match:
            continue
        for cat_name in ["basic_function", "configuration", "error", "corner", "stress", "boundary"]:
            if cat_name in line.lower():
                current_category = cat_name
                test_points.append({"category": cat_name, "tests": []})
    if not test_points:
        test_points = [
            {'category': 'basic_function', 'tests': [
                {'name': 'test_alu_add', 'description': 'ADD basic test'},
                {'name': 'test_alu_sub', 'description': 'SUB basic test'},
                {'name': 'test_alu_mul', 'description': 'MUL basic test'},
                {'name': 'test_alu_div', 'description': 'DIV basic test'},
                {'name': 'test_alu_logic', 'description': 'AND/OR/XOR/NOT tests'},
                {'name': 'test_alu_shift', 'description': 'SLL/SRL/SRA tests'},
                {'name': 'test_alu_compare', 'description': 'SLT/SLTU tests'},
            ]},
            {'category': 'configuration', 'tests': [
                {'name': 'test_alu_single_cycle', 'description': 'Single-cycle mode'},
                {'name': 'test_alu_multi_cycle', 'description': 'Multi-cycle mode'},
                {'name': 'test_alu_pipeline', 'description': 'Pipeline mode'},
            ]},
            {'category': 'error_injection', 'tests': [
                {'name': 'test_alu_div_zero', 'description': 'Divide by zero'},
                {'name': 'test_alu_overflow', 'description': 'Overflow detection'},
            ]},
            {'category': 'corner_cases', 'tests': [
                {'name': 'test_alu_max_values', 'description': 'Max value operations'},
                {'name': 'test_alu_flag_corners', 'description': 'N/Z/C/V flag corners'},
            ]},
            {'category': 'stress', 'tests': [
                {'name': 'test_alu_random_1k', 'description': 'Random 1000 ops'},
                {'name': 'test_alu_back_to_back', 'description': 'Back-to-back ops'},
            ]},
        ]

    return {
        "design_name": "ALU",
        "version": "1.0",
        "overview": f"32-bit ALU supporting 16 arithmetic/logic/shift operations with APB interface",
        "features": features or [
            {"name": "alu_arithmetic", "description": "ADD/SUB/MUL/DIV/DIVU", "priority": "P0"},
            {"name": "alu_logic",      "description": "AND/OR/XOR/NOR/NOT", "priority": "P0"},
            {"name": "alu_shift",      "description": "SLL/SRL/SRA", "priority": "P0"},
            {"name": "alu_compare",    "description": "SLT/SLTU", "priority": "P1"},
            {"name": "alu_flags",      "description": "N/Z/C/V flag generation", "priority": "P0"},
        ],
        "interfaces": [
            {"name": "ALU_in", "type": "parallel", "data_width": data_width,
             "signals": {"output": ["a", "b", "op", "valid"], "input": ["ready", "result"]},
             "clock": "clk", "protocol_checks": ["valid/ready handshake"]},
            {"name": "ALU_out", "type": "parallel", "data_width": data_width,
             "signals": {"input": ["result", "flags", "valid"], "output": ["ready"]},
             "clock": "clk"},
        ],
        "clock_domains": [{"name": "clk", "frequency": "100MHz", "domain": "ALU", "signals": ["all"]}],
        "registers": registers or [
            {"name": "ALU_CTRL", "offset": "0x00", "width": 8, "access": "RW",
             "fields": [{"bit": 0, "name": "ALU_OP[3:0]", "description": "Operation select"},
                        {"bit": 4, "name": "START", "description": "Start operation"}]},
            {"name": "ALU_OPA", "offset": "0x04", "width": 32, "access": "RW"},
            {"name": "ALU_OPB", "offset": "0x08", "width": 32, "access": "RW"},
            {"name": "ALU_RESULT", "offset": "0x0C", "width": 32, "access": "RO"},
            {"name": "ALU_FLAGS", "offset": "0x10", "width": 4, "access": "RO"},
        ],
        "test_points": test_points,
        "risks": [
            {"item": "Overflow detection", "level": "MEDIUM",
             "mitigation": "Constrained random + boundary test"},
            {"item": "Divide by zero", "level": "HIGH",
             "mitigation": "Error injection + flag check"},
        ],
        "coverage_goals": {
            "code_coverage": {"line": 95, "branch": 95, "toggle": 90, "fsm": 100},
            "functional_coverage": {"operations": 100, "flags": 100, "data_patterns": 100},
            "assertion_coverage": 100
        },
        "verification_methodology": "UVM",
        "estimated_effort": "1-2 weeks",
        "dependencies": ["UVM 1.2", "QuestaSim"],
        "verification_architecture": {
            "env_name": "alu",
            "agents": [
                {
                    "name": "ALU_in", "type": "UVM_ACTIVE",
                    "interface": "alu_in_interface", "clock": "clk", "reset": "rst",
                    "ports": [
                        {"name": "clk", "dir": "input", "width": 1},
                        {"name": "rst", "dir": "input", "width": 1},
                        {"name": "a", "dir": "output", "width": data_width},
                        {"name": "b", "dir": "output", "width": data_width},
                        {"name": "op", "dir": "output", "width": op_width},
                        {"name": "valid", "dir": "output", "width": 1},
                        {"name": "ready", "dir": "input", "width": 1},
                        {"name": "result", "dir": "input", "width": 2*data_width},
                    ],
                    "transaction_vars": [
                        {"name": "a", "type": f"bit [{data_width-1}:0]", "iscompare": "True", "isrand": "True"},
                        {"name": "b", "type": f"bit [{data_width-1}:0]", "iscompare": "True", "isrand": "True"},
                        {"name": "op", "type": f"bit [{op_width-1}:0]", "iscompare": "True", "isrand": "True"},
                        {"name": "result", "type": f"bit [{2*data_width-1}:0]", "iscompare": "True", "isrand": "False"},
                    ],
                },
                {
                    "name": "ALU_out", "type": "UVM_PASSIVE",
                    "interface": "alu_out_interface", "clock": "clk", "reset": "rst",
                    "ports": [
                        {"name": "clk", "dir": "input", "width": 1},
                        {"name": "rst", "dir": "input", "width": 1},
                        {"name": "result", "dir": "input", "width": data_width},
                        {"name": "flags", "dir": "input", "width": 4},
                        {"name": "valid", "dir": "input", "width": 1},
                        {"name": "ready", "dir": "output", "width": 1},
                    ],
                    "transaction_vars": [
                        {"name": "result", "type": f"bit [{data_width-1}:0]", "iscompare": "True", "isrand": "False"},
                        {"name": "flags", "type": "bit [3:0]", "iscompare": "True", "isrand": "False"},
                        {"name": "valid", "type": "bit", "iscompare": "False", "isrand": "False"},
                    ],
                }
            ],
            "scoreboards": [
                {"name": "alu_scoreboard", "type": "uvm_in_order_class_comparator",
                 "transaction_type": "ALU_out_transaction", "enabled": True},
            ],
            "tlm_connections": [
                {"from": "ALU_in_agent_h.mon.item_collected_port", "to": "alu_scoreboard_h.analysis_export"},
            ],
            "virtual_sequencer": {"enabled": True, "name": "alu_env_virtual_sequencer"},
            "clock_reset": {"interface": "clk_rst_if", "clocks": ["clk"], "resets": ["rst"]},
            "config_vars": [
                {"name": "has_scoreboard", "type": "bit", "value": 1},
                {"name": "has_functional_coverage", "type": "bit", "value": 1},
            ],
            "constraint_policies": _derive_constraint_policies(spec_text, features, registers),
        },
    }


def _derive_constraint_policies(spec_text: str, features: list, registers: list) -> list:
    """Derive constraint policies from spec analysis — replaces static YAML."""
    policies = []
    text = spec_text.lower()

    # Arithmetic precision
    if any(kw in text for kw in ["add", "sub", "mul", "div", "arithmetic"]):
        policies.append({"name": "arithmetic_precision", "description": "Arithmetic operation precision",
                         "priority": 1, "enabled": True, "applies_to": ["cfg", "input"]})

    # Data width / overflow
    if any(kw in text for kw in ["32bit", "32-bit", "overflow", "flag"]):
        policies.append({"name": "overflow_detection", "description": "Overflow and carry flag validation",
                         "priority": 2, "enabled": True, "applies_to": ["input", "output"]})

    # Multi-mode (single cycle / multi cycle / pipeline)
    if any(kw in text for kw in ["single", "multi", "cycle", "pipeline", "mode"]):
        policies.append({"name": "operation_mode", "description": "Single/multi-cycle mode switching",
                         "priority": 3, "enabled": True, "applies_to": ["cfg", "input"]})

    # Shift ops
    if any(kw in text for kw in ["shift", "sll", "srl", "sra", "barrel"]):
        policies.append({"name": "shift_boundary", "description": "Shift amount boundary (0-31)",
                         "priority": 4, "enabled": True, "applies_to": ["input"]})

    # Boundary stress
    policies.append({"name": "boundary_stress", "description": "Max/min operand boundaries",
                     "priority": 5, "enabled": True, "applies_to": ["input", "output"]})

    # Flag consistency
    if any(kw in text for kw in ["flag", "n", "z", "c", "v", "negative", "zero", "carry"]):
        policies.append({"name": "flag_consistency", "description": "N/Z/C/V flag cross-check",
                         "priority": 6, "enabled": True, "applies_to": ["output"]})

    # Register access
    if registers:
        policies.append({"name": "register_access", "description": "APB register read/write consistency",
                         "priority": 7, "enabled": True, "applies_to": ["cfg"]})

    if not policies:
        policies = [
            {"name": "basic_stimulus", "description": "Basic input stimulus", "priority": 1,
             "enabled": True, "applies_to": ["cfg", "input"]},
            {"name": "error_injection", "description": "Error injection", "priority": 2,
             "enabled": True, "applies_to": ["input", "output"]},
        ]
    return policies


def _build_uart_plan() -> dict:
    """Fallback UART plan (kept for compatibility)."""
    return {
        "design_name": "UART Controller", "version": "2.1",
        "overview": "全双工异步通信控制器",
        "features": [
            {"name": "uart_tx", "description": "UART 发送通路", "priority": "P0"},
            {"name": "uart_rx", "description": "UART 接收通路", "priority": "P0"},
        ],
        "interfaces": [
            {"name": "UART", "type": "serial",
             "signals": {"output": ["tx"], "input": ["rx"]}, "clock": "baud_clk"},
        ],
        "clock_domains": [{"name": "pclk", "frequency": "50MHz", "domain": "APB"}],
        "registers": [
            {"name": "CTRL", "offset": "0x00", "width": 8, "access": "RW"},
            {"name": "STATUS", "offset": "0x04", "width": 8, "access": "RO"},
        ],
        "test_points": [
            {"category": "basic_function", "tests": [
                {"name": "test_tx", "description": "发送测试"},
                {"name": "test_rx", "description": "接收测试"},
            ]},
        ],
        "risks": [{"item": "CDC", "level": "HIGH", "mitigation": "2-stage sync"}],
        "coverage_goals": {
            "code_coverage": {"line": 95, "branch": 95},
            "functional_coverage": {"baud_rates": 100},
            "assertion_coverage": 100
        },
        "verification_methodology": "UVM",
        "estimated_effort": "2-3 weeks",
        "dependencies": ["UVM 1.2"],
        "verification_architecture": {
            "agents": [
                {"name": "UART_in", "type": "UVM_ACTIVE", "interface": "uart_if",
                 "clock": "pclk", "reset": "presetn",
                 "ports": [{"name": "pclk","dir":"input","width":1},{"name":"presetn","dir":"input","width":1},
                          {"name":"tx","dir":"output","width":1},{"name":"rx","dir":"input","width":1}],
                 "transaction_vars": [{"name":"data","type":"bit [7:0]","iscompare":"True","isrand":"True"}]},
            ],
            "scoreboards": [{"name": "uart_scb", "type": "uvm_in_order_class_comparator",
                            "transaction_type": "UART_transaction", "enabled": True}],
            "virtual_sequencer": {"enabled": False},
            "clock_reset": {"interface": "clk_rst_if", "clocks": ["pclk"], "resets": ["presetn"]},
            "config_vars": [],
        },
    }


def _build_generic_plan(spec_text: str) -> dict:
    """Generic fallback plan."""
    return {
        "design_name": "DUT", "version": "1.0",
        "overview": "Auto-detected design",
        "features": [], "interfaces": [], "clock_domains": [],
        "registers": [], "test_points": [], "risks": [],
        "coverage_goals": {"code_coverage": {"line": 90}},
        "verification_methodology": "UVM",
        "verification_architecture": {"agents": [], "scoreboards": [],
            "virtual_sequencer": {"enabled": False}, "clock_reset": {},
            "config_vars": []},
    }


@register_agent("spec_and_test_planner")
class SpecAndTestPlanner(BaseAgent):
    """规格分析与测试规划Agent"""
    
    # 设置任务类型，LLM工厂会自动选择最优模型
    task_type = "spec_analysis"
    consumes = []
    produces = "spec"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="spec_and_test_planner",
            display_name="规格与测试规划师",
            description="分析设计规格文档，生成验证测试计划",
            config=config or {}
        )
        self.spec_tools = SpecAnalysisTools()
        self.min_score = 60   # must have features/interfaces/registers
        self.max_retries = 2

    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证规格分析专家。分析输入的设计文档，严格只输出 JSON（不要 Markdown 代码块，不要解释文字，不要添加样本数据）。
JSON 格式：{{"design_name":"...","version":"...","overview":"...","features":[{{"name":"...","description":"...","priority":"P0"}}],"interfaces":[{{"name":"...","type":"...","data_width":32,"clock":"...","signals":{{}}}}],"registers":[{{"name":"...","offset":"0x00","width":8,"access":"RW","description":"..."}}],"test_points":[{{"category":"basic_function","tests":[{{"name":"test_...","description":"..."}}]}}],"coverage_goals":{{"code_coverage":{{"line":95}}}},"verification_architecture":{{"agents":[{{"name":"...","type":"UVM_ACTIVE","interface":"...","clock":"clk","reset":"rst","ports":[],"transaction_vars":[]}}],"scoreboards":[],"virtual_sequencer":{{"enabled":false}},"clock_reset":{{}},"config_vars":[]}}}}"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.spec_tools.get_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """直接执行"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    # ── bypass: 分析规格，输出结构化验证计划 ──

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            return await super().execute_task(task)

        from datetime import datetime
        spec_text = task.get("input", str(task))
        start_time = datetime.now()

        plan = _build_spec_plan(spec_text)
        result_text = json.dumps(plan, indent=2, ensure_ascii=False)

        execution_time = (datetime.now() - start_time).total_seconds()
        self.metrics["tasks_completed"] += 1
        self.metrics["total_time"] += execution_time

        from src.middleware.debug_logger import debug_logger
        debug_logger.log_agent_call(
            self.role, self.display_name, str(task)[:500],
            "bypass spec analysis", result_text[:500],
            [], 0, execution_time, True
        )

        # Score: completeness of spec analysis
        n_features = len(plan.get("features", []))
        n_interfaces = len(plan.get("interfaces", []))
        n_test_pts = sum(len(tp.get("tests", [])) for tp in plan.get("test_points", []))
        n_regs = len(plan.get("registers", []))
        score = min(10 * n_features + 5 * n_interfaces + 3 * n_test_pts + 5 * n_regs, 95)

        return AgentResult(success=True, data={
            "output": result_text, "spec": plan, "score": score,
        }, execution_time=execution_time)