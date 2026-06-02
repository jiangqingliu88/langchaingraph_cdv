"""
规格与测试规划Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent
from src.core.registry import register_agent
from src.tools.spec_tools import SpecAnalysisTools
import structlog

logger = structlog.get_logger()

@register_agent("spec_and_test_planner")
class SpecAndTestPlanner(BaseAgent):
    """规格分析与测试规划Agent"""
    
    # 设置任务类型，LLM工厂会自动选择最优模型
    task_type = "spec_analysis"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="spec_and_test_planner",
            display_name="规格与测试规划师",
            description="分析设计规格文档，生成验证测试计划",
            config=config or {}
        )
        self.spec_tools = SpecAnalysisTools()
    
    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证的规格分析与测试规划专家。

【核心能力】
1. 分析设计规格文档，提取验证需求
2. 设计测试策略和测试用例
3. 定义覆盖率目标
4. 评估验证难度和风险

【工作流程】
Step 1: 解析设计规格
  - 识别功能特性
  - 提取接口协议
  - 分析时钟域
  - 确定约束条件

Step 2: 构建验证需求矩阵
  | 功能点 | 优先级 | 验证方法 | 覆盖率目标 | 风险等级 |

Step 3: 设计测试策略
  - Directed Tests: 基本功能验证
  - Constrained Random: 功能组合验证
  - Corner Cases: 边界条件测试
  - Error Injection: 错误处理验证

Step 4: 定义覆盖率模型
  - Code Coverage: line/branch/toggle/FSM
  - Functional Coverage: covergroups
  - Cross Coverage: 交叉覆盖率

【输出格式】
请以结构化的JSON格式输出，包含：
{{
  "spec_analysis": {{
    "features": [...],
    "interfaces": [...],
    "clock_domains": [...],
    "constraints": {{...}},
    "risk_areas": [...]
  }},
  "test_plan": {{
    "test_categories": [...],
    "coverage_goals": {{...}},
    "estimated_effort": "..."
  }}
}}

可用工具：No tools available
            """),
            ("human", "{input}"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.spec_tools.get_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """直接执行"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}