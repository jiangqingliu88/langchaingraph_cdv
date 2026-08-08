"""
Fake LLM —— 确定性测试替身，不访问网络、不需要 API Key

用法:
    from src.core.fake_llm import FakeChatModel, set_test_mode
    set_test_mode()  # 全局启用测试模式
    # 或在 fixture 中:
    from src.core.llm_factory import LLMFactory
    LLMFactory._test_llm = FakeChatModel(task_type="code_generation")
"""

import json
from typing import Any, List, Optional, Sequence
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks import CallbackManagerForLLMRun


# ── 按 agent 产出的确定性响应 ──

_RESPONSES: dict[str, str] = {
    "spec_and_test_planner": json.dumps({
        "design_name": "dut",
        "features": [
            {"name": "basic_operation", "description": "基本功能", "category": "basic_function"},
            {"name": "configuration", "description": "配置功能", "category": "configuration"},
            {"name": "error_handling", "description": "错误处理", "category": "error_injection"},
        ],
        "interfaces": [
            {"name": "clk", "dir": "input", "width": 1, "desc": "时钟"},
            {"name": "rst_n", "dir": "input", "width": 1, "desc": "复位"},
            {"name": "data_in", "dir": "input", "width": 32, "desc": "输入数据"},
            {"name": "data_out", "dir": "output", "width": 32, "desc": "输出数据"},
            {"name": "valid_in", "dir": "input", "width": 1, "desc": "输入有效"},
            {"name": "ready_out", "dir": "output", "width": 1, "desc": "输出就绪"},
        ],
        "test_points": [
            {"category": "basic_function", "tests": [
                {"name": "test_basic_op", "description": "基本运算验证"},
                {"name": "test_data_path", "description": "数据通路验证"},
            ]},
            {"category": "configuration", "tests": [
                {"name": "test_config_mode", "description": "配置模式验证"},
            ]},
            {"category": "error_injection", "tests": [
                {"name": "test_overflow", "description": "溢出测试"},
            ]},
        ],
        "registers": [],
        "coverage_goals": {"line": 95, "toggle": 90, "branch": 85},
        "verification_architecture": {"methodology": "UVM", "agent_count": 2},
        "version": "1.0",
        "overview": "Test DUT specification",
        "score": 90,
    }, ensure_ascii=False),

    "design_architect": json.dumps({
        "module_name": "dut",
        "function_hier": {
            "top": "dut",
            "submodules": [{"name": "alu", "description": "运算单元"}],
        },
        "rtl_hier": {
            "files": ["dut_top.sv"],
            "modules": [{"name": "dut", "ports": ["clk", "rst_n", "data_in", "data_out"]}],
        },
        "signoff_checklist": [
            {"item": "代码规范检查", "status": "PASS"},
            {"item": "接口一致性检查", "status": "PASS"},
        ],
        "score": 58,
        "design_arch": {
            "module_name": "dut",
            "function_hier": {"top": "dut"},
            "rtl_hier": {"files": [], "modules": []},
            "signoff_checklist": [],
        },
    }, ensure_ascii=False),

    "model_agent": json.dumps({
        "module": "dut",
        "model_type": "cpp_ref",
        "analysis": {"operations": ["add", "sub"], "signals": ["data_in", "data_out"]},
        "ref_model": "class DutModel { ... };",
        "operations": ["add", "sub", "mul"],
        "model": {
            "model_type": "cpp_ref",
            "operations": ["add", "sub"],
        },
        "score": 70,
    }, ensure_ascii=False),

    "verification_architect": json.dumps({
        "status": "generated",
        "file_count": 38,
        "agents": ["dut_in", "dut_out"],
        "files": [],
        "quality": {
            "passed": True,
            "verdict": "READY",
            "scores": {"static": "25/25", "compile": "25/25", "loopback": "25/25", "total": "75/75"},
            "static_pass": True,
            "compile_pass": True,
            "loopback_pass": True,
        },
        "env_name": "dut_env",
        "agent_count": 2,
        "filelist": "output/inputs/filelists/filelist.f",
        "env": {
            "env_name": "dut_env",
            "output_dir": "output",
            "agent_count": 2,
            "agents": ["dut_in", "dut_out"],
            "filelist": "output/inputs/filelists/filelist.f",
            "files": [],
        },
        "score": 75,
    }, ensure_ascii=False),

    "test_engineer": json.dumps({
        "scenarios": [
            {"name": "basic_function_test", "description": "基本功能测试",
             "timeout": 600, "combinator_mode": "APPLY_SEQUENTIAL",
             "policies": ["precision_consistency", "compute_mode"],
             "priority": "P0", "repeat": 5, "source_tests": ["test_basic_op"]},
        ],
        "scenario_count": 3,
        "test_names": ["test_basic_op", "test_data_path", "test_config_mode"],
        "test_count": 3,
        "policies": ["precision_consistency", "compute_mode"],
        "yaml": "",
        "tests": {
            "test_names": ["test_basic_op", "test_data_path", "test_config_mode"],
            "test_count": 3,
            "scenario_count": 3,
            "test_cases": [
                {"name": "test_basic_op", "uvm_test": "dut_base_test", "top": "dut_env_tb_top", "category": "basic_function"},
                {"name": "test_data_path", "uvm_test": "dut_base_test", "top": "dut_env_tb_top", "category": "basic_function"},
                {"name": "test_config_mode", "uvm_test": "dut_base_test", "top": "dut_env_tb_top", "category": "configuration"},
            ],
        },
        "score": 75,
    }, ensure_ascii=False),

    "assertion_engineer": json.dumps({
        "assertions": ["assert property (@(posedge clk) disable iff(!rst_n) ...)"],
        "assertion_count": 5,
        "score": 85,
    }, ensure_ascii=False),

    "regression_manager": json.dumps({
        "compile": "PASS",
        "compile_status": "PASS",
        "passed": 5,
        "failed": 0,
        "total": 5,
        "pass_rate": "100%",
        "tests": [
            {"name": "test_basic_op", "status": "PASS", "time": "0.5s"},
            {"name": "test_data_path", "status": "PASS", "time": "0.3s"},
            {"name": "test_config_mode", "status": "PASS", "time": "0.8s"},
        ],
        "regression": {
            "compile": "PASS",
            "compile_status": "PASS",
            "passed": 5,
            "failed": 0,
            "total": 5,
            "pass_rate": "100%",
        },
        "reports": {"json": "output/report.json", "html": "output/report.html"},
        "score": 85,
    }, ensure_ascii=False),

    "coverage_manager": json.dumps({
        "coverage_data": {"line": 92.3, "branch": 85.0, "toggle": 78.5},
        "line_pct": 92.3,
        "branch_pct": 85.0,
        "toggle_pct": 78.5,
        "coverage_pct": 92.3,
        "gaps": [{"file": "dut_top.sv", "line": 42, "reason": "未覆盖分支"}],
        "suggestions": [{"type": "regression", "description": "补充定向测试"}],
        "coverage": {
            "line_pct": 92.3,
            "branch_pct": 85.0,
            "toggle_pct": 78.5,
            "coverage_pct": 92.3,
            "gaps": [],
            "suggestions": [],
        },
        "score": 80,
    }, ensure_ascii=False),

    "debug_engineer": json.dumps({
        "category": "none",
        "errors": [],
        "suggestion": "",
        "fix_agent": "",
        "scores": {"accuracy": 90, "completeness": 85},
        "debug": {
            "category": "none",
            "errors": [],
            "suggestion": "",
            "fix_agent": "",
        },
        "score": 90,
    }, ensure_ascii=False),

    "quality_assurance": json.dumps({
        "checks": {"syntax": "PASS", "style": "PASS", "completeness": "PASS"},
        "issues": [],
        "score": 90,
    }, ensure_ascii=False),

    "report_generator": json.dumps({
        "reports": {"json": "output/report.json", "html": "output/report.html"},
        "signoff": {"status": "APPROVED"},
        "summary": {"total_tests": 5, "passed": 5, "failed": 0, "pass_rate": "100%"},
        "verdict": "READY",
        "report": {
            "reports": {"json": "output/report.json", "html": "output/report.html"},
            "signoff": {"status": "APPROVED"},
            "summary": {"total_tests": 5, "passed": 5, "failed": 0, "pass_rate": "100%"},
            "verdict": "READY",
        },
        "score": 85,
    }, ensure_ascii=False),
}


