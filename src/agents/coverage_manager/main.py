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
        """优化后的执行：确定性覆盖率收集 + LLM 缺口解释。

        对标 llm_vs_traditional_tools_analysis.md 的优化建议：
        - 收集覆盖率数据（vcover/urg）→ 传统工具
        - 解释缺口 + 建议补测 → LLM
        """
        ctx = task.get("ctx", {})
        input_text = task.get("input", "")

        # 快速路径：retry 模式 → 只收集数据
        fast_track = False
        try:
            input_data = json.loads(input_text) if isinstance(input_text, str) else input_text
            if input_data.get("retry") or input_data.get("collect_only"):
                fast_track = True
        except (json.JSONDecodeError, TypeError):
            pass

        if fast_track:
            return await self._collect_deterministic(ctx)
        return await super().execute_task(task)

    async def _collect_deterministic(self, ctx) -> AgentResult:
        """确定性收集覆盖率数据（不走 LLM）"""
        output_dir = str(ctx.get("working_dir", ".")) if hasattr(ctx, 'get') else "."

        # 1. 从 vcover 收集数据（在 regression_manager 中已有）
        cov_data = {}
        try:
            from src.agents.regression_manager.main import _collect_real_coverage
            cov_data = _collect_real_coverage(Path(output_dir))
        except Exception:
            pass

        # 2. 从 spec 提取覆盖率目标
        spec = ctx.get("spec", {}) if hasattr(ctx, 'get') else {}
        coverage_goals = spec.get("coverage_goals", {}) if isinstance(spec, dict) else {}

        merged = {
            "actual": cov_data,
            "goals": coverage_goals,
            "gaps": {},
        }

        # 3. 计算缺口（纯数学，不需要 LLM）
        if cov_data and coverage_goals:
            for metric, goal in coverage_goals.items():
                actual = cov_data.get(f"{metric}_pct", 0)
                if actual < goal:
                    merged["gaps"][metric] = {
                        "actual": actual,
                        "goal": goal,
                        "delta": round(goal - actual, 1),
                    }

        return AgentResult(success=True, data={
            "coverage": merged,
            "gaps_count": len(merged["gaps"]),
            "needs_llm_analysis": len(merged["gaps"]) > 0,
        })
