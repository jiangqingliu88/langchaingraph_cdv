"""
[DEPRECATED] Step Executor — 阶段执行引擎（旧线性流水线 run_pipeline 的内层）

职责:
  1. 执行前: 条件求值 + 状态快照
  2. 执行中: Agent 调用 + 重试 + 回滚
  3. 执行后: Diff 追踪 + 结果写回 + ctx 清理

与 ContextStore 配合:
  - 执行前 snapshot() → 失败时 restore()
  - 执行后 put() → 自动溯源
  - 完成后 prune() → 自动清理
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.core.context import ContextStore


@dataclass
class StepResult:
    """单阶段执行结果"""
    phase_name: str
    status: str           # passed | degraded | failed | skipped | error
    score: float = 0
    elapsed: float = 0
    retries: int = 0
    error: Optional[str] = None
    ctx_diff: Dict[str, Any] = field(default_factory=dict)   # 本阶段新增/变更的 key
    snapshot_id: int = 0


class StepExecutor:
    """阶段执行器 — 每个阶段一个实例，管理完整的执行生命周期"""

    def __init__(self, phase_name: str, agent, ctx: ContextStore,
                 output_dir: str | None = None,
                 on_progress: Callable = None,
                 approval_gate = None):
        self.phase_name = phase_name
        self.agent = agent
        self.ctx = ctx
        from src.core.output_config import make_output_root
        self.output_dir = make_output_root(output_dir)
        self.on_progress = on_progress
        self.approval_gate = approval_gate

        self.max_retries = getattr(agent, 'max_retries', 2)
        self.min_score = getattr(agent, 'min_score', 50)
        self.produces = getattr(agent, 'produces', None)
        self.role = getattr(agent, 'role', 'unknown')

    # ═══════════════════════════════════════════════════════
    # 条件求值
    # ═══════════════════════════════════════════════════════

    def check_dependencies(self) -> List[str]:
        """检查 consumes 声明的依赖是否在 ctx 中可用。返回缺失列表。"""
        consumes = getattr(self.agent, 'consumes', [])
        if not consumes:
            return []
        if isinstance(consumes, dict):
            keys = list(consumes.keys())
        else:
            keys = consumes
        missing = []
        for k in keys:
            val = self.ctx.get(k)
            if val is None:
                missing.append(k)
        if missing:
            print(f"  [DEPS] {self.agent.role}: missing={missing}  ctx_keys={list(self.ctx.keys())}")  # DEBUG
        return missing

    # ═══════════════════════════════════════════════════════
    # 状态快照
    # ═══════════════════════════════════════════════════════

    def _snapshot(self) -> tuple:
        """创建 ctx 快照，返回 (snapshot_copy, keys_before)。"""
        return (self.ctx.snapshot(), set(self.ctx.keys()))

    def _restore(self, snapshot: dict, keys_before: set = None) -> None:
        """回滚 ctx 到快照状态（仅还原本阶段涉及的 key，不影响并行执行的其它阶段）。"""
        if keys_before is None:
            keys_before = set(snapshot.keys())
        keys_after = set(self.ctx.keys())
        # 仅删除本阶段新增的 key (不影响其它并行阶段写入的)
        keys_added_by_us = keys_after - keys_before
        for key in keys_added_by_us:
            if key in self.ctx._data:
                del self.ctx._data[key]
        # 恢复快照中本阶段可能修改过的 key
        for key, value in snapshot.items():
            if key in keys_before:
                self.ctx.put(key, value, source="restore")

    def _diff(self, keys_before: set) -> Dict[str, Any]:
        """计算执行前后的 ctx 变更。"""
        keys_after = set(self.ctx.keys())
        added = keys_after - keys_before
        return {k: self.ctx.get(k) for k in added}

    # ═══════════════════════════════════════════════════════
    # 执行
    # ═══════════════════════════════════════════════════════

    async def execute(self, task_input: Any) -> StepResult:
        """执行阶段，含重试和回滚。"""
        snapshot, keys_before = self._snapshot()
        best_score = 0
        best_result = None
        final_status = "skipped"

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                # 重试前回滚 ctx（仅还原本阶段涉及的 key）
                self._restore(snapshot, keys_before)
                self._notify("running", f"retry {attempt}/{self.max_retries} (ctx restored)")

            task = {
                "ctx": self.ctx,
                "input": task_input,
                "output_dir": self.output_dir,
            }
            if attempt > 0:
                task["_retry"] = attempt

            t0 = time.time()
            try:
                r = await self.agent.execute_task(task)
                elapsed = time.time() - t0

                if not r.success:
                    if attempt < self.max_retries:
                        continue
                    final_status = "failed"
                    break

                score = r.data.get("score", 0)
                if score > best_score:
                    best_score = score
                    best_result = r

                # ── ReAct 循环: Think → Observe → Act ──
                # 1. Validate: agent 自己的 validate() + schema 校验
                passed, reason = self.agent.validate(r.data)
                schema_ok, schema_issues = self.agent.validate_output(r.data)

                if not schema_ok:
                    reason += f" | Schema violations: {'; '.join(schema_issues[:3])}"

                if (passed and schema_ok) or attempt >= self.max_retries:
                    final_status = "passed" if (passed and schema_ok) else "degraded"
                    break
                elif attempt < self.max_retries:
                    # 2. Observe: 将校验问题反馈给 Agent
                    task_input = self._build_retry_input(attempt, reason, r)
                    continue
                else:
                    final_status = "degraded"
                    break

            except Exception as e:
                if attempt < self.max_retries:
                    continue
                final_status = "error"
                return StepResult(
                    phase_name=self.phase_name,
                    status="error",
                    error=str(e)[:200],
                    retries=attempt,
                    snapshot_id=id(snapshot),
                )

        # ── 审批门控: 执行完成后检查是否需要人工审批 ──
        if self.approval_gate and self.approval_gate.requires_approval(
            self.phase_name,
            "medium" if final_status == "degraded" else "low"
        ):
            summary = f"阶段: {self.phase_name}, 状态: {final_status}, 评分: {best_score}"
            record = self.approval_gate.ask(self.phase_name, summary,
                                            "medium" if final_status == "degraded" else "low")
            if record.decision.value == "reject":
                from src.core.approval import PipelineTerminatedError
                raise PipelineTerminatedError(
                    f"用户拒绝 {self.phase_name} 阶段，流程终止")
            if record.decision.value == "skip":
                final_status = "skipped"
                return StepResult(
                    phase_name=self.phase_name,
                    status="skipped",
                    error="用户跳过",
                    retries=attempt,
                    snapshot_id=id(snapshot),
                )

        # ── 计算 diff ──
        diff = self._diff(keys_before)

        return StepResult(
            phase_name=self.phase_name,
            status=final_status,
            score=best_score,
            elapsed=round(time.time() - time.time() + (best_result.execution_time if best_result else 0), 1) or 0.1,
            retries=attempt if final_status != "skipped" else 0,
            ctx_diff=diff,
            snapshot_id=id(snapshot),
        )

    def _build_retry_input(self, attempt: int, reason: str, prev_result) -> str:
        """构造重试输入。"""
        import json
        return json.dumps({
            "retry": attempt + 1,
            "reason": reason,
            "prev": str(prev_result.data)[:300],
        }, ensure_ascii=False)

    def _notify(self, status: str, msg: str) -> None:
        if self.on_progress:
            try:
                self.on_progress(self.phase_name, status, msg)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════
# Step — 可编程 Pipeline 步骤定义
# ═══════════════════════════════════════════════════════════

@dataclass
class FailStrategy:
    """on_fail 策略枚举"""
    RETRY:    str = "retry"     # 重试当前步骤
    ROLLBACK: str = "rollback"  # 回滚到上一步后重试
    FALLBACK: str = "fallback"  # 执行 on_error 回退链
    SKIP:     str = "skip"      # 跳过继续
    ABORT:    str = "abort"     # 终止整个 pipeline


@dataclass
class Step:
    """Pipeline 步骤定义 — 声明式，与执行引擎解耦"""
    name: str
    consumes: List[str] = field(default_factory=list)
    input_mapping: Optional[Callable] = None
    condition: Optional[Callable] = None

    # ── 错误处理 ──
    on_fail: str = FailStrategy.RETRY       # retry | rollback | fallback | skip | abort
    on_error: List["Step"] = field(default_factory=list)  # fallback 时的回退链
    max_retries: int = 2
    loop_back: bool = False

    # ── Hooks 系统 ──
    # pre:  step 执行前检查 (ctx) → bool (False=skip this step)
    # post: step 执行后处理 (ctx, result) → None
    hooks_pre: Optional[Callable] = None
    hooks_post: Optional[Callable] = None

    # ── 超时 ──
    timeout: float = 0          # 秒, 0=不限制

    # ── 关键路径 ──
    required: bool = True       # True=失败则 pipeline 整体 fail

    # ── Planner 覆盖 ──
    override_params: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# PipelineExecutor — 声明式 Pipeline 执行引擎
# ═══════════════════════════════════════════════════════════

class PipelineExecutor:
    """接收 Step 列表 + Agent 注册表，确定性执行。

    用法:
      executor = PipelineExecutor(ctx)
      executor.register_agent("TestAgent", scenario_designer_func)
      executor.register_agent("Regression", regression_func)

      pipeline = [
          Step("TestAgent", consumes=["test_points"],
               condition=lambda ctx: ctx.get("dut_config") == "ready",
               on_error=[Step("DebugAgent")], loop_back=True),
          Step("Regression", consumes=["test_cases"]),
      ]
      results = await executor.run(pipeline)
    """

    def __init__(self, ctx: ContextStore, enable_rules: bool = False):
        self.ctx = ctx
        self.agents: Dict[str, Callable] = {}
        self.run_log: List[StepResult] = []
        self.rules_engine = None
        if enable_rules:
            from src.core.rules_engine import RulesEngine
            self.rules_engine = RulesEngine()

    def register_agent(self, name: str, agent_func: Callable) -> None:
        """注册 Agent: 可以是 async 函数或同步函数"""
        self.agents[name] = agent_func

    # ── Planner JSON → Pipeline ──

    @classmethod
    def from_planner_json(cls, ctx: ContextStore, planner_output: dict,
                          agent_registry: Dict[str, Callable]) -> "PipelineExecutor":
        """从 Planner JSON 构建执行器。

        Planner JSON 格式:
        {
          "pipeline_id": "cim_fi_boost",
          "override_params": {"coverage_threshold": 85, "max_loop_back": 3},
          "steps": ["DesignAgent", "TestAgent", "Regression", "Coverage"]
        }
        """
        executor = cls(ctx)
        for name, func in agent_registry.items():
            executor.register_agent(name, func)

        override = planner_output.get("override_params", {})
        steps = []
        for step_name in planner_output.get("steps", []):
            step = Step(
                name=step_name,
                max_retries=override.get("max_loop_back", 2),
                loop_back=override.get("max_loop_back", 0) > 0,
                override_params=override,
            )
            steps.append(step)

        executor._pipeline_def = steps
        return executor

    # ── 执行 ──

    async def run(self, pipeline: List[Step]) -> List[StepResult]:
        """按序执行 pipeline，支持 condition/on_fail/timeout/required + rules engine"""
        results = []
        for step in pipeline:
            result = await self._execute_step(step)
            results.append(result)
            self.run_log.append(result)

            # ── Rules Engine: 每步后自动评估 ──
            if self.rules_engine:
                rule_results = self.rules_engine.evaluate(self.ctx)
                if self.rules_engine.has_critical(rule_results):
                    result.status = "aborted"
                    result.error = self.rules_engine.summary(rule_results)
                    results.append(StepResult(
                        phase_name="rules_engine", status="aborted",
                        error=result.error))
                    return results

            # ── required 检查: 关键步骤失败 → 整个 pipeline abort ──
            if step.required and result.status in ("failed", "error"):
                result.status = "aborted"
                return results

            # ── on_fail 策略 ──
            if result.status == "failed":
                if step.on_fail == FailStrategy.FALLBACK and step.on_error:
                    for fb in step.on_error:
                        fb_result = await self._execute_step(fb)
                        results.append(fb_result)

                elif step.on_fail == FailStrategy.RETRY:
                    for retry in range(step.max_retries):
                        result = await self._execute_step(step)
                        results.append(result)
                        if result.status == "passed":
                            break

                elif step.on_fail == FailStrategy.ABORT:
                    return results

        return results

    async def _execute_step(self, step: Step) -> StepResult:
        """执行单个 Step，含超时保护"""
        agent = self.agents.get(step.name)
        if not agent:
            return StepResult(phase_name=step.name, status="skipped",
                            error=f"Agent '{step.name}' not registered")

        # ── Pre-hook: 执行前检查 ──
        if step.hooks_pre:
            try:
                ok = step.hooks_pre(self.ctx)
                if ok is False:
                    return StepResult(phase_name=step.name, status="skipped",
                                    error="pre-hook rejected")
            except Exception as e:
                return StepResult(phase_name=step.name, status="error",
                                error=f"pre-hook failed: {e}")

        # 条件门控
        if step.condition and not step.condition(self.ctx):
            return StepResult(phase_name=step.name, status="skipped",
                            error="condition not met")

        # 构造输入
        if step.input_mapping:
            agent_input = step.input_mapping(self.ctx)
        else:
            agent_input = {c: (self.ctx.get(c) if hasattr(self.ctx, 'get') else None)
                          for c in step.consumes}

        # ── 快照（执行前） ──
        keys_before = set(self.ctx.keys()) if hasattr(self.ctx, 'keys') else set()
        snapshot = self.ctx.snapshot() if hasattr(self.ctx, 'snapshot') else {}
        ver_before = self.version if hasattr(self, 'version') else 0

        try:
            import asyncio
            if step.timeout > 0:
                # 超时保护
                async def _timed():
                    if asyncio.iscoroutinefunction(agent):
                        return await agent(agent_input)
                    return agent(agent_input)
                result_data = await asyncio.wait_for(_timed(), timeout=step.timeout)
            else:
                if asyncio.iscoroutinefunction(agent):
                    result_data = await agent(agent_input)
                else:
                    result_data = agent(agent_input)

            # 写回 ctx（先写，后 diff）
            if isinstance(result_data, dict) and "data" in result_data:
                for k, v in result_data["data"].items():
                    if hasattr(self.ctx, 'put'):
                        self.ctx.put(k, v, source=step.name)

            diff = self._compute_diff(keys_before)

            # ── Post-hook: 执行后处理 ──
            if step.hooks_post:
                try:
                    step.hooks_post(self.ctx, result_data)
                except Exception:
                    pass  # post-hook 失败不影响主流程

            return StepResult(phase_name=step.name, status="passed", score=100,
                            ctx_diff=diff, snapshot_id=ver_before)

        except asyncio.TimeoutError:
            self._restore_snapshot(snapshot)
            return StepResult(phase_name=step.name, status="failed",
                            error=f"timeout after {step.timeout}s")

        except Exception as e:
            if step.on_fail == FailStrategy.ROLLBACK:
                self._restore_snapshot(snapshot)
            return StepResult(phase_name=step.name, status="error", error=str(e)[:200])

    def _capture(self) -> tuple:
        snap = self.ctx.snapshot() if hasattr(self.ctx, 'snapshot') else dict(self.ctx)
        keys = set(self.ctx.keys()) if hasattr(self.ctx, 'keys') else set(snap.keys())
        return snap, keys

    def _compute_diff(self, keys_before: set) -> dict:
        """计算 ctx 变更: {key: {_added: bool, _stats: dict, value: any}}"""
        keys_after = set(self.ctx.keys()) if hasattr(self.ctx, 'keys') else set()
        added = keys_after - keys_before
        modified = set()
        # 检测修改的 key (值发生了变化)
        for k in keys_before & keys_after:
            old = self.ctx.get(k) if hasattr(self.ctx, 'get') else None
            # entry version > 1 means modified
            if hasattr(self.ctx, 'get_entry'):
                e = self.ctx.get_entry(k)
                if e and e.version > 1:
                    modified.add(k)
        diff = {}
        for k in (added | modified):
            val = self.ctx.get(k) if hasattr(self.ctx, 'get') else None
            if val is None:
                continue
            entry = {"_added": k in added, "_modified": k in modified}
            # 统计摘要
            if isinstance(val, dict):
                stats = {}
                for pf_key in ('passed', 'pass', 'failed', 'fail'):
                    if pf_key in val:
                        stats[pf_key] = val[pf_key]
                for pct_key in ('pass_rate', 'line_pct', 'branch_pct', 'toggle_pct'):
                    if pct_key in val:
                        # 去掉 _pct 后缀，加 % 符号
                        label = pct_key.replace('_pct', '')
                        stats[label] = f"{val[pct_key]}%"
                if 'test_count' in val: stats['count'] = val['test_count']
                if 'test_names' in val: stats['count'] = len(val['test_names'])
                if 'agent_count' in val: stats['agents'] = val['agent_count']
                entry["_stats"] = stats
            elif isinstance(val, list):
                entry["_count"] = len(val)
            entry["value"] = val if isinstance(val, (dict, list, str, int, float)) else str(val)
            diff[k] = entry
        return diff

    def _restore_snapshot(self, snapshot: dict) -> None:
        if hasattr(self.ctx, '_restore'):
            for key in list(self.ctx.keys()):
                try: del self.ctx._data[key]
                except Exception: pass
            for k, v in snapshot.items():
                if hasattr(self.ctx, 'put'):
                    self.ctx.put(k, v, source="restore")

    @property
    def version(self) -> int:
        if not hasattr(self.ctx, '_data'):
            return 0
        return max((e.version for e in self.ctx._data.values()), default=0)

    @property
    def diff_log(self) -> List[dict]:
        return [{"phase": r.phase_name, "status": r.status, "diff": r.ctx_diff}
                for r in self.run_log]

    def print_diff_log(self) -> str:
        """CLI Diff 仪表盘"""
        lines = ["=" * 72, f"{'Phase':<22} {'Status':<8} {'Changes':<40}", "=" * 72]
        for i, r in enumerate(self.run_log):
            icon = "OK" if r.status == "passed" else "FAIL" if r.status == "failed" else "SKIP"
            ver = self.version if hasattr(self, 'version') else i
            name = f"{r.phase_name}@{ver}"
            changes = []
            for key, entry in r.ctx_diff.items():
                if not isinstance(entry, dict):
                    continue
                if entry.get("_added"):
                    tag = "+"
                    stats = entry.get("_stats", {})
                    if stats:
                        stat_str = ", ".join(f"{k}={v}" for k, v in sorted(stats.items()))
                        changes.append(f"{tag}{key}({stat_str})")
                    elif "_count" in entry:
                        changes.append(f"{tag}{key}[{entry['_count']}]")
                    else:
                        changes.append(f"{tag}{key}")
                elif entry.get("_modified"):
                    changes.append(f"~{key}")
            lines.append(f"{name:<22} {icon:<8} {', '.join(changes)[:40]}")
        lines.append("=" * 72)
        passed = sum(1 for r in self.run_log if r.status == "passed")
        lines.append(f"Total: {len(self.run_log)} steps, {passed} passed, "
                      f"v{self.version if hasattr(self,'version') else '?'}")
        return "\n".join(lines)

    def export_diff_json(self, path: str = None) -> str:
        import json
        data = {
            "version": self.version if hasattr(self, 'version') else 0,
            "steps": [
                {"phase": r.phase_name, "status": r.status,
                 "score": r.score, "elapsed": r.elapsed,
                 "changes": list(r.ctx_diff.keys()),
                 "detail": {k: v.get("_stats", v.get("_count", str(v.get("value",""))[:80]))
                           for k, v in r.ctx_diff.items() if isinstance(v, dict)}}
                for r in self.run_log
            ],
        }
        json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        if path:
            from pathlib import Path
            Path(path).write_text(json_str, encoding="utf-8")
        return json_str


# ═══════════════════════════════════════════════════════════
# Pipeline Orchestrator — 调度层
# ═══════════════════════════════════════════════════════════

@dataclass
class PipelineState:
    """管道全局状态"""
    run_id: str
    workflow: str
    phases_status: List[Dict] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    @property
    def passed_count(self) -> int:
        return sum(1 for p in self.phases_status if p.get("status") == "passed")

    @property
    def total_count(self) -> int:
        return len(self.phases_status)


class PipelineOrchestrator:
    """管道编排器 — 协调阶段调度、反馈闭环、状态追踪"""

    def __init__(self, ctx: ContextStore, output_dir: str | None = None,
                 on_progress: Callable = None):
        self.ctx = ctx
        from src.core.output_config import make_output_root
        self.output_dir = make_output_root(output_dir)
        self.on_progress = on_progress
        self.state = PipelineState(run_id="", workflow="")

    def check_feedback_condition(self, ctx: ContextStore) -> Optional[str]:
        """检查是否需要反馈闭环。返回需要修复的 agent role 名称，或 None。"""
        debug_data = ctx.get("debug")
        if not isinstance(debug_data, dict):
            return None
        category = debug_data.get("category", "none")
        if category == "none":
            return None
        return debug_data.get("fix_agent")

    def resolve_fix_chain(self, fix_agent_role: str) -> List[str]:
        """根据 fix_agent 确定需要重新运行的阶段链。"""
        chain_map = {
            "design":      ["design"],
            "uvm": ["UVM", "test", "regress", "cover", "debug"],
            "model":           ["model", "test", "regress", "cover", "debug"],
            "spec":          ["spec", "design", "model", "UVM", "test"],
        }
        return chain_map.get(fix_agent_role, [])


# ═══════════════════════════════════════════════════════════
# 内置验证 Hooks 库
# ═══════════════════════════════════════════════════════════

class VHooks:
    """验证场景常用 Hooks — 可直接作为 Step.hooks_pre / hooks_post 使用

    用法:
      Step("Regression", hooks_pre=VHooks.check_filelist_exists,
                         hooks_post=VHooks.parse_sim_log)
    """

    # ── Pre-hooks ──

    @staticmethod
    def check_filelist_exists(ctx) -> bool:
        """编译前: 检查 filelist.f 存在"""
        from pathlib import Path
        fl = ctx.get("env", {}).get("filelist", "") if isinstance(ctx.get("env"), dict) else ""
        if fl and Path(fl).exists():
            return True
        print(f"[PRE-HOOK] filelist not found: {fl}")
        return False

    @staticmethod
    def check_no_failures(ctx) -> bool:
        """回归前: 确认没有残留的 fail"""
        reg = ctx.get("regression", {}) if hasattr(ctx, 'get') else {}
        if isinstance(reg, dict) and (reg.get("failed", 0) > 0 or reg.get("fail", 0) > 0):
            print(f"[PRE-HOOK] Cannot proceed: {reg.get('failed',0) or reg.get('fail',0)} failures pending")
            return False
        return True

    @staticmethod
    def check_build_ready(ctx) -> bool:
        """仿真前: 确认编译库存在"""
        from pathlib import Path
        work_dir = Path(ctx.get("working_dir", "output")) / "build" / "work"
        ok = work_dir.exists() and any(work_dir.iterdir())
        if not ok:
            print(f"[PRE-HOOK] Build library not ready: {work_dir}")
        return ok

    # ── Post-hooks ──

    @staticmethod
    def parse_sim_log(ctx, result: dict = None) -> None:
        """仿真后: 解析日志提取 matched/mismatched/driven"""
        sim_dir = ctx.get("working_dir", "output")
        from pathlib import Path
        import re
        for log in Path(str(sim_dir)).glob("sim/agent/sim_*_lb.log"):
            text = log.read_text(encoding="utf-8", errors="replace")
            matched = re.findall(r"matched\s*[:=]\s*(\d+)", text)
            mismatched = re.findall(r"mismatched\s*[:=]\s*(\d+)", text)
            driven = re.findall(r"driven\s*[:=]\s*(\d+)", text)
            stats = {
                "matched": int(matched[-1]) if matched else 0,
                "mismatched": int(mismatched[-1]) if mismatched else 0,
                "driven": int(driven[-1]) if driven else 0,
            }
            if hasattr(ctx, 'put'):
                ctx.put("loopback_results", stats, source="post-hook")

    @staticmethod
    def check_pass_rate(ctx, result: dict = None) -> None:
        """回归后: 计算 pass_rate 并写回 ctx"""
        reg = ctx.get("regression", {}) if hasattr(ctx, 'get') else {}
        if not isinstance(reg, dict):
            return
        total = reg.get("total", 0)
        passed = reg.get("passed", 0) or (total - reg.get("failed", 0) - reg.get("fail", 0))
        if total > 0:
            pr = f"{passed * 100 // total}%"
            if hasattr(ctx, 'put'):
                reg["pass_rate"] = pr
                ctx.put("regression", reg, source="post-hook")

    @staticmethod
    def extract_coverage(ctx, result: dict = None) -> None:
        """覆盖率后: 从 vcover 输出提取 line/branch/toggle"""
        cov = ctx.get("coverage", {}) if hasattr(ctx, 'get') else {}
        if not isinstance(cov, dict) or cov.get("line_pct"):
            return  # 已有数据，跳过
        # 尝试从 .ucdb 提取（需要 vcover report 已运行）
        from pathlib import Path
        ucdb_files = list(Path(".").glob("*.ucdb"))
        if ucdb_files and hasattr(ctx, 'put'):
            ctx.put("coverage", {
                "line_pct": 0, "branch_pct": 0, "toggle_pct": 0,
                "_note": f"Run 'vcover report {ucdb_files[0]}' to populate",
            }, source="post-hook")
