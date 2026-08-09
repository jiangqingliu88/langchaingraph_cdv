"""
失败原因聚类 + 知识复用引擎

- FailureCluster: 相似失败自动归类（compile_error/timeout/coverage_gap等）
- KnowledgeExtractor: 成功/失败经验自动沉淀为知识条目
- BatchOps: 批量操作框架
"""
from __future__ import annotations

import re
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════
# 失败聚类
# ═══════════════════════════════════════════════════════════

@dataclass
class FailureSignature:
    """失败特征签名"""
    category: str           # compile_error / timeout / assertion_fail / coverage_gap / tool_crash / uvm_error
    pattern: str            # 匹配模式
    severity: str = "medium"
    auto_fixable: bool = False
    fix_suggestion: str = ""


FAILURE_SIGNATURES = [
    FailureSignature("compile_error", r"(?i)(syntax error|undeclared|undefined identifier|could not find|module not found)",
                     severity="high", auto_fixable=False,
                     fix_suggestion="检查 RTL 语法、include 路径和模块声明"),
    FailureSignature("compile_error", r"(?i)(multiple drivers|unresolved reference|port size mismatch)",
                     severity="high", auto_fixable=False,
                     fix_suggestion="检查信号连接和多驱动冲突"),
    FailureSignature("timeout", r"(?i)(simulation timeout|UVM_TIMEOUT|timeout reached|watchdog)",
                     severity="medium", auto_fixable=False,
                     fix_suggestion="增大 timeout 值或检查是否有死锁"),
    FailureSignature("assertion_fail", r"(?i)(assertion failed|SVA.*fail|property.*violated|ASRT_)",
                     severity="high", auto_fixable=False,
                     fix_suggestion="检查断言条件是否正确，或波形定位触发时机"),
    FailureSignature("scoreboard_mismatch", r"(?i)(scoreboard.*mismatch|data mismatch|expected.*actual|comparison fail)",
                     severity="high", auto_fixable=False,
                     fix_suggestion="比对参考模型和 DUT 输出，定位第一个不一致 cycle"),
    FailureSignature("coverage_gap", r"(?i)(coverage gap|uncovered|hole|toggle.*0%|branch.*0%|not covered)",
                     severity="low", auto_fixable=True,
                     fix_suggestion="AI 自动生成定向测试覆盖该 gap"),
    FailureSignature("tool_crash", r"(?i)(segmentation fault|core dumped|tool crash|internal error|fatal.*signal)",
                     severity="critical", auto_fixable=False,
                     fix_suggestion="检查 EDA 工具 license、内存和版本兼容性"),
    FailureSignature("uvm_error", r"(?i)(UVM_ERROR|UVM_FATAL|uvm_fatal|uvm_error)",
                     severity="high", auto_fixable=False,
                     fix_suggestion="定位 UVM 错误的具体 phase 和组件"),
    FailureSignature("fifo_overflow", r"(?i)(fifo overflow|overflow detected|FIFO.*full.*write)",
                     severity="medium", auto_fixable=True,
                     fix_suggestion="检查 FIFO 深度设置和读写速率匹配"),
    FailureSignature("randomization_fail", r"(?i)(randomization fail|could not randomize|constraint conflict|solve.*fail)",
                     severity="medium", auto_fixable=False,
                     fix_suggestion="放宽约束条件或增加随机重试次数"),
    FailureSignature("connection_error", r"(?i)(connection error|cross.*bar.*error|interface.*not.*found|port.*not.*connected)",
                     severity="high", auto_fixable=False,
                     fix_suggestion="检查顶层互连和接口绑定"),
    FailureSignature("power_violation", r"(?i)(power.*violation|leakage.*exceed|dynamic.*power.*fail|IR.*drop)",
                     severity="medium", auto_fixable=False,
                     fix_suggestion="优化功耗设计，检查 clock gating 和电源域"),
]


@dataclass
class ClusteredFailure:
    """聚合后的失败聚类"""
    cluster_id: str
    category: str
    pattern: str
    count: int = 0
    occurrences: list = field(default_factory=list)
    representative_log: str = ""
    suggested_fix: str = ""
    auto_fixable: bool = False
    first_seen: str = ""
    last_seen: str = ""


