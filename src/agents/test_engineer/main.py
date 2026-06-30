"""
测试工程师 Agent —— 合并 sequence_engineer + testcase_engineer

   spec + env → constraint policies → scenarios → SV 测试代码 + simargs/run.sh + 覆盖率检查

   工具集: src/tools/testcase_tools/tools.py (6 个 @tool)
   生成器: src/tools/testcase_tools/generator.py
"""
from typing import Dict, List, Any
from datetime import datetime as dt
import json, os, tempfile, yaml
from pathlib import Path

from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.testcase_tools.tools import (
    parse_test_points,
    map_policies_to_tests,
    build_scenario_yaml,
    build_priority_rules,
    generate_test_cases,
    check_test_coverage,
)
import structlog

logger = structlog.get_logger()


@register_agent("test_engineer")
class TestEngineer(BaseAgent):
    """测试工程师 —— 策略→场景→测试代码→simargs 一站式生成"""

    task_type = "code_generation"
    consumes = ["spec", "env"]
    produces = "tests"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="test_engineer",
            display_name="测试工程师",
            description="约束策略→场景映射→SV测试代码→仿真参数一站式生成",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证测试工程师。

【职责】
1. 解析 spec_planner 输出的 test_points
2. 生成 constraint policies 约束策略
3. 映射 policies → 测试场景
4. 生成 SV 测试代码 + run.sh + simargs
5. 检查测试覆盖率

【工具】
- parse_test_points: spec JSON → 结构化测试列表
- map_policies_to_tests: 分类 → policies 场景映射
- build_scenario_yaml: 场景 JSON → YAML
- build_priority_rules: 策略 → 权重规则
- generate_test_cases: YAML → SV 代码 + run.sh
- check_test_coverage: 覆盖率对比

            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [
            parse_test_points, map_policies_to_tests,
            build_scenario_yaml, build_priority_rules,
            generate_test_cases, check_test_coverage,
        ]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}


    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从 LLM 输出提取测试用例数据。"""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        parsed = _extract_json_from_llm(output_text)
        if parsed:
            tests = parsed.get("tests", parsed.get("test_cases", []))
            if tests:
                result["tests"] = {
                    "test_names": [t.get("name", f"test_{i}") for i, t in enumerate(tests)],
                    "test_count": len(tests),
                    "test_cases": tests,
                }
                result["score"] = min(60 + len(tests) * 5, 95)
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        return await super().execute_task(task)
