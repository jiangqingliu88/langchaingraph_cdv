"""
规则变更影响评估 — DependencyTracker + BlastRadius + RuleVersioning

三个核心能力:
  1. RuleRegistry — 所有可配置规则/阈值/模板的集中注册
  2. DependencyTracker — 规则→项目→流程的依赖关系追踪
  3. ImpactAnalyzer — 变更前自动计算影响范围（Blast Radius）

用法:
  from src.infra.impact_analyzer import RuleRegistry, ImpactAnalyzer

  registry = RuleRegistry()
  registry.register_rule("coverage.line_threshold", value=85,
                         affects=["pipeline.coverage_check", "signoff.coverage_gate"])

  analyzer = ImpactAnalyzer(registry)
  report = analyzer.analyze_change("coverage.line_threshold", new_value=90)
  # → {affected_projects: 5, affected_signoffs: 12, risk: "medium", ...}
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import json


# ═══════════════════════════════════════════════════════════
# 1. 规则注册中心
# ═══════════════════════════════════════════════════════════

class RuleCategory(str, Enum):
    COVERAGE = "coverage"
    SCORE = "score"
    THRESHOLD = "threshold"
    WORKFLOW = "workflow"
    TEMPLATE = "template"
    SECURITY = "security"


@dataclass
class Rule:
    """可配置规则"""
    rule_id: str
    name: str
    description: str
    category: RuleCategory
    current_value: Any
    default_value: Any
    affects: List[str] = field(default_factory=list)        # 影响的功能点
    dependent_rules: List[str] = field(default_factory=list) # 依赖的其他规则
    usage_count: int = 0                                      # 被引用次数
    last_changed: str = ""
    change_history: List[dict] = field(default_factory=list)  # 变更历史
    version: int = 1


@dataclass
class RuleChange:
    """一次规则变更记录"""
    rule_id: str
    old_value: Any
    new_value: Any
    changed_by: str
    reason: str
    timestamp: str
    version_before: int
    version_after: int
    blast_radius: dict = field(default_factory=dict)


class RuleRegistry:
    """规则注册中心 — 所有可配置规则的唯一真实来源"""

    def __init__(self):
        self._rules: Dict[str, Rule] = {}
        self._change_log: List[RuleChange] = []
        self._register_defaults()

    def _register_defaults(self):
        """注册所有默认规则"""
        defaults = [
            Rule("coverage.line_threshold", "行覆盖率阈值", "代码行覆盖率最低要求",
                 RuleCategory.COVERAGE, 85, 85,
                 affects=["pipeline.coverage_check", "signoff.coverage_gate", "quality_report"]),
            Rule("coverage.branch_threshold", "分支覆盖率阈值", "分支覆盖率最低要求",
                 RuleCategory.COVERAGE, 75, 75,
                 affects=["pipeline.coverage_check", "signoff.coverage_gate"]),
            Rule("coverage.toggle_threshold", "翻转覆盖率阈值", "翻转覆盖率最低要求",
                 RuleCategory.COVERAGE, 60, 60,
                 affects=["pipeline.coverage_check"]),
            Rule("score.pass_threshold", "综合评分通过线", "综合评分 >= 此值才算 completed",
                 RuleCategory.SCORE, 70, 70,
                 affects=["pipeline.completion_check", "signoff.readiness_check"]),
            Rule("score.phase_min", "单阶段最低评分", "每个 phase 的最低通过评分",
                 RuleCategory.SCORE, 50, 50,
                 affects=["pipeline.phase_pass"]),
            Rule("regression.pass_rate_threshold", "回归通过率阈值", "回归测试通过率最低要求",
                 RuleCategory.THRESHOLD, 90, 90,
                 affects=["signoff.regression_gate", "quality_report"]),
            Rule("signoff.max_pending_hours", "签核最大待审时间", "签核超过此时长自动 escalation",
                 RuleCategory.THRESHOLD, 48, 48,
                 affects=["signoff.escalation", "notification"]),
            Rule("pipeline.max_duration_minutes", "流水线最大执行时间", "流水线超过此时长告警",
                 RuleCategory.THRESHOLD, 120, 120,
                 affects=["pipeline.monitoring"]),
            Rule("evidence.min_phases_for_signoff", "签核最少阶段数", "签核要求的流水线最少阶段数",
                 RuleCategory.THRESHOLD, 5, 5,
                 affects=["signoff.evidence_gate"]),
            Rule("workflow.mandatory_phases", "强制阶段列表", "必须全部通过的 phase 列表",
                 RuleCategory.WORKFLOW, ["spec", "design", "vplan", "UVM", "cover"],
                 ["spec", "design", "vplan", "UVM", "cover"],
                 affects=["pipeline.phase_execution", "signoff.readiness_check"]),
        ]
        for rule in defaults:
            self._rules[rule.rule_id] = rule

    def register_rule(self, rule_id: str, name: str = "", description: str = "",
                      category: RuleCategory = RuleCategory.THRESHOLD,
                      value: Any = None, affects: List[str] = None,
                      dependent_rules: List[str] = None) -> Rule:
        if rule_id in self._rules:
            return self._rules[rule_id]
        rule = Rule(
            rule_id=rule_id, name=name or rule_id, description=description,
            category=category, current_value=value, default_value=value,
            affects=affects or [], dependent_rules=dependent_rules or [],
            last_changed=datetime.now().isoformat(),
        )
        self._rules[rule_id] = rule
        return rule

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        return self._rules.get(rule_id)

    def get_all_rules(self) -> List[Rule]:
        return list(self._rules.values())

    def get_rules_by_category(self, category: RuleCategory) -> List[Rule]:
        return [r for r in self._rules.values() if r.category == category]

    def get_rules_affecting(self, target: str) -> List[Rule]:
        """获取影响某功能点的所有规则"""
        return [r for r in self._rules.values() if target in r.affects]

    def change_rule(self, rule_id: str, new_value: Any, changed_by: str,
                    reason: str, dry_run: bool = False) -> RuleChange:
        """变更规则 — 记录历史"""
        rule = self._rules.get(rule_id)
        if not rule:
            raise ValueError(f"规则不存在: {rule_id}")

        old_value = rule.current_value
        change = RuleChange(
            rule_id=rule_id, old_value=old_value, new_value=new_value,
            changed_by=changed_by, reason=reason,
            timestamp=datetime.now().isoformat(),
            version_before=rule.version, version_after=rule.version + 1,
        )

        if not dry_run:
            rule.current_value = new_value
            rule.version += 1
            rule.last_changed = change.timestamp
            rule.change_history.append({
                "version": rule.version, "old": old_value, "new": new_value,
                "changed_by": changed_by, "reason": reason,
                "timestamp": change.timestamp,
            })
            self._change_log.append(change)
            if len(self._change_log) > 200:
                self._change_log = self._change_log[-200:]

        return change

    def rollback_rule(self, rule_id: str, target_version: int, changed_by: str) -> Optional[RuleChange]:
        """回退规则到指定版本"""
        rule = self._rules.get(rule_id)
        if not rule:
            return None
        # 查找目标版本的 value
        for entry in reversed(rule.change_history):
            if entry["version"] == target_version:
                return self.change_rule(rule_id, entry["old"], changed_by,
                                        f"回退到版本 {target_version}")
        return None

    def get_change_history(self, rule_id: str = None, limit: int = 30) -> List[dict]:
        if rule_id:
            rule = self._rules.get(rule_id)
            return rule.change_history[-limit:] if rule else []
        return [{
            "rule_id": c.rule_id, "old": c.old_value, "new": c.new_value,
            "changed_by": c.changed_by, "reason": c.reason,
            "timestamp": c.timestamp, "version": c.version_after,
        } for c in self._change_log[-limit:]]


# ═══════════════════════════════════════════════════════════
# 2. 依赖追踪器
# ═══════════════════════════════════════════════════════════

@dataclass
class Dependency:
    """依赖关系"""
    source: str            # 依赖方 (规则/模板/模块)
    target: str            # 被依赖方
    dep_type: str          # uses / extends / triggers / constrains
    strength: str = "strong"  # strong (必须) / weak (建议)


class DependencyTracker:
    """依赖关系追踪器 — 构建完整的规则-项目-流程依赖图"""

    def __init__(self, registry: RuleRegistry):
        self.registry = registry
        self._dependencies: List[Dependency] = []
        self._project_usage: Dict[str, Set[str]] = {}  # rule_id → {project_ids}
        self._signoff_usage: Dict[str, Set[int]] = {}  # rule_id → {signoff_ids}

    def add_dependency(self, source: str, target: str, dep_type: str = "uses",
                       strength: str = "strong"):
        self._dependencies.append(Dependency(source, target, dep_type, strength))

    def record_usage(self, rule_id: str, project_id: str = None, signoff_id: int = None):
        """记录规则被哪个项目/签核使用"""
        if project_id:
            if rule_id not in self._project_usage:
                self._project_usage[rule_id] = set()
            self._project_usage[rule_id].add(project_id)
            rule = self.registry.get_rule(rule_id)
            if rule:
                rule.usage_count += 1
        if signoff_id:
            if rule_id not in self._signoff_usage:
                self._signoff_usage[rule_id] = set()
            self._signoff_usage[rule_id].add(signoff_id)

    def get_dependents(self, rule_id: str) -> List[Dependency]:
        """获取依赖此规则的所有依赖方"""
        return [d for d in self._dependencies if d.target == rule_id]

    def get_dependencies(self, rule_id: str) -> List[Dependency]:
        """获取此规则依赖的所有目标"""
        return [d for d in self._dependencies if d.source == rule_id]

    def get_dependency_graph(self) -> dict:
        """导出完整的依赖图"""
        graph = {"nodes": [], "edges": []}
        node_ids = set()
        for dep in self._dependencies:
            graph["edges"].append({
                "source": dep.source, "target": dep.target,
                "type": dep.dep_type, "strength": dep.strength,
            })
            node_ids.add(dep.source)
            node_ids.add(dep.target)
        for nid in node_ids:
            rule = self.registry.get_rule(nid)
            graph["nodes"].append({
                "id": nid, "name": rule.name if rule else nid,
                "category": rule.category.value if rule else "unknown",
                "usages": self._project_usage.get(nid, set()),
            })
        return graph


# ═══════════════════════════════════════════════════════════
# 3. 影响分析器 (Blast Radius)
# ═══════════════════════════════════════════════════════════

class ChangeRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ImpactReport:
    """变更影响报告"""
    rule_id: str
    rule_name: str
    old_value: Any
    new_value: Any
    risk: ChangeRisk
    affected_projects: int
    affected_signoffs: int
    affected_rules: List[str]        # 受影响的其他规则
    affected_functions: List[str]    # 受影响的功能点
    dependent_rules: List[str]       # 依赖此规则的规则
    recommendations: List[str]
    requires_approval: bool
    rollback_plan: str


class ImpactAnalyzer:
    """变更影响分析器 — 改前计算 Blast Radius"""

    def __init__(self, registry: RuleRegistry, tracker: DependencyTracker = None):
        self.registry = registry
        self.tracker = tracker or DependencyTracker(registry)

    def analyze_change(self, rule_id: str, new_value: Any,
                       changed_by: str = "", reason: str = "") -> ImpactReport:
        """分析规则变更的影响范围"""
        rule = self.registry.get_rule(rule_id)
        if not rule:
            raise ValueError(f"规则不存在: {rule_id}")

        # 1. 计算受影响的功能点
        affected_functions = list(rule.affects)

        # 2. 计算受影响的项目和签核
        affected_projects = len(self.tracker._project_usage.get(rule_id, set()))
        affected_signoffs = len(self.tracker._signoff_usage.get(rule_id, set()))

        # 3. 计算受影响的其他规则（依赖链）
        dependents = self.tracker.get_dependents(rule_id)
        affected_rules = [d.source for d in dependents]

        # 4. 计算依赖此规则的规则（级联影响）
        cascading = []
        for dep in dependents:
            cascading.extend(self.tracker.get_dependents(dep.source))
        affected_rules.extend([d.source for d in cascading])
        affected_rules = list(set(affected_rules))

        # 5. 风险评估
        risk = self._assess_risk(rule, new_value, affected_projects, affected_signoffs, dependents)

        # 6. 建议
        recommendations = self._generate_recommendations(rule, risk, affected_projects, affected_signoffs)

        # 7. 回退计划
        rollback_plan = f"执行 rule_registry.rollback_rule('{rule_id}', {rule.version}, 'admin') 回退到当前版本"

        return ImpactReport(
            rule_id=rule_id, rule_name=rule.name,
            old_value=rule.current_value, new_value=new_value,
            risk=risk,
            affected_projects=affected_projects,
            affected_signoffs=affected_signoffs,
            affected_rules=affected_rules,
            affected_functions=affected_functions,
            dependent_rules=[d.source for d in dependents],
            recommendations=recommendations,
            requires_approval=risk in (ChangeRisk.HIGH, ChangeRisk.CRITICAL),
            rollback_plan=rollback_plan,
        )

    def _assess_risk(self, rule: Rule, new_value: Any, affected_projects: int,
                     affected_signoffs: int, dependents: List[Dependency]) -> ChangeRisk:
        """评估变更风险"""
        score = 0

        # 规则类别权重
        if rule.category == RuleCategory.SECURITY:
            score += 30
        elif rule.category == RuleCategory.COVERAGE:
            score += 20
        elif rule.category == RuleCategory.THRESHOLD:
            score += 15

        # 影响范围
        if affected_projects > 10:
            score += 25
        elif affected_projects > 3:
            score += 15
        elif affected_projects > 0:
            score += 5

        if affected_signoffs > 20:
            score += 20
        elif affected_signoffs > 5:
            score += 10

        # 依赖链深度
        if len(dependents) > 5:
            score += 20
        elif len(dependents) > 2:
            score += 10

        # 变更幅度
        if isinstance(new_value, (int, float)) and isinstance(rule.current_value, (int, float)):
            delta_pct = abs(new_value - rule.current_value) / max(abs(rule.current_value), 1)
            if delta_pct > 0.3:
                score += 20
            elif delta_pct > 0.1:
                score += 10

        if score >= 50:
            return ChangeRisk.CRITICAL
        elif score >= 30:
            return ChangeRisk.HIGH
        elif score >= 15:
            return ChangeRisk.MEDIUM
        return ChangeRisk.LOW

    def _generate_recommendations(self, rule: Rule, risk: ChangeRisk,
                                   affected_projects: int, affected_signoffs: int) -> List[str]:
        recs = []
        if risk == ChangeRisk.CRITICAL:
            recs.append("CRITICAL: 建议在非生产环境先行验证")
            recs.append("通知所有受影响项目的 SignOff 经理")
            recs.append("准备详细的回退方案")
        elif risk == ChangeRisk.HIGH:
            recs.append("建议在 1-2 个项目上灰度验证后再全量推送")
            recs.append("更新相关文档和阈值说明")
        elif risk == ChangeRisk.MEDIUM:
            recs.append("建议记录变更原因和预期效果")
        else:
            recs.append("低风险变更，可直接执行")

        if affected_projects > 0:
            recs.append(f"将影响 {affected_projects} 个项目的验证流程")
        if affected_signoffs > 0:
            recs.append(f"将影响 {affected_signoffs} 个签核的审批标准")
        return recs

    def simulate_change(self, rule_id: str, new_value: Any) -> ImpactReport:
        """模拟变更（不执行，仅分析）"""
        return self.analyze_change(rule_id, new_value, changed_by="simulation", reason="dry-run")


# ═══════════════════════════════════════════════════════════
# 4. 变更审批链 — 规则变更需审批后才生效
# ═══════════════════════════════════════════════════════════

@dataclass
class ChangeRequest:
    """变更请求"""
    request_id: str
    rule_id: str
    old_value: Any
    new_value: Any
    requested_by: str
    reason: str
    impact_report: ImpactReport
    status: str = "pending"  # pending / approved / rejected / executed
    approver: str = ""
    approved_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ChangeApprovalChain:
    """变更审批链 — 高风险变更必须审批后才生效"""

    def __init__(self, analyzer: ImpactAnalyzer, registry: RuleRegistry):
        self.analyzer = analyzer
        self.registry = registry
        self._pending_requests: Dict[str, ChangeRequest] = {}

    def request_change(self, rule_id: str, new_value: Any, requested_by: str,
                       reason: str) -> ChangeRequest:
        """发起变更请求 — 高风险变更进入审批队列"""
        import uuid
        report = self.analyzer.analyze_change(rule_id, new_value, requested_by, reason)

        cr = ChangeRequest(
            request_id=str(uuid.uuid4())[:12],
            rule_id=rule_id, old_value=report.old_value, new_value=new_value,
            requested_by=requested_by, reason=reason,
            impact_report=report,
        )

        if report.requires_approval:
            self._pending_requests[cr.request_id] = cr
            cr.status = "pending"
        else:
            # 低风险变更直接执行
            self.registry.change_rule(rule_id, new_value, requested_by, reason)
            cr.status = "executed"

        return cr

    def approve_change(self, request_id: str, approver: str) -> ChangeRequest:
        """审批通过 — 执行变更"""
        cr = self._pending_requests.get(request_id)
        if not cr:
            raise ValueError(f"Change request not found: {request_id}")
        cr.status = "approved"
        cr.approver = approver
        cr.approved_at = datetime.now().isoformat()
        # 执行变更
        self.registry.change_rule(cr.rule_id, cr.new_value, approver,
                                   f"Approved change request {request_id}: {cr.reason}")
        cr.status = "executed"
        return cr

    def reject_change(self, request_id: str, approver: str, reason: str = "") -> ChangeRequest:
        """驳回变更"""
        cr = self._pending_requests.get(request_id)
        if not cr:
            raise ValueError(f"Change request not found: {request_id}")
        cr.status = "rejected"
        cr.approver = approver
        return cr

    def get_pending_requests(self) -> List[ChangeRequest]:
        return list(self._pending_requests.values())


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_rule_registry: Optional[RuleRegistry] = None
_impact_analyzer: Optional[ImpactAnalyzer] = None


def get_rule_registry() -> RuleRegistry:
    global _rule_registry
    if _rule_registry is None:
        _rule_registry = RuleRegistry()
    return _rule_registry


def get_impact_analyzer() -> ImpactAnalyzer:
    global _impact_analyzer
    if _impact_analyzer is None:
        registry = get_rule_registry()
        tracker = DependencyTracker(registry)
        # 注册一些默认依赖关系
        tracker.add_dependency("signoff.coverage_gate", "coverage.line_threshold", "constrains")
        tracker.add_dependency("signoff.coverage_gate", "coverage.branch_threshold", "constrains")
        tracker.add_dependency("signoff.coverage_gate", "coverage.toggle_threshold", "constrains")
        tracker.add_dependency("quality_report", "coverage.line_threshold", "uses")
        tracker.add_dependency("signoff.readiness_check", "score.pass_threshold", "constrains")
        tracker.add_dependency("signoff.readiness_check", "workflow.mandatory_phases", "constrains")
        tracker.add_dependency("signoff.regression_gate", "regression.pass_rate_threshold", "constrains")
        tracker.add_dependency("signoff.evidence_gate", "evidence.min_phases_for_signoff", "constrains")
        _impact_analyzer = ImpactAnalyzer(registry, tracker)
    return _impact_analyzer
