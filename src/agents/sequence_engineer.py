"""
序列工程师Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent
from src.core.registry import register_agent
from src.tools.uvm_tools import UVMTools
import structlog

logger = structlog.get_logger()

@register_agent("sequence_engineer")
class SequenceEngineer(BaseAgent):
    """序列工程师Agent"""
    
    task_type = "sequence_generation"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="sequence_engineer",
            display_name="序列工程师",
            description="设计UVM测试序列和场景，实现约束随机化",
            config=config or {}
        )
        self.uvm_tools = UVMTools()
    
    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是UVM测试序列设计专家。

【职责】
1. 设计测试序列和场景
2. 实现约束随机化
3. 构建复杂测试场景
4. 优化序列覆盖率
5. 设计Virtual Sequence

【序列类型】
- Simple Sequence: 基本事务序列
- Hierarchical Sequence: 嵌套序列
- Virtual Sequence: 多接口协调
- Register Sequence: 寄存器访问
- Stress Sequence: 压力测试序列

【约束设计原则】
1. 合法约束 - 确保数据有效性
2. 覆盖约束 - 覆盖所有合法值
3. 性能约束 - 时序和吞吐量要求

可用工具：{tools}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.uvm_tools.get_sequence_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """执行序列设计"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}