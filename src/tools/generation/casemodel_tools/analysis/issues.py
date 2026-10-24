"""Issue —— schema_check 与 completeness 共用的诊断条目。

与 uvm_tools/tool_uvm/semantic_check.py 的 Issue 保持同形
（severity / rule / target / message），这样两个工具的 CLI 输出可以并排看。
category 是本工具额外加的，用来在 GUI 里分页归类。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

# 诊断分类 —— 报告的规则分组与 GUI 标签页都按此归类
CATEGORY_SCHEMA = "schema"              # JSON Schema 语法/类型违规
CATEGORY_REFERENCE = "reference"        # 悬空引用（节点/维度/字段/专题）
CATEGORY_ORTHOGONAL = "orthogonality"   # 层级正交性 / 错位
CATEGORY_ORG_TREE = "org_tree"          # 功能组织树（叶子覆盖、代号唯一）
CATEGORY_THEME = "theme"                # 专题（优先级、目标、重叠、范围）
CATEGORY_CROSS = "cross"                # 维度交叉矩阵 / 交叉组
CATEGORY_COVERAGE = "coverage"          # 字段取值覆盖缺口
CATEGORY_ENVIRONMENT = "environment"    # 环境指纹 / 检查项完备性
CATEGORY_EXTERNAL = "external"          # 外部真实 case 列表的反向核对

#: 展示顺序 —— 与「从骨架到取值」的阅读顺序一致
CATEGORY_ORDER = (
    CATEGORY_SCHEMA, CATEGORY_REFERENCE, CATEGORY_ORTHOGONAL, CATEGORY_ORG_TREE,
    CATEGORY_THEME, CATEGORY_CROSS, CATEGORY_COVERAGE, CATEGORY_ENVIRONMENT,
    CATEGORY_EXTERNAL,
)

CATEGORY_NAMES = {
    CATEGORY_SCHEMA: "Schema 校验",
    CATEGORY_REFERENCE: "引用完整性",
    CATEGORY_ORTHOGONAL: "层级正交性",
    CATEGORY_ORG_TREE: "功能组织树",
    CATEGORY_THEME: "专题",
    CATEGORY_CROSS: "维度交叉",
    CATEGORY_COVERAGE: "取值覆盖",
    CATEGORY_ENVIRONMENT: "环境与检查",
    CATEGORY_EXTERNAL: "真实 case 核对",
}

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

SEVERITY_NAMES = {"error": "错误", "warning": "警告", "info": "提示"}


@dataclass
class Issue:
    severity: str        # error | warning | info
    rule: str
    target: str
    message: str
    category: str = ""

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    @property
    def severity_cn(self) -> str:
        return SEVERITY_NAMES.get(self.severity, self.severity)

    @property
    def category_cn(self) -> str:
        return CATEGORY_NAMES.get(self.category, self.category)

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.rule} @ {self.target}: {self.message}"


def sort_issues(issues: Iterable[Issue]) -> List[Issue]:
    """稳定的排序：先按严重度，再按分类，最后按规则/目标 —— 让输出可 diff。"""
    return sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9),
                                         i.category, i.rule, i.target, i.message))


def count_by_severity(issues: Iterable[Issue]) -> dict:
    counts = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1
    return counts


def category_rank(category: str) -> int:
    try:
        return CATEGORY_ORDER.index(category)
    except ValueError:
        return len(CATEGORY_ORDER)


def group_by_category(issues: Iterable[Issue]) -> dict:
    """按分类分组，键按 CATEGORY_ORDER 排序（不是出现顺序）。"""
    grouped: dict = {}
    for i in issues:
        grouped.setdefault(i.category, []).append(i)
    return {k: grouped[k] for k in sorted(grouped, key=category_rank)}
