"""
覆盖率驱动决策层 (L3) —— 从"流水线式"到"目标导向闭环式"

决策层 = 目标函数（覆盖率目标） + 反馈信号（覆盖率空洞）
         + 动作空间（加测/加种子/改设计/环境自愈） + 优化算法（当前为规则，可换 LLM）

与执行层 (L2) 通过标准 JSON 解耦：
  观测接口 Observation → 决策引擎 → 动作接口 Action → 执行层

用法:
    engine = CoverageDrivenDecisionEngine(target=95.0)
    action = engine.decide(observation)
    # → {"action_type": "GENERATE_DIRECTED_TEST", "params": {...}, "priority": "HIGH"}
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 接口契约 (L3 ↔ L2)
# ═══════════════════════════════════════════════════════════════

@dataclass
class Observation:
    """执行层上报给决策层的观测数据"""
    iteration_id: int = 0
    coverage: Dict[str, float] = field(default_factory=dict)   # {"functional": 90.0, "line": 85.0}
    uncovered_bins: List[str] = field(default_factory=list)     # ["wr_burst_len_8", ...]
    gaps: List[Dict] = field(default_factory=list)              # 语义层降维后的 gap 向量
    failed_tests: List[str] = field(default_factory=list)
    dead_code_modules: List[str] = field(default_factory=list)  # 0% 触发的 RTL 模块
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    coverage_history: List[float] = field(default_factory=list) # 前几轮功能覆盖率，用于检测停滞
    model_mismatch: List[Dict] = field(default_factory=list)    # 比对失败: [{"test": "...", "suspected": "模型过时"}]
    compile_error: Optional[Dict] = None                         # 编译失败: {"error_type": "...", "message": "...", "file": "...", "line": N}


@dataclass
class Action:
    """决策层下发给执行层的动作"""
    action_type: str          # GENERATE_DIRECTED_TEST | EXPAND_SEEDS | REFACTOR_RTL | RETRY_ENV | CONVERGE
    params: Dict[str, Any] = field(default_factory=dict)
    priority: str = "MEDIUM"
    max_retries: int = 3
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# 决策引擎
# ═══════════════════════════════════════════════════════════════

class CoverageDrivenDecisionEngine:
    """覆盖率驱动决策状态机。

    动作优先级: 环境失败 > 覆盖率停滞 > 覆盖率空洞 > 死代码 > 达标收敛
    """

    def __init__(self, target: float = 95.0, stall_threshold: float = 1.0,
                 stall_rounds: int = 2, seed_expand_count: int = 1000):
        self.target = target
        self.stall_threshold = stall_threshold     # 多轮增长 < 此值视为停滞
        self.stall_rounds = stall_rounds           # 连续 N 轮停滞才触发扩种
        self.seed_expand_count = seed_expand_count

    def decide(self, observation: Observation) -> Action:
        """根据观测决定下一步动作。先规则，后可换 LLM。"""
        cov = observation.coverage
        functional = cov.get("functional", 0.0)
        uncovered = observation.uncovered_bins
        failed = observation.failed_tests
        dead = observation.dead_code_modules
        mismatch = observation.model_mismatch
        compile_err = observation.compile_error

        # ── -1. 编译失败 → 自愈/重试（最高优先级，编译不过后面全废）──
        if compile_err:
            return Action(
                action_type="COMPILE_RETRY",
                params={"compile_error": compile_err},
                priority="HIGH",
                reason=f"编译失败({compile_err.get('error_type','unknown')})，触发自愈",
            )

        # ── 0. 比对失败 → 更新参考模型 ──
        if mismatch:
            return Action(
                action_type="UPDATE_MODEL",
                params={"mismatch_info": mismatch},
                priority="HIGH",
                reason=f"比对失败 {len(mismatch)} 处，疑似模型过时，更新参考模型",
            )

        # ── 1. 编译/运行失败 → 环境自愈 ──
        if failed:
            return Action(
                action_type="RETRY_ENV",
                params={"failed_tests": failed},
                priority="HIGH",
                reason=f"{len(failed)} 个测试失败，需环境自愈/重试",
            )

        # ── 2. 覆盖率停滞 → 随机种子扩增 ──
        if self._is_stalled(observation.coverage_history):
            return Action(
                action_type="EXPAND_SEEDS",
                params={"count": self.seed_expand_count},
                priority="MEDIUM",
                reason=f"覆盖率连续 {self.stall_rounds} 轮增长 < {self.stall_threshold}%，扩增种子",
            )

        # ── 3. 覆盖率不达标 → 按 gap reason 分流（语义层降维后的精准决策）──
        if functional < self.target:
            gaps = observation.gaps or []
            # 3a. 不可达/死代码 → 重构 RTL（最高，因为不是"补测"能解决的）
            unreachable = [g for g in gaps if g.get("reason") == "unreachable"]
            if unreachable:
                return Action(
                    action_type="REFACTOR_RTL",
                    params={"gaps": unreachable},
                    priority="HIGH",
                    reason=f"发现 {len(unreachable)} 处不可达/死代码，需重构 RTL",
                )
            # 3b. 约束型缺口 → 放宽约束（约束是人为限制，放宽即提升）
            constraint = [g for g in gaps if g.get("reason") == "constraint"]
            if constraint:
                unstimulated = [g for g in gaps if g.get("reason") == "unstimulated"]
                action = Action(
                    action_type="RELAX_CONSTRAINT",
                    params={"gaps": constraint},
                    priority="HIGH",
                    reason=f"覆盖率 {functional}% < {self.target}%，存在 {len(constraint)} 处约束型缺口，放宽约束",
                )
                # L4 记忆：RELAX_CONSTRAINT 历史无效 → 降级为定向测试
                fallback = Action(
                    action_type="GENERATE_DIRECTED_TEST",
                    params={"gaps": unstimulated},
                    priority="HIGH",
                    reason=f"覆盖率 {functional}% < {self.target}%，定向测试补未激励缺口",
                ) if unstimulated else None
                return self._with_experience(action, fallback)
            # 3c. 未激励缺口 → 定向测试生成
            unstimulated = [g for g in gaps if g.get("reason") == "unstimulated"]
            if unstimulated:
                return self._with_experience(Action(
                    action_type="GENERATE_DIRECTED_TEST",
                    params={"gaps": unstimulated},
                    priority="HIGH",
                    reason=f"覆盖率 {functional}% < {self.target}%，存在 {len(unstimulated)} 处未激励缺口，生成定向测试",
                ))
            # 3d. 旧接口 uncovered_bins → 定向测试
            if uncovered:
                return Action(
                    action_type="GENERATE_DIRECTED_TEST",
                    params={"target_bins": uncovered[:20]},
                    priority="HIGH",
                    reason=f"覆盖率 {functional}% < {self.target}%，存在 {len(uncovered)} 个未覆盖 bin",
                )

        # ── 4. 死代码（旧接口 dead_code_modules）→ 设计回滚/重构 ──
        if dead:
            return Action(
                action_type="REFACTOR_RTL",
                params={"modules": dead},
                priority="MEDIUM",
                reason=f"发现死代码模块: {dead}",
            )

        # ── 5. 达标 → 收敛签署 ──
        if functional >= self.target:
            return Action(
                action_type="CONVERGE",
                params={"final_coverage": functional},
                priority="LOW",
                reason=f"覆盖率 {functional}% ≥ {self.target}%，收敛",
            )

        # ── 兜底: 不达标但无空洞（rare）→ 继续扩种 ──
        return Action(
            action_type="EXPAND_SEEDS",
            params={"count": self.seed_expand_count},
            priority="LOW",
            reason=f"覆盖率 {functional}% < {self.target}% 但无明确空洞，扩种",
        )

    def _with_experience(self, action: Action, fallback: Action = None) -> Action:
        """L4 记忆：附加动作历史效果说明；若历史证明无效且有 fallback，降级。

        决策逻辑保持确定性（规则先行），经验只做"增强"——无效动作降级，
        而不是让 LLM/经验直接拍板。
        """
        try:
            from src.core.growth import get_action_experience_note, is_action_proven_ineffective
            note = get_action_experience_note(action.action_type)
            if note:
                action.reason += note
            if fallback is not None and is_action_proven_ineffective(action.action_type):
                fallback.reason += f" [经验: {action.action_type} 历史证明无效，降级]"
                return fallback
        except Exception:
            pass
        return action

    def _is_stalled(self, history: List[float]) -> bool:
        """判断覆盖率是否停滞。"""
        if len(history) < self.stall_rounds + 1:
            return False
        recent = history[-(self.stall_rounds + 1):]
        growth = recent[-1] - recent[0]
        return growth < self.stall_threshold


# ═══════════════════════════════════════════════════════════════
# 动作 → 执行层 handler 映射
# ═══════════════════════════════════════════════════════════════

class ActionDispatcher:
    """把决策动作映射到执行层的具体操作。

    与 PipelineExecutionService 解耦，动作通过 Action 对象传递。
    """

    def __init__(self, service=None):
        self.service = service

    def dispatch(self, action: Action) -> dict:
        """执行动作，返回结果。"""
        handler = ACTION_HANDLERS.get(action.action_type)
        if not handler:
            return {"status": "unknown_action", "action": action.action_type}
        try:
            return handler(self, action)
        except Exception as e:
            return {"status": "error", "action": action.action_type, "error": str(e)[:200]}

    # ── 具体 handler ──
    def _generate_directed_test(self, action: Action) -> dict:
        """定向测试生成：回退 test agent 补 case"""
        return {"status": "dispatched", "rerun_phase": "test",
                "params": action.params, "reason": action.reason}

    def _expand_seeds(self, action: Action) -> dict:
        """随机种子扩增：带新 seed 重跑回归"""
        return {"status": "dispatched", "rerun_phase": "regress_cov",
                "params": action.params, "reason": action.reason}

    def _refactor_rtl(self, action: Action) -> dict:
        """设计回滚/重构：通知 rtl agent 修复死代码"""
        return {"status": "dispatched", "rerun_phase": "rtl",
                "params": action.params, "reason": action.reason,
                "fix": action.reason}

    def _retry_env(self, action: Action) -> dict:
        """环境自愈：重试编译/仿真"""
        return {"status": "dispatched", "retry_env": True,
                "params": action.params, "reason": action.reason}

    def _converge(self, action: Action) -> dict:
        """收敛：停止迭代"""
        return {"status": "converged", "final": action.params, "reason": action.reason}

    def _update_model(self, action: Action) -> dict:
        """更新参考模型：比对失败 → 通知 model agent 更新"""
        return {"status": "dispatched", "rerun_phase": "model",
                "params": action.params, "reason": action.reason}

    def _compile_retry(self, action: Action) -> dict:
        """编译失败自愈：触发自愈引擎，返回修复结果"""
        from src.core.compile_healer import CompileResult, CompileErrorType, CompileSelfHealer
        compile_err = action.params.get("compile_error", {})
        err = CompileResult(
            success=False,
            error_type=CompileErrorType(compile_err.get("error_type", "unknown")),
            error_message=compile_err.get("message", ""),
            error_file=compile_err.get("file"),
            error_line=compile_err.get("line"),
        )
        healer = CompileSelfHealer()
        heal = healer.heal(err)
        return {"status": "healed" if heal["fixed"] else "need_retry",
                "rerun_phase": "ops", "fix_actions": heal["actions"],
                "reason": action.reason}

    def _relax_constraint(self, action: Action) -> dict:
        """放宽约束：通知 verify agent 放宽 transaction 约束后重新生成/仿真"""
        return {"status": "dispatched", "rerun_phase": "verify",
                "params": action.params, "reason": action.reason}


ACTION_HANDLERS = {
    "COMPILE_RETRY":         ActionDispatcher._compile_retry,
    "UPDATE_MODEL":          ActionDispatcher._update_model,
    "GENERATE_DIRECTED_TEST": ActionDispatcher._generate_directed_test,
    "EXPAND_SEEDS":          ActionDispatcher._expand_seeds,
    "REFACTOR_RTL":          ActionDispatcher._refactor_rtl,
    "RETRY_ENV":             ActionDispatcher._retry_env,
    "RELAX_CONSTRAINT":      ActionDispatcher._relax_constraint,
    "CONVERGE":              ActionDispatcher._converge,
}


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def decide_next(observation: dict, target: float = 95.0) -> dict:
    """便捷入口：dict 入 dict 出。"""
    obs = Observation(
        iteration_id=observation.get("iteration_id", 0),
        coverage=observation.get("coverage", {}),
        uncovered_bins=observation.get("uncovered_bins", []),
        failed_tests=observation.get("failed_tests", []),
        dead_code_modules=observation.get("dead_code_modules", []),
        resource_usage=observation.get("resource_usage", {}),
        coverage_history=observation.get("coverage_history", []),
    )
    engine = CoverageDrivenDecisionEngine(target=target)
    action = engine.decide(obs)
    return action.to_dict()
