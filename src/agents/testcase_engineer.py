"""
测试用例工程师 Agent —— 接收 spec_planner 的 test_points → 生成场景 YAML + SV 测试代码

  工具集: src/tools/testcase/tools.py
  生成器: src/tools/testcase/generator.py
"""
from typing import Dict, List, Any
from datetime import datetime as dt
import json, os, tempfile
from pathlib import Path

from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.testcase.tools import (
    parse_test_points,
    map_policies_to_tests,
    build_scenario_yaml,
    build_priority_rules,
    generate_test_cases,
    check_test_coverage,
)
import structlog

logger = structlog.get_logger()


def _extract_test_points(raw_input: str, ctx: dict = None) -> dict:
    """兼容 pipeline 结构化输入 / 原始 spec JSON / 已处理的 categories"""
    ctx = ctx or {}
    try:
        data = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except (json.JSONDecodeError, TypeError):
        data = {}

    if isinstance(data, dict):
        # 格式 A: pipeline 结构化 {"test_points": [...], ...}
        if "test_points" in data and isinstance(data["test_points"], list):
            raw_tp = data["test_points"]
        # 格式 B: categories 已解析
        elif "categories" in data:
            return data
        # 格式 C: 从 ctx.spec 取
        elif ctx.get("spec", {}).get("test_points"):
            raw_tp = ctx["spec"]["test_points"]
        else:
            raw_tp = data.get("test_points", [])
    else:
        raw_tp = []

    # 统一转 categories
    raw_func = parse_test_points.func if hasattr(parse_test_points, 'func') else parse_test_points
    result = json.loads(raw_func(json.dumps({"test_points": raw_tp}, ensure_ascii=False)))
    return result


@register_agent("testcase_engineer")
class TestCaseEngineer(BaseAgent):
    """测试用例工程师 —— 从验证计划 test_points 生成场景化测试用例代码"""

    task_type = "code_generation"
    consumes = ["spec", "env", "policies"]
    produces = "tests"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="testcase_engineer",
            display_name="测试用例工程师",
            description="从验证计划 test_points 生成场景化测试用例代码",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证测试用例工程师。

【职责】
1. 解析 spec_planner 输出的 test_points
2. 映射到 constraint policies 生成场景
3. 构建场景 YAML → 生成 SV 测试代码
4. 检查覆盖率

【工具】
- parse_test_points: spec JSON → 结构化测试列表
- map_policies_to_tests: 映射 policies → 场景定义
- build_scenario_yaml: 场景 JSON → YAML
- build_priority_rules: 生成权重规则
- generate_test_cases: YAML → SV 代码
- check_test_coverage: 对比覆盖率

可用工具：{tools}
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

    # ── bypass: test_points → 场景 YAML → SV 代码 ──

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            return await super().execute_task(task)

        start_time = dt.now()
        try:
            raw_input = task.get("input", str(task))
            output_dir = task.get("output_dir", "output/testcases")
            ctx = task.get("ctx", {})
            env_name = ctx.get("env", {}).get("env_name", "uart_env")
            env_policies = ctx.get("policies", {}).get("policies", [])
            self._last_prompt = "bypass: test_points → scenarios → SV tests"

            # 提取原始函数（绕过 @tool 包装）
            _ptp = parse_test_points.func if hasattr(parse_test_points, 'func') else parse_test_points
            _mpt = map_policies_to_tests.func if hasattr(map_policies_to_tests, 'func') else map_policies_to_tests
            _bsy = build_scenario_yaml.func if hasattr(build_scenario_yaml, 'func') else build_scenario_yaml
            _ctc = check_test_coverage.func if hasattr(check_test_coverage, 'func') else check_test_coverage

            # Step 1: test_points → categories
            tp = _extract_test_points(raw_input, ctx)
            if "error" in tp:
                return AgentResult(success=False, error=tp["error"])

            # Step 2: categories → scenarios (with pipeline policies)
            if env_policies:
                pnames = [p.get("name", p) if isinstance(p, dict) else p for p in env_policies]
                map_input = json.dumps({"categories": tp["categories"], "available_policies": pnames}, ensure_ascii=False)
            else:
                map_input = json.dumps(tp, ensure_ascii=False)
            mapped = _mpt(map_input)
            scenarios_data = json.loads(mapped)

            # Step 3: scenarios → YAML
            yaml_str = _bsy(json.dumps(scenarios_data, ensure_ascii=False))

            # Step 4: YAML → SV files
            from src.tools.testcase.generator import TestCaseGenerator as _TCG
            _tf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
            try:
                _tf.write(yaml_str); _tf.close()
                _gen = _TCG(_tf.name)
                gen_summary = _gen.generate_all(output_dir)
            finally:
                try: os.unlink(_tf.name)
                except Exception: pass

            # Step 5: coverage
            cov_result = _ctc(json.dumps(tp, ensure_ascii=False), json.dumps(scenarios_data, ensure_ascii=False))
            cov = json.loads(cov_result)

            summary = (f"Test Points → {gen_summary['total_tests']} scenarios generated\n"
                       f"Output: {output_dir}\n"
                       f"Env: {env_name}\n"
                       f"Coverage: {cov.get('coverage_pct','?')} "
                       f"({cov.get('covered',0)}/{cov.get('total_test_points',0)})\n")
            for t in gen_summary.get("tests", []):
                summary += f"  [{t['id']}] {t['test_name']}\n"

            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += (dt.now() - start_time).total_seconds()

            return AgentResult(success=True, data={
                "output": summary,
                "tests": {
                    "output_dir": str(Path(output_dir).resolve()),
                    "scenario_count": gen_summary.get("total_tests", 0),
                    "coverage_pct": cov.get("coverage_pct", "0%"),
                    "scenarios": gen_summary.get("tests", []),
                },
                "yaml": yaml_str,
                "scenarios": scenarios_data,
                "coverage": cov,
                "files": [f["files"] for f in gen_summary.get("tests", [])],
            }, execution_time=(dt.now() - start_time).total_seconds())

        except Exception as e:
            import traceback
            return AgentResult(success=False, error=f"{e}\n{traceback.format_exc()}")
