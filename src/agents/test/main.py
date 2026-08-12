"""
测试工程师 Agent —— 测试点→场景→约束 YAML→SV 测试代码

黑板书通信:
  consumes: ["spec", "env"]
  produces: "tests"

工具链:
  1. parse_test_points    — spec → 结构化测试列表
  2. map_policies_to_tests — 分类 → 策略场景映射（通用策略推断）
  3. build_scenario_yaml  — 场景 JSON → 完整 constraint YAML
  4. build_priority_rules — 策略 → 权重规则
  5. generate_test_cases  — YAML → SV 测试代码（调 CLI）
  6. check_test_coverage  — 覆盖率检查
"""
from typing import Dict, List, Any
from datetime import datetime as dt
import json, os, sys, yaml
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


@register_agent("test")
class TestAgent(BaseAgent):
    """测试工程师 —— 测试点→场景→约束 YAML→SV 测试代码"""

    task_type = "code_generation"
    consumes = ["spec", "env"]
    produces = "tests"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="test",
            display_name="测试工程师",
            description="测试点→场景→约束→测试代码 一站式生成",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证测试工程师。从 spec 和 UVM env 出发，生成约束 YAML 并调用 CLI 生成 SV 测试代码。

═══════════════ 工具（严格按顺序调用） ═══════════════

1. parse_test_points(spec_json)
   → 输入: spec JSON（包含 features, interfaces, test_points）
   → 输出: 结构化测试列表 {{"categories":[...], "total_tests":N}}

2. map_policies_to_tests(input_json)
   → 输入: parse_test_points 的输出 + {{"features":[...]}}
   → 输出: {{"scenarios":[...], "available_policies":[...]}}
   → 策略名是通用的（config_consistency, data_integrity, timing_constraint...），不绑定特定模块

3. build_scenario_yaml(scenarios_json, output_dir)
   → 输入: map_policies_to_tests 的输出 + env_name + features + interfaces
   → 输出: 完整 constraint YAML（含 constraint, transactions, policies, combinator, scenarios）
   → 自动推断 transactions（按接口类型: APB→reg_rw, UART→uart_frame, INTR→irq_event）
   → 保存到 output_dir/inputs/yaml/constraint.yaml

4. build_priority_rules(policies_json)  ← 可选，有特殊权重需求时调用
   → 输入: {{"policies":["pol1","pol2",...]}}
   → 输出: 权重规则

5. generate_test_cases(yaml_spec, output_dir)
   → 输入: build_scenario_yaml 输出的完整 YAML 字符串
   → 等价于: python -m src.tools.testcase_tools.main <yaml> --all --output <dir>
   → 输出: test_summary.json（含生成的 .sv 文件列表）

6. check_test_coverage(spec_json, scenarios_json)
   → 验证 test_points 覆盖率

