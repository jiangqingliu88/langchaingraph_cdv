"""
验证架构师Agent - 使用LLM工厂
代码生成任务自动使用deepseek-coder
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent
from src.core.registry import register_agent
from src.core.llm_factory import LLMFactory
from src.tools.uvm_tools import UVMTools
import structlog

logger = structlog.get_logger()

@register_agent("verification_architect")
class VerificationArchitect(BaseAgent):
    """验证架构师Agent - 使用DeepSeek Coder进行代码生成"""
    
    # 代码生成任务类型
    task_type = "code_generation"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="verification_architect",
            display_name="验证架构师",
            description="设计UVM验证环境架构并生成所有组件代码",
            config=config or {}
        )
        self.uvm_tools = UVMTools()
    
    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是UVM验证环境架构设计专家。

【职责】
1. 设计UVM验证环境整体架构
2. 定义组件层次和接口
3. 生成所有UVM组件代码：
   - Testbench Top
   - Environment
   - Agent (Active/Passive)
   - Driver
   - Monitor
   - Sequencer
   - Scoreboard
   - Coverage Collector
   - Virtual Sequencer
4. 实现TLM通信机制

【架构设计原则】
1. 可重用性 (Reusability)
2. 可扩展性 (Scalability)
3. 可维护性 (Maintainability)

【代码生成规范】
- 遵循UVM 1.2标准
- 使用`uvm_component_utils宏注册
- 实现完整phase
- 正确的TLM端口声明和连接

可用工具：{tools}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.uvm_tools.get_all_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """执行架构设计"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}
    
    async def generate_component(self, component_type: str, specs: Dict) -> str:
        """生成特定UVM组件"""
        component_generators = {
            "driver": self.uvm_tools.generate_uvm_driver,
            "monitor": self.uvm_tools.generate_uvm_monitor,
            "scoreboard": self.uvm_tools.generate_uvm_scoreboard,
            "agent": self.uvm_tools.generate_uvm_agent,
            "environment": self.uvm_tools.generate_uvm_environment,
            "test": self.uvm_tools.generate_uvm_test,
            "transaction": self.uvm_tools.generate_uvm_transaction,
        }
        
        generator = component_generators.get(component_type)
        if generator:
            import json
            return generator(json.dumps(specs))
        return f"不支持的组件类型: {component_type}"