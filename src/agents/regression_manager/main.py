"""
回归管理器Agent —— 使用回归框架 RegressionRunner + ShellGenerator + Scheduler
"""
from typing import Dict, List, Any
import json
from pathlib import Path
from datetime import datetime

from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.json import JsonReporter
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.html import HtmlReporter
import structlog

logger = structlog.get_logger()


@register_agent("regression_manager")
class RegressionManager(BaseAgent):
    """回归管理器Agent —— 编译 + 仿真 + 结果分析"""

    task_type = "regression_management"
    consumes = ["env", "tests"]
    produces = "regression"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="regression_manager",
            display_name="回归管理器",
            description="管理回归测试执行和结果分析",
            config=config or {}
        )

    async def _setup(self):
        from src.core.agent_tools import register_all_tools
        self.tool_registry = register_all_tools()
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """Role: Regression Test Manager
Goal: Compile UVM env, run simulation tests, collect pass/fail rates, generate reports.

WORKFLOW (execute in order):
1. CALL compile_env(filelist, output_dir, top_module)
   → Returns a compile result containing status, error count, and elapsed seconds.
   IF status == "FAIL" → report failures, stop.
2. CALL run_simulation(output_dir, tests_json)
   → tests_json is a JSON array of test objects with name, uvm_test, top, and coverage fields.
   → Returns test results with passed, failed, and total counts.
3. CALL generate_regression_report(output_dir, tasks_json)
   → tasks_json uses results from step 2, including name, status, elapsed, sim_time, and work_dir.
   → Returns JSON and HTML report paths.

OUTPUT FORMAT:
Return an object with compile, passed, failed, total, pass_rate, and reports fields.

RULES:
- Derive top_module from env_name in the supplied input.
- If compile fails, DO NOT run simulation. Report the errors.
- Collect ALL test results before generating report.
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [
            _compile_env,
            _run_simulation,
            _generate_regression_report,
        ]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """提取回归结果"""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        data = _extract_json_from_llm(output_text)
        if data:
            result["regression"] = data
            passed = data.get("passed", 0)
            total = data.get("total", 1)
            result["score"] = min(int(80 * passed / max(total, 1)) + 10, 95)
        else:
            result["score"] = 10
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        return await super().execute_task(task)


# ── LangChain Tools ──

from langchain.tools import tool

@tool("compile_env")
def _compile_env(filelist: str, output_dir: str, top_module: str) -> str:
    """编译 UVM 环境。输入: filelist路径, output目录, top模块名。返回编译结果JSON。"""
    # Save regression compile config
    test_yaml_dir = Path(output_dir) / "inputs" / "yaml" / "dut_test"
    test_yaml_dir.mkdir(parents=True, exist_ok=True)
    import yaml as _yaml
    compile_cfg = {
        "regression": {
            "filelist": filelist,
            "top_module": top_module,
            "output_dir": output_dir,
            "coverage": False,
        }
    }
    (test_yaml_dir / "regression.yaml").write_text(
        _yaml.dump(compile_cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8", errors="replace")

    runner = RegressionRunner(
        env_output_dir=output_dir,
        filelist=filelist,
        top_module=top_module,
        coverage=False,
    )
    result = runner.compile()
    return json.dumps(result, ensure_ascii=False)


@tool("run_simulation")
def _run_simulation(output_dir: str, tests_json: str) -> str:
    """执行仿真测试。tests_json: [{"name":"test_xxx","uvm_test":"..."}...]。返回仿真结果。"""
    try:
        tests = json.loads(tests_json) if isinstance(tests_json, str) else tests_json
    except json.JSONDecodeError:
        return json.dumps({"error": "invalid tests_json format"})

    # Save regression test list to YAML
    test_yaml_dir = Path(output_dir) / "inputs" / "yaml" / "dut_test"
    test_yaml_dir.mkdir(parents=True, exist_ok=True)
    import yaml as _yaml
    reg_path = test_yaml_dir / "regression.yaml"
    # Append tests to existing regression config
    reg_data = {}
    if reg_path.exists():
        reg_data = _yaml.safe_load(reg_path.read_text(encoding="utf-8", errors="replace")) or {}
    reg_data["tests"] = tests
    reg_path.write_text(
        _yaml.dump(reg_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8", errors="replace")

    results = []
    for t in tests:
        runner = RegressionRunner(
            env_output_dir=output_dir,
            top_module=t.get("top", "tb_top"),
            coverage=t.get("coverage", False),
        )
        r = runner.collect_coverage(
            test_name=t.get("name", "test"),
            uvm_test=t.get("uvm_test", ""),
        )
        results.append(r)

    passed = sum(1 for r in results if r.get("status") == "PASS")
    return json.dumps({
        "tests": results,
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
    }, ensure_ascii=False)


@tool("generate_regression_report")
def _generate_regression_report(output_dir: str, tasks_json: str) -> str:
    """生成回归报告（JSON + HTML）。tasks_json: [{"name":"","status":"","elapsed":0,...}]。返回报告路径。"""
    from src.tools.regression_tools.regression_framwork.src.regression_framework.models.task import Task

    try:
        task_dicts = json.loads(tasks_json) if isinstance(tasks_json, str) else tasks_json
    except json.JSONDecodeError:
        return json.dumps({"error": "invalid tasks_json format"})

    class SimpleTask:
        def __init__(self, d):
            self.name = d.get("name", "")
            self.status = d.get("status", "unknown")
            self.work_dir = d.get("work_dir", "")
            self.elapsed = d.get("elapsed", 0)
            self.job_id = d.get("job_id", "")
            self.fingerprint = d.get("fingerprint", "")
            self.sim_time = d.get("sim_time", 0)
            self.wave_path = d.get("wave_path", "")
            self.performance_degraded = d.get("performance_degraded", False)

    tasks = [SimpleTask(d) for d in task_dicts]

    root = Path(output_dir)
    json_reporter = JsonReporter()
    html_reporter = HtmlReporter()
    json_reporter.generate(tasks, str(root))
    html_reporter.generate(tasks, str(root))

    return json.dumps({
        "report_json": str(root / "report.json"),
        "report_html": str(root / "report.html"),
        "status": "generated",
    })
