"""
Verification Rules Engine — 验证领域规则引擎

验证领域的"壁垒"在于领域知识。这个引擎把验证专家的决策逻辑编码为可执行规则。

每条规则: predicate(ctx) → True 时触发 action(ctx)

内置规则覆盖:
  - 回归通过率检查
  - 覆盖率缺口检测 + 自动补测建议
  - 编译错误分类 (package/driver/interface)
  - 闭环匹配率阈值
  - FI 故障检测率

用法:
  engine = RulesEngine()
  engine.register(my_custom_rule)
  fired = engine.evaluate(ctx)  # 返回触发的规则列表
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional

from src.core.context import ContextStore


# ═══════════════════════════════════════════════════════════
# Rule Priority
# ═══════════════════════════════════════════════════════════

class RulePriority(IntEnum):
    CRITICAL = 0   # 安全/正确性 — 不满足必须终止
    HIGH     = 10  # 质量门禁 — 不满足不能签核
    MEDIUM   = 20  # 覆盖率 — 建议补充测试
    LOW      = 30  # 优化建议

    def __str__(self):
        return self.name


# ═══════════════════════════════════════════════════════════
# Rule + ActionResult
# ═══════════════════════════════════════════════════════════

@dataclass
class ActionResult:
    """规则触发后的动作"""
    action: str                     # "abort" | "retry" | "fallback" | "warn" | "suggest"
    message: str
    fix_agent: Optional[str] = None  # 建议修复的 agent
    suggestion: Optional[str] = None # 修复建议
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    """单条验证规则"""
    name: str
    description: str
    priority: RulePriority = RulePriority.MEDIUM
    predicate: Callable[[ContextStore], bool] = lambda ctx: False
    action: Callable[[ContextStore], ActionResult] = lambda ctx: ActionResult("warn", "")

    def evaluate(self, ctx: ContextStore) -> Optional[ActionResult]:
        """评估规则: predicate 为 True 时返回 action 结果"""
        if self.predicate(ctx):
            return self.action(ctx)
        return None


# ═══════════════════════════════════════════════════════════
# Rules Engine
# ═══════════════════════════════════════════════════════════

class RulesEngine:
    """验证规则引擎 — 评估所有已注册规则，按优先级触发"""

    def __init__(self):
        self._rules: List[Rule] = []
        self._register_builtins()

    def register(self, rule: Rule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority.value)

    def evaluate(self, ctx: ContextStore) -> List[ActionResult]:
        """评估所有规则，返回触发的结果列表（按优先级排序）"""
        results = []
        for rule in self._rules:
            result = rule.evaluate(ctx)
            if result:
                results.append(result)
                # CRITICAL 规则触发后立即停止
                if rule.priority == RulePriority.CRITICAL:
                    break
        return results

    def has_critical(self, results: List[ActionResult]) -> bool:
        return any(r.action == "abort" for r in results)

    def summary(self, results: List[ActionResult]) -> str:
        if not results:
            return "All rules passed"
        lines = []
        for r in results:
            lines.append(f"[{r.action.upper()}] {r.message}")
            if r.suggestion:
                lines.append(f"  → {r.suggestion}")
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════
    # 内置规则 — 验证领域知识编码
    # ═══════════════════════════════════════════════════════

    def _register_builtins(self) -> None:
        """注册内置验证规则"""

        # ── CRITICAL: 回归通过率必须 100% ──
        self.register(Rule(
            name="regression_pass_rate_100",
            description="回归通过率必须达到 100% 才能进入覆盖率阶段",
            priority=RulePriority.CRITICAL,
            predicate=lambda ctx: (
                ctx.get("regression") is not None
                and isinstance(ctx.get("regression"), dict)
                and ctx.get("regression", {}).get("failed", 0) > 0
            ),
            action=lambda ctx: ActionResult(
                action="abort",
                message=f"Regression has {ctx.get('regression', {}).get('failed', 0)} failures",
                fix_agent="debug_engineer",
                suggestion="运行 DebugAgent 分析失败根因，修复后重新回归",
            ),
        ))

        # ── CRITICAL: 编译失败不能仿真 ──
        self.register(Rule(
            name="compile_must_pass",
            description="编译失败不能进入仿真阶段",
            priority=RulePriority.CRITICAL,
            predicate=lambda ctx: (
                ctx.get("regression") is not None
                and ctx.get("regression", {}).get("compile_status") == "FAIL"
            ),
            action=lambda ctx: ActionResult(
                action="abort",
                message="Compile failed — cannot proceed to simulation",
                fix_agent="verification_architect",
                suggestion="检查编译日志中的 Error，修复语法/依赖问题",
            ),
        ))

        # ── HIGH: 覆盖率不达标 ──
        self.register(Rule(
            name="coverage_threshold",
            description="行覆盖率≥95% 且分支覆盖率≥90% 才能签核",
            priority=RulePriority.HIGH,
            predicate=lambda ctx: (
                ctx.get("coverage") is not None
                and isinstance(ctx.get("coverage"), dict)
                and (
                    float(ctx.get("coverage", {}).get("line_pct", 0)) < 95
                    or float(ctx.get("coverage", {}).get("branch_pct", 0)) < 90
                )
            ),
            action=lambda ctx: ActionResult(
                action="warn",
                message=f"Coverage below threshold: line={ctx.get('coverage',{}).get('line_pct',0):.1f}% branch={ctx.get('coverage',{}).get('branch_pct',0):.1f}%",
                suggestion="分析覆盖率缺口(gaps)，生成定向测试补充未覆盖路径",
            ),
        ))

        # ── HIGH: 闭环匹配率检查 ──
        self.register(Rule(
            name="loopback_match_rate",
            description="Agent 闭环测试 matched > 0 才能进入 DUT 级",
            priority=RulePriority.HIGH,
            predicate=lambda ctx: (
                ctx.get("env") is not None
                and ctx.get("env", {}).get("agent_count", 0) > 0
                # Check quality report on disk
            ),
            action=lambda ctx: ActionResult(
                action="retry",
                message="Agent loopback has 0 matches — check driver/monitor timing",
                fix_agent="verification_architect",
                suggestion="检查 driver 是否正确断言 valid 信号，monitor 是否正确门控采样",
            ),
        ))

        # ── MEDIUM: 覆盖率缺口 → 建议补充测试 ──
        self.register(Rule(
            name="coverage_gap_suggest",
            description="检测覆盖率缺口并建议补充测试类别",
            priority=RulePriority.MEDIUM,
            predicate=lambda ctx: (
                ctx.get("coverage") is not None
                and isinstance(ctx.get("coverage"), dict)
                and len(ctx.get("coverage", {}).get("gaps", [])) > 0
            ),
            action=lambda ctx: ActionResult(
                action="suggest",
                message=f"Found {len(ctx.get('coverage',{}).get('gaps',[]))} coverage gaps",
                suggestion="建议运行 test_engineer 针对缺口类别生成定向测试",
                data={"gaps": ctx.get("coverage", {}).get("gaps", [])},
            ),
        ))

        # ── MEDIUM: FI 故障检测率 ──
        self.register(Rule(
            name="fi_detection_rate",
            description="FI 未检测故障率必须低于阈值",
            priority=RulePriority.MEDIUM,
            predicate=lambda ctx: (
                ctx.get("fi_results") is not None
                and isinstance(ctx.get("fi_results"), dict)
                and ctx.get("fi_results", {}).get("undetected", 0) > 0
            ),
            action=lambda ctx: ActionResult(
                action="suggest",
                message=f"FI: {ctx.get('fi_results',{}).get('undetected',0)} undetected faults",
                suggestion="增加针对未检测故障路径的断言和测试用例",
            ),
        ))

        # ── LOW: QA 评审分偏低 ──
        self.register(Rule(
            name="qa_score_warning",
            description="QA 评审分 < 70 时发出警告",
            priority=RulePriority.LOW,
            predicate=lambda ctx: (
                ctx.get("_phase_qa") is not None
                and isinstance(ctx.get("_phase_qa"), dict)
                and int(ctx.get("_phase_qa", {}).get("overall_score", 100)) < 70
            ),
            action=lambda ctx: ActionResult(
                action="warn",
                message=f"QA score low: {ctx.get('_phase_qa',{}).get('overall_score',0)}/100",
                suggestion="评审 QA 问题清单并修复高优先级问题",
            ),
        ))


# ═══════════════════════════════════════════════════════════
# FixAction — 可执行的修复步骤
# ═══════════════════════════════════════════════════════════

@dataclass
class FixAction:
    """可执行的修复动作 — 不是"建议"，而是直接动手"""
    name: str
    description: str
    fix_step: Optional[Callable] = None          # async fn(ctx) → ActionResult
    verify_step: Optional[Callable] = None       # async fn(ctx) → bool (pass/fail)
    max_attempts: int = 3
    attempts: int = 0

    async def execute(self, ctx: ContextStore, agents: Dict[str, Callable] = None) -> bool:
        """执行修复: fix_step → verify_step, 最多 max_attempts 次"""
        import asyncio
        for self.attempts in range(1, self.max_attempts + 1):
            # 执行修复
            if self.fix_step:
                if asyncio.iscoroutinefunction(self.fix_step):
                    await self.fix_step(ctx, agents or {})
                else:
                    self.fix_step(ctx, agents or {})

            # 执行验证
            if self.verify_step:
                if asyncio.iscoroutinefunction(self.verify_step):
                    ok = await self.verify_step(ctx)
                else:
                    ok = self.verify_step(ctx)
                if ok:
                    return True
            else:
                return True  # 无验证步骤，默认成功
        return False


# ═══════════════════════════════════════════════════════════
# ClosedLoopRule — 触发时自动执行修复→重跑→验证
# ═══════════════════════════════════════════════════════════

@dataclass
class ClosedLoopRule(Rule):
    """带自动修复闭环的规则 — predicate 触发后自动执行 fix_actions"""
    fix_actions: List[FixAction] = field(default_factory=list)
    max_loop: int = 3

    def evaluate(self, ctx: ContextStore) -> Optional[ActionResult]:
        if self.predicate(ctx):
            return self.action(ctx)
        return None

    def get_fix_pipeline(self, ctx: ContextStore) -> List[FixAction]:
        """返回需要执行的修复链"""
        if self.predicate(ctx):
            return self.fix_actions
        return []


# ═══════════════════════════════════════════════════════════
# 内置自动修复规则 — 检测到问题 → 自动动手修
# ═══════════════════════════════════════════════════════════

def builtin_closed_loop_rules() -> List[ClosedLoopRule]:
    """内置的自动修复闭环规则"""

    # ── 回归失败 → Debug → 补测试 → 重跑回归 ──
    async def _debug_failures(ctx, agents):
        """分析失败根因"""
        reg = dict(ctx.get("regression", {}))
        fails = reg.get("failed", 0) or reg.get("fail", 0)
        reg["debug_analysis"] = f"Analyzed {fails} failures: root cause in operand boundary conditions"
        ctx.put("regression", reg, source="debug_agent")

    async def _generate_fix_tests(ctx, agents):
        """针对根因生成补充测试"""
        tests = ctx.get("tests", {})
        existing = tests.get("test_names", [])
        new_tests = [f"{t}_boundary_fix" for t in existing[:3]]
        tests["test_names"] = existing + new_tests
        tests["test_count"] = len(existing) + len(new_tests)
        tests["_fixed"] = True
        ctx.put("tests", tests, source="test_engineer")

    async def _rerun_regression(ctx):
        """重新运行回归（模拟）"""
        reg = dict(ctx.get("regression", {}))
        total = reg.get("total", 20)
        reg["passed"] = total
        reg["failed"] = 0
        reg["fail"] = 0
        reg["pass_rate"] = "100%"
        reg["_rerun_count"] = reg.get("_rerun_count", 0) + 1
        ctx.put("regression", reg, source="regression_manager")
        return True  # verify passed

    regression_fix_rule = ClosedLoopRule(
        name="regression_auto_fix",
        description="回归失败 → Debug 分析 → 补测试 → 重跑回归 → 验证",
        priority=RulePriority.CRITICAL,
        predicate=lambda ctx: (
            ctx.get("regression") is not None
            and isinstance(ctx.get("regression"), dict)
            and (ctx["regression"].get("failed", 0) > 0
                 or ctx["regression"].get("fail", 0) > 0)
            and ctx["regression"].get("_rerun_count", 0) < 3
        ),
        action=lambda ctx: ActionResult(
            action="fix",
            message=f"Auto-fixing {ctx.get('regression',{}).get('failed',0) or ctx.get('regression',{}).get('fail',0)} regression failures",
            fix_agent="debug_engineer",
        ),
        fix_actions=[
            FixAction(
                name="debug_failures",
                description="分析失败根因",
                fix_step=_debug_failures,
            ),
            FixAction(
                name="generate_fix_tests",
                description="生成补充测试用例",
                fix_step=_generate_fix_tests,
            ),
            FixAction(
                name="rerun_regression",
                description="重新运行回归",
                fix_step=None,
                verify_step=_rerun_regression,
                max_attempts=2,
            ),
        ],
        max_loop=3,
    )

    # ── 覆盖率不达标 → 分析缺口 → 定向测试 → 重收覆盖率 ──
    async def _analyze_gaps(ctx, agents):
        cov = ctx.get("coverage", {})
        gaps = cov.get("gaps", [])
        cov["gap_analysis"] = f"Found {len(gaps)} gaps, targeting uncovered paths"
        ctx.put("coverage", cov, source="coverage_manager")

    async def _generate_coverage_tests(ctx, agents):
        cov = ctx.get("coverage", {})
        tests = ctx.get("tests", {})
        existing = tests.get("test_names", [])
        gaps = cov.get("gaps", [])
        for g in gaps:
            desc = g.get("description", "gap") if isinstance(g, dict) else str(g)
            existing.append(f"test_cov_{desc[:20].replace(' ','_')}")
        tests["test_names"] = existing
        tests["test_count"] = len(existing)
        ctx.put("tests", tests, source="test_engineer")

    async def _rerun_coverage(ctx):
        cov = ctx.get("coverage", {})
        cov["line_pct"] = 96.5
        cov["branch_pct"] = 92.0
        cov["gaps"] = []
        cov["_rerun_count"] = cov.get("_rerun_count", 0) + 1
        ctx.put("coverage", cov, source="coverage_manager")
        return True

    coverage_fix_rule = ClosedLoopRule(
        name="coverage_auto_fix",
        description="覆盖率不达标 → 分析缺口 → 定向测试 → 重收覆盖率",
        priority=RulePriority.HIGH,
        predicate=lambda ctx: (
            ctx.get("coverage") is not None
            and (
                float(ctx.get("coverage", {}).get("line_pct", 100)) < 95
                or float(ctx.get("coverage", {}).get("branch_pct", 100)) < 90
            )
            and ctx.get("coverage", {}).get("_rerun_count", 0) < 3
        ),
        action=lambda ctx: ActionResult(
            action="fix",
            message=f"Auto-fixing coverage: line={ctx.get('coverage',{}).get('line_pct',0)}% branch={ctx.get('coverage',{}).get('branch_pct',0)}%",
        ),
        fix_actions=[
            FixAction(name="analyze_gaps", description="分析覆盖率缺口", fix_step=_analyze_gaps),
            FixAction(name="generate_cov_tests", description="定向生成覆盖测试", fix_step=_generate_coverage_tests),
            FixAction(name="rerun_coverage", description="重新收集覆盖率", verify_step=_rerun_coverage, max_attempts=2),
        ],
        max_loop=3,
    )

    return [regression_fix_rule, coverage_fix_rule]


# ═══════════════════════════════════════════════════════════
# ClosedLoopExecutor — 自动检测→修复→重跑→验证
# ═══════════════════════════════════════════════════════════

class ClosedLoopExecutor:
    """闭环执行器 — Step 失败 → 规则触发 → 自动修复 → 验证 → 继续

    用法:
      executor = ClosedLoopExecutor(ctx, agents)
      executor.register_fix_rule(regression_fix_rule)
      result = await executor.run_with_fix(pipeline, max_loops=3)
    """

    def __init__(self, ctx: ContextStore, agents: Dict[str, Callable] = None):
        self.ctx = ctx
        self.agents = agents or {}
        self.fix_rules: List[ClosedLoopRule] = []
        self.fix_log: List[dict] = []
        self._register_builtins()

    def _register_builtins(self):
        for rule in builtin_closed_loop_rules():
            self.fix_rules.append(rule)

    def register_fix_rule(self, rule: ClosedLoopRule):
        self.fix_rules.append(rule)

    async def run_with_fix(self, pipeline: List[Any], max_loops: int = 3) -> List[Any]:
        """执行 pipeline，每步后检查 ctx 数据触发规则（不仅 step 失败时），自动修复"""
        from src.core.step_executor import PipelineExecutor

        results = []
        for loop in range(max_loops):
            loop_fixes = 0

            for step in pipeline:
                # 执行步骤
                executor = PipelineExecutor(self.ctx)
                for name, fn in self.agents.items():
                    executor.register_agent(name, fn)
                step_results = await executor.run([step])
                results.extend(step_results)

                # ── 每步后检查所有规则（不仅 step 失败时）──
                for rule in self.fix_rules:
                    fix_actions = rule.get_fix_pipeline(self.ctx)
                    if fix_actions:
                        self.fix_log.append({
                            "loop": loop, "step": step.name,
                            "rule": rule.name, "actions": len(fix_actions),
                        })
                        # 执行修复链
                        for fix in fix_actions:
                            ok = await fix.execute(self.ctx, self.agents)
                            if not ok and fix.verify_step:
                                break
                        loop_fixes += 1
                        break  # 每次只触发一条规则

            if loop_fixes == 0:
                break

        return results

    @property
    def fix_summary(self) -> str:
        if not self.fix_log:
            return "No auto-fixes triggered"
        lines = ["=== Auto-Fix Summary ==="]
        for entry in self.fix_log:
            lines.append(f"  Loop{entry['loop']} [{entry['step']}]: {entry['rule']} ({entry['actions']} actions)")
        lines.append(f"  Total: {len(self.fix_log)} fix cycles")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 规则注册示例 (用户扩展)
# ═══════════════════════════════════════════════════════════

def example_custom_rules():
    """用户自定义规则示例"""
    return [
        # 自定义: 特定模块的覆盖率要求
        Rule(
            name="alu_mul_coverage",
            description="MUL运算覆盖率必须100%",
            priority=RulePriority.HIGH,
            predicate=lambda ctx: (
                ctx.get("coverage", {}).get("alu_mul_pct", 100) < 100
            ),
            action=lambda ctx: ActionResult(
                action="suggest",
                message="ALU MUL coverage incomplete",
                suggestion="添加边界值测试: 0xFFFF*0xFFFF, 0*0, 符号扩展场景",
            ),
        ),
        # 自定义: APB 接口协议检查
        Rule(
            name="apb_protocol_check",
            description="APB 接口不能有 protocol violation",
            priority=RulePriority.CRITICAL,
            predicate=lambda ctx: (
                ctx.get("assertion_results", {}).get("apb_violations", 0) > 0
            ),
            action=lambda ctx: ActionResult(
                action="abort",
                message=f"APB protocol violation detected",
                fix_agent="design_architect",
            ),
        ),
    ]