═══════════════ 执行规则 ═══════════════
- 不要跳过任何工具，严格按 1→2→3→5 顺序调用
- build_scenario_yaml 必须传入 output_dir（从上下文获取）
- 完成后输出 JSON: {{"test_names":[...], "test_count":N, "scenarios":[...]}}
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
        """从 LLM 输出和工具调用提取测试数据。"""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        steps = result.get("intermediate_steps", [])

        # 1) 从 generate_test_cases 工具调用提取
        for step in steps:
            if isinstance(step, tuple) and len(step) >= 2:
                action, obs = step[0], step[1]
                tn = getattr(action, 'tool', '')
                if tn == 'generate_test_cases':
                    try:
                        d = json.loads(str(obs)) if isinstance(obs, str) else obs
                        if d.get("tests") or d.get("total_tests"):
                            result["tests"] = {
                                "test_count": d.get("total_tests", len(d.get("tests", []))),
                                "test_names": [t.get("test_name", "") for t in d.get("tests", [])],
                                "test_cases": d.get("tests", []),
                                "summary": d,
                            }
                            result["score"] = min(60 + d.get("total_tests", 0) * 3, 95)
                            return result
                    except (json.JSONDecodeError, TypeError):
                        pass

        # 2) 从 build_scenario_yaml 工具调用提取场景数
        scenario_count = 0
        for step in steps:
            if isinstance(step, tuple) and len(step) >= 2:
                action, obs = step[0], step[1]
                tn = getattr(action, 'tool', '')
                if tn == 'build_scenario_yaml':
                    try:
                        obs_str = str(obs)
                        if "scenarios:" in obs_str:
                            scenario_count = obs_str.count("\n  - name:")
                            if scenario_count == 0:
                                scenario_count = obs_str.count("- name:")
                    except:
                        pass

        # 3) 从 LLM 文本提取
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

        if scenario_count > 0:
            result["score"] = min(50 + scenario_count * 10, 85)

        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        result = await super().execute_task(task)

        data = result.data if isinstance(result.data, dict) else {}
        if data.get("offline") or result.data.get("score", 0) < 30:
            # LLM 路径失败 → 确定性回退：直接从 spec 构建 constraint YAML + 调 CLI
            fallback = self._run_deterministic(task)
            if fallback:
                if isinstance(result.data, dict):
                    result.data.update(fallback)
                    result.data["score"] = max(result.data.get("score", 0), 60)
                ctx = task.get("ctx", {})
                if hasattr(ctx, 'put'):
                    ctx.put("tests", fallback.get("tests", {}), source="test_deterministic")
                elif isinstance(ctx, dict):
                    ctx["tests"] = fallback.get("tests", {})
                logger.info(f"TestAgent deterministic: {fallback.get('test_count', 0)} tests")
        return result

    def _run_deterministic(self, task: Dict[str, Any]) -> dict | None:
        """确定性路径：spec → constraint YAML → CLI → SV 测试代码。"""
        ctx = task.get("ctx", {})
        output_dir = task.get("output_dir", "output")
        if hasattr(ctx, 'get'):
            spec = ctx.get("spec", {}) or {}
            env = ctx.get("env", {}) or {}
        else:
            spec, env = {}, {}

        if isinstance(spec, str):
            try: spec = json.loads(spec)
            except: spec = {}
        if isinstance(env, str):
            try: env = json.loads(env)
            except: env = {}

        features = spec.get("features", []) if isinstance(spec, dict) else []
        interfaces = spec.get("interfaces", []) if isinstance(spec, dict) else []
        design_name = spec.get("design_name", "dut") if isinstance(spec, dict) else "dut"
        env_name = env.get("env_name", f"{design_name}_env") if isinstance(env, dict) else f"{design_name}_env"

        # 1. 构建 constraint YAML
        from src.tools.testcase_tools.tools import (
            _infer_policies_from_features, _infer_transactions_from_features,
            _infer_combinator,
        )
        policies = _infer_policies_from_features(features)
        transactions = _infer_transactions_from_features(features, interfaces)
        combinator = _infer_combinator(policies)

        yaml_data = {
            "constraint": {
                "name": design_name,
                "env_name": env_name,
                "description": f"Constraint configuration for {design_name}",
            },
            "transactions": transactions,
            "policies": [
                {"name": pn, "description": f"Auto-generated: {pn}", "enabled": True, "weight": max(10 - i, 1)}
                for i, pn in enumerate(policies)
            ],
            "combinator": {
                "default_mode": combinator["mode_sequence"],
                "supported_modes": ["APPLY_ALL", "APPLY_SEQUENTIAL", "APPLY_WEIGHTED", "APPLY_FIRST_MATCH"],
                "enable_chain": combinator["enable_chain"],
                "enable_weighted": combinator["enable_weighted"],
            },
            "scenarios": [
                {
                    "name": "smoke_test",
                    "description": "冒烟测试 — 基础策略快速通过",
                    "timeout": 300,
                    "combinator_mode": "APPLY_SEQUENTIAL",
                    "policies": policies[:2] if len(policies) >= 2 else policies,
                    "repeat": 5,
                },
                {
                    "name": "full_regression",
                    "description": "全策略回归",
                    "timeout": 1800,
                    "combinator_mode": "APPLY_WEIGHTED",
                    "policies": policies,
                    "repeat": 20,
                },
            ],
        }

        if len(policies) >= 4:
            yaml_data["scenarios"].append({
                "name": "stress_test",
                "description": "压力测试 — 极限参数组合",
                "timeout": 3600,
                "combinator_mode": "APPLY_ALL",
                "policies": policies,
                "repeat": 50,
            })

        yaml_str = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # 2. 保存 YAML
        yaml_dir = Path(output_dir) / "inputs" / "yaml"
        yaml_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = yaml_dir / "constraint.yaml"
        yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")

        # 3. 调用 CLI
        import subprocess
        testcases_out = str(Path(output_dir) / "testcases")
        try:
            r = subprocess.run(
                [sys.executable, "-m", "src.tools.testcase_tools.main",
                 str(yaml_path), "--all", "--output", testcases_out],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120, cwd=str(Path.cwd()),
            )
        except Exception as e:
            logger.warning(f"testcase CLI failed: {e}")
            return None

        # 4. 读取生成的汇总
        summary_path = Path(testcases_out) / "test_summary.json"
        tests = []
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
                tests = summary.get("tests", [])
            except:
                pass

        test_names = [t.get("test_name", f"test_{i}") for i, t in enumerate(tests)]
        test_cases = [
            {
                "name": t.get("test_name", f"test_{i}"),
                "uvm_test": f"{env_name}_base_test",
                "scenario": t.get("scenario", ""),
                "policies": t.get("policies", []),
                "files": t.get("files", []),
            }
            for i, t in enumerate(tests)
        ]

        return {
            "tests": {
                "test_names": test_names,
                "test_count": len(tests),
                "test_cases": test_cases,
            },
            "yaml_path": str(yaml_path),
            "test_count": len(tests),
            "score": min(60 + len(tests) * 3, 90) if tests else 60,
        }

    def validate(self, result_data: dict) -> tuple:
        ok, reason = super().validate(result_data)
        if not ok:
            return ok, reason
        tests = result_data.get("tests", {})
        if isinstance(tests, dict):
            count = tests.get("test_count", 0)
            names = tests.get("test_names", [])
            if count == 0 and not names:
                return False, "tests empty: no test_names"
        else:
            return False, "tests missing"
        return True, "OK"
