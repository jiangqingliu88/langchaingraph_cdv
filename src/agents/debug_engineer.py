"""
调试工程师Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent
from src.core.registry import register_agent
from src.tools.debug_tools import DebugTools
import structlog
import json

logger = structlog.get_logger()

@register_agent("debug_engineer")
class DebugEngineer(BaseAgent):
    """调试工程师Agent"""
    
    task_type = "debug_analysis"
    consumes: List[str] = []
    produces = None  # text chain only
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="debug_engineer",
            display_name="调试工程师",
            description="分析失败测试，定位问题根因",
            config=config or {}
        )
        self.debug_tools = DebugTools()
    
    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是验证调试专家。

【职责】
1. 分析测试失败原因
2. 定位设计缺陷
3. 提供修复建议
4. 跟踪调试进度

【调试方法论】
1. 错误分类：DUT Bug / TB Bug / Test Bug
2. 多维度分析：日志/波形/覆盖率/断言
3. 根因定位：缩小范围→最小复现→波形回溯→确定根因

可用工具：{tools}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.debug_tools.get_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """执行调试分析"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}