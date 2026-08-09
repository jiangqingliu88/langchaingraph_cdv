"""
统一业务口径与可解释性引擎 — Business Glossary + DecisionTrace + EvidenceChain

三个核心能力:
  1. BusinessGlossary — 所有业务术语的精确定义，消除口径歧义
  2. DecisionTrace — AI 决策的完整推理链（证据+规则+上下文+置信度）
  3. ExplainabilityReport — 面向用户的可解释性报告生成器

业务口径示例:
  - "已完成" (completed): 所有 mandatory phases passed + evidence hash verified + score >= threshold
  - "已通过" (passed): phase 执行成功 + 评分 >= min_score + 产物 hash 校验通过
  - "签核通过" (approved): evidence chain 完整 + manifest hash 一致 + 审批人确认 + 审计记录不可篡改

用法:
  from src.infra.business_glossary import BusinessGlossary, DecisionTracer

  glossary = BusinessGlossary()
  definition = glossary.define("completed")
  # → "流水线的所有 mandatory phases 状态为 passed, evidence hash 校验通过, 综合评分 >= 70"

  tracer = DecisionTracer()
  trace = tracer.trace_decision("signoff_approve", context={...}, result="approved")
  # → DecisionTrace(steps=[...], evidence=[...], confidence=0.95)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json


# ═══════════════════════════════════════════════════════════
# 1. 统一业务术语表
# ═══════════════════════════════════════════════════════════

@dataclass
class BusinessTerm:
    """业务术语定义"""
    term: str                          # 术语名
    display_name: str                  # 中文名
    definition: str                    # 精确定义
    formula: str = ""                  # 计算公式（如有）
    thresholds: Dict[str, Any] = field(default_factory=dict)  # 相关阈值
    examples: List[str] = field(default_factory=list)          # 正例
    counter_examples: List[str] = field(default_factory=list)  # 反例
    related_terms: List[str] = field(default_factory=list)     # 关联术语
    scope: str = "global"              # 作用域: global / project / module


class BusinessGlossary:
    """统一业务术语表 — 消除口径歧义"""

    def __init__(self):
        self._terms: Dict[str, BusinessTerm] = {}
        self._define_all()

    def _define_all(self):
        # ── 流程状态类 ──
        self._terms["completed"] = BusinessTerm(
            term="completed", display_name="已完成",
            definition="流水线的所有 mandatory phases 执行状态为 passed, evidence hash 校验通过, comprehensive score >= pass_threshold",
            formula="all(phase.status == 'passed' for phase in mandatory_phases) AND evidence_hash_verified AND score >= threshold",
            thresholds={"pass_threshold": 70, "min_phases_passed_ratio": 0.85},
            examples=["17/17 phases passed, score=92, evidence hash verified"],
            counter_examples=["15/17 phases passed (missing 2 mandatory), score=85", "all passed but evidence hash mismatch"],
            related_terms=["passed", "verified", "score"],
        )

        self._terms["passed"] = BusinessTerm(
            term="passed", display_name="已通过（阶段级）",
            definition="单个 phase 执行成功, 产出 artifact 生成且 hash 校验通过, 评分 >= phase.min_score（如设定）",
            formula="phase.exit_code == 0 AND artifact.hash_verified AND phase.score >= phase.min_score",
            thresholds={"default_min_score": 50},
            examples=["RTL generation phase: output generated, score=88, hash verified"],
            counter_examples=["Phase ran but artifact corrupted (hash mismatch)", "Phase passed but score=30 (below min_score=50)"],
            related_terms=["completed", "degraded", "failed"],
        )

        self._terms["approved"] = BusinessTerm(
            term="approved", display_name="签核通过",
            definition="签核状态为 approved, evidence chain 完整性校验通过, manifest hash 一致, 审批人具有有效权限, 审计链未断裂",
            formula="signoff.status == 'approved' AND evidence_integrity_valid AND manifest_hash_consistent AND approver_authorized AND audit_chain_intact",
            thresholds={},
            examples=["UART tapeout signoff: evidence chain verified, admin approved, audit chain intact"],
            counter_examples=["Signoff approved but manifest hash later tampered", "Approved by unauthorized user"],
            related_terms=["verified", "signed_off", "rejected"],
        )

        # ── 证据类 ──
        self._terms["verified"] = BusinessTerm(
            term="verified", display_name="已验证",
            definition="证据链的所有 hash 校验通过, manifest 自校验通过, 文件完整性检查通过, 5 层证据链无断裂",
            formula="manifest_hash_ok AND evidence_hash_ok AND phases_complete AND missing_files==0 AND hash_mismatches==0",
            thresholds={},
            examples=["5-layer evidence chain: all hashes match, 0 missing files"],
            counter_examples=["Evidence hash ok but 3 files missing from output dir"],
            related_terms=["approved", "integrity", "evidence_chain"],
        )

        self._terms["integrity"] = BusinessTerm(
            term="integrity", display_name="完整性",
            definition="manifest 自校验 hash 匹配 AND 所有声明的 artifact 文件存在 AND 每个文件的 SHA256 与 manifest 记录一致 AND 审计链哈希连续",
            formula="manifest_self_hash_valid AND all(artifact.exists() for artifact in manifest.artifacts) AND all(sha256(artifact) == manifest.hash for artifact in manifest.artifacts) AND audit_chain.verify()",
            thresholds={},
            examples=["Manifest hash: abc123, all 45 files present, all hashes match"],
            counter_examples=["Manifest hash matches but 2 artifact files deleted from disk"],
            related_terms=["verified", "evidence_chain", "tamper_detection"],
        )

        # ── 评分类 ──
        self._terms["score"] = BusinessTerm(
            term="score", display_name="综合评分",
            definition="所有 phase 评分的加权平均值, 权重按 phase 类型设定: mandatory=2.0, optional=1.0, critical=3.0",
            formula="sum(phase.score * phase.weight) / sum(phase.weight)",
            thresholds={"excellent": 90, "good": 75, "acceptable": 60, "insufficient": 40},
            examples=["17 phases: weighted avg = 88.5 → 'good'"],
            counter_examples=["Only 5/17 phases scored (incomplete run)"],
            related_terms=["completed", "passed"],
        )

        # ── 覆盖率类 ──
        self._terms["coverage_adequate"] = BusinessTerm(
            term="coverage_adequate", display_name="覆盖率达标",
            definition="line_coverage >= line_threshold AND branch_coverage >= branch_threshold AND toggle_coverage >= toggle_threshold",
            formula="line_cov >= 85 AND branch_cov >= 75 AND toggle_cov >= 60",
            thresholds={"line_threshold": 85, "branch_threshold": 75, "toggle_threshold": 60},
            examples=["Line: 92%, Branch: 82%, Toggle: 68% → all above thresholds"],
            counter_examples=["Line: 90% but Branch: 60% (below 75% threshold)"],
            related_terms=["coverage", "threshold"],
        )

        # ── 流程类 ──
        self._terms["signoff_ready"] = BusinessTerm(
            term="signoff_ready", display_name="可签核状态",
            definition="流水线 completed AND coverage_adequate AND evidence_verified AND no_critical_gaps AND regression_pass_rate >= 90%",
            formula="pipeline.completed AND coverage_adequate AND evidence.verified AND gaps.critical==0 AND regression.pass_rate >= 0.90",
            thresholds={"regression_pass_rate": 0.90, "max_critical_gaps": 0},
            examples=["Pipeline done, coverage 92/82/68, 0 critical gaps, regression 95% pass"],
            counter_examples=["Pipeline done but 3 critical coverage gaps remain"],
            related_terms=["completed", "coverage_adequate", "approved"],
        )

    # ── 查询方法 ──

    def define(self, term: str) -> Optional[BusinessTerm]:
        return self._terms.get(term)

    def all_terms(self) -> List[str]:
        return list(self._terms.keys())

    def check(self, term: str, metrics: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
        """检查给定指标是否满足某业务口径。返回 (符合, 原因, 不满足项列表)。"""
        t = self._terms.get(term)
        if not t:
            return False, f"未定义的术语: {term}", []

        failures = []
        for key, threshold in t.thresholds.items():
            actual = metrics.get(key)
            if actual is None:
                failures.append(f"缺少指标: {key}")
            elif actual < threshold:
                failures.append(f"{key}: {actual} < {threshold} (threshold)")

        if failures:
            return False, f"不符合 '{term}' 口径: " + "; ".join(failures), failures
        return True, f"符合 '{term}' 口径", []

    def export_glossary(self) -> List[dict]:
        """导出术语表"""
        return [{
            "term": t.term, "display_name": t.display_name,
            "definition": t.definition, "formula": t.formula,
            "thresholds": t.thresholds,
            "examples": t.examples,
            "related_terms": t.related_terms,
        } for t in self._terms.values()]


# ═══════════════════════════════════════════════════════════
# 2. 决策追溯引擎
# ═══════════════════════════════════════════════════════════

@dataclass
class ReasoningStep:
    """推理步骤"""
    step_number: int
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)  # 支撑证据
    rule_applied: str = ""                                    # 应用的规则
    conclusion: str = ""                                      # 中间结论
    confidence: float = 0.0                                   # 该步骤置信度


@dataclass
class DecisionTrace:
    """完整决策追溯"""
    decision_id: str
    decision_type: str                    # signoff_approve / phase_pass / coverage_check / etc.
    timestamp: str
    context: Dict[str, Any] = field(default_factory=dict)   # 决策上下文
    steps: List[ReasoningStep] = field(default_factory=list) # 推理步骤链
    evidence_sources: List[str] = field(default_factory=list)# 证据来源
    final_conclusion: str = ""
    overall_confidence: float = 0.0
    human_review_required: bool = False
    review_reason: str = ""


class DecisionTracer:
    """AI 决策可解释性引擎 — 记录完整的推理链"""

    def __init__(self):
        self._traces: List[DecisionTrace] = []
        self._glossary = BusinessGlossary()

    def trace_decision(self, decision_type: str, context: Dict[str, Any],
                       result: Any) -> DecisionTrace:
        """记录一个决策的完整推理过程"""
        import uuid
        trace = DecisionTrace(
            decision_id=str(uuid.uuid4())[:12],
            decision_type=decision_type,
            timestamp=datetime.now().isoformat(),
            context=context,
        )

        # 根据决策类型构建推理链
        if decision_type == "signoff_approve":
            trace.steps, trace.overall_confidence = self._trace_signoff_approve(context, result)
        elif decision_type == "phase_pass":
            trace.steps, trace.overall_confidence = self._trace_phase_pass(context, result)
        elif decision_type == "coverage_check":
            trace.steps, trace.overall_confidence = self._trace_coverage_check(context, result)
        elif decision_type == "regression_pass":
            trace.steps, trace.overall_confidence = self._trace_regression_pass(context, result)
        else:
            trace.steps = [ReasoningStep(
                step_number=1, description=f"Generic decision: {decision_type}",
                evidence=context, conclusion=str(result), confidence=0.5
            )]
            trace.overall_confidence = 0.5

        # 判断是否需要人工审核
        trace.human_review_required = (
            trace.overall_confidence < 0.75
            or any(s.confidence < 0.5 for s in trace.steps)
        )
        if trace.human_review_required:
            low_steps = [s for s in trace.steps if s.confidence < 0.5]
            trace.review_reason = f"{len(low_steps)} 个推理步骤置信度过低，建议人工审核"

        trace.final_conclusion = str(result)
        self._traces.append(trace)
        if len(self._traces) > 500:
            self._traces = self._traces[-500:]
        return trace

    def _trace_signoff_approve(self, context: dict, result: Any) -> Tuple[List[ReasoningStep], float]:
        steps = []
        evidence_sources = []

        # Step 1: 检查签核状态
        status = context.get("status", "")
        steps.append(ReasoningStep(1, "检查签核状态", {"status": status},
                                    "SIGNOFF_STATE_MACHINE", f"状态为 '{status}'",
                                    0.99 if status == "pending" else 0.3))

        # Step 2: 证据完整性
        integrity_valid = context.get("integrity_valid", False)
        manifest_ok = context.get("manifest_hash_ok", False)
        steps.append(ReasoningStep(2, "校验证据链完整性",
                                    {"integrity_valid": integrity_valid, "manifest_hash_ok": manifest_ok},
                                    "EVIDENCE_INTEGRITY_RULE",
                                    f"完整性: {integrity_valid}, Manifest: {manifest_ok}",
                                    0.95 if integrity_valid and manifest_ok else 0.4))

        # Step 3: 审批人权限
        approver_role = context.get("approver_role", "")
        steps.append(ReasoningStep(3, "验证审批人权限",
                                    {"role": approver_role},
                                    "RBAC_SIGNOFF_APPROVE",
                                    f"审批人角色: {approver_role}",
                                    0.99 if approver_role in ("admin", "verification_manager") else 0.0))

        # Step 4: 覆盖率达标检查
        coverage = context.get("coverage_line_pct", 0)
        steps.append(ReasoningStep(4, "检查覆盖率是否达标",
                                    {"coverage_line_pct": coverage},
                                    "COVERAGE_THRESHOLD:85",
                                    f"行覆盖率: {coverage}% {'>=85' if coverage >= 85 else '<85'}",
                                    0.9 if coverage >= 85 else 0.5))

        # Step 5: 回归通过率
        pass_rate = context.get("regression_pass_rate", 0)
        steps.append(ReasoningStep(5, "检查回归通过率",
                                    {"pass_rate": pass_rate},
                                    "REGRESSION_THRESHOLD:90",
                                    f"回归通过率: {pass_rate}% {'>=90' if pass_rate >= 90 else '<90'}",
                                    0.9 if pass_rate >= 90 else 0.5))

        # Evidence sources
        evidence_sources = ["manifest.json", "signoff_events", "rbac_check", "coverage_summary", "regression_history"]

        overall = sum(s.confidence for s in steps) / len(steps)
        return steps, round(overall, 3)

    def _trace_phase_pass(self, context: dict, result: Any) -> Tuple[List[ReasoningStep], float]:
        steps = [
            ReasoningStep(1, "检查 phase 退出码", {"exit_code": context.get("exit_code", -1)},
                         "PHASE_EXIT_RULE", f"退出码: {context.get('exit_code')}", 0.99),
            ReasoningStep(2, "校验产物 hash", {"hash_verified": context.get("hash_verified", False)},
                         "ARTIFACT_HASH_RULE", f"Hash 校验: {context.get('hash_verified')}", 0.95),
            ReasoningStep(3, "检查评分阈值", {"score": context.get("score", 0), "min_score": context.get("min_score", 50)},
                         "PHASE_SCORE_RULE", f"评分 {context.get('score')} >= {context.get('min_score', 50)}", 0.85),
        ]
        overall = sum(s.confidence for s in steps) / len(steps)
        return steps, round(overall, 3)

    def _trace_coverage_check(self, context: dict, result: Any) -> Tuple[List[ReasoningStep], float]:
        steps = [
            ReasoningStep(1, "行覆盖率检查", {"actual": context.get("line_pct", 0), "threshold": 85},
                         "COVERAGE_LINE_RULE", f"Line: {context.get('line_pct')}%", 0.95),
            ReasoningStep(2, "分支覆盖率检查", {"actual": context.get("branch_pct", 0), "threshold": 75},
                         "COVERAGE_BRANCH_RULE", f"Branch: {context.get('branch_pct')}%", 0.95),
            ReasoningStep(3, "翻转覆盖率检查", {"actual": context.get("toggle_pct", 0), "threshold": 60},
                         "COVERAGE_TOGGLE_RULE", f"Toggle: {context.get('toggle_pct')}%", 0.90),
        ]
        overall = sum(s.confidence for s in steps) / len(steps)
        return steps, round(overall, 3)

    def _trace_regression_pass(self, context: dict, result: Any) -> Tuple[List[ReasoningStep], float]:
        pass_rate = context.get("pass_rate", 0)
        failed = context.get("failed_count", 0)
        total = context.get("total_count", 0)
        steps = [
            ReasoningStep(1, "回归通过率检查", {"pass_rate": pass_rate, "threshold": 90},
                         "REGRESSION_PASS_RATE_RULE",
                         f"通过率: {pass_rate}% {'>=90' if pass_rate >= 90 else '<90'}",
                         0.95),
            ReasoningStep(2, "失败用例分析", {"failed": failed, "total": total},
                         "REGRESSION_FAIL_ANALYSIS",
                         f"失败 {failed}/{total}",
                         0.85 if failed / max(total, 1) < 0.1 else 0.5),
        ]
        overall = sum(s.confidence for s in steps) / len(steps)
        return steps, round(overall, 3)

    def get_trace(self, decision_id: str) -> Optional[DecisionTrace]:
        for t in self._traces:
            if t.decision_id == decision_id:
                return t
        return None

    def get_recent_traces(self, limit: int = 20) -> List[DecisionTrace]:
        return self._traces[-limit:]

    def get_traces_requiring_review(self) -> List[DecisionTrace]:
        return [t for t in self._traces if t.human_review_required]

    def generate_explainability_report(self, decision_id: str) -> str:
        """生成面向用户的可解释性报告（Markdown 格式）"""
        trace = self.get_trace(decision_id)
        if not trace:
            return f"未找到决策 {decision_id}"

        lines = [
            f"# 决策可解释性报告",
            f"",
            f"**决策ID:** {trace.decision_id}",
            f"**类型:** {trace.decision_type}",
            f"**时间:** {trace.timestamp}",
            f"**结论:** {trace.final_conclusion}",
            f"**综合置信度:** {trace.overall_confidence:.1%}",
            f"**需人工审核:** {'是 ⚠️' if trace.human_review_required else '否 ✅'}",
            f"",
            f"## 推理链",
            f"",
        ]

        for step in trace.steps:
            conf_icon = "✅" if step.confidence >= 0.8 else ("⚠️" if step.confidence >= 0.5 else "❌")
            lines.append(f"### Step {step.step_number}: {step.description} {conf_icon}")
            lines.append(f"- **规则:** `{step.rule_applied}`")
            lines.append(f"- **证据:** {json.dumps(step.evidence, ensure_ascii=False)}")
            lines.append(f"- **结论:** {step.conclusion}")
            lines.append(f"- **置信度:** {step.confidence:.1%}")
            lines.append(f"")

        lines.append(f"## 证据来源")
        for src in trace.evidence_sources:
            lines.append(f"- {src}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 3. 可解释性报告 API 辅助
# ═══════════════════════════════════════════════════════════

class ExplainabilityReporter:
    """面向最终用户的可解释性报告生成"""

    @staticmethod
    def why_approved(signoff: dict, evidence: dict, trace: DecisionTrace) -> str:
        """解释为什么签核被批准"""
        lines = [
            f"## 为什么签核 \"{signoff.get('title', '')}\" 被批准?",
            f"",
            f"### 决策依据 (综合置信度: {trace.overall_confidence:.0%})",
            f"",
        ]
        for s in trace.steps:
            lines.append(f"{'✅' if s.confidence >= 0.8 else '⚠️'} **{s.description}**: {s.conclusion}")
        lines.append(f"")
        lines.append(f"### 关键证据")
        lines.append(f"- 证据链完整性: {'通过' if evidence.get('integrity', {}).get('valid') else '未通过'}")
        lines.append(f"- Manifest Hash: `{evidence.get('manifest_hash', 'N/A')[:16]}...`")
        lines.append(f"- 审批人: {signoff.get('approved_by_name', 'N/A')}")
        lines.append(f"")
        return "\n".join(lines)

    @staticmethod
    def why_rejected(signoff: dict, trace: DecisionTrace) -> str:
        """解释为什么签核被驳回"""
        lines = [
            f"## 为什么签核 \"{signoff.get('title', '')}\" 被驳回?",
            f"",
            f"驳回理由: {signoff.get('reject_reason', '未提供')}",
            f"",
            f"### 不满足的条件:",
        ]
        for s in trace.steps:
            if s.confidence < 0.8:
                lines.append(f"- ❌ {s.description}: {s.conclusion}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_glossary: Optional[BusinessGlossary] = None
_tracer: Optional[DecisionTracer] = None


def get_glossary() -> BusinessGlossary:
    global _glossary
    if _glossary is None:
        _glossary = BusinessGlossary()
    return _glossary


def get_tracer() -> DecisionTracer:
    global _tracer
    if _tracer is None:
        _tracer = DecisionTracer()
    return _tracer
