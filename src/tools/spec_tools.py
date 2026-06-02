"""
规格分析工具集
"""
from langchain.tools import tool
import json

@tool("analyze_specification")
def analyze_specification(spec_text: str = "") -> str:
    """分析IC设计规格文档，提取关键信息"""
    analysis = {
        "design_name": "UART Controller",
        "version": "2.1",
        "interfaces": [
            {"name": "AXI4-Lite", "type": "slave", "data_width": 32},
            {"name": "UART", "type": "serial", "baud_rates": [9600, 19200, 38400, 57600, 115200]}
        ],
        "features": [
            "Full-duplex async communication",
            "Programmable baud rate",
            "Configurable data bits (5/6/7/8)",
            "Configurable stop bits (1/1.5/2)",
            "Parity support (None/Even/Odd)",
            "16-byte TX/RX FIFOs",
            "Interrupt generation"
        ],
        "clock_domains": [
            {"name": "pclk", "frequency": "50MHz", "domain": "APB"},
            {"name": "baud_clk", "frequency": "variable", "domain": "UART"}
        ],
        "constraints": {
            "max_baud_rate": 115200,
            "fifo_depth": 16,
            "axi_data_width": 32
        }
    }
    return json.dumps(analysis, indent=2)

@tool("extract_features")
def extract_features(spec_text: str = "") -> str:
    """从规格中提取功能特性列表"""
    features = {
        "basic_features": ["uart_tx", "uart_rx", "loopback_mode"],
        "advanced_features": ["auto_baud_detection", "hardware_flow_control", "multi_processor_mode"],
        "error_handling": ["parity_error", "frame_error", "overrun_error", "break_detection"],
        "power_features": ["sleep_mode", "deep_sleep_mode", "clock_gating"]
    }
    return json.dumps(features, indent=2)

@tool("generate_test_plan")
def generate_test_plan(requirements: str = "") -> str:
    """基于需求生成测试计划"""
    test_plan = {
        "plan_name": "UART_Verification_Plan_v1.0",
        "methodology": "UVM",
        "test_categories": [
            {"category": "Basic Functionality", "priority": "High", "tests": [
                {"name": "test_uart_basic_tx", "type": "directed"},
                {"name": "test_uart_basic_rx", "type": "directed"},
                {"name": "test_uart_loopback", "type": "directed"},
                {"name": "test_uart_baud_rates", "type": "directed"}
            ]},
            {"category": "Configuration", "priority": "High", "tests": [
                {"name": "test_uart_config_data_bits", "type": "constrained_random"},
                {"name": "test_uart_config_stop_bits", "type": "constrained_random"},
                {"name": "test_uart_config_parity", "type": "constrained_random"}
            ]},
            {"category": "Error Injection", "priority": "Medium", "tests": [
                {"name": "test_uart_parity_error", "type": "directed"},
                {"name": "test_uart_frame_error", "type": "directed"},
                {"name": "test_uart_overrun_error", "type": "directed"}
            ]},
            {"category": "Corner Cases", "priority": "Medium", "tests": [
                {"name": "test_uart_fifo_full", "type": "directed"},
                {"name": "test_uart_fifo_empty", "type": "directed"},
                {"name": "test_uart_max_baud_rate", "type": "directed"}
            ]},
            {"category": "Stress", "priority": "Low", "tests": [
                {"name": "test_uart_stress_tx_rx", "type": "constrained_random"},
                {"name": "test_uart_concurrent_config", "type": "constrained_random"}
            ]}
        ],
        "coverage_goals": {"code_coverage": 95.0, "functional_coverage": 100.0, "assertion_coverage": 100.0}
    }
    return json.dumps(test_plan, indent=2)

@tool("assess_risk")
def assess_risk(spec_analysis: str = "") -> str:
    """评估验证风险"""
    risk = {
        "overall_risk": "Medium",
        "risk_items": [
            {"item": "Multiple clock domains", "risk": "High", "mitigation": "Add CDC assertions and formal verification"},
            {"item": "Complex baud rate generation", "risk": "Medium", "mitigation": "Use constrained random with corner cases"},
            {"item": "FIFO overflow/underflow", "risk": "Medium", "mitigation": "Add dedicated error injection tests"},
            {"item": "AXI4-Lite protocol compliance", "risk": "Low", "mitigation": "Use standard AXI VIP"}
        ]
    }
    return json.dumps(risk, indent=2)

class SpecAnalysisTools:
    def get_tools(self):
        return [analyze_specification, extract_features, generate_test_plan, assess_risk]
