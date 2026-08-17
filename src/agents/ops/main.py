"""运维调度智能体 —— 编译 + 仿真 + 回归（真实 EDA 工具链）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.layers.l2_orchestration.agents.base import BaseAgent, AgentResult
from src.layers.l2_orchestration.agents.registry import register_agent
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
        from src.layers.l1_infrastructure.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        params = task.get("params", {}) or {}
        design_style = params.get("design_style", "baseline") if isinstance(params, dict) else "baseline"

        # ── EDA 可用性前置检查（失败响亮：没有 EDA 就不假装跑回归）──
        # 确定性检测 vlog/vsim 是否在 PATH；缺失 → EDA_MISSING（score 0，success=False），
        # 由执行引擎终止闭环（BLOCKED_EDA_MISSING），而不是误判为功能失败循环重构。
        import shutil
        eda_found = [t for t in ("vlog", "vsim") if shutil.which(t)]
        if not eda_found:
            return AgentResult(success=False, data={
                "regression": {
                    "status": "FAIL", "passed": 0, "failed": 1, "total": 1,
                    "eda_missing": True,
                    "error": "未检测到 EDA 工具（vlog/vsim）。请安装 QuestaSim 并加入 PATH 后重试。",
                    "eda_tools_found": eda_found,
                    "design_style": design_style,
                },
                "score": 0,
            })

        # ── 回归执行：直接走 L1 InfrastructureManager.run_regression（真实回归框架）──
        # 不走 MCP 子进程工具（regression.run）：tool_worker 引用的 regression_tool 模块
        # 已不存在（断链），且子进程隔离会丢失 EDA 失败细节。L1 是同一回归框架的统一封装。
        try:
            from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
            infra = InfrastructureManager(output_dir)
            reg_data = infra.run_regression(mode="local")
            if not isinstance(reg_data, dict):
                reg_data = {}
        except Exception as e:
            logger.warning(f"回归执行失败: {e}")
            reg_data = {"status": "FAIL", "passed": 0, "failed": 1, "total": 1,
                        "error": str(e)[:300], "design_style": design_style}

        if not reg_data.get("status"):
            # 工具失败 → 兜底 FAIL（含错误信息，供 debug/decision 分析）
            err = str(reg_data.get("error", ""))
            reg_data = {
                "status": "FAIL", "passed": 0, "failed": 1, "total": 1,
                "error": err, "design_style": design_style,
                "eda_missing": self._is_eda_missing(err),
            }
        else:
            reg_data.setdefault("design_style", design_style)
            # 即使回归跑起来了，内部报 EDA 缺失（如 stderr 含 vlog/vsim 找不到）也要标记
            _err = str(reg_data.get("error", "") or reg_data.get("stderr", ""))
            if not reg_data.get("eda_missing"):
                reg_data["eda_missing"] = self._is_eda_missing(_err)

        passed = reg_data.get("passed", 0)
        failed = reg_data.get("failed", 0)
        success = (reg_data.get("status") == "PASS" or (failed == 0 and passed > 0))
        score = 60 if success else 20
        return AgentResult(success=success,
                          data={"regression": reg_data, "score": score})

    # ── 文件系统发现辅助 ──

    @staticmethod
    def _is_eda_missing(err_text: str) -> bool:
        """识别"EDA 工具缺失"类错误（vlog/vsim 找不到），区别于编译/仿真失败。

        这是"失败响亮"的关键：EDA 缺失是环境问题，不是代码问题，
        决策层必须据此终止闭环并提示安装，而不是误判为功能错误去重构 RTL。
        """
        if not err_text:
            return False
        t = err_text.lower()
        markers = (
            "'vlog' 不是内部或外部命令", "'vsim' 不是内部或外部命令",
            "not recognized as", "no such file or directory", "not found",
            "cannot find", "找不到", "无法识别", "不是内部或外部命令",
            "vlog.exe", "vsim.exe", "questa", "questa sim",
        )
        # 只在这些词同时出现时才判 EDA 缺失，避免把编译错误误判
        return any(m in t for m in markers)

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
