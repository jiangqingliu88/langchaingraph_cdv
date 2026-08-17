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

        # ── 签核前置门禁（历史 bug：audit 永远 success=True，0% 覆盖率也"通过"）──
        # 任一门禁不满足 → NEEDS_FIX 且 success=False（失败响亮，禁止粉饰）
        gates = {}
        # G1: RTL 真实存在且通过 vlog 编译（无 RTL = 无签核对象）
        try:
            rtl_dir = output_dir / "rtl"
            rtl_files = sorted(rtl_dir.glob("*.sv")) if rtl_dir.exists() else []
            gates["rtl_present"] = len(rtl_files) > 0
            gates["rtl_files"] = [f.name for f in rtl_files][:20]
        except Exception:
            gates["rtl_present"] = False
            gates["rtl_files"] = []
        # G1b: RTL 顶层不是占位骨架（LLM 连线失败回退的确定性骨架无真实互连逻辑）
        try:
            _arch = ctx.get("design_arch", {}) if hasattr(ctx, "get") else {}
            gates["rtl_real"] = bool(gates["rtl_present"]) and not bool(
                (_arch if isinstance(_arch, dict) else {}).get("rtl_placeholder", False))
        except Exception:
            gates["rtl_real"] = bool(gates["rtl_present"])
        # G2: 回归真实执行且全过（total>0 且 failed==0）
        gates["regression_passed"] = failed == 0 and total > 0
        # G3: 覆盖率来自真实收集（>0 才算收集过；0 或缺失 = 没跑覆盖率）
        gates["coverage_collected"] = isinstance(overall, (int, float)) and overall > 0
        # G4: 参考模型是真实模型（禁止 a+b 模板占位模型通过签核）
        # ctx["model"] 已是 model_data（execution.py 的 ctx.update(data) 直接展开），
        # 历史读取层级错误（_model["model"]）导致占位模型被误判为真实。
        try:
            _model = ctx.get("model", {}) if hasattr(ctx, "get") else {}
            _model_data = _model if isinstance(_model, dict) else {}
            gates["model_real"] = not bool(_model_data.get("placeholder", False))
            gates["model_placeholder_reason"] = str(_model_data.get("placeholder_reason", ""))[:200]
        except Exception:
            gates["model_real"] = False
            gates["model_placeholder_reason"] = "无法读取模型状态"

        # 判定
        pass_rate_ok = gates["regression_passed"]
        coverage_ok = isinstance(overall, (int, float)) and overall >= 95
        verdict = "READY" if (pass_rate_ok and coverage_ok and gates.get("rtl_real", False)
                              and gates["model_real"]) else "NEEDS_FIX"

        # ── 签核报告（证据链）──
        signoff = {
            "verdict": verdict,
            "pass_rate": f"{passed}/{total}",
            "coverage": overall,
            "gates": gates,
            "summary": {
                "total_tests": total, "passed": passed, "failed": failed,
                "overall_coverage": overall,
                "rtl_present": gates["rtl_present"],
                "coverage_collected": gates["coverage_collected"],
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
        # 说真话：门禁不满足 → 如实失败（success=False），不再无条件"通过"
        return AgentResult(success=(verdict == "READY"), data={"report": signoff, "score": score})
