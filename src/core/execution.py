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

from src.core.output_config import make_output_root

from src.core.registry import AgentRegistry
from src.core.context import ContextStore
from src.tools.doc_tools.pipeline_docs import generate_phase_doc, update_flow_doc
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
from src.agents.write_rtl.main import WriteRTL
from config.settings import Settings

logger = structlog.get_logger()

# Pipeline 阶段定义
# doc_only=True 的阶段仅生成文档，不执行 Agent
FULL_PHASES = [
    # 前端设计 (de/)
    ("spec",    "spec_and_test_planner",    "spec",        False),
    ("design",  "design_architect",         "design_arch", False),
    ("model",   "model_agent",              "model",       False),
    ("rtl",     "write_rtl",                "rtl",         False),   # RTL 代码生成
    ("ifspec",  None,                       None,          True),   # 接口控制文档
    ("rtlsign", None,                       None,          True),   # RTL 签核报告
    # 功能验证 (dv/)
    ("vplan",   None,                       None,          True),   # 验证计划
    ("tpoint",  None,                       None,          True),   # 测试点分解
    ("rtm",     None,                       None,          True),   # 需求追踪矩阵
    ("UVM",     "verification_architect",   "env",         False),
    ("test",    "test_engineer",            "tests",       False),
    ("assert",  "assertion_engineer",       None,          False),
    ("regress", "regression_manager",       "regression",  False),
    ("cover",   "coverage_manager",         "coverage",    False),
    ("debug",   "debug_engineer",           None,          False),
    ("qa",      "quality_assurance",        None,          False),
    ("report",  "report_generator",         None,          False),
    ("vclose",  None,                       None,          True),   # 验证收敛报告
]

QUICK_PHASES = FULL_PHASES[:5]  # spec → design → model → vplan → tpoint

# 工作流名称 → 可执行阶段列表映射
_WORKFLOW_PHASE_MAP = {
    "full_verification": FULL_PHASES,
    "quick_check":       QUICK_PHASES,
    "regression_only":   [
        FULL_PHASES[11],  # regress
        FULL_PHASES[12],  # cover
        FULL_PHASES[15],  # report
    ],
    "ppa_analysis":      [
        FULL_PHASES[6],   # vplan (doc_only)
        FULL_PHASES[15],  # report
    ],
}


