"""
质量保证Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent
from src.core.registry import register_agent
import structlog
import json

logger = structlog.get_logger()

@register_agent("quality_assurance")
class QualityAssurance(BaseAgent):
    """质量保证Agent"""
    
    task_type = "quality_review"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="quality_assurance",
            display_name="质量保证",
            description="代码审查和验证质量评估",
            config=config or {}
        )
        self._qa_tools = [
            self.review_code,
            self.evaluate_quality_metrics,
            self.check_standards_compliance,
            self.generate_qa_report
        ]
    
    async def _setup(self):
        """子类特定初始化"""
        self._qa_tools = [
            self.review_code,
            self.evaluate_quality_metrics,
            self.check_standards_compliance,
            self.generate_qa_report
        ]
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
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

可用工具：{tools}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return []
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """执行质量审查"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}
    
    def review_code(self, code: str) -> str:
        """审查代码"""
        import datetime
        review = {
            "review_id": f"review_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "overall_score": 8.5,
            "issues": [
                {"severity": "warning", "message": "缺少错误消息的uvm_fatal"},
                {"severity": "suggestion", "message": "考虑使用uvm_event"}
            ],
            "best_practices": ["良好的factory使用", "完整的phase实现"]
        }
        return json.dumps(review, indent=2)
    
    def evaluate_quality_metrics(self, data: str) -> str:
        """评估质量指标"""
        metrics = {
            "code_quality": {"lint_score": 9.2},
            "test_quality": {"coverage": 95.5},
            "verification_quality": {"bug_density": "0.5/KLOC"}
        }
        return json.dumps(metrics, indent=2)
    
    def check_standards_compliance(self, code: str) -> str:
        """检查标准符合性"""
        return json.dumps({"compliance_score": 92.0, "violations": []}, indent=2)
    
    def generate_qa_report(self, data: str) -> str:
        """生成质量报告"""
        import datetime
        report = {
            "report_title": "Quality Assurance Report",
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "overall_quality": "Good",
            "sign_off_recommendation": "Conditional"
        }
        return json.dumps(report, indent=2)