class FailureClusterEngine:
    """失败聚类引擎"""

    def analyze(self, logs: list[dict]) -> dict:
        """
        对一批失败日志进行聚类分析

        Args:
            logs: [{"run_id": str, "phase": str, "error_log": str, "timestamp": str}, ...]
        """
        clusters: dict[str, ClusteredFailure] = {}

        for entry in logs:
            error_log = entry.get("error_log", "")
            category, sig = self._match_signature(error_log)

            if sig:
                cluster_key = f"{category}:{sig.pattern[:30]}"
                if cluster_key not in clusters:
                    clusters[cluster_key] = ClusteredFailure(
                        cluster_id=f"cluster_{len(clusters)+1:03d}",
                        category=category,
                        pattern=sig.pattern[:60],
                        suggested_fix=sig.fix_suggestion,
                        auto_fixable=sig.auto_fixable,
                        first_seen=entry.get("timestamp", ""),
                        representative_log=error_log[:500],
                    )
                c = clusters[cluster_key]
                c.count += 1
                c.occurrences.append({
                    "run_id": entry.get("run_id", ""),
                    "phase": entry.get("phase", ""),
                    "timestamp": entry.get("timestamp", ""),
                })
                c.last_seen = entry.get("timestamp", "")

        # 按频次排序
        sorted_clusters = sorted(clusters.values(), key=lambda c: -c.count)

        return {
            "total_failures": len(logs),
            "total_clusters": len(sorted_clusters),
            "clusters": [{
                "cluster_id": c.cluster_id,
                "category": c.category,
                "count": c.count,
                "percentage": round(c.count / max(len(logs), 1) * 100, 1),
                "suggested_fix": c.suggested_fix,
                "auto_fixable": c.auto_fixable,
                "first_seen": c.first_seen,
                "last_seen": c.last_seen,
                "sample_occurrences": c.occurrences[:5],
                "representative_log": c.representative_log[:200],
            } for c in sorted_clusters],
            "summary": {
                "top_category": sorted_clusters[0].category if sorted_clusters else "none",
                "auto_fixable_count": sum(1 for c in sorted_clusters if c.auto_fixable),
                "critical_count": sum(1 for c in sorted_clusters
                                      if any(s.category == c.category and s.severity == "critical"
                                             for s in FAILURE_SIGNATURES)),
            },
        }

    def _match_signature(self, log: str) -> tuple[str, Optional[FailureSignature]]:
        """匹配失败特征"""
        for sig in FAILURE_SIGNATURES:
            if re.search(sig.pattern, log, re.IGNORECASE):
                return sig.category, sig
        return "unclassified", None


# ═══════════════════════════════════════════════════════════
# 知识复用引擎
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeSuggestion:
    """知识复用建议"""
    type: str           # fix / pattern / optimization
    title: str
    content: str
    source: str         # 来源 run_id 或经验来源
    confidence: float = 0.5
    category: str = "best_practice"


