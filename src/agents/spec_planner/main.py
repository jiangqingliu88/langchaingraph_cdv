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
                    if "design_name" in data and data["design_name"] != "UART Controller":
                        spec = data
                        break
                except Exception:
                    pass

        if spec:
            result["spec"] = spec
            nf = len(spec.get("features", [])); ni = len(spec.get("interfaces", []))
            nt = sum(len(tp.get("tests", [])) for tp in spec.get("test_points", []))
            nr = len(spec.get("registers", []))
            result["score"] = min(10*nf + 5*ni + 3*nt + 5*nr, 90)
        else:
            result["score"] = 10
        return result


    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM
        return await super().execute_task(task)