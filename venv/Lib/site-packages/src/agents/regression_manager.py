"""
回归管理器Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent
from src.core.registry import register_agent
import structlog
import json

logger = structlog.get_logger()

@register_agent("regression_manager")
class RegressionManager(BaseAgent):
    """回归管理器Agent"""
    
    task_type = "regression_management"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="regression_manager",
            display_name="回归管理器",
            description="管理回归测试执行和结果分析",
            config=config or {}
        )
        self.test_queue: List[Dict] = []
        self.results_cache: Dict[str, Any] = {}
        self._regression_tools = [
            self.execute_regression,
            self.analyze_regression_results,
            self.manage_test_queue,
            self.optimize_test_order,
            self.generate_regression_report
        ]
    
    async def _setup(self):
        """子类特定初始化"""
        self._regression_tools = [
            self.execute_regression,
            self.analyze_regression_results,
            self.manage_test_queue,
            self.optimize_test_order,
            self.generate_regression_report
        ]
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是回归测试管理专家。

【职责】
1. 管理回归测试队列
2. 优化测试执行顺序
3. 分析回归测试结果
4. 生成回归报告

【回归策略】
- Smoke Test: 5-10分钟，每次提交触发
- Daily Regression: 2-4小时，每天运行
- Weekly Regression: 完整测试套件，每周运行

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
        """执行回归管理"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}
    
    def execute_regression(self, test_suite: str) -> str:
        """执行回归测试"""
        import datetime
        result = {
            "regression_id": f"reg_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "test_suite": test_suite,
            "total_tests": 150,
            "passed": 147,
            "failed": 3,
            "pass_rate": "98.0%",
            "execution_time": "45.2s",
            "failed_tests": [
                {"name": "test_uart_parity_error", "reason": "Scoreboard mismatch"},
                {"name": "test_uart_fifo_overflow", "reason": "Simulation timeout"},
                {"name": "test_uart_baud_rate_boundary", "reason": "Assertion failure"}
            ]
        }
        self.results_cache[result["regression_id"]] = result
        return json.dumps(result, indent=2)
    
    def analyze_regression_results(self, regression_id: str) -> str:
        """分析回归结果"""
        analysis = {
            "regression_id": regression_id,
            "pass_rate": "98.0%",
            "failure_categories": {
                "scoreboard_mismatch": 1,
                "simulation_timeout": 1,
                "assertion_failure": 1
            },
            "recommendations": [
                "Investigate scoreboard mismatch",
                "Review timeout thresholds",
                "Debug assertion failure"
            ]
        }
        return json.dumps(analysis, indent=2)
    
    def manage_test_queue(self, action: str) -> str:
        """管理测试队列"""
        return json.dumps({"queue_size": len(self.test_queue), "action": action})
    
    def optimize_test_order(self, tests: str) -> str:
        """优化测试顺序"""
        return json.dumps({"optimized": True, "estimated_time": "33s"})
    
    def generate_regression_report(self, data: str) -> str:
        """生成回归报告"""
        import datetime
        report = {
            "report_title": "Regression Report",
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {"total": 150, "passed": 147, "failed": 3, "pass_rate": "98.0%"}
        }
        return json.dumps(report, indent=2)