class FakeChatModel(BaseChatModel):
    """确定性测试替身 —— 按 agent role 返回预设 JSON 响应。

    不访问网络，不需要 API Key，不消耗 token。
    输出是合法 JSON，触发 BaseAgent 的 auto-detect 评分逻辑。
    """

    role: str = "spec_and_test_planner"
    """绑定的 agent role，用于选择对应的预设响应。"""

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        response_text = _RESPONSES.get(self.role, '{"output": "fake response", "score": 75}')
        message = AIMessage(content=response_text)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    def invoke(
        self,
        input: Any,
        config: Optional[dict] = None,
        *,
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """兼容 LangChain 的 invoke 接口。"""
        if isinstance(input, str):
            response_text = _RESPONSES.get(self.role, '{"output": "fake response", "score": 75}')
            return AIMessage(content=response_text)
        elif isinstance(input, list):
            response_text = _RESPONSES.get(self.role, '{"output": "fake response", "score": 75}')
            return AIMessage(content=response_text)
        else:
            return AIMessage(content=_RESPONSES.get(self.role, '{"output": "fake", "score": 75}'))

    def bind_tools(self, tools: list, **kwargs) -> "FakeChatModel":
        """兼容 tool binding —— 返回自身。"""
        return self

    def with_structured_output(self, schema, **kwargs) -> "FakeChatModel":
        """兼容 structured output —— 返回自身。"""
        return self


# ── 测试模式管理 ──

_test_mode = False


def set_test_mode(enable: bool = True) -> None:
    """全局启用/关闭测试模式。

    启用后，LLMFactory._test_override 会注入 FakeChatModel。
    """
    global _test_mode
    _test_mode = enable


def is_test_mode() -> bool:
    return _test_mode
