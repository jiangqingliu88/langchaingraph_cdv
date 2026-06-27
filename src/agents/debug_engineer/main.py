"""
调试工程师Agent — 分析仿真日志，定位根因，路由修复建议
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.debug_tools import DebugTools
import structlog, json, re, subprocess
from pathlib import Path

logger = structlog.get_logger()

# ── Error classification patterns ──
# ── Design vs Model cross-check ──

def _cross_check_design_model(design: dict, model: dict) -> dict:
    """Compare design_arch output with model output for consistency."""
    mismatches = []
    if not design or not model:
        return {"mismatches": [], "primary_issue": "", "suggestion": "", "fix_agent": ""}

    # Compare module name
    d_name = design.get("module_name", "")
    m_name = model.get("module", "")
    if d_name and m_name and d_name.lower() != m_name.lower():
        mismatches.append({"field": "module_name", "design": d_name, "model": m_name})

    # Compare register count (design stores in register_count, model in analysis.register_count)
    d_rc = design.get("register_count", 0)
    m_analysis = model.get("analysis", {})
    if isinstance(m_analysis, str):
        try: m_analysis = json.loads(m_analysis)
        except Exception: m_analysis = {}
    m_rc = m_analysis.get("register_count", 0) if isinstance(m_analysis, dict) else 0
    if d_rc > 0 and m_rc > 0 and d_rc != m_rc:
        mismatches.append({"field": "register_count", "design": d_rc, "model": m_rc})

    # Compare function count
    d_fc = design.get("function_count", 0)
    m_fc = m_analysis.get("function_count", 0) if isinstance(m_analysis, dict) else 0
    if d_fc > 0 and m_fc > 0 and d_fc != m_fc:
        mismatches.append({"field": "function_count", "design": d_fc, "model": m_fc})

    # Compare test vectors
    d_module = design.get("module_name", "")
    m_module = model.get("module", "") or m_analysis.get("module_name", "")
    if d_module and m_module and d_module.lower() != m_module.lower():
        mismatches.append({"field": "module_name", "design": d_module, "model": m_module})

    # Determine primary issue
    if mismatches:
        # If design has more features than model → model is incomplete
        primary = "model" if d_rc > m_rc or d_fc > m_fc else "rtl"
        return {
            "mismatches": mismatches,
            "primary_issue": primary,
            "suggestion": (f"Model has {m_rc} registers but design has {d_rc}. "
                          f"Re-run model_agent to align with design.") if primary == "model"
                          else f"Design has fewer features than expected. Re-run design_architect.",
            "fix_agent": "model_agent" if primary == "model" else "design_architect",
        }
    return {"mismatches": [], "primary_issue": "", "suggestion": "", "fix_agent": ""}
ENV_PATTERNS = [
    r"virtual interface not set", r"config_db", r"UVM_FATAL.*CFG",
    r"UVM_FATAL.*NOVIF", r"UVM_FATAL.*VIF", r"uvm_config_db",
    r"interface.*not found", r"Module.*not defined",
    r"could not find package", r"import.*not found",
]
RTL_PATTERNS = [
    r"X/Z detected", r"X detected", r"\bX\b.*signal",
    r"mismatch.*expected", r"scoreboard.*mismatch",
    r"assertion.*fail", r"SVA.*fail",
    r"flags.*mismatch", r"result.*mismatch",
    r"timing.*violation", r"setup.*violation", r"hold.*violation",
]
MODEL_PATTERNS = [
    r"predictor.*mismatch", r"reference.*model.*fail",
    r"expected.*!=.*actual", r"scoreboard.*error",
    r"cmp.*mismatch", r"golden.*mismatch",
]
SPEC_PATTERNS = [
    r"undefined.*signal", r"port.*mismatch", r"width.*mismatch",
    r"spec.*violation", r"protocol.*error",
]


def _classify_error(log_text: str) -> dict:
    """Parse simulation log and classify errors."""
    errors = [l for l in log_text.split("\n") if "UVM_ERROR" in l or "UVM_FATAL" in l or "** Error" in l]
    if not errors:
        return {"category": "none", "errors": [], "suggestion": "No errors found"}

    env_hits = sum(1 for e in errors for p in ENV_PATTERNS if re.search(p, e, re.IGNORECASE))
    rtl_hits = sum(1 for e in errors for p in RTL_PATTERNS if re.search(p, e, re.IGNORECASE))
    model_hits = sum(1 for e in errors for p in MODEL_PATTERNS if re.search(p, e, re.IGNORECASE))
    spec_hits = sum(1 for e in errors for p in SPEC_PATTERNS if re.search(p, e, re.IGNORECASE))

    scores = {"env": env_hits, "rtl": rtl_hits, "model": model_hits, "spec": spec_hits}
    primary = max(scores, key=scores.get) if any(scores.values()) else "unknown"

    suggestions = {
        "env": "Re-run verification_architect to fix UVM environment",
        "rtl": "Re-run design_architect to fix RTL design",
        "model": "Re-run model_agent to fix reference model",
        "spec": "Check spec_planner output for missing signals/ports",
        "unknown": "Manual review needed",
    }

    return {
        "category": primary,
        "scores": scores,
        "errors": errors[:5],
        "total_errors": len(errors),
        "suggestion": suggestions.get(primary, suggestions["unknown"]),
        "fix_agent": {"env": "verification_architect", "rtl": "design_architect",
                      "model": "model_agent", "spec": "spec_planner"}.get(primary, "none"),
    }


@register_agent("debug_engineer")
class DebugEngineer(BaseAgent):
    """调试工程师Agent — 分析日志，定位根因，路由修复"""

    task_type = "debug_analysis"
    consumes = ["regression", "tests", "env"]
    produces = "debug"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="debug_engineer", display_name="调试工程师",
            description="分析失败测试，定位问题根因，路由修复建议",
            config=config or {})
        self.debug_tools = DebugTools()
        self.min_score = 30

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是验证调试专家。分析仿真日志，分类错误(env/rtl/model/spec)，给出修复建议。"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"), MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return self.debug_tools.get_tools()

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}


    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM
        return await super().execute_task(task)

