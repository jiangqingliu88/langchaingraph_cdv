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
from typing import Any, Dict, List, Optional, Protocol


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
    gap_paths: List[Dict] = field(default_factory=list)          # 语义路径（Knowledge Graph 溯源）: [{requirement, feature, module, signal, bin, test, suggestion}]


@dataclass
class Action:
    """决策层下发给执行层的动作"""
    # 动作全集：与 decide() 实际产出、execution.py 的动作分支一一对应
    # 改设计/改模型的动作用 `FIX_<类别>_bug` —— 名字本身就说明修的哪一类问题
    action_type: str          # FIX_COMPILE_bug | FIX_MODEL_bug | FIX_FUNCTIONAL_bug |
                              # FIX_PROTOCOL_bug | FIX_DEADCODE_bug | EXPAND_SEEDS |
                              # RELAX_CONSTRAINT | GENERATE_DIRECTED_TEST | CONVERGE
    params: Dict[str, Any] = field(default_factory=dict)
    priority: str = "MEDIUM"
    max_retries: int = 3
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# 决策引擎
# ═══════════════════════════════════════════════════════════════

class ExperienceProvider(Protocol):
    """动作经验查询 —— **L3 定义接口，L5 提供实现，L2 负责装配**。

    为什么要有这层接口，而不是直接 `from ...l5_evolution.growth import ...`：
        `l5_evolution` 在 L3 **之上**。L3 直接 import 它就是**越级反向依赖**
        （原来是靠函数体内延迟 import 遮着的）。反了的话，决策引擎就没法脱离
        进化层单独跑 —— 而它全是确定性规则，是最该能单独测的那一块。

    实现方：`src/layers/l5_evolution/growth.py` 的 `experience_provider`。
    """

    def note(self, action_type: str) -> str:
        """这个动作的历史效果说明（没有就返回空串）。"""
        ...

    def ineffective(self, action_type: str) -> bool:
        """历史是否证明这个动作无效（用于降级到 fallback）。"""
        ...


