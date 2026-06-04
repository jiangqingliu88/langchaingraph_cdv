"""
Pipeline 执行服务 —— CLI 和 Web API 共享的验证流水线引擎

单例模式，管理 Agent 生命周期 + 流水线执行 + 运行状态追踪。
"""
from __future__ import annotations
import time, json, uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.core.registry import AgentRegistry
from src.agents.spec_planner import SpecAndTestPlanner
from src.agents.architect import VerificationArchitect
from src.agents.sequence_engineer import SequenceEngineer
from src.agents.assertion_engineer import AssertionEngineer
from src.agents.coverage_manager import CoverageManager
from src.agents.regression_manager import RegressionManager
from src.agents.debug_engineer import DebugEngineer
from src.agents.quality_assurance import QualityAssurance
from src.agents.report_generator import ReportGenerator
from src.agents.testcase_engineer import TestCaseEngineer
from src.agents.design_arch import DesignArchitect
from config.settings import Settings

logger = structlog.get_logger()

# Pipeline 阶段定义
FULL_PHASES = [
    ("spec",    "spec_and_test_planner",    "spec"),
    ("arch",    "verification_architect",   "env"),
    ("seq",     "sequence_engineer",        "policies"),
    ("tc",      "testcase_engineer",        "tests"),
    ("design",  "design_architect",         "design_arch"),
    ("assert",  "assertion_engineer",       None),
    ("regress", "regression_manager",       "regression"),
    ("cover",   "coverage_manager",         "coverage"),
    ("debug",   "debug_engineer",           None),
    ("qa",      "quality_assurance",        None),
    ("report",  "report_generator",         None),
]

QUICK_PHASES = FULL_PHASES[:4]  # spec → arch → seq → tc


