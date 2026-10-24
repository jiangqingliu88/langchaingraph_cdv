"""AnalysisResult —— 分析的产物。

视图层只读这个对象，不自己算任何东西。所以它必须自带所有下游需要的东西：
分层统计、组织树、专题表、交叉矩阵、覆盖结构、诊断、评分。

`issues` 与 `model_issues` 的分工是刻意的：
  · model_issues  只含模型自身的诊断 —— **评分只据此计算**
  · issues        模型自身 ∪ 外部核对，报告与退出码用这个（不丢信息）

否则同一个模型传两份完整度不同的 case 列表会得到两个分数，
分数就不再可复现。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional

from ..domain import CaseAttribute, CaseModel
from ..generation import GenerationResult
from .coverage import DimensionCoverage, FieldCoverage
from .external import ExternalReport
from .issues import Issue, count_by_severity, group_by_category
from .matrix import CrossMatrix
from .score import ScoreBreakdown


@dataclass
class AnalysisResult:
    """一次完备性分析的全部产物。"""
    model: CaseModel
    generation: GenerationResult
    issues: List[Issue] = _field(default_factory=list)
    model_issues: List[Issue] = _field(default_factory=list)
    matrix: Optional[CrossMatrix] = None
    dimension_coverage: List[DimensionCoverage] = _field(default_factory=list)
    field_coverage: List[FieldCoverage] = _field(default_factory=list)
    score: ScoreBreakdown = _field(default_factory=ScoreBreakdown)
    explosion: List[Dict[str, Any]] = _field(default_factory=list)
    external: Optional[ExternalReport] = None

    # ── 便捷视图 ──

    def by_category(self) -> Dict[str, List[Issue]]:
        return group_by_category(self.issues)

    def counts(self) -> Dict[str, int]:
        return count_by_severity(self.issues)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.is_error]

    @property
    def model_errors(self) -> List[Issue]:
        return [i for i in self.model_issues if i.is_error]

    @property
    def coverage_ratio(self) -> float:
        total = sum(d.total for d in self.dimension_coverage)
        hit = sum(d.hit_count for d in self.dimension_coverage)
        return hit / total if total else 1.0

    # ── 组织树 / 专题 × case 视图 ──

    def cases_for_node(self, node_id: str) -> List[CaseAttribute]:
        return [c for c in self.generation.cases if c.node_key == node_id]

    def cases_for_theme(self, theme_id: str) -> List[CaseAttribute]:
        return [c for c in self.generation.cases if c.theme == theme_id]

    def node_rows(self) -> List[Dict[str, Any]]:
        """组织树逐节点行，附上打在这里的专题与 case 数。"""
        by_node: Dict[str, List[CaseAttribute]] = {}
        for c in self.generation.cases:
            by_node.setdefault(c.node_key, []).append(c)
        rows: List[Dict[str, Any]] = []
        for node in self.model.tree_nodes:
            cases = by_node.get(node.id, []) if node.is_leaf else []
            themes = sorted({c.theme for c in cases if c.theme})
            rows.append({
                **next(r for r in self.model.org_tree_rows() if r["id"] == node.id),
                "themes": themes,
                "theme_count": len(themes),
                "case_count": len(cases),
                "covered": bool(cases) or not node.is_leaf,
            })
        return rows

    def theme_rows(self) -> List[Dict[str, Any]]:
        """专题逐行，附上它生成的 case 数与实际目标节点。"""
        rows: List[Dict[str, Any]] = []
        for row in self.model.theme_rows():
            cases = self.cases_for_theme(row["id"])
            nodes = sorted({c.sub_object_id for c in cases if c.sub_object_id})
            rows.append({
                **row,
                "case_count": len(cases),
                "actual_nodes": nodes,
                "actual_node_count": len(nodes),
            })
        return rows

    def summary(self) -> Dict[str, Any]:
        c = self.counts()
        out: Dict[str, Any] = {
            "case_count": self.generation.count,
            "case_total_before_cap": self.generation.total_before_cap,
            "truncated": self.generation.truncated,
            "dropped": self.generation.dropped,
            "driver": self.generation.driver,
            "theme_count": len(self.generation.themes_used),
            "org_leaf_count": len(self.model.leaf_nodes),
            "error_count": c["error"],
            "warning_count": c["warning"],
            "info_count": c["info"],
            "score": round(self.score.total, 1),
            "coverage_ratio": round(self.coverage_ratio, 4),
        }
        if self.external is not None:
            out["external_case_count"] = self.external.case_count
            out["external_coverage_ratio"] = round(self.external.coverage_ratio, 4)
            out["external_issue_count"] = len(self.external.issues)
            out["model_error_count"] = len(self.model_errors)
        return out
