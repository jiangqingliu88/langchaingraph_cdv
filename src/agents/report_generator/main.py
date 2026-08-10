"""
报告生成器Agent —— 使用回归框架的 JsonReporter / HtmlReporter 生成报告
"""
from typing import Dict, List, Any
from pathlib import Path
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.json import JsonReporter
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.html import HtmlReporter
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.trend_db import TrendDatabase
import structlog
import json

logger = structlog.get_logger()

@register_agent("report_generator")
class ReportGenerator(BaseAgent):
    """报告生成器Agent"""

    task_type = "report_generation"
    consumes: List[str] = []
    produces = None  # text chain only

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="report_generator",
            display_name="报告生成器",
            description="生成最终验证报告和签核文档",
            config=config or {}
        )

    async def _setup(self):
        from src.core.agent_tools import register_all_tools
        self.tool_registry = register_all_tools()
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是验证报告生成专家。

【职责】
1. 生成最终验证报告（使用 JsonReporter / HtmlReporter）
2. 创建签核文档
3. 生成覆盖率报告
4. 创建需求追踪矩阵

【输出格式】JSON:
{{"reports": {{"json": "...", "html": "..."}}, "signoff": {{"status": "APPROVED|CONDITIONAL|REJECTED"}},
 "summary": {{"total_tests": N, "passed": N, "failed": N, "pass_rate": "XX%"}},
 "verdict": "READY|NEEDS_FIX"}}

            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [
            _generate_reports,
            _query_trend_history,
        ]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        data = _extract_json_from_llm(output_text)
        if data:
            result["report"] = data
            result["score"] = 85
        else:
            result["score"] = 10
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        return await super().execute_task(task)


# ── LangChain Tools ──

from langchain.tools import tool

@tool("generate_reports")
def _generate_reports(output_dir: str, tasks_json: str) -> str:
    """使用回归框架生成 JSON + HTML 报告。tasks_json: [{"name":"","status":"","elapsed":0,...}]。"""
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
    root = str(Path(output_dir).resolve())

    try:
        JsonReporter().generate(tasks, root)
        HtmlReporter().generate(tasks, root)
        TrendDatabase().save(tasks, root)
    except Exception as e:
        return json.dumps({"error": str(e)})

    return json.dumps({
        "report_json": str(Path(output_dir) / "report.json"),
        "report_html": str(Path(output_dir) / "report.html"),
        "trend_db": str(Path(output_dir) / "regression_trend.db"),
        "status": "generated",
    })


@tool("query_trend_history")
def _query_trend_history(task_name: str = "", limit: int = 10) -> str:
    """查询历史趋势数据。task_name 为空时返回运行历史。"""
    db = TrendDatabase()
    if task_name:
        history = db.query_task_history(task_name, limit)
    else:
        history = db.query_history(limit)
    return json.dumps(history, ensure_ascii=False, default=str)


@tool("generate_spa_summary")
def _generate_spa_summary(
    output_dir: str,
    run_id: str = "",
    profile: str = "standard",
    phases_json: str = "[]",
    coverage_json: str = "{}",
    regression_json: str = "{}",
    approvals_json: str = "{}",
) -> str:
    """
    生成 SPA 风格摘要 JSON（对标原型架构输出）。
    不替代完整证据链——只提供快速概览。

    参数:
      output_dir: 输出目录路径
      run_id: 运行 ID
      profile: 使用的 profile 名称
      phases_json: 阶段状态 JSON 字符串
      coverage_json: 覆盖率数据 JSON 字符串
      regression_json: 回归结果 JSON 字符串
      approvals_json: 审批记录 JSON 字符串
    """
    try:
        phases = json.loads(phases_json) if isinstance(phases_json, str) else phases_json
        coverage = json.loads(coverage_json) if isinstance(coverage_json, str) else coverage_json
        regression = json.loads(regression_json) if isinstance(regression_json, str) else regression_json
        approvals = json.loads(approvals_json) if isinstance(approvals_json, str) else approvals_json
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    spa = {
        "spa_id": run_id or f"spa_{uuid.uuid4().hex[:8]}",
        "profile": profile,
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "stages_executed": [p.get("name", "") for p in phases],
        "stages": [
            {
                "name": p.get("name", ""),
                "status": p.get("status", "unknown"),
                "score": p.get("score", 0),
                "time_s": p.get("time", 0),
                "retries": p.get("retries", 0),
            }
            for p in phases
        ],
        "passed_count": sum(1 for p in phases if p.get("status") == "passed"),
        "total_count": len(phases),
        "coverage": coverage,
        "regression": regression,
        "approvals": approvals,
        "quality_score": sum(p.get("score", 0) for p in phases) // max(len(phases), 1),
    }

    import uuid
    output_path = Path(output_dir) / "spa_summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spa, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")

    return json.dumps({
        "status": "generated",
        "spa_path": str(output_path),
        "summary": f"{spa['passed_count']}/{spa['total_count']} phases passed, "
                    f"quality_score={spa['quality_score']}",
    }, ensure_ascii=False)
