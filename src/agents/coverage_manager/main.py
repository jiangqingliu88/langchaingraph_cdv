"""
"""
from typing import Dict, List, Any
import json
from datetime import datetime

from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.coverage_tools import CoverageTools
import structlog

logger = structlog.get_logger()

@register_agent("coverage_manager")
class CoverageManager(BaseAgent):
    """覆盖率管理器Agent —— 收集分析代码及功能覆盖率"""

    task_type = "coverage_analysis"
    consumes = ["spec", "regression"]
    produces = "coverage"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="coverage_manager",
            display_name="覆盖率管理器",
            description="收集和分析代码及功能覆盖率",
            config=config or {}
        )
        self.coverage_tools = CoverageTools()

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是覆盖率收集和分析专家。

【职责】
1. 收集代码覆盖率 (Line/Branch/Toggle/FSM)
2. 收集功能覆盖率 (Covergroups)
3. 分析覆盖率缺口
4. 生成覆盖率报告
5. 提供改进建议

【覆盖率目标】
- 代码覆盖率 >= 95%
- 功能覆盖率 >= 100%
- 断言覆盖率 >= 100%

            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return self.coverage_tools.get_tools()

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}


    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM
        return await super().execute_task(task)
