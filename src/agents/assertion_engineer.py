"""
断言工程师Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent
from src.core.registry import register_agent
from src.tools.assertion_tools import AssertionTools
from src.middleware.retry import retry, RetryStrategy
import structlog

logger = structlog.get_logger()

@register_agent("assertion_engineer")
class AssertionEngineer(BaseAgent):
    """断言工程师Agent - 使用DeepSeek Coder生成断言代码"""
    
    task_type = "assertion_generation"
    consumes: List[str] = []
    produces = None  # text chain only
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="assertion_engineer",
            display_name="断言工程师",
            description="生成SVA断言、形式验证属性和CDC检查",
            config=config or {}
        )
        self.assertion_tools = AssertionTools()
    
    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是SVA(SystemVerilog Assertions)和形式验证专家。

【核心职责】
1. SVA断言生成：为设计生成完整的SVA断言代码
2. 形式验证属性：生成安全性和活性属性
3. CDC检查：生成跨时钟域检查断言
4. 覆盖率属性：生成cover property
5. 断言质量分析：分析覆盖率并提供改进建议

【断言设计原则】
1. 完整性：覆盖所有关键协议和接口
2. 正确性：断言逻辑正确反映设计意图
3. 可读性：清晰的命名和注释
4. 可维护性：模块化组织

【协议断言模板】
1. 握手协议：valid/ready, req/ack
2. 数据完整性：数据稳定性，无X/Z检查
3. 时序检查：延迟范围，最小/最大时间
4. 状态机：合法转换，死锁检测

可用工具：{tools}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.assertion_tools.get_tools()
    
    @retry(RetryStrategy(max_retries=2, delay=1.0))
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """执行断言生成"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}
    
    async def generate_protocol_assertions(self, protocol: str, interface_signals: Dict) -> Dict[str, Any]:
        """为特定协议生成断言"""
        import json
        protocol_specs = {
            "axi4": {
                "design_name": "axi4_interface",
                "clock_signal": interface_signals.get("clock", "clk"),
                "reset_signal": interface_signals.get("reset", "rst_n"),
                "assertions": [
                    {
                        "type": "concurrent",
                        "property_name": "awvalid_stable",
                        "severity": "Error",
                        "property": "awvalid && !awready |=> $stable(awaddr)",
                        "message": "AWADDR changed while AWVALID asserted"
                    },
                    {
                        "type": "concurrent",
                        "property_name": "wvalid_stable",
                        "severity": "Error",
                        "property": "wvalid && !wready |=> $stable(wdata)",
                        "message": "WDATA changed while WVALID asserted"
                    }
                ]
            },
            "axi4_stream": {
                "design_name": "axis_interface",
                "clock_signal": interface_signals.get("clock", "clk"),
                "reset_signal": interface_signals.get("reset", "rst_n"),
                "assertions": [
                    {
                        "type": "concurrent",
                        "property_name": "tvalid_stable",
                        "severity": "Error",
                        "property": "tvalid && !tready |=> $stable(tdata)",
                        "message": "TDATA changed while TVALID asserted"
                    }
                ]
            }
        }
        
        spec = protocol_specs.get(protocol.lower(), {"assertions": []})
        return await self._execute(
            f"使用generate_sva_assertions工具生成{protocol}协议断言:\n{json.dumps(spec, indent=2)}"
        )