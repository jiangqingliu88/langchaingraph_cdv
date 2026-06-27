"""
"""
from typing import Dict, List, Any
import json
from datetime import datetime

from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
import structlog

logger = structlog.get_logger()

QUESTA = "f:/questasim64_2024.1/win64"
UVM_SRC = "f:/questasim64_2024.1/verilog_src/uvm-1.2/src"


@register_agent("regression_manager")
class RegressionManager(BaseAgent):
    """回归管理器Agent —— 编译 + 仿真 + 结果分析"""

    task_type = "regression_management"
    consumes = ["env", "tests"]
    produces = "regression"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="regression_manager",
            display_name="回归管理器",
            description="管理回归测试执行和结果分析",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是回归测试管理专家。

【职责】
1. 编译 UVM 环境
2. 执行仿真测试
3. 分析结果
4. 生成回归报告

            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return []

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}


    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM
        return await super().execute_task(task)