class PipelineExecutionService:
    """流水线执行服务（单例）"""

    _instance: Optional[PipelineExecutionService] = None

    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = AgentRegistry.get_instance()
        self._initialized = False
        self._runs: Dict[str, dict] = {}  # run_id → {state, phases, results, ctx}

    @classmethod
    def get_instance(cls) -> PipelineExecutionService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Agent 生命周期 ──

    async def initialize_agents(self) -> None:
        """初始化所有 10 个 Agent（幂等）"""
        if self._initialized:
            return

        agents = [
            ("spec_and_test_planner",   SpecAndTestPlanner()),
            ("verification_architect",  VerificationArchitect()),
            ("sequence_engineer",        SequenceEngineer()),
            ("assertion_engineer",       AssertionEngineer()),
            ("coverage_manager",         CoverageManager()),
            ("regression_manager",       RegressionManager()),
            ("debug_engineer",           DebugEngineer()),
            ("quality_assurance",        QualityAssurance()),
            ("report_generator",         ReportGenerator()),
            ("testcase_engineer",        TestCaseEngineer()),
            ("design_architect",         DesignArchitect()),
        ]
        for role, agent in agents:
            await agent.initialize()
            self.registry.set_agent_instance(role, agent)

        self._initialized = True
        logger.info("All agents initialized via PipelineExecutionService")

    @property
    def initialized(self) -> bool:
        return self._initialized

    # ── 流水线执行 ──

    async def run_pipeline(
        self,
        spec_text: str,
        workflow: str = "full_verification",
        output_root: str = "output",
        bypass: bool = True,
    ) -> dict:
        """执行验证流水线，返回 {run_id, phases, passed, total, ctx}"""
        if not self._initialized:
            await self.initialize_agents()

        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        phases = FULL_PHASES if workflow != "quick_check" else QUICK_PHASES

        # 初始化运行状态
        run_state = {
            "run_id": run_id,
            "workflow": workflow,
            "state": "running",
            "bypass": bypass,
            "started_at": datetime.now().isoformat(),
            "current_phase": None,
            "phases": [],
            "ctx": {
                "spec": {}, "env": {}, "policies": {},
                "tests": {}, "regression": {}, "coverage": {},
                "working_dir": str(Path(output_root).resolve()),
            },
        }
        self._runs[run_id] = run_state

        ctx = run_state["ctx"]
        prev_output = spec_text
        results = {}

        for name, role, ctx_key in phases:
            run_state["current_phase"] = name

            agent = self.registry.get_agent_instance(role)
            if not agent:
                run_state["phases"].append({"name": name, "status": "skipped", "time": 0})
                continue

            agent.config["bypass"] = bypass
            task = {"bypass": bypass, "ctx": ctx, "input": prev_output}

            t0 = time.time()
            try:
                r = await agent.execute_task(task)
                t1 = time.time() - t0

                if r.success:
                    results[name] = "passed"
                    prev_output = r.data.get("output", prev_output)
                    run_state["phases"].append({
                        "name": name, "status": "passed", "time": round(t1, 1),
                    })
                else:
                    results[name] = "failed"
                    run_state["phases"].append({
                        "name": name, "status": "failed", "time": round(t1, 1),
                        "error": r.error[:200] if r.error else "unknown",
                    })
            except Exception as e:
                t1 = time.time() - t0
                results[name] = "error"
                run_state["phases"].append({
                    "name": name, "status": "error", "time": round(t1, 1),
                    "error": str(e)[:200],
                })

        passed = sum(1 for v in results.values() if v == "passed")
        run_state["state"] = "completed" if passed == len(phases) else "completed_with_errors"
        run_state["completed_at"] = datetime.now().isoformat()
        run_state["passed"] = passed
        run_state["total"] = len(phases)

        # 持久化到数据库
        try:
            from src.database.repository import save_pipeline_run
            await save_pipeline_run(
                wf=workflow,
                spec="(from web)",
                total=len(phases),
                passed=passed,
                degraded=len(phases) - passed,
                ttime=sum(p.get("time", 0) for p in run_state["phases"]),
                results=json.dumps(results, ensure_ascii=False),
            )
        except Exception:
            pass  # DB 不可用时忽略

        return {
            "run_id": run_id,
            "workflow": workflow,
            "phases": run_state["phases"],
            "passed": passed,
            "total": len(phases),
            "ctx": ctx,
        }

    # ── 运行状态查询 ──

    def get_run_status(self, run_id: str) -> Optional[dict]:
        """获取运行状态（供 SSE 轮询）"""
        run = self._runs.get(run_id)
        if not run:
            return None
        return {
            "run_id": run["run_id"],
            "state": run["state"],
            "current_phase": run["current_phase"],
            "phases": run["phases"],
            "passed": run.get("passed", 0),
            "total": run.get("total", 0),
        }

    def list_runs(self) -> List[dict]:
        """列出所有运行"""
        return [
            {"run_id": r["run_id"], "workflow": r["workflow"],
             "state": r["state"], "started_at": r["started_at"]}
            for r in self._runs.values()
        ]

    # ── 单 Agent 执行 ──

    async def run_single_agent(
        self, role: str, input_text: str, bypass: bool = True
    ) -> dict:
        """执行单个 Agent，返回 {success, output, error}"""
        if not self._initialized:
            await self.initialize_agents()

        agent = self.registry.get_agent_instance(role)
        if not agent:
            return {"success": False, "error": f"Agent not found: {role}"}

        agent.config["bypass"] = bypass
        task = {"bypass": bypass, "ctx": {}, "input": input_text}
        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "output": r.data.get("output", "") if r.data else "",
            "error": r.error,
        }

    # ── 测试用例生成 ──

    async def generate_testcases(
        self, spec_text: str, output_dir: str = "output/testcases", bypass: bool = True
    ) -> dict:
        """运行 tc_engineer Agent 生成测试用例"""
        if not self._initialized:
            await self.initialize_agents()

        ctx = {
            "spec": {"test_points": []},
            "env": {"env_name": "uart_env"},
            "policies": {"policies": []},
        }

        agent = self.registry.get_agent_instance("testcase_engineer")
        if not agent:
            return {"success": False, "error": "testcase_engineer not found"}

        agent.config["bypass"] = bypass
        task = {
            "bypass": bypass,
            "ctx": ctx,
            "input": json.dumps({
                "test_points": [],
                "env": ctx["env"],
                "policies": ctx["policies"],
            }),
            "output_dir": output_dir,
        }

        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "tests": r.data.get("tests", {}),
            "output": r.data.get("output", ""),
            "error": r.error,
        }
