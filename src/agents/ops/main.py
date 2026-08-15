"""运维调度智能体 —— 编译 + 仿真 + 回归（真实 EDA 工具链）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
import structlog

logger = structlog.get_logger()


@register_agent("ops")
class OpsAgent(BaseAgent):
    """运维调度智能体 = 编译 + 仿真（RegressionRunner）"""

    task_type = "regression_management"
    consumes = ["env", "tests"]
    produces = "regression"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="ops", display_name="运维调度智能体",
            description="编译+仿真+回归", config=config or {})

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return {"output": ""}

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        from src.core.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        params = task.get("params", {}) or {}
        design_style = params.get("design_style", "baseline") if isinstance(params, dict) else "baseline"

        # ── 回归执行：走 MCP 工具 regression.run（吃 regression.yaml 批量跑 case）──
        # 所有 EDA 命令统一通过 regression_tool.py 的 ITool（MCP 协议）调用，
        # 工具内部走 L1 InfrastructureManager.run_regression → 回归框架。
        import asyncio
        from src.core.tool_subprocess import run_tool_in_subprocess
        try:
            resp = await asyncio.to_thread(
                run_tool_in_subprocess, "regression.run",
                {"output_dir": str(output_dir), "mode": "local"})
        except Exception as e:
            logger.warning(f"回归工具调用失败: {e}")
            resp = {"success": False, "error": str(e)}

        reg_data = resp.get("data", {}) if resp.get("success") and isinstance(resp.get("data"), dict) else {}
        if not reg_data:
            # 工具失败 → 兜底 FAIL（含错误信息，供 debug/decision 分析）
            reg_data = {
                "status": "FAIL", "passed": 0, "failed": 1, "total": 1,
                "error": resp.get("error", ""), "design_style": design_style,
            }
        else:
            reg_data.setdefault("design_style", design_style)

        passed = reg_data.get("passed", 0)
        failed = reg_data.get("failed", 0)
        success = (reg_data.get("status") == "PASS" or (failed == 0 and passed > 0))
        score = 60 if success else 20
        return AgentResult(success=success,
                          data={"regression": reg_data, "score": score})

    # ── 文件系统发现辅助 ──

    @staticmethod
    def _discover_env_name(output_dir: Path) -> str:
        """从 env/*_pkg.sv 发现环境名（如 dut_env）。"""
        try:
            for p in sorted((output_dir / "env").glob("*_pkg.sv")):
                return p.name.replace("_pkg.sv", "")
        except Exception:
            pass
        return "dut_env"

    @staticmethod
    def _discover_agent_names(output_dir: Path) -> list:
        """从 agents/ 子目录发现 agent 名（如 dut_in, dut_out）。"""
        try:
            agents_dir = output_dir / "agents"
            if agents_dir.exists():
                return sorted(d.name for d in agents_dir.iterdir() if d.is_dir())
        except Exception:
            pass
        return []

    @staticmethod
    def _discover_top_module(output_dir: Path) -> str:
        """从 bench/*_tb_top.sv 发现 testbench 顶层模块名。"""
        try:
            for p in sorted((output_dir / "bench").glob("*_tb_top.sv")):
                return p.stem
        except Exception:
            pass
        return ""
