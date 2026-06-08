"""
调试工具集
"""
from langchain.tools import tool
import json

@tool("analyze_simulation_log")
def analyze_simulation_log(log_path: str = "") -> str:
    """分析仿真日志，提取错误和警告"""
    analysis = {
        "log_file": log_path or "sim.log",
        "errors": [
            {"time": "450ns", "severity": "UVM_ERROR", "message": "Scoreboard mismatch: expected 0xABCD1234, got 0xABCE1234"}
        ],
        "warnings": [
            {"time": "120ns", "severity": "UVM_WARNING", "message": "Sequence timeout after 1000 cycles"}
        ],
        "simulation_stats": {"total_time": "1.2us", "transactions": 450}
    }
    return json.dumps(analysis, indent=2)

@tool("analyze_waveform")
def analyze_waveform(waveform_path: str = "", signals: str = "") -> str:
    """分析VCD/FSDB波形文件"""
    analysis = {
        "waveform_file": waveform_path or "waves.vcd",
        "anomalies": [
            {"time": "450ns", "signal": "data[31:0]", "expected": "0xABCD1234", "actual": "0xABCE1234"}
        ],
        "timing_violations": [
            {"time": "455ns", "path": "req->ack", "actual_delay": "6.2ns", "max_allowed": "5.0ns"}
        ]
    }
    return json.dumps(analysis, indent=2)

@tool("trace_error_source")
def trace_error_source(error_description: str = "") -> str:
    """追踪错误源头"""
    trace = {
        "error": error_description or "Scoreboard mismatch",
        "root_cause": {"category": "Design Bug", "confidence": "85%"},
        "fix_priority": "High"
    }
    return json.dumps(trace, indent=2)

@tool("generate_fix_suggestion")
def generate_fix_suggestion(root_cause: str = "") -> str:
    """生成修复建议"""
    suggestions = {
        "root_cause": root_cause,
        "suggested_fixes": [
            {"type": "Design Fix", "priority": "High", "description": "Initialize register in reset"}
        ]
    }
    return json.dumps(suggestions, indent=2)

class DebugTools:
    def get_tools(self):
        return [analyze_simulation_log, analyze_waveform, trace_error_source, generate_fix_suggestion]