def _writeback_produces(agent, result_data: Any, ctx: dict) -> None:
    """按 Agent 声明的 produces 契约写回共享上下文。"""
    key = getattr(agent, "produces", None)
    if not key or not isinstance(result_data, dict):
        return
    value = result_data.get(key)
    if not value:
        return
    source = getattr(agent, 'role', 'unknown')
    if hasattr(ctx, 'put'):
        ctx.put(key, value, source=source)
    else:
        ctx[key] = value


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
            ("write_rtl",                WriteRTL()),
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
        output_root: str | None = None,
        on_progress: callable = None,
        refine: bool = False,
        run_id: str | None = None,
    ) -> dict:
        """执行验证流水线，返回 {run_id, phases, passed, total, ctx}

        run_id 可由调用方预生成（Web API），或自动生成（CLI）。
        output_root 默认 None → 自动生成 output_{user}_{timestamp}。
        """
        output_root = make_output_root(output_root)
        if not self._initialized:
            await self.initialize_agents()

        if run_id is None:
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        phases = _WORKFLOW_PHASE_MAP.get(workflow, FULL_PHASES)

        # 初始化运行状态
        run_state = {
            "run_id": run_id,
            "workflow": workflow,
            "state": "running",
            "started_at": datetime.now().isoformat(),
            "current_phase": None,
            "phases": [],
            "ctx": ContextStore(),
        }
        # 初始化配置
        run_state["ctx"]["working_dir"] = str(Path(output_root).resolve())

        # ── 创建 docs 目录 ──
        docs_dir = Path(output_root) / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        # ── 持久化：创建运行记录 ──
        try:
            from src.database.repository import create_pipeline_run
            await create_pipeline_run(run_id, workflow, spec_text[:500], len(phases))
        except Exception:
            pass
        self._runs[run_id] = run_state

        ctx = run_state["ctx"]
        results = {}
        scores = {}  # per-agent scores

        # ── Log pipeline start ──
        try:
            from src.middleware.debug_logger import tracer
            tracer.pipeline_start(workflow, spec_text[:80], [p[0] for p in phases])
        except Exception: pass

        # ── 顺序执行所有阶段 (doc_only + agent 混合，保持依赖顺序) ──
        from src.core.step_executor import StepExecutor
        for p_tuple in phases:
            name, role, ctx_key = p_tuple[0], p_tuple[1], p_tuple[2]
            doc_only = p_tuple[3] if len(p_tuple) > 3 else False

            # doc_only 阶段: 跳过 Agent，直接生成文档
            if doc_only:
                try:
                    from src.tools.doc_tools.pipeline_docs import generate_phase_doc
                    generate_phase_doc(name, ctx, str(docs_dir), run_state["phases"])
                except Exception as e:
                    logger.warning(f"Doc generation failed for {name}: {e}")
                run_state["phases"].append({
                    "name": name, "status": "passed", "time": 0,
                    "score": 100, "retries": 0,
                })
                continue

            run_state["current_phase"] = name
            phase_started = time.monotonic()
            try:
                from src.middleware.debug_logger import tracer
                display = getattr(self.registry.get_agent_instance(role), 'display_name', role)
                tracer.phase_start(name, display)
            except Exception: pass

            agent = self.registry.get_agent_instance(role)
            if not agent:
                run_state["phases"].append({"name": name, "status": "skipped", "time": 0, "score": 0,
                                             "started_at": datetime.now().isoformat(), "ended_at": None, "duration_ms": 0})
                continue

            # ── 依赖检查 ──
            executor = StepExecutor(name, agent, ctx, output_root, on_progress)
            missing = executor.check_dependencies()
            if missing and role != "spec_and_test_planner":
                print(f"\n  [PIPE] {name}: SKIPPED — missing={missing}  ctx_keys={list(ctx.keys())}")
                run_state["phases"].append({
                    "name": name, "status": "skipped", "time": 0, "score": 0,
                    "reason": f"missing inputs: {missing}",
                    "started_at": datetime.now().isoformat(), "ended_at": None, "duration_ms": 0,
                })
                continue

            # ── 字段级 task_input: 不再 json.dumps 全量 ctx ──
            consumes = getattr(agent, 'consumes', [])
            if not consumes:
                task_input = spec_text
            elif isinstance(consumes, dict):
                # 字段级: 只取需要的字段
                ctx_parts = {}
                for ck, fields in consumes.items():
                    if hasattr(ctx, 'fetch'):
                        val = ctx.fetch(ck, fields=fields)
                    else:
                        val = ctx.get(ck)
                        if isinstance(val, dict) and fields:
                            val = {f: val[f] for f in fields if f in val}
                    if val is not None:
                        ctx_parts[ck] = val
                task_input = json.dumps(ctx_parts, ensure_ascii=False, default=str) if ctx_parts else spec_text
            else:
                # 列表: 取全部
                ctx_parts = {k: ctx.get(k) for k in consumes if ctx.get(k) is not None}
                task_input = json.dumps(ctx_parts, ensure_ascii=False, default=str) if ctx_parts else spec_text

            # ── 使用 StepExecutor 执行 (含快照/回滚/diff) ──
            step_result = await executor.execute(task_input)
            final_status = step_result.status
            final_score = step_result.score
            attempt = step_result.retries

            results[name] = final_status
            scores[name] = final_score
            phase_ended = time.monotonic()
            phase_time = round(phase_ended - phase_started, 1)
            run_state["phases"].append({
                "name": name, "status": final_status, "time": phase_time,
                "score": final_score,
                "retries": attempt if final_status != "skipped" else 0,
                "started_at": datetime.fromtimestamp(phase_started).isoformat(),
                "ended_at": datetime.fromtimestamp(phase_ended).isoformat(),
                "duration_ms": int((phase_ended - phase_started) * 1000),
            })
            try:
                from src.middleware.debug_logger import tracer
                tracer.phase_end(name, final_status, final_score, phase_time)
            except Exception: pass

            # ── SSE 实时推送阶段状态 ──
            try:
                from src.web.sse import _sse_notify_phase
                import asyncio as _asyncio
                _asyncio.create_task(_sse_notify_phase(run_id, name, final_status, final_score, phase_time))
            except Exception: pass

            # ── 文本链阶段：存储输出数据 ──
            if ctx_key is None:
                # 从 ctx diff 中提取文本输出
                for diff_key in step_result.ctx_diff:
                    if diff_key.startswith(f"_phase_"):
                        ctx[f"_phase_{name}"] = step_result.ctx_diff[diff_key]
                        break

            # ── 生成阶段 Markdown 文档 ──
            try:
                from src.tools.doc_tools.pipeline_docs import generate_phase_doc
                generate_phase_doc(name, ctx, str(docs_dir), run_state["phases"])
            except Exception as e:
                logger.warning(f"Doc generation failed for phase {name}: {e}")

            # ── ctx 清理 ──
            try:
                completed_roles = [p[1] for p in FULL_PHASES if p[0] in results]
                if hasattr(ctx, 'prune'):
                    ctx.prune(completed_roles)
            except Exception:
                pass

            # ── 持久化 ──
            try:
                from src.database.repository import update_pipeline_run
                await update_pipeline_run(run_id,
                    phases_json=run_state["phases"],
                    state=run_state["state"],
                    results=results,
                    passed=sum(1 for v in results.values() if v == "passed"),
                )
            except Exception:
                pass

        passed = sum(1 for v in results.values() if v == "passed")
        degraded = sum(1 for v in results.values() if v == "degraded")
        failed = sum(1 for v in results.values() if v in ("failed", "error"))
        skipped = sum(1 for v in results.values() if v == "skipped")
        run_state["state"] = "completed" if passed + degraded == len(phases) else "completed_with_errors"
        run_state["passed"] = passed
        run_state["degraded"] = degraded
        run_state["failed"] = failed
        run_state["skipped"] = skipped
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
                "verification_architect": ("UVM", "verification_architect"),
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
            task = {"ctx": ctx,
                    "input": json.dumps({"fix": debug_data.get("suggestion", ""),
                                         "errors": debug_data.get("errors", [])[:3]},
                                        ensure_ascii=False),
                    "output_dir": output_root}
            try:
                r = await agent.execute_task(task)
                if r.success:
                    _writeback_produces(agent, r.data, ctx)
                    # Re-run test_engineer
                    test_agent = self.registry.get_agent_instance("test_engineer")
                    if test_agent:
                        test_task = {"ctx": ctx,
                                     "input": json.dumps({"fix": True}, ensure_ascii=False),
                                     "output_dir": output_root}
                        tr = await test_agent.execute_task(test_task)
                        if tr.success:
                            _writeback_produces(test_agent, tr.data, ctx)
                    # Re-run regression
                    reg_agent = self.registry.get_agent_instance("regression_manager")
                    if reg_agent:
                        rr = await reg_agent.execute_task(
                            {"ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if rr.success:
                            _writeback_produces(reg_agent, rr.data, ctx)
                    # Re-run coverage
                    cov_agent = self.registry.get_agent_instance("coverage_manager")
                    if cov_agent:
                        cr = await cov_agent.execute_task(
                            {"ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if cr.success:
                            _writeback_produces(cov_agent, cr.data, ctx)
                    # Re-run debug
                    dbg_agent = self.registry.get_agent_instance("debug_engineer")
                    if dbg_agent:
                        dr = await dbg_agent.execute_task(
                            {"ctx": ctx,
                             "input": json.dumps({"retry": True}, ensure_ascii=False),
                             "output_dir": output_root})
                        if dr.success:
                            _writeback_produces(dbg_agent, dr.data, ctx)

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
        passed = sum(1 for v in results.values() if v == "passed")
        run_state["passed"] = passed

        # 持久化：最终状态
        run_state["state"] = "completed" if passed == len(phases) else "completed_with_errors"
        run_state["completed_at"] = datetime.now().isoformat()
        try:
            from src.database.repository import update_pipeline_run
            await update_pipeline_run(run_id,
                state=run_state["state"],
                phases_json=run_state["phases"],
                results=results,
                passed=passed,
                degraded=len(phases) - passed,
                total_time=sum(p.get("time", 0) for p in run_state["phases"]),
                completed_at=datetime.now(),
            )
        except Exception:
            pass  # DB 不可用时忽略

        # ── 聚合评分 ──
        active_agents = [p for p in run_state["phases"] if p["status"] != "skipped"]
        overall_score = int(sum(scores.get(p["name"], 0) for p in active_agents) / max(len(active_agents), 1))

        # ── Log pipeline end ──
        try:
            from src.middleware.debug_logger import tracer
            total_time = sum(p.get("time", 0) for p in run_state["phases"])
            tracer.pipeline_end(passed, len(phases), total_time, scores)
        except Exception: pass
        ctx["_scores"] = scores
        ctx["_overall_score"] = overall_score
        ctx["_iterations"] = iteration_count

        # ── 最终 flow.md 更新 ──
        try:
            update_flow_doc(run_state, ctx, str(docs_dir))
        except Exception as e:
            logger.warning(f"Final flow.md update failed: {e}")

        # ── 生成 Artifact Manifest (签核证据链) ──
        manifest_path = ""
        try:
            from src.core.manifest import ManifestBuilder
            from src.middleware.debug_logger import tracer
            session_id = getattr(tracer, 'session_id', run_id.replace('run_', ''))
            # 注入 run_type
            run_type = getattr(self, '_run_types', {}).get(run_id, 'traditional')
            ctx["_run_type"] = run_type
            builder = ManifestBuilder()
            manifest = builder.build(
                session_id=session_id,
                run_state={"run_id": run_id, "workflow": workflow,
                           "state": run_state["state"],
                           "started_at": run_state.get("started_at", ""),
                           "completed_at": run_state.get("completed_at", ""),
                           "passed": passed, "total": len(phases),
                           "ctx": ctx},
                phases=run_state["phases"],
                ctx=ctx,
                output_root=output_root,
            )
            manifest_json = builder.to_json(manifest)
            manifest_path = str(Path(output_root) / "docs" / "manifest.json")
            Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(manifest_path).write_text(manifest_json, encoding="utf-8")
            logger.info(f"Manifest saved: {manifest_path}")
        except Exception as e:
            logger.warning(f"Manifest generation failed: {e}")

        # ── 证据链收集 ──
        evidence_path = ""
        try:
            from src.core.evidence import collect_evidence
            chain = collect_evidence(run_id, output_root, ctx, run_state["phases"])
            evidence_json = json.dumps(chain.to_dict(), indent=2, ensure_ascii=False, default=str)
            evidence_path = str(Path(output_root) / "docs" / "evidence_chain.json")
            Path(evidence_path).parent.mkdir(parents=True, exist_ok=True)
            Path(evidence_path).write_text(evidence_json, encoding="utf-8")
            logger.info(f"Evidence chain saved: {evidence_path}")
        except Exception as e:
            logger.warning(f"Evidence collection failed: {e}")

        # ── 三层映射: 需求→模块→功能点→测试点 ──
        try:
            from src.core.design_mapper import DesignArchitectMapper
            mapper = DesignArchitectMapper()
            spec_data = ctx.get("spec", {}) if hasattr(ctx, 'get') else {}
            design_data = ctx.get("design_arch", {}) if hasattr(ctx, 'get') else {}

            # 从 spec + design 提取结构化数据
            spec_str = json.dumps(spec_data, default=str) if isinstance(spec_data, dict) else str(spec_data)
            design_str = json.dumps(design_data, default=str) if isinstance(design_data, dict) else str(design_data)
            combined_md = spec_str + "\n" + design_str

            modules = mapper.parse_md_modules(combined_md)
            # 从 spec 提取需求
            vp = None
            try:
                from src.web.api import _get_vplan
                vp = _get_vplan()
            except Exception: pass
            requirements = [{"id": r.id, "description": r.description}
                            for r in (vp.matrix.requirements.values() if vp and hasattr(vp, 'matrix') else [])]
            if not requirements and isinstance(spec_data, dict):
                features = spec_data.get("features", [])
                requirements = [{"id": f"REQ_AUTO_{i:03d}", "description": f.get("name", f.get("description", ""))}
                                for i, f in enumerate(features[:20])]

            mappings = mapper.match_req_to_features(requirements, modules)
            stored = await mapper.store(0, modules, mappings)
            logger.info(f"Design mapping stored: {stored}")
        except Exception as e:
            logger.warning(f"Design mapping failed: {e}")

        # ── 五大差异化引擎 ──
        try:
            from src.core.engines import VPlanGenerator, CoverageDrivenRegressor, DebugCopilot, RegressionTriage
            spec_str = json.dumps(ctx.get("spec", {}), default=str) if hasattr(ctx, 'get') else ""
            vplan_gen = VPlanGenerator(); vplan = vplan_gen.generate(spec_str)
            regressor = CoverageDrivenRegressor(ctx.get("coverage", {}) if hasattr(ctx, 'get') else {}, [{"name": tc.name, "level": tc.level} for tc in vplan.testcases]); smart_plan = regressor.select()
            copilot = DebugCopilot(); sim_logs = ""; [sim_logs := sim_logs + f.read_text(encoding="utf-8", errors="replace")[:50000] for f in Path(output_root).rglob("*.log") if f.exists()]; insights = copilot.analyze(sim_logs) if sim_logs else []
            triage = RegressionTriage(); failed_ps = [p for p in run_state["phases"] if p.get("status") in ("failed", "error")]; triage_result = triage.classify(failed_ps)
            engines = {"vplan":{"reqs":len(vplan.requirements),"cps":len(vplan.coverage_points),"tests":len(vplan.testcases),"risks":len(vplan.risk_items)},"smart_regression":{"selected":len(smart_plan.selected_tests),"skipped":len(smart_plan.skipped_tests),"time_saved_pct":smart_plan.time_saved_pct},"debug":{"insights":len(insights),"time_saved":copilot.time_saved_estimate(insights),"auto_fixable":sum(1 for i in insights if i.auto_fixable)},"triage":{"total":triage_result.total,"root_causes":triage_result.root_causes,"estimated_manual_time":triage_result.estimated_manual_time}}
            engines_path = str(Path(output_root) / "docs" / "engines.json"); Path(engines_path).parent.mkdir(parents=True, exist_ok=True); Path(engines_path).write_text(json.dumps(engines, indent=2, ensure_ascii=False, default=str), encoding="utf-8"); logger.info(f"Engines saved: {engines_path}")
        except Exception as e:
            logger.warning(f"Engines failed: {e}")

        # ── SSE 推送完成 ──
        try:
            from src.web.sse import _sse_notify_complete
            import asyncio as _asyncio
            _asyncio.create_task(_sse_notify_complete(run_id, passed, len(phases), overall_score))
        except Exception: pass

        return {
            "run_id": run_id,
            "workflow": workflow,
            "phases": run_state["phases"],
            "passed": passed,
            "total": len(phases),
            "scores": scores,
            "overall_score": overall_score,
            "ctx": ctx,
            "manifest_path": manifest_path,
            "evidence_path": evidence_path,
        }

    # ── 运行状态查询 ──

    def get_run_status(self, run_id: str) -> Optional[dict]:
        """获取运行状态（供 SSE 轮询 / 前端查询）。优先内存，其次 DB。"""
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
            "started_at": run.get("started_at", ""),
            "completed_at": run.get("completed_at", ""),
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
        self, role: str, input_text: str
    ) -> dict:
        """执行单个 Agent，返回 {success, output, error}"""
        if not self._initialized:
            await self.initialize_agents()

        agent = self.registry.get_agent_instance(role)
        if not agent:
            return {"success": False, "error": f"Agent not found: {role}"}

        task = {"ctx": {}, "input": input_text}
        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "output": r.data.get("output", "") if r.data else "",
            "error": r.error,
        }

    # ── 测试用例生成 ──

    async def generate_testcases(
        self, spec_text: str, output_dir: str = "output/testcases"
    ) -> dict:
        """运行 test_engineer Agent 生成测试用例"""
        if not self._initialized:
            await self.initialize_agents()

        ctx = {
            "spec": {"test_points": []},
            "env": {"env_name": "dut_env"},
        }

        agent = self.registry.get_agent_instance("test_engineer")
        if not agent:
            return {"success": False, "error": "test_engineer not found"}

        task = {
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
