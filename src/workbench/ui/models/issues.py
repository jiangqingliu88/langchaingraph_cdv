"""诊断表模型 —— 严重度着色是它存在的理由。

为什么不用通用 `RowsModel`：诊断的每一行都要按 severity 上色，而且用户会按
严重度/分类筛。把着色放进模型而不是逐行塞控件，是 Qt model/view 的基本做法：
数据一变只发 dataChanged，视图自己重画，不用手工清表重填。

**不依赖任何具体诊断类型**：只需要对象有 `severity / category / rule / target /
message` 和两个中文字段 `severity_cn / category_cn`（下面用 `IssueLike` 协议
写清楚）。原来的实现直接 import 了 case 模型的 `Issue`，那会让这份完全通用的
表模型被焊在一个领域上。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from ..theme import palette as theme

#: 严重度 → 前景色。**跟着主题走**：写死的话，深色主题下这行诊断是一片暗红，
#: 比背景还暗。所以不存常量，画的时候现取（见 `severity_color`）。
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def severity_color(severity: str):
    """严重度 → 当前主题下的 QColor。认不出的严重度返回 None（不着色）。"""
    if severity not in SEVERITY_ORDER:
        return None
    return theme.SEVERITY.get(severity)


@runtime_checkable
class IssueLike(Protocol):
    """一条诊断需要长什么样。只是文档 + 静态检查，运行时不强制。"""

    severity: str
    category: str
    rule: str
    target: str
    message: str
    severity_cn: str
    category_cn: str


class IssueTableModel(QAbstractTableModel):
    """扁平展示诊断列表。"""

    COLUMNS = (
        ("severity_cn", "严重度", 70),
        ("category_cn", "分类", 110),
        ("rule", "规则", 220),
        ("target", "目标", 250),
        ("message", "说明", 640),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._issues: List[Any] = []

    # ── 数据 ──

    def set_issues(self, issues: Sequence[Any]) -> None:
        self.beginResetModel()
        self._issues = list(issues)
        self.endResetModel()

    def issues(self) -> List[Any]:
        return list(self._issues)

    def issue_at(self, row: int) -> Optional[Any]:
        return self._issues[row] if 0 <= row < len(self._issues) else None

    def counts(self) -> Dict[str, int]:
        out = {"error": 0, "warning": 0, "info": 0}
        for issue in self._issues:
            severity = getattr(issue, "severity", "info")
            out[severity] = out.get(severity, 0) + 1
        return out

    # ── Qt ──

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._issues)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        issue = self._issues[index.row()]
        key = self.COLUMNS[index.column()][0]

        if role == Qt.ItemDataRole.DisplayRole:
            return str(getattr(issue, key, "") or "")
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(issue)
        if role == Qt.ItemDataRole.ForegroundRole:
            return severity_color(getattr(issue, "severity", ""))
        if role == Qt.ItemDataRole.UserRole:        # 排序用：严重度按语义排，不按字母
            if key == "severity_cn":
                return SEVERITY_ORDER.get(getattr(issue, "severity", ""), 9)
            return str(getattr(issue, key, "") or "")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal \
                and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section][1]
        return None

    def apply_column_widths(self, view) -> None:
        for i, (_key, _head, width) in enumerate(self.COLUMNS):
            view.setColumnWidth(i, width)


class IssueFilterModel(QSortFilterProxyModel):
    """按严重度 / 分类 / 关键字过滤诊断。

    放在 proxy 而不是 model 里，是为了让「原始诊断」保持完整 ——
    过滤只是视图的事，改过滤条件不该动数据。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._severities: set = set()
        self._categories: set = set()
        self._keyword = ""
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def set_severities(self, severities) -> None:
        self._severities = set(severities)
        self.invalidateFilter()

    def set_categories(self, categories) -> None:
        self._categories = set(categories)
        self.invalidateFilter()

    def set_keyword(self, keyword: str) -> None:
        self._keyword = (keyword or "").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model = self.sourceModel()
        issue = model.issue_at(row) if hasattr(model, "issue_at") else None
        if issue is None:
            return True
        if self._severities and getattr(issue, "severity", None) not in self._severities:
            return False
        if self._categories and getattr(issue, "category", None) not in self._categories:
            return False
        if self._keyword:
            haystack = " ".join(str(getattr(issue, key, "")) for key in
                                ("rule", "target", "message")).lower()
            if self._keyword not in haystack:
                return False
        return True
