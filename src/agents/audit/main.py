"""审计智能体 —— 质量审查 + 签核证据链"""
from typing import Dict, Any
import json
from pathlib import Path

from src.layers.l2_orchestration.agents.base import BaseAgent, AgentResult
from src.layers.l2_orchestration.agents.registry import register_agent
import structlog

logger = structlog.get_logger()


@register_agent("audit")
class AuditAgent(BaseAgent):
    """审计智能体 = 质量审查 + 签核报告"""

    task_type = "quality_review"
    consumes = ["regression", "coverage"]
    produces = None

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="audit", display_name="审计智能体",
            description="质量审查+签核证据链", config=config or {})

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return {"output": ""}

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        from src.layers.l1_infrastructure.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        ctx = task.get("ctx", {})
        regression = ctx.get("regression", {}) if hasattr(ctx, 'get') else {}
        coverage = ctx.get("coverage", {}) if hasattr(ctx, 'get') else {}
        if not isinstance(regression, dict):
            regression = {}
        if not isinstance(coverage, dict):
            coverage = {}

        # ── 质量审查（真实逻辑）──
        passed = regression.get("passed", 0)
        failed = regression.get("failed", 0)
        total = regression.get("total", 0)
        overall = coverage.get("overall_pct", coverage.get("coverage_pct", 0))

        # 判定
        pass_rate_ok = failed == 0 and total > 0
        coverage_ok = isinstance(overall, (int, float)) and overall >= 95
        verdict = "READY" if (pass_rate_ok and coverage_ok) else "NEEDS_FIX"

        # ── 签核报告（证据链）──
        signoff = {
            "verdict": verdict,
            "pass_rate": f"{passed}/{total}",
            "coverage": overall,
            "summary": {
                "total_tests": total, "passed": passed, "failed": failed,
                "overall_coverage": overall,
            },
            "signoff_status": "APPROVED" if verdict == "READY" else "CONDITIONAL",
        }

        # 写签核报告
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "report.json"
        try:
            report_path.write_text(json.dumps(signoff, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"签核报告写入失败: {e}")

        score = 80 if verdict == "READY" else 40
        return AgentResult(success=True, data={"report": signoff, "score": score})
