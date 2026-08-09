"""
自动建议闭环引擎 — FailureAnalyzer + FixRecommender + AutoFixDetector + FixVerifier

从"报错器"变成"智能助手":
  1. FailureAnalyzer — 分类失败 + 根因分析 + 置信度评估
  2. FixRecommender — 基于历史成功修复的推荐排序
  3. AutoFixDetector — 判断是否可自动修复 + 生成修复脚本
  4. FixVerifier — 修复后验证是否解决问题

闭环流程:
  失败发生 → FailureAnalyzer 分类定位根因
          → FixRecommender 推荐修复方案(排序)
          → AutoFixDetector 判断是否可自动修复
          → 如果可以 → 生成修复脚本 → 执行 → FixVerifier 验证
          → 如果不可以 → 输出修复建议 → 人工介入

用法:
  from src.infra.auto_fix_engine import AutoFixEngine, get_auto_fix_engine

  engine = get_auto_fix_engine()
  result = engine.analyze_and_suggest(error_log, context={"module": "uart", "phase": "UVM"})
  # → {category: "UVM_ERROR", root_cause: "...", fixes: [...], auto_fixable: True/False, ...}
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import re
import json


# ═══════════════════════════════════════════════════════════
# 失败分析器
# ═══════════════════════════════════════════════════════════

class FailureCategory(str, Enum):
    COMPILE_ERROR = "compile_error"
    UVM_ERROR = "uvm_error"
    SCOREBOARD_MISMATCH = "scoreboard_mismatch"
    TIMEOUT = "timeout"
    ASSERTION_FAIL = "assertion_fail"
    COVERAGE_GAP = "coverage_gap"
    REGRESSION_FAIL = "regression_fail"
    EVIDENCE_MISSING = "evidence_missing"
    MANIFEST_TAMPERED = "manifest_tampered"
    PERMISSION_DENIED = "permission_denied"
    CONFIG_ERROR = "config_error"
    UNKNOWN = "unknown"


@dataclass
class FailureAnalysis:
    """失败分析结果"""
    category: FailureCategory
    root_cause: str
    location: str = ""           # 文件:行号
    evidence: str = ""           # 关键日志行
    severity: str = "medium"     # critical / high / medium / low
    confidence: float = 0.0      # 0-100


@dataclass
class FixSuggestion:
    """修复建议"""
    suggestion_id: str
    title: str
    description: str
    category: str                  # auto_fix / manual_fix / workaround / investigation
    auto_fixable: bool = False
    fix_script: str = ""           # 自动修复脚本（如果是 auto_fix）
    estimated_effort_minutes: int = 15
    success_rate: float = 0.0      # 历史成功率
    prerequisites: List[str] = field(default_factory=list)  # 前置条件
    risk_level: str = "low"        # low / medium / high


@dataclass
class FixVerification:
    """修复验证结果"""
    fix_id: str
    verified: bool
    original_error_gone: bool
    new_errors: List[str] = field(default_factory=list)
    side_effects: List[str] = field(default_factory=list)
    recommendation: str = ""


# ═══════════════════════════════════════════════════════════
# 1. 失败分析器
# ═══════════════════════════════════════════════════════════

class FailureAnalyzer:
    """失败分类 + 根因定位"""

    _PATTERNS = [
        # 编译错误
        (r"\*\*\s*Error[:\s]*(.*?)(?=\n|$)", FailureCategory.COMPILE_ERROR, 90),
        (r"(?i)undefined\s+(identifier|reference).*?['\"]?(\w+)['\"]?", FailureCategory.COMPILE_ERROR, 85),
        (r"(?i)could not find field.*?['\"]?(\w+)['\"]?", FailureCategory.COMPILE_ERROR, 90),
        (r"(?i)syntax\s+error.*?near\s+[\"'](.*?)[\"']", FailureCategory.COMPILE_ERROR, 95),

        # UVM 错误
        (r"UVM_ERROR.*?(\S+\.sv):(\d+).*?(\S.*?)(?=\n|$)", FailureCategory.UVM_ERROR, 80),
        (r"UVM_FATAL.*?(\S+\.sv):(\d+).*?(\S.*?)(?=\n|$)", FailureCategory.UVM_ERROR, 90),

        # Scoreboard mismatch
        (r"(?i)scoreboard.*?mismatch.*?(\d+).*?(\d+)", FailureCategory.SCOREBOARD_MISMATCH, 85),
        (r"(?i)(expected|actual).*?(\d+).*?(actual|expected).*?(\d+)", FailureCategory.SCOREBOARD_MISMATCH, 75),

        # 超时
        (r"(?i)(timeout|timed\s*out)", FailureCategory.TIMEOUT, 70),
        (r"(?i)simulation.*?(did not finish|hung|stalled)", FailureCategory.TIMEOUT, 65),

        # SVA 断言
        (r"(?i)(assertion|SVA).*?(fail|violat).*?(\S+\.sv):(\d+)", FailureCategory.ASSERTION_FAIL, 80),
        (r"(?i)property\s+(\w+)\s+failed", FailureCategory.ASSERTION_FAIL, 85),

        # 覆盖率空洞
        (r"(?i)coverage\s+gap.*?(\S+\.sv).*?(\d+)%", FailureCategory.COVERAGE_GAP, 70),
        (r"(?i)(uncovered|un-hit)\s+(bin|point).*?(\w+)", FailureCategory.COVERAGE_GAP, 65),

        # 证据缺失
        (r"(?i)manifest.*?(not found|missing|corrupted)", FailureCategory.EVIDENCE_MISSING, 80),
        (r"(?i)hash.*?mismatch.*?(\S+)", FailureCategory.MANIFEST_TAMPERED, 85),

        # 权限
        (r"(?i)(permission denied|access denied|unauthorized|forbidden)", FailureCategory.PERMISSION_DENIED, 90),

        # 回归失败
        (r"(?i)regression.*?(failed|FAIL).*?(\d+)/(\d+)", FailureCategory.REGRESSION_FAIL, 75),

        # 配置错误
        (r"(?i)(config|env|setting).*?(not found|missing|invalid)", FailureCategory.CONFIG_ERROR, 70),
    ]

    def analyze(self, error_log: str, context: dict = None) -> FailureAnalysis:
        """分析失败日志，返回分类和根因"""
        log_lower = error_log.lower()
        best_match = None
        best_confidence = 0

        for pattern, category, base_confidence in self._PATTERNS:
            match = re.search(pattern, error_log, re.IGNORECASE | re.MULTILINE)
            if match:
                # 根据匹配的精确度调整置信度
                groups = len([g for g in match.groups() if g])
                confidence = min(base_confidence + groups * 3, 99)

                if confidence > best_confidence:
                    best_confidence = confidence
                    location = ""
                    for g in match.groups():
                        if ".sv" in str(g) or ".v" in str(g):
                            location = str(g)
                            break

                    best_match = FailureAnalysis(
                        category=category,
                        root_cause=self._extract_root_cause(category, match, error_log),
                        location=location,
                        evidence=match.group(0)[:200],
                        severity=self._assess_severity(category),
                        confidence=confidence,
                    )

        if best_match:
            return best_match

        # 通用分析
        key_lines = [l.strip() for l in error_log.split("\n")
                    if any(w in l.lower() for w in ["error", "fail", "fatal", "warning"])][:5]
        return FailureAnalysis(
            category=FailureCategory.UNKNOWN,
            root_cause="日志中发现可疑行但无法自动分类",
            evidence="\n".join(key_lines) if key_lines else error_log[:300],
            severity="medium",
            confidence=30,
        )

    def _extract_root_cause(self, category: FailureCategory, match: re.Match, full_log: str) -> str:
        """从匹配中提取根因描述"""
        if category == FailureCategory.COMPILE_ERROR:
            return f"编译错误: {match.group(0)[:150].strip()}"
        elif category == FailureCategory.UVM_ERROR:
            return f"UVM 错误: {match.group(0)[:150].strip()}"
        elif category == FailureCategory.SCOREBOARD_MISMATCH:
            return f"Scoreboard 比对失败: 期望值与实际值不匹配"
        elif category == FailureCategory.TIMEOUT:
            return f"仿真超时: {match.group(0)[:100].strip()}"
        elif category == FailureCategory.ASSERTION_FAIL:
            return f"断言失败: {match.group(0)[:150].strip()}"
        elif category == FailureCategory.COVERAGE_GAP:
            return f"覆盖率空洞: {match.group(0)[:150].strip()}"
        elif category == FailureCategory.EVIDENCE_MISSING:
            return "证据缺失: manifest 或 artifact 文件丢失"
        elif category == FailureCategory.MANIFEST_TAMPERED:
            return "证据完整性: hash 校验不匹配，可能存在篡改"
        elif category == FailureCategory.PERMISSION_DENIED:
            return "权限不足: 操作被拒绝"
        elif category == FailureCategory.REGRESSION_FAIL:
            return f"回归测试失败: {match.group(0)[:100].strip()}"
        else:
            return match.group(0)[:200].strip() if match else "未知错误"

    def _assess_severity(self, category: FailureCategory) -> str:
        severe = {FailureCategory.COMPILE_ERROR, FailureCategory.UVM_ERROR,
                  FailureCategory.ASSERTION_FAIL, FailureCategory.MANIFEST_TAMPERED}
        if category in severe: return "critical"
        medium = {FailureCategory.SCOREBOARD_MISMATCH, FailureCategory.TIMEOUT,
                  FailureCategory.REGRESSION_FAIL, FailureCategory.PERMISSION_DENIED}
        if category in medium: return "high"
        return "medium"


# ═══════════════════════════════════════════════════════════
# 2. 修复推荐器
# ═══════════════════════════════════════════════════════════

class FixRecommender:
    """基于失败分类推荐修复方案 — 排序"""

    _FIX_KNOWLEDGE_BASE = {
        FailureCategory.COMPILE_ERROR: [
            FixSuggestion("fix-compile-1", "修正语法错误", "根据编译器提示修正代码语法", "manual_fix",
                         estimated_effort_minutes=10, success_rate=0.95),
            FixSuggestion("fix-compile-2", "添加缺失的 include/import", "检查并添加缺失的头文件引用", "auto_fix",
                         auto_fixable=True, fix_script="# 搜索并添加缺失的 include 声明",
                         estimated_effort_minutes=5, success_rate=0.90),
            FixSuggestion("fix-compile-3", "修正接口信号名", "检查 interface 定义，修正信号名拼写", "manual_fix",
                         estimated_effort_minutes=15, success_rate=0.85,
                         prerequisites=["interface 文档", "RTL 端口列表"]),
        ],
        FailureCategory.UVM_ERROR: [
            FixSuggestion("fix-uvm-1", "检查 driver/monitor 信号引用", "对照 RTL 端口修正 UVM 组件中的信号引用", "manual_fix",
                         estimated_effort_minutes=20, success_rate=0.80),
            FixSuggestion("fix-uvm-2", "修正 phase objection", "检查并修正 UVM phase 的 raise/drop objection", "manual_fix",
                         estimated_effort_minutes=15, success_rate=0.85),
            FixSuggestion("fix-uvm-3", "修正 config_db 路径", "检查 config_db::set/get 的路径字符串", "auto_fix",
                         auto_fixable=True, fix_script="# 统一 config_db 路径格式",
                         estimated_effort_minutes=5, success_rate=0.90),
        ],
        FailureCategory.SCOREBOARD_MISMATCH: [
            FixSuggestion("fix-sb-1", "比对波形定位不一致 cycle", "使用 Verdi/DVE 波形比对，定位第一个不一致", "investigation",
                         estimated_effort_minutes=30, success_rate=0.75),
            FixSuggestion("fix-sb-2", "检查参考模型实现", "对比 C++ 参考模型与 RTL 的运算逻辑", "manual_fix",
                         estimated_effort_minutes=45, success_rate=0.70),
            FixSuggestion("fix-sb-3", "确认时序对齐", "检查 monitor 采样时刻与 DUT 输出时刻是否对齐", "manual_fix",
                         estimated_effort_minutes=20, success_rate=0.80),
        ],
        FailureCategory.TIMEOUT: [
            FixSuggestion("fix-to-1", "增大 UVM_TIMEOUT", "适当增加仿真超时时间", "auto_fix",
                         auto_fixable=True, fix_script="export UVM_TIMEOUT=1000000000",
                         estimated_effort_minutes=2, success_rate=0.60),
            FixSuggestion("fix-to-2", "检查死锁/无限循环", "检查是否有等待条件永远不满足", "investigation",
                         estimated_effort_minutes=60, success_rate=0.50),
            FixSuggestion("fix-to-3", "检查 sequence 是否正确发送", "确认 driver 有正确驱动 sequence item", "manual_fix",
                         estimated_effort_minutes=25, success_rate=0.75),
        ],
        FailureCategory.ASSERTION_FAIL: [
            FixSuggestion("fix-as-1", "追踪断言波形", "在波形中查看断言相关信号", "investigation",
                         estimated_effort_minutes=30, success_rate=0.70),
            FixSuggestion("fix-as-2", "检查断言条件是否过严", "评估 SVA 属性是否需要放宽", "manual_fix",
                         estimated_effort_minutes=20, success_rate=0.80),
        ],
        FailureCategory.COVERAGE_GAP: [
            FixSuggestion("fix-cg-1", "生成定向测试", "针对未覆盖 bin 生成定向测试用例", "auto_fix",
                         auto_fixable=True, fix_script="vagent gen_test --target-gap {gap_id}",
                         estimated_effort_minutes=10, success_rate=0.85),
            FixSuggestion("fix-cg-2", "添加覆盖率 waive", "如确认为不可覆盖场景，提交 waive 申请", "manual_fix",
                         estimated_effort_minutes=5, success_rate=0.95),
        ],
        FailureCategory.EVIDENCE_MISSING: [
            FixSuggestion("fix-ev-1", "重新生成 manifest", "运行流水线的 manifest 生成阶段", "auto_fix",
                         auto_fixable=True, fix_script="vagent manifest --rebuild",
                         estimated_effort_minutes=5, success_rate=0.95),
            FixSuggestion("fix-ev-2", "检查 output 目录权限", "确认 output 目录可写且未被清理", "manual_fix",
                         estimated_effort_minutes=5, success_rate=0.90),
        ],
        FailureCategory.PERMISSION_DENIED: [
            FixSuggestion("fix-pd-1", "检查用户角色", "确认用户拥有执行该操作的权限", "investigation",
                         estimated_effort_minutes=5, success_rate=0.95),
            FixSuggestion("fix-pd-2", "申请权限提升", "向 SignOff 经理申请临时权限", "manual_fix",
                         estimated_effort_minutes=15, success_rate=0.80),
        ],
        FailureCategory.REGRESSION_FAIL: [
            FixSuggestion("fix-rg-1", "重跑失败用例 (不同 seed)", "用不同随机种子重新运行失败的测试", "auto_fix",
                         auto_fixable=True, fix_script="vagent regression --rerun-failed --seed-random",
                         estimated_effort_minutes=30, success_rate=0.50),
            FixSuggestion("fix-rg-2", "分析失败日志定位根因", "逐一分析失败用例的日志", "investigation",
                         estimated_effort_minutes=60, success_rate=0.65),
        ],
        FailureCategory.UNKNOWN: [
            FixSuggestion("fix-uk-1", "人工审查日志", "将完整日志提交给 SignOff 经理进行人工分析", "investigation",
                         estimated_effort_minutes=30, success_rate=0.50),
            FixSuggestion("fix-uk-2", "与上一次成功运行对比", "diff 当前日志与上一次成功运行的日志", "investigation",
                         estimated_effort_minutes=20, success_rate=0.60),
        ],
    }

    def recommend(self, analysis: FailureAnalysis, context: dict = None) -> List[FixSuggestion]:
        """推荐修复方案（按成功率和努力程度排序）"""
        suggestions = self._FIX_KNOWLEDGE_BASE.get(analysis.category, [])
        if not suggestions:
            suggestions = self._FIX_KNOWLEDGE_BASE.get(FailureCategory.UNKNOWN, [])

        # 排序: 优先 auto_fixable + 高成功率 + 低努力
        def score(s: FixSuggestion) -> float:
            auto_bonus = 30 if s.auto_fixable else 0
            return s.success_rate * 100 + auto_bonus - s.estimated_effort_minutes * 0.2

        ranked = sorted(suggestions, key=score, reverse=True)
        return ranked


# ═══════════════════════════════════════════════════════════
# 3. 自动修复检测器
# ═══════════════════════════════════════════════════════════

class AutoFixDetector:
    """判断失败是否可自动修复 + 生成修复脚本"""

    @staticmethod
    def can_auto_fix(analysis: FailureAnalysis, suggestions: List[FixSuggestion]) -> Tuple[bool, str, Optional[FixSuggestion]]:
        """判断是否可以自动修复。返回 (can_fix, reason, best_fix)"""
        # 置信度过低 → 不建议自动修复
        if analysis.confidence < 50:
            return False, f"置信度过低 ({analysis.confidence}%)，不建议自动修复", None

        # 高危失败 → 不建议自动修复
        if analysis.severity == "critical" and analysis.category in (
            FailureCategory.MANIFEST_TAMPERED, FailureCategory.ASSERTION_FAIL):
            return False, f"高危失败 ({analysis.category.value})，需要人工判断", None

        # 查找可自动修复的建议
        auto_fixes = [s for s in suggestions if s.auto_fixable]
        if not auto_fixes:
            return False, "没有可用的自动修复方案", None

        best_fix = auto_fixes[0]
        if best_fix.success_rate < 0.60:
            return False, f"自动修复成功率过低 ({best_fix.success_rate:.0%})，建议人工处理", None

        return True, f"可使用 {best_fix.title} 自动修复 (成功率 {best_fix.success_rate:.0%})", best_fix

    @staticmethod
    def generate_fix_script(analysis: FailureAnalysis, fix: FixSuggestion, context: dict = None) -> str:
        """生成具体的自动修复脚本"""
        scripts = []

        if analysis.category == FailureCategory.TIMEOUT:
            scripts.append("#!/bin/bash")
            scripts.append("# Auto-fix: Timeout resolution")
            scripts.append(f"# Analysis confidence: {analysis.confidence}%")
            scripts.append("export UVM_TIMEOUT=5000000000  # 5x default")
            scripts.append("# If still timeout, consider:")
            scripts.append("# 1. Check for infinite loops in: " + (analysis.location or "unknown"))
            scripts.append("# 2. Verify phase objection raise/drop pairing")

        elif analysis.category == FailureCategory.COVERAGE_GAP:
            gap_id = re.search(r'(\w+_gap|\w+_uncovered)', analysis.root_cause)
            gap = gap_id.group(1) if gap_id else "unknown_gap"
            scripts.append("#!/bin/bash")
            scripts.append(f"# Auto-fix: Generate targeted test for coverage gap: {gap}")
            scripts.append(f"vagent gen_test --target-gap {gap} --output output/testcases/test_{gap}.sv")
            scripts.append(f"vagent run_test --test test_{gap}")

        elif analysis.category == FailureCategory.EVIDENCE_MISSING:
            scripts.append("#!/bin/bash")
            scripts.append("# Auto-fix: Rebuild manifest and evidence chain")
            scripts.append("vagent manifest --rebuild --verify")
            scripts.append("vagent evidence --verify-integrity")

        elif analysis.category == FailureCategory.COMPILE_ERROR:
            scripts.append("#!/bin/bash")
            scripts.append("# Auto-fix: Compile error resolution")
            scripts.append(f"# Error: {analysis.root_cause[:100]}")
            scripts.append("# 1. Check include paths")
            scripts.append("vagent compile --check-deps")
            scripts.append("# 2. If interface mismatch detected, run signal checker")
            if "field" in analysis.root_cause.lower():
                scripts.append("vagent check-interfaces --auto-correct")

        elif analysis.category == FailureCategory.REGRESSION_FAIL:
            scripts.append("#!/bin/bash")
            scripts.append("# Auto-fix: Regression failure retry with different seeds")
            scripts.append("vagent regression --rerun-failed --seed-random --max-retries 3")
            scripts.append("# If still failing, create debug session")
            scripts.append("vagent debug --create-session --from-regression")

        else:
            scripts.append(f"# Auto-fix script for: {analysis.category.value}")
            scripts.append(f"# Generated: {datetime.now().isoformat()}")
            scripts.append(f"# Root cause: {analysis.root_cause[:150]}")
            scripts.append(fix.fix_script)

        return "\n".join(scripts)


# ═══════════════════════════════════════════════════════════
# 4. 修复验证器
# ═══════════════════════════════════════════════════════════

class FixVerifier:
    """修复后验证"""

    def verify(self, fix: FixSuggestion, original_analysis: FailureAnalysis,
               after_log: str = "", context: dict = None) -> FixVerification:
        """验证修复是否有效"""
        import uuid
        fix_id = str(uuid.uuid4())[:12]

        if not after_log:
            return FixVerification(
                fix_id=fix_id, verified=False,
                original_error_gone=False,
                recommendation="需要提供修复后的日志才能验证",
            )

        # 重新分析修复后的日志
        analyzer = FailureAnalyzer()
        new_analysis = analyzer.analyze(after_log, context)

        original_error_gone = new_analysis.category != original_analysis.category
        new_errors = []
        side_effects = []

        if new_analysis.category != FailureCategory.UNKNOWN and not original_error_gone:
            new_errors.append(f"仍有错误: {new_analysis.category.value}")

        # 检查是否引入新问题
        if "warning" in after_log.lower() or "ERROR" in after_log:
            warning_lines = [l.strip() for l in after_log.split("\n") if "warning" in l.lower()][:3]
            if warning_lines:
                side_effects = warning_lines

        if original_error_gone and not new_errors:
            recommendation = f"✅ 修复成功: 原始错误 {original_analysis.category.value} 已解决"
        elif not original_error_gone:
            recommendation = f"❌ 修复无效: 原始错误仍然存在，建议尝试其他方案"
        else:
            recommendation = "⚠️ 原始错误已解决但引入了新问题，请检查"

        return FixVerification(
            fix_id=fix_id, verified=original_error_gone and not new_errors,
            original_error_gone=original_error_gone,
            new_errors=new_errors, side_effects=side_effects,
            recommendation=recommendation,
        )


# ═══════════════════════════════════════════════════════════
# 5. 自动修复引擎主控
# ═══════════════════════════════════════════════════════════

@dataclass
class AutoFixResult:
    """自动修复引擎的完整输出"""
    analysis: FailureAnalysis
    suggestions: List[FixSuggestion]
    auto_fixable: bool
    auto_fix_reason: str
    best_auto_fix: Optional[FixSuggestion] = None
    fix_script: str = ""
    verification: Optional[FixVerification] = None
    recommended_action: str = ""  # 给用户的最终建议
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AutoFixEngine:
    """自动修复闭环引擎主控"""

    def __init__(self):
        self.analyzer = FailureAnalyzer()
        self.recommender = FixRecommender()
        self.detector = AutoFixDetector()
        self.verifier = FixVerifier()
        self._history: List[AutoFixResult] = []

    def analyze_and_suggest(self, error_log: str, context: dict = None) -> AutoFixResult:
        """分析错误并给出修复建议"""
        # 1. 分析失败
        analysis = self.analyzer.analyze(error_log, context)

        # 2. 推荐修复方案
        suggestions = self.recommender.recommend(analysis, context)

        # 3. 检测是否可自动修复
        auto_fixable, reason, best_fix = self.detector.can_auto_fix(analysis, suggestions)

        # 4. 生成修复脚本
        fix_script = ""
        if auto_fixable and best_fix:
            fix_script = self.detector.generate_fix_script(analysis, best_fix, context)

        # 5. 生成最终建议
        if auto_fixable:
            recommended_action = f"✅ 可自动修复: {best_fix.title} — {reason}"
        elif suggestions:
            top_fix = suggestions[0]
            recommended_action = f"🔧 建议人工处理: {top_fix.title} (预计 {top_fix.estimated_effort_minutes} 分钟)"
        else:
            recommended_action = "❓ 无法自动推荐修复方案，建议人工审查"

        result = AutoFixResult(
            analysis=analysis, suggestions=suggestions,
            auto_fixable=auto_fixable, auto_fix_reason=reason,
            best_auto_fix=best_fix, fix_script=fix_script,
            recommended_action=recommended_action,
        )
        self._history.append(result)
        if len(self._history) > 200:
            self._history = self._history[-200:]
        return result

    def verify_fix(self, fix: FixSuggestion, analysis: FailureAnalysis,
                   after_log: str, context: dict = None) -> FixVerification:
        """验证修复效果"""
        return self.verifier.verify(fix, analysis, after_log, context)

    def get_history(self, limit: int = 20) -> List[dict]:
        """获取修复历史"""
        return [{
            "timestamp": r.timestamp,
            "category": r.analysis.category.value,
            "root_cause": r.analysis.root_cause[:100],
            "auto_fixable": r.auto_fixable,
            "recommended_action": r.recommended_action,
            "confidence": r.analysis.confidence,
        } for r in self._history[-limit:]]

    def get_success_rate(self) -> dict:
        """获取自动修复成功率统计"""
        if not self._history: return {"total": 0, "auto_fixable_rate": 0}
        auto_fixable_count = sum(1 for r in self._history if r.auto_fixable)
        return {
            "total_analyses": len(self._history),
            "auto_fixable": auto_fixable_count,
            "auto_fixable_rate": round(auto_fixable_count / len(self._history), 3),
            "by_category": {},
        }


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_auto_fix_engine: Optional[AutoFixEngine] = None


def get_auto_fix_engine() -> AutoFixEngine:
    global _auto_fix_engine
    if _auto_fix_engine is None:
        _auto_fix_engine = AutoFixEngine()
    return _auto_fix_engine
