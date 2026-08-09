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
    
    # ── schema: design_name 不能是占位符 ──
    _DESIGN_NAME_PLACEHOLDERS = {"dut", "dut_top", "dut_env", "top", "chip", "block", "design", "module", ""}

    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证规格分析专家。分析输入的设计文档，严格只输出 JSON（不要 Markdown 代码块，不要解释文字，不要添加样本数据）。

**重要约束 — design_name 必须从输入文档中提取真实的模块名称**：
- 从文档标题、模块声明、设计概述中找出设计的实际名称（如 UART、SPI、ALU、AHB_Bridge）
- **严禁**使用 "dut"、"DUT"、"dut_top"、"top"、"chip"、"block"、"design"、"module" 等占位符
- 如果文档中找不到明确的模块名，从 features/interfaces 的命名模式推断（如 UART TX → design_name: "UART"）

JSON 格式：{{"design_name":"<从文档提取的真实模块名>","version":"...","overview":"...","features":[{{"name":"...","description":"...","priority":"P0"}}],"interfaces":[{{"name":"...","type":"...","data_width":32,"clock":"...","signals":{{}}}}],"registers":[{{"name":"...","offset":"0x00","width":8,"access":"RW","description":"..."}}],"test_points":[{{"category":"basic_function","tests":[{{"name":"test_...","description":"..."}}]}}],"coverage_goals":{{"code_coverage":{{"line":95}}}},"verification_architecture":{{"agents":[{{"name":"...","type":"UVM_ACTIVE","interface":"...","clock":"clk","reset":"rst","ports":[],"transaction_vars":[]}}],"scoreboards":[],"virtual_sequencer":{{"enabled":false}},"clock_reset":{{}},"config_vars":[]}}}}"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.spec_tools.get_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """Fallback only — base class calls executor directly."""
        return {"output": "Agent未初始化", "score": 0}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured spec data from agent executor output."""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        import json as _json

        # Try the final LLM output first
        spec = _extract_json_from_llm(output_text)

        # If not found, try intermediate tool results
        if not spec:
            steps = result.get("intermediate_steps", []) if isinstance(result, dict) else []
            for action, tool_output in steps:
                try:
                    data = _json.loads(str(tool_output))
                    if "design_name" in data:
                        spec = data
                        break
                except Exception:
                    pass

        if spec:
            result["spec"] = spec
            nf = len(spec.get("features", [])); ni = len(spec.get("interfaces", []))
            nt = sum(len(tp.get("tests", [])) for tp in spec.get("test_points", []))
            nr = len(spec.get("registers", []))
            base_score = min(10*nf + 5*ni + 3*nt + 5*nr, 90)
            # schema 校验：design_name 必须是有效值
            dn = spec.get("design_name", "")
            if self._is_design_name_invalid(dn):
                result["score"] = min(base_score, 50)  # 压低分数触发重试
                result["_validate_error"] = f"design_name '{dn}' 是占位符，请从输入文档中提取真实模块名"
            else:
                result["score"] = base_score
        elif result.get("score", 0) >= 55:
            result["spec"] = {"design_name": "DUT", "status": "llm_output_unparseable",
                              "raw_output": str(output_text)[:500]}
            result["score"] = 45  # 低于 min_score=60，触发重试
        return result

    def _is_design_name_invalid(self, name: str) -> bool:
        """检查 design_name 是否是无效占位符"""
        return (not name or name.lower().strip() in self._DESIGN_NAME_PLACEHOLDERS)

    # ── schema 校验：design_name 必须是真实模块名 ──

    def validate(self, result_data: dict) -> tuple[bool, str]:
        """验证 spec 质量：design_name 不能是占位符"""
        # 先检查基本分数
        score = result_data.get("score", 0)
        if score < self.min_score:
            # 如果有 schema 错误信息，优先展示
            err = result_data.get("_validate_error", "")
            if err:
                return False, err
            return False, f"score {score} < min {self.min_score}"
        # schema 检查 design_name
        spec = result_data.get("spec", {})
        dn = spec.get("design_name", "") if isinstance(spec, dict) else ""
        if self._is_design_name_invalid(dn):
            return False, f"design_name '{dn}' 是无效占位符，必须从输入文档提取真实模块名（如 UART、SPI、ALU）"
        return True, "OK"


    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM
        return await super().execute_task(task)