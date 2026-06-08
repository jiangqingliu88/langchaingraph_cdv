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
from src.agents.design_architect import DesignArchitect
from src.agents.verify_architect import VerificationArchitect
from src.agents.test_engineer import TestEngineer
from src.agents.assertion_engineer import AssertionEngineer
from src.agents.coverage_manager import CoverageManager
from src.agents.regression_manager import RegressionManager
from src.agents.debug_engineer import DebugEngineer
from src.agents.quality_assurance import QualityAssurance
from src.agents.report_generator import ReportGenerator
from src.agents.model_agent import ModelAgent
from config.settings import Settings

logger = structlog.get_logger()

# Pipeline 阶段定义（12 Agent → 11 阶段，seq+tc 已合并为 test）
FULL_PHASES = [
    ("spec",    "spec_and_test_planner",    "spec"),
    ("design",  "design_architect",         "design_arch"),
    ("arch",    "verification_architect",   "env"),
    ("model",   "model_agent",              "model"),
    ("test",    "test_engineer",            "tests"),
    ("assert",  "assertion_engineer",       None),
    ("regress", "regression_manager",       "regression"),
    ("cover",   "coverage_manager",         "coverage"),
    ("debug",   "debug_engineer",           None),
    ("qa",      "quality_assurance",        None),
    ("report",  "report_generator",         None),
]