class KnowledgeExtractor:
    """知识提取器 — 从成功/失败经验中提取可复用知识"""

    def extract_from_success(self, run_id: str, phases: list[dict]) -> list[KnowledgeSuggestion]:
        """从成功运行中提取最佳实践"""
        suggestions = []
        for p in phases:
            if p.get("status") == "passed" and p.get("score", 0) >= 90:
                phase_name = p.get("phase_name", "")
                # 高频成功模式 → 知识条目
                suggestions.append(KnowledgeSuggestion(
                    type="pattern", title=f"高通过率模式: {phase_name}",
                    content=f"阶段 {phase_name} 得分 {p.get('score')} — 策略可复用",
                    source=run_id, confidence=0.8,
                    category="best_practice",
                ))
        return suggestions

    def extract_from_failure(self, run_id: str, error_log: str, cluster: dict) -> KnowledgeSuggestion:
        """从失败中提取经验"""
        return KnowledgeSuggestion(
            type="fix",
            title=f"修复方案: {cluster.get('category', 'unknown')}",
            content=f"失败模式: {cluster.get('pattern', '')}\n建议: {cluster.get('suggested_fix', '')}",
            source=run_id,
            confidence=0.7,
            category="bug_case",
        )

    async def auto_store(self, suggestion: KnowledgeSuggestion):
        """自动存储知识条目到数据库"""
        try:
            from src.database.repository import create_knowledge
            await create_knowledge(
                title=suggestion.title,
                category=suggestion.category,
                tags=f"auto,{suggestion.type}",
                content=suggestion.content,
                author_id=0,  # system
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 批量操作框架
# ═══════════════════════════════════════════════════════════

@dataclass
class BatchResult:
    """批量操作结果"""
    operation: str
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    details: list = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""


class BatchOperations:
    """批量操作引擎"""

    async def batch_approve_signoffs(self, signoff_ids: list[int], approver_id: int,
                                     approver_name: str, comment: str = "") -> BatchResult:
        """批量批准签核"""
        from src.database.repository import update_signoff, get_signoff_by_id
        result = BatchResult(operation="batch_approve", total=len(signoff_ids),
                             started_at=datetime.now().isoformat())
        for sid in signoff_ids:
            try:
                sf = await get_signoff_by_id(sid)
                if sf and sf.get("status") == "pending":
                    ok = await update_signoff(sid, "approved", approver_id, comment,
                                              approver_name=approver_name)
                    if ok:
                        result.succeeded += 1
                        result.details.append({"id": sid, "status": "approved"})
                    else:
                        result.failed += 1
                        result.details.append({"id": sid, "status": "failed", "error": "update failed"})
                else:
                    result.skipped += 1
                    result.details.append({"id": sid, "status": "skipped",
                                           "reason": f"not pending: {sf.get('status') if sf else 'not found'}"})
            except Exception as e:
                result.failed += 1
                result.details.append({"id": sid, "status": "error", "error": str(e)})
        result.completed_at = datetime.now().isoformat()
        return result

    async def batch_sync_docs(self, project_ids: list[int], author_id: int) -> BatchResult:
        """批量同步多个项目的文档"""
        from src.database.repository import sync_fs_to_db
        from config.settings import Settings
        settings = Settings()
        specs_dir = getattr(settings, 'SPECS_DIR', 'specs')

        result = BatchResult(operation="batch_sync_docs", total=len(project_ids),
                             started_at=datetime.now().isoformat())
        for pid in project_ids:
            try:
                r = await sync_fs_to_db(specs_dir, pid, author_id)
                result.succeeded += 1
                result.details.append({"project_id": pid, "result": r})
            except Exception as e:
                result.failed += 1
                result.details.append({"project_id": pid, "error": str(e)})
        result.completed_at = datetime.now().isoformat()
        return result

    async def batch_rerun_regressions(self, run_ids: list[str]) -> BatchResult:
        """批量重跑回归"""
        from src.core.execution import PipelineExecutionService
        service = PipelineExecutionService.get_instance()

        result = BatchResult(operation="batch_rerun", total=len(run_ids),
                             started_at=datetime.now().isoformat())
        for rid in run_ids:
            try:
                status = service.get_run_status(rid)
                if status:
                    await service.run_single_agent("regression_manager", json.dumps({"rerun_id": rid}))
                    result.succeeded += 1
                else:
                    result.skipped += 1
            except Exception as e:
                result.failed += 1
                result.details.append({"run_id": rid, "error": str(e)})
        result.completed_at = datetime.now().isoformat()
        return result


# ── 全局实例 ──
_failure_cluster: Optional[FailureClusterEngine] = None
_knowledge_extractor: Optional[KnowledgeExtractor] = None
_batch_ops: Optional[BatchOperations] = None


def get_failure_cluster() -> FailureClusterEngine:
    global _failure_cluster
    if _failure_cluster is None:
        _failure_cluster = FailureClusterEngine()
    return _failure_cluster


def get_knowledge_extractor() -> KnowledgeExtractor:
    global _knowledge_extractor
    if _knowledge_extractor is None:
        _knowledge_extractor = KnowledgeExtractor()
    return _knowledge_extractor


def get_batch_ops() -> BatchOperations:
    global _batch_ops
    if _batch_ops is None:
        _batch_ops = BatchOperations()
    return _batch_ops