class CoverageDrivenDecisionEngine:
    """覆盖率驱动决策状态机。

    动作优先级: 环境失败 > 覆盖率停滞 > 覆盖率空洞 > 死代码 > 达标收敛
    """

    def __init__(self, target: float = 95.0, stall_threshold: float = 1.0,
                 stall_rounds: int = 2, seed_expand_count: int = 1000,
                 experience: "ExperienceProvider" = None):
        self.target = target
        self.stall_threshold = stall_threshold     # 多轮增长 < 此值视为停滞
        self.stall_rounds = stall_rounds           # 连续 N 轮停滞才触发扩种
        self.seed_expand_count = seed_expand_count
        #: 动作经验查询 —— **不 import L5**，由 L2 装配时注入（见 `ExperienceProvider`）。
        #: 不注入就是"没有经验可参考"，决策照常走规则 —— 那是合法的降级，
        #: 不是错误（决策引擎本来就是规则先行，经验只做增强）。
        self._experience = experience

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
                action_type=FIX_COMPILE,
                params={"compile_error": compile_err},
                priority="HIGH",
                reason=f"编译失败({compile_err.get('error_type','unknown')})，触发自愈",
            )

        # ── 0. 比对失败 → 更新参考模型 ──
        if mismatch:
            return Action(
                action_type=FIX_MODEL,
                params={"mismatch_info": mismatch},
                priority="HIGH",
                reason=f"比对失败 {len(mismatch)} 处，疑似模型过时，更新参考模型",
            )

        # ── 1. 功能回归失败 → 改 RTL（scoreboard mismatch 说明 DUT 功能错，重试环境无意义）──
        #     动作名带上**哪一类 bug**（功能 / 协议时序），见 `classify_fix_bug`
        if failed:
            kind = classify_fix_bug(observation)
            return Action(
                action_type=kind,
                params={"failed_tests": failed},
                priority="HIGH",
                reason=f"{len(failed)} 个测试失败（{kind}），改 RTL",
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
            # 3z. 优先：Knowledge Graph 语义路径（gap_paths）给出精确归因
            #     "REQ_xxx 的 bin 已有测试但约束过紧 → RELAX_CONSTRAINT" 而非泛泛 GENERATE_TEST
            if observation.gap_paths:
                semantic = self._decide_from_semantics(observation.gap_paths, functional)
                if semantic:
                    return semantic
            gaps = observation.gaps or []
            # 3a. 不可达/死代码 → 改 RTL（最高，因为不是"补测"能解决的）
            unreachable = [g for g in gaps if g.get("reason") == "unreachable"]
            if unreachable:
                return Action(
                    action_type=FIX_DEADCODE,
                    params={"gaps": unreachable},
                    priority="HIGH",
                    reason=f"发现 {len(unreachable)} 处不可达/死代码，需改 RTL",
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
                # ⚠️ **必须给 fallback**：`_with_experience` 的"无效就降级"是
                # **有 fallback 才生效**的，而这里原来没给 —— 于是"该动作历史
                # 79 次尝试、改善率 4%"被算出来、写进 reason，然后**照选不误**。
                # 实测：闭环六轮每轮都选它，覆盖率每轮钉在 56.2。
                return self._with_experience(Action(
                    action_type="GENERATE_DIRECTED_TEST",
                    params={"gaps": unstimulated},
                    priority="HIGH",
                    reason=f"覆盖率 {functional}% < {self.target}%，存在 {len(unstimulated)} 处未激励缺口，生成定向测试",
                ), self.expand_seeds_action())
            # 3d. 旧接口 uncovered_bins → 定向测试
            if uncovered:
                return Action(
                    action_type="GENERATE_DIRECTED_TEST",
                    params={"target_bins": uncovered[:20]},
                    priority="HIGH",
                    reason=f"覆盖率 {functional}% < {self.target}%，存在 {len(uncovered)} 个未覆盖 bin",
                )

        # ── 4. 死代码（旧接口 dead_code_modules）→ 改 RTL ──
        if dead:
            return Action(
                action_type=FIX_DEADCODE,
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

    def _decide_from_semantics(self, gap_paths: List[Dict], functional: float) -> Optional[Action]:
        """从 Knowledge Graph 语义路径决定动作。

        有测试但 bin 未命中 → RELAX_CONSTRAINT；无测试 → GENERATE_DIRECTED_TEST。
        无语义归属（INVESTIGATE）返回 None，交回规则层兜底。
        """
        relax = [g for g in gap_paths if g.get("suggestion") == "RELAX_CONSTRAINT"]
        directed = [g for g in gap_paths if g.get("suggestion") == "GENERATE_DIRECTED_TEST"]
        if relax:
            return Action(
                action_type="RELAX_CONSTRAINT",
                params={"gaps": relax},
                priority="HIGH",
                reason=f"语义归因：{len(relax)} 个 bin 已有测试但约束过紧"
                       f"（{self._semantic_reason(relax)}）",
            )
        if directed:
            return Action(
                action_type="GENERATE_DIRECTED_TEST",
                params={"gaps": directed},
                priority="HIGH",
                reason=f"语义归因：{len(directed)} 个 bin 无覆盖测试"
                       f"（{self._semantic_reason(directed)}）",
            )
        return None

    @staticmethod
    def _semantic_reason(gap_paths: List[Dict]) -> str:
        """把语义路径压缩成可读归因。"""
        parts = []
        for g in gap_paths[:3]:
            feat = g.get("feature")
            target = g.get("bin") or g.get("signal")
            if feat and target:
                parts.append(f"{feat}.{target}")
        return "；".join(parts) if parts else "（未映射）"

    def expand_seeds_action(self) -> Action:
        """**无效动作的替代**：扩种（换随机流）。

        为什么固定是它：扩种与"补定向"是**不同手段**（换随机流 vs 补特定组合），
        且无前置条件（任何时候都做得了）。被降级的动作本身就是扩种时，
        `_with_experience` 不会再往下降（见那里的判断），所以不会自指。
        """
        return Action(
            action_type="EXPAND_SEEDS",
            params={"count": self.seed_expand_count},
            priority="MEDIUM",
            reason="扩种：换一批随机流（覆盖率停滞，且原动作历史已证明无效）",
        )

    def with_experience(self, action: Action, fallback: Action = None) -> Action:
        """公开入口 —— **决策层两条路径共用这一个降级机制**。

        brain 的 RL 覆盖路径原来自己重写了一遍同样的判断，而那条路顺手
        `import l5_evolution`（越级反向依赖，被层向测试抓到）。机制只有这一处，
        装配（谁提供经验）由 L2 注入。
        """
        return self._with_experience(action, fallback)

    def _with_experience(self, action: Action, fallback: Action = None) -> Action:
        """记忆：附加动作历史效果说明；若历史证明无效且有 fallback，降级。

        决策逻辑保持确定性（规则先行），经验只做"增强"——无效动作降级，
        而不是让 LLM/经验直接拍板。

        经验从哪来是**注入**的（`ExperienceProvider`）—— 本模块不 import
        `l5_evolution`（那是越级反向依赖）。没注入就跳过，决策照常。
        """
        if self._experience is None:
            return action
        try:
            note = self._experience.note(action.action_type)
            if note:
                action.reason += note
            if fallback is not None and self._experience.ineffective(action.action_type):
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

    def _converge(self, action: Action) -> dict:
        """收敛：停止迭代"""
        return {"status": "converged", "final": action.params, "reason": action.reason}

    def _update_model(self, action: Action) -> dict:
        """更新参考模型：比对失败 → 通知 model agent 更新"""
        return {"status": "dispatched", "rerun_phase": "model",
                "params": action.params, "reason": action.reason}

    def _compile_retry(self, action: Action) -> dict:
        """编译失败自愈：触发自愈引擎，返回修复结果"""
        from src.layers.l1_infrastructure.compile_healer import CompileResult, CompileErrorType, CompileSelfHealer
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

#: **改设计的动作都要说清"修的是哪一类 bug"**。
#:
#: 原来三种完全不同的情况都叫 `REFACTOR_RTL`：编译不过、功能不符、死代码 ——
#: 于是在决策轨迹、证据链、界面上长得一模一样，复盘时读不出"这一轮为什么动
#: 设计、动的是哪一类问题"。分类之后 `fix_*` 名字本身就是结论：
#:
#:   FIX_COMPILE_bug    编译/elaboration 不过（改某个编译不过的文件）
#:   FIX_MODEL_bug      参考模型过时（改的是模型，**没动 RTL**）
#:   FIX_FUNCTIONAL_bug 功能不符：测试挂 / scoreboard 比对失败
#:   FIX_PROTOCOL_bug   协议/时序：握手、反压、时钟复位类失败
#:   FIX_DEADCODE_bug   死代码 / 不可达
FIX_COMPILE = "FIX_COMPILE_bug"
FIX_MODEL = "FIX_MODEL_bug"
FIX_FUNCTIONAL = "FIX_FUNCTIONAL_bug"
FIX_PROTOCOL = "FIX_PROTOCOL_bug"
FIX_DEADCODE = "FIX_DEADCODE_bug"
FIX_CDC = "FIX_CDC_bug"
FIX_RESET = "FIX_RESET_bug"

#: **根因 → 验证计划**。第三维（验证方式）是这三轴里唯一**能驱动行为**的一轴 ——
#: 它决定"这次改动要跑多少、还要补什么验证"，而不是只留个标签。
#:
#: 依据是各类 bug 的**破坏面**与**该有的证据**：
#:   · CDC 破坏面最广（跨时钟信号谁都在用）→ 强制全量重跑
#:   · 协议/复位类有现成的定向用例（tag）→ 必须带上，否则"修没修好"无从判断
#:   · 编译/编码类只需要编译门禁 → 不必全仿真
#:   · 功能类按改动面决定（默认路径）
#: `needs_human` 留给"机器判不了"的场合：CDC 有没有同步器，得人看一眼。
VERIFICATION_PLANS = {
    FIX_CDC: {"scope": "full", "tags": "", "extra": ["cdc_review"],
              "needs_human": True,
              "why": "CDC 破坏面最广（跨时钟信号谁都在用），且同步器是否正确机器判不了"},
    FIX_RESET: {"scope": "tagged", "tags": "reset,rst", "extra": [],
                "needs_human": False,
                "why": "复位类必须带上复位定向用例，否则修没修好无从判断"},
    FIX_PROTOCOL: {"scope": "tagged", "tags": "handshake,backpressure,protocol",
                   "extra": ["sva"], "needs_human": False,
                   "why": "协议类要有握手/背压定向用例 + 时序断言"},
    FIX_COMPILE: {"scope": "compile", "tags": "", "extra": [], "needs_human": False,
                  "why": "编译/编码类只需编译门禁，不必全仿真"},
    FIX_DEADCODE: {"scope": "human", "tags": "", "extra": [], "needs_human": True,
                   "why": "死代码/不可达是否真不可达是设计知识，机器判不了"},
    FIX_FUNCTIONAL: {"scope": "by_change", "tags": "", "extra": [],
                     "needs_human": False,
                     "why": "功能类按改动面决定重跑范围（默认路径）"},
}


#: **「改 RTL」这一族** —— 对决策（尤其对 RL）来说它们是**同一件事**：
#: "要不要动设计"。至于"是哪一类 bug"，必须由**证据**定（`classify_fix_bug`）。
#:
#: 为什么单独拎出来：这五个名字一旦各自进 RL 的动作空间，RL 就会**挑标签** ——
#: 而它没有任何证据能区分复位/协议/CDC，挑出来的是猜的。标签又顺着验证计划
#: 决定"跑哪些 tag、要不要全量"，猜错就把验证带偏（实测：一轮里 RL 选出
#: `FIX_RESET_bug`，而那轮的证据里一个复位线索都没有）。
FIX_FAMILY = (FIX_FUNCTIONAL, FIX_PROTOCOL, FIX_RESET, FIX_CDC, FIX_DEADCODE)


def rl_action(name: str) -> str:
    """动作名 → **RL 记账用的名字**：改 RTL 那一族折叠成一个代表。

    RL 学的是"这个状态下该不该动设计"，不是"这是哪一类 bug"。折叠之后：
    Q 表里一族只有一条经验（而不是五条互相抢），老名字 `REFACTOR_RTL`
    经 `canonical_action` 也落进同一条。
    """
    name = canonical_action(name)
    return FIX_FUNCTIONAL if name in FIX_FAMILY else name


def verification_plan(action_type: str) -> Dict[str, Any]:
    """根因 → 验证计划。未知根因按功能类（最保守的默认路径）。

    返回 `{scope, tags, extra, needs_human, why}`：
      scope      `full` 全量 / `tagged` 只跑这些 tag / `by_change` 按改动面 /
                 `compile` 只编译 / `human` 交人
      extra      还要补的验证（`sva` 时序断言 / `cdc_review` 人工审同步器）
      needs_human 这一步机器给不出可信结论
    """
    plan = VERIFICATION_PLANS.get(canonical_action(action_type))
    if plan is None:
        plan = VERIFICATION_PLANS[FIX_FUNCTIONAL]
    return dict(plan)

#: 老名字 → 新名字。**读的时候必须认**：RL 策略文件（`.signoffai/rl_policy.json`）
#: 里存的是老名字，历史运行的轨迹、还有测试里都还在用。
LEGACY_ACTIONS = {
    "REFACTOR_RTL": FIX_FUNCTIONAL,   # 老名字分不出类别，按最常见的功能错归类
    "COMPILE_RETRY": FIX_COMPILE,
    "UPDATE_MODEL": FIX_MODEL,
}


def canonical_action(name: str) -> str:
    """动作名归一 —— 老名字映射到分类名，新名字原样返回。"""
    return LEGACY_ACTIONS.get(name, name)


#: 各类失败的**点击词** —— 用例名与失败证据里出现就算。顺序即优先级：
#: CDC 先于协议（`async_fifo_handshake` 两个词都有，但它首先是跨时钟问题），
#: 复位先于协议（`reset_handshake` 同理）。
#:
#: 宁可归到 `FIX_FUNCTIONAL_bug`（默认类）也不要乱归：分类影响**命名与验证计划**
#: （跑多少、补什么验证），判错了会让验证计划偏。
_CDC_TOKENS = ("cdc", "async_fifo", "asyncfifo", "gray", "cross_clock", "跨时钟",
               "同步器", "synchronizer", "two_flop", "双拍")
_RESET_TOKENS = ("reset", "rst", "复位")
_PROTOCOL_TOKENS = ("handshake", "protocol", "握手", "时序", "timing",
                    "backpressure", "反压", "ready", "valid", "timeout", "超时")


def classify_fix_bug(observation: "Observation") -> str:
    """「这次改 RTL 修的是哪一类 bug」—— **从已有证据分类，不猜**。

    顺序从确定到不确定：

      编译错误 → 可综合/编码类（有 `CompileErrorAnalyzer` 的错误类型，是确认的）
      不可达/死代码 → 死代码类（有覆盖率 0% 的 metric/bin，也是确认的）
      点击词（CDC > 复位 > 协议）→ 对应类
      其余 → 功能类（默认，也是最不需要额外证据的一类）

    **判不出来的不硬塞**：功能类是诚实的默认值，不是垃圾桶 —— 它的验证计划
    （按改动面决定重跑范围）本来就是最保守的那条路。
    """
    if observation.compile_error:
        return FIX_COMPILE
    if observation.dead_code_modules:
        return FIX_DEADCODE
    for gap in observation.gaps or []:
        if isinstance(gap, dict) and gap.get("reason") == "unreachable":
            return FIX_DEADCODE

    evidence = " ".join(str(t) for t in (observation.failed_tests or [])).lower()
    evidence += " " + str(observation.model_mismatch or "")[:200].lower()
    for tokens, kind in ((_CDC_TOKENS, FIX_CDC),
                         (_RESET_TOKENS, FIX_RESET),
                         (_PROTOCOL_TOKENS, FIX_PROTOCOL)):
        if any(tok in evidence for tok in tokens):
            return kind
    return FIX_FUNCTIONAL



# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════



# 动作全集 —— 全项目唯一来源。
# 此前有三份互不同步的动作清单：本文件的 ACTION_HANDLERS、rl_policy 的
# SOFT_ACTIONS（4 个）、以及 execution 里的 if/elif 分支。任何一份漏改都会
# 造成「决策层发出了执行层不认的动作」这类只在运行期暴露的问题。
ALL_ACTIONS = (
    FIX_COMPILE,              # 编译/elaboration 不过 → 自愈
    FIX_MODEL,                # 比对失败 → 更新参考模型
    FIX_FUNCTIONAL,           # 功能不符（测试挂 / 比对不一致）→ 改 RTL
    FIX_PROTOCOL,             # 协议/时序类失败 → 改 RTL
    FIX_RESET,                # 复位类失败 → 改 RTL
    FIX_CDC,                  # 跨时钟/CDC → 改 RTL（破坏面最广，强制全量重跑）
    FIX_DEADCODE,             # 死代码 / 不可达 → 改 RTL
    "EXPAND_SEEDS",           # 覆盖率停滞 → 扩种
    "RELAX_CONSTRAINT",       # 约束过紧 → 放宽
    "GENERATE_DIRECTED_TEST", # 激励不足 → 定向补测
    "CONVERGE",               # 达标 → 收敛（确定性终态）
)
# 注：原 "RETRY_ENV" 条目已移除——decide() 从不产生该动作（编译失败走
# COMPILE_RETRY，见 infrastructure.py:244 "而非 RETRY_ENV"），execution.py
# 的动作分支里也没有它，保留只会让动作全集看起来比实际多一个。
ACTION_HANDLERS = {
    FIX_COMPILE:             ActionDispatcher._compile_retry,
    FIX_MODEL:               ActionDispatcher._update_model,
    "GENERATE_DIRECTED_TEST": ActionDispatcher._generate_directed_test,
    "EXPAND_SEEDS":          ActionDispatcher._expand_seeds,
    # 改 RTL 的三类走同一个分发器 —— 分类只影响**命名与重跑范围**，
    # 不改变"谁去改、怎么改"（都在 design agent 的 `fix_agent=rtl` 那条路）
    FIX_FUNCTIONAL:          ActionDispatcher._refactor_rtl,
    FIX_PROTOCOL:            ActionDispatcher._refactor_rtl,
    FIX_RESET:               ActionDispatcher._refactor_rtl,
    FIX_CDC:                 ActionDispatcher._refactor_rtl,
    FIX_DEADCODE:            ActionDispatcher._refactor_rtl,
    "RELAX_CONSTRAINT":      ActionDispatcher._relax_constraint,
    "CONVERGE":              ActionDispatcher._converge,
}

# 硬失败类：由规则引擎确定性处理，RL 不参与
HARD_ACTIONS = (FIX_COMPILE, FIX_MODEL)
# 终态：达标收敛，不属于 RL 的动作空间
TERMINAL_ACTIONS = ("CONVERGE",)

# 构图期自检：handler 表必须与动作全集一一对应
if set(ACTION_HANDLERS) != set(ALL_ACTIONS):
    raise ValueError(
        "ACTION_HANDLERS 与 ALL_ACTIONS 不一致："
        f"仅前者有 {sorted(set(ACTION_HANDLERS) - set(ALL_ACTIONS))}；"
        f"仅后者有 {sorted(set(ALL_ACTIONS) - set(ACTION_HANDLERS))}"
    )


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
        gaps=observation.get("gaps", []),
        gap_paths=observation.get("gap_paths", []),
    )
    engine = CoverageDrivenDecisionEngine(target=target)
    action = engine.decide(obs)
    return action.to_dict()


async def enrich_observation(observation: Observation, spec: dict) -> Observation:
    """用 Verification Knowledge Graph 给 Observation 补语义路径（gap_paths）。

    优先从持久化表载入设计时子图（跨 run 沉淀），空则从 spec 重建；
    再把 uncovered_bins / gaps 溯源成 requirement/feature/module/test 归因，
    供 decide() 的语义分支做精准决策。

    用法:
        observation = await enrich_observation(observation, spec_json)
    """
    if not spec or not isinstance(spec, dict):
        return observation
    try:
        from src.tools.spec_tools.verify_dsl import build_graph_from_spec
        from src.layers.l3_decision.knowledge.query import find_gap_contexts
        # spec 建全图（含运行时 coverage_bin），DB 作补充（跨 run 的 bug/fix 等）
        graph = build_graph_from_spec(spec)
        try:
            from src.layers.l3_decision.knowledge.persistence import load_graph_from_db
            db_graph = await load_graph_from_db()
            if db_graph is not None and len(db_graph) > 0:
                graph.merge(db_graph)
        except Exception:
            pass

        raw_gaps = []
        for b in observation.uncovered_bins or []:
            raw_gaps.append({"bin": b} if isinstance(b, str) else b)
        for g in observation.gaps or []:
            raw_gaps.append(g)
        if raw_gaps:
            observation.gap_paths = find_gap_contexts(graph, raw_gaps)
    except Exception:
        # 图构建/加载失败不阻断决策，gap_paths 保持空，退化为纯规则决策
        pass
    return observation
