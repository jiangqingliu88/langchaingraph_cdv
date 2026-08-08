"""
质量保证Agent —— 代码审查和验证质量评估
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
import structlog
import json

logger = structlog.get_logger()

@register_agent("quality_assurance")
class QualityAssurance(BaseAgent):
    """质量保证Agent"""

    task_type = "quality_review"
    consumes: List[str] = ["regression", "coverage"]
    produces = None  # text chain only

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="quality_assurance",
            display_name="质量保证",
            description="代码审查和验证质量评估",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是验证质量保证专家。

【职责】
1. 审查验证代码质量
2. 评估验证完整性
3. 检查编码规范
4. 生成质量报告

【审查维度】
1. 代码质量：可读性/可维护性/可重用性
2. 架构质量：组件层次/接口设计/TLM连接
3. 功能质量：测试覆盖率/断言完整性
4. 规范符合性：UVM标准/编码规范

【输出格式】JSON:
{{"overall_score": 0-100, "issues": [{{"severity":"error|warning|suggestion","message":"..."}}],
 "best_practices": [...], "verdict": "READY|NEEDS_FIX|FAILED"}}

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

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从 LLM 输出提取 QA 报告"""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        qa = _extract_json_from_llm(output_text)
        if qa:
            result["quality"] = qa
            score = qa.get("overall_score", 0)
            result["score"] = min(int(score * 0.95), 95)
        else:
            result["score"] = 10
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        return await super().execute_task(task)