QUICK_PHASES = FULL_PHASES[:5]  # spec → design → arch → model → test


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
        """初始化所有 12 个 Agent（幂等）"""
        if self._initialized:
            return

        agents = [
            ("spec_and_test_planner",   SpecAndTestPlanner()),
            ("design_architect",         DesignArchitect()),
            ("verification_architect",  VerificationArchitect()),
            ("model_agent",              ModelAgent()),
            ("test_engineer",            TestEngineer()),
            ("assertion_engineer",       AssertionEngineer()),
            ("coverage_manager",         CoverageManager()),
            ("regression_manager",       RegressionManager()),
            ("debug_engineer",           DebugEngineer()),
            ("quality_assurance",        QualityAssurance()),
            ("report_generator",         ReportGenerator()),
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
        on_progress: callable = None,
        refine: bool = False,
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
                "spec": {}, "design_arch": {}, "env": {}, "model": {},
                "tests": {}, "regression": {}, "coverage": {},
                "working_dir": str(Path(output_root).resolve()),
            },
        }
        self._runs[run_id] = run_state

        ctx = run_state["ctx"]
        results = {}
        scores = {}  # per-agent scores

        # ── Log pipeline start ──
        try:
            from src.middleware.debug_logger import debug_logger
            debug_logger.log_pipeline_start(workflow, "spec", [p[0] for p in phases])
        except Exception: pass

        for name, role, ctx_key in phases:
            run_state["current_phase"] = name

            agent = self.registry.get_agent_instance(role)
            if not agent:
                run_state["phases"].append({"name": name, "status": "skipped", "time": 0, "score": 0})
                continue

            # ── 依赖检查：如果 consumes 声明的数据 ctx 中不存在，跳过 ──
            missing = [c for c in getattr(agent, 'consumes', []) if not ctx.get(c)]
            if missing and role != "spec_and_test_planner":
                run_state["phases"].append({
                    "name": name, "status": "skipped",
                    "time": 0, "score": 0,
                    "reason": f"missing inputs: {missing}",
                })
                continue

            # ── 构建 task：注入 ctx 中已存在的数据 ──
            task_input = spec_text if name == "spec" else json.dumps({
                k: ctx[k] for k in getattr(agent, 'consumes', []) if k in ctx
            }, ensure_ascii=False, default=str) if getattr(agent, 'consumes', []) else spec_text

            agent.config["bypass"] = bypass
            # Hybrid: non-spec agents use bypass when ctx has their required inputs
            effective_bypass = bypass
            if not bypass and role != "spec_and_test_planner":
                has_inputs = all(ctx.get(c) for c in getattr(agent, 'consumes', []))
                if has_inputs:
                    effective_bypass = True
            max_retries = getattr(agent, 'max_retries', 2)
            best_score = 0
            best_r = None
            final_status = "skipped"
            final_score = 0

            for attempt in range(max_retries + 1):
                display = getattr(agent, 'display_name', role)
                produces = getattr(agent, 'produces', '') or ''
                prod_hint = f" → {produces}" if produces else ""
                label = f"{display}{prod_hint}..." if attempt == 0 else f"{display} retry {attempt}/{max_retries}"
                try:
                    if on_progress: on_progress(name, "running", label)
                except Exception: pass

                task = {"bypass": effective_bypass, "ctx": ctx, "input": task_input, "output_dir": output_root, "refine": refine}
                if attempt > 0:
                    task["_retry"] = attempt

                t0 = time.time()
                try:
                    r = await agent.execute_task(task)
                    t1 = time.time() - t0

                    if not r.success and attempt < max_retries:
                        logger.warning(f"[{name}] fail, retry {attempt+1}/{max_retries}: {str(r.error)[:80]}")
                        continue
                    if not r.success:
                        final_status = "failed"; final_score = 0; break

                    score = r.data.get("score", 0)
                    if score > best_score: best_score = score; best_r = r

                    # Validate: check if score meets threshold
                    passed, reason = agent.validate(r.data)
                    if passed or bypass or attempt >= max_retries:
                        ftag = "passed" if passed else "degraded"
                        final_status = ftag; final_score = max(best_score, score)
                        for k in ("spec","design_arch","env","model","tests","regression","coverage","report"):
                            if k in r.data and r.data[k]: ctx[k] = r.data[k]
                        # ── Write debug log ──
                        try:
                            from src.middleware.debug_logger import debug_logger
                            io_preview = str(task_input)[:300]
                            out_preview = str(r.data.get("output", ""))[:500]
                            debug_logger.log_agent_call(
                                role, display, io_preview,
                                "bypass" if effective_bypass else "llm",
                                out_preview, [], attempt, t1, True)
                        except Exception: pass
                        tag = "OK" if attempt == 0 else f"OK(r{attempt})"
                        try:
                            if on_progress: on_progress(name, ftag, f"{tag} {prod_hint[3:] if prod_hint else ''} score={final_score} ({t1:.1f}s)")
                        except Exception: pass
                        break
                    elif attempt < max_retries:
                        logger.warning(f"[{name}] validation fail: {reason}, retry {attempt+1}/{max_retries}")
                        task_input = json.dumps({"retry":attempt+1,"reason":reason,"prev":str(r.data)[:300]}, ensure_ascii=False)
                        continue
                    else:
                        final_status = "degraded"; final_score = max(best_score, score)
                        if on_progress: on_progress(name, "degraded", f"score={final_score} (max retries, {reason})")
                        break

                except Exception as e:
                    if attempt < max_retries:
                        logger.warning(f"[{name}] exception, retry {attempt+1}/{max_retries}: {e}")
                        continue
                    final_status = "error"; final_score = 0
                    try:
                        if on_progress: on_progress(name, "error", f"err")
                    except Exception: pass
                    break

            results[name] = final_status if final_status != "skipped" else "passed"
            scores[name] = final_score
            run_state["phases"].append({
                "name": name, "status": final_status, "time": 0 if final_status == "skipped" else round(time.time() - (locals().get('t0', time.time())), 1),
                "score": final_score,
                "retries": attempt if final_status != "skipped" else 0,
            })

        passed = sum(1 for v in results.values() if v in ("passed", "degraded"))
        run_state["state"] = "completed" if passed == len(phases) else "completed_with_errors"
        run_state["completed_at"] = datetime.now().isoformat()
        run_state["passed"] = passed
        run_state["total"] = len(phases)

        # ── 反馈闭环：debug 分析 → 路由修复 → 重试 ──
        MAX_FEEDBACK_LOOPS = 2
        iteration_count = 0
        for loop in range(MAX_FEEDBACK_LOOPS):
            iteration_count = loop + 1
            if on_progress:
                try: on_progress("ITER", "running", f"Feedback iteration {iteration_count}...")
                except Exception: pass
            debug_data = ctx.get("debug", {})
            if not isinstance(debug_data, dict) or debug_data.get("category") == "none":
                break  # no issues to fix

            fix_agent_role = debug_data.get("fix_agent", "")
            if not fix_agent_role:
                break

            # Map fix_agent_role to phase name
            role_to_phase = {
                "design_architect": ("design", "design_architect"),
                "verification_architect": ("arch", "verification_architect"),
                "model_agent": ("model", "model_agent"),
                "spec_planner": ("spec", "spec_and_test_planner"),
            }
            if fix_agent_role not in role_to_phase:
                break
            phase_name, agent_role = role_to_phase[fix_agent_role]

            agent = self.registry.get_agent_instance(agent_role)
            if not agent:
                break

            logger.info(f"[feedback loop {loop+1}] re-running {phase_name} to fix {fix_agent_role}")
            task = {"bypass": bypass, "ctx": ctx,
                    "input": json.dumps({"fix": debug_data.get("suggestion", ""),
                                         "errors": debug_data.get("errors", [])[:3]},
                                        ensure_ascii=False),
                    "output_dir": output_root}
            agent.config["bypass"] = bypass
            try:
                r = await agent.execute_task(task)
                if r.success:
                    # Update ctx
                    for k in ("spec", "design_arch", "env", "model", "tests",
                              "regression", "coverage"):
                        if k in r.data and r.data[k]:
                            ctx[k] = r.data[k]
                    # Re-run test_engineer
                    test_agent = self.registry.get_agent_instance("test_engineer")
                    if test_agent:
                        test_task = {"bypass": bypass, "ctx": ctx,
                                     "input": json.dumps({"fix": True}, ensure_ascii=False),
                                     "output_dir": output_root}
                        test_agent.config["bypass"] = bypass
                        tr = await test_agent.execute_task(test_task)
                        if tr.success and "tests" in tr.data:
                            ctx["tests"] = tr.data["tests"]
                    # Re-run regression
                    reg_agent = self.registry.get_agent_instance("regression_manager")
                    if reg_agent:
                        reg_agent.config["bypass"] = bypass
                        rr = await reg_agent.execute_task(
                            {"bypass": bypass, "ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if rr.success and "regression" in rr.data:
                            ctx["regression"] = rr.data["regression"]
                    # Re-run coverage
                    cov_agent = self.registry.get_agent_instance("coverage_manager")
                    if cov_agent:
                        cov_agent.config["bypass"] = bypass
                        cr = await cov_agent.execute_task(
                            {"bypass": bypass, "ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if cr.success and "coverage" in cr.data:
                            ctx["coverage"] = cr.data["coverage"]
                    # Re-run debug
                    dbg_agent = self.registry.get_agent_instance("debug_engineer")
                    if dbg_agent:
                        dbg_agent.config["bypass"] = bypass
                        dr = await dbg_agent.execute_task(
                            {"bypass": bypass, "ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if dr.success and "debug" in dr.data:
                            ctx["debug"] = dr.data["debug"]

                    logger.info(f"[feedback loop {loop+1}] fix applied, re-ran test+regress+cover+debug")
                else:
                    logger.warning(f"[feedback loop {loop+1}] fix agent {fix_agent_role} failed")
                    break
            except Exception as e:
                logger.error(f"[feedback loop {loop+1}] error: {e}")
                break

            # Re-check debug
            new_debug = ctx.get("debug", {})
            if isinstance(new_debug, dict) and new_debug.get("category") == "none":
                logger.info(f"[feedback loop {loop+1}] all issues resolved!")
                break

        # Recalculate passed
        passed = sum(1 for v in results.values() if v in ("passed", "degraded"))
        run_state["passed"] = passed

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

        # ── 聚合评分 ──
        active_agents = [p for p in run_state["phases"] if p["status"] != "skipped"]
        overall_score = int(sum(scores.get(p["name"], 0) for p in active_agents) / max(len(active_agents), 1))

        # ── Log pipeline end ──
        try:
            from src.middleware.debug_logger import debug_logger
            total_time = sum(p.get("time", 0) for p in run_state["phases"])
            debug_logger.log_pipeline_end(passed, len(phases) - passed, total_time)
        except Exception: pass
        ctx["_scores"] = scores
        ctx["_overall_score"] = overall_score
        ctx["_iterations"] = iteration_count

        return {
            "run_id": run_id,
            "workflow": workflow,
            "phases": run_state["phases"],
            "passed": passed,
            "total": len(phases),
            "scores": scores,
            "overall_score": overall_score,
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
        """运行 test_engineer Agent 生成测试用例"""
        if not self._initialized:
            await self.initialize_agents()

        ctx = {
            "spec": {"test_points": []},
            "env": {"env_name": "uart_env"},
        }

        agent = self.registry.get_agent_instance("test_engineer")
        if not agent:
            return {"success": False, "error": "test_engineer not found"}

        agent.config["bypass"] = bypass
        task = {
            "bypass": bypass,
            "ctx": ctx,
            "input": json.dumps({
                "test_points": [],
                "env": ctx["env"],
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
