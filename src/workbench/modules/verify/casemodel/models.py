"""case 模型专属的 Qt 模型。

放这里而不是 `workbench/ui/`：这两个模型认识 `CaseAttribute` / `OrgNode` /
`AnalysisResult`，是**领域**的东西。`ui/` 里只放不懂业务的通用件。

> 原在 `casemodel_tools/view/gui/models/case_model.py` 与 `tree_model.py`，
> 工作台第二轮搬进模块内 —— 通用的行表模型与诊断表模型已经上提到 `ui/`。
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from src.layers.l3_decision.casemodel.domain import CaseAttribute, OrgNode
from src.workbench.ui.models.issues import severity_color

# ════════════════════════════════════════════════════════════
# case 属性表
# ════════════════════════════════════════════════════════════

#: 优先级 → 严重度语义。现取主题色，不存常量 —— 写死的话深色主题下是一片暗色。
#: P0/P1/P2 分别对应「错 / 警 / 提示」，与诊断表用的是同一套语义色。
PRIORITY_SEVERITY = {"P0": "error", "P1": "warning", "P2": "info"}


def priority_color(priority: str):
    severity = PRIORITY_SEVERITY.get(priority)
    return severity_color(severity) if severity else None


def _fields_text(case: CaseAttribute) -> str:
    return "；".join(f"{k}={v}" for k, v in case.fields.items())


def _checks_text(case: CaseAttribute) -> str:
    return "、".join(case.checks) or "（无）"


class CaseTableModel(QAbstractTableModel):
    """列：case_id / 优先级 / 专题 / 节点路径 / 方法 / 字段取值 / 检查。

    `fields` 是 dict、`checks` 是 list，展平成人读的「a=1；b=2」在这里做 ——
    视图不该知道 CaseAttribute 的内部结构。整条 case 留在 UserRole 里，
    选中行时详情面板直接取，不用再回查一遍。
    """

    COLUMNS = (
        ("case_id", "case_id", 190),
        ("priority", "优先级", 66),
        ("theme", "专题", 110),
        ("tree_path", "节点路径", 200),
        ("method", "方法", 60),
        ("fields", "字段取值", 470),
        ("checks", "检查", 180),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cases: List[CaseAttribute] = []

    # ── 数据 ──

    def set_cases(self, cases: Sequence[CaseAttribute]) -> None:
        self.beginResetModel()
        self._cases = list(cases)
        self.endResetModel()

    def case_at(self, row: int) -> Optional[CaseAttribute]:
        return self._cases[row] if 0 <= row < len(self._cases) else None

    @property
    def cases(self) -> List[CaseAttribute]:
        return list(self._cases)

    # ── Qt ──

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._cases)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        case = self._cases[index.row()]
        key = self.COLUMNS[index.column()][0]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(case, key)
        if role == Qt.ItemDataRole.ForegroundRole:
            if key == "priority":
                return priority_color(case.priority)
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(case)
        if role == Qt.ItemDataRole.UserRole:
            return case                       # 详情面板直接取，不用回查
        if role == Qt.ItemDataRole.TextAlignmentRole and key in ("priority", "method"):
            return Qt.AlignmentFlag.AlignCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal \
                and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section][1]
        return None

    def _text(self, case: CaseAttribute, key: str) -> str:
        if key == "fields":
            return _fields_text(case)
        if key == "checks":
            return _checks_text(case)
        if key == "tree_path":
            return case.tree_path or "（不作用功能组织树）"
        return str(getattr(case, key, "") or "")

    def _tooltip(self, case: CaseAttribute) -> str:
        return "\n".join([
            f"{case.case_id}",
            f"专题：{case.theme or '（无）'}　优先级 {case.priority or '—'}",
            f"树路径：{case.tree_path or '（不作用功能组织树）'}",
            f"方法：{case.method} {case.method_name}",
            f"字段：{_fields_text(case)}",
            f"检查：{_checks_text(case)}",
            f"环境：{'、'.join(f'{k}={v}' for k, v in case.environment.items()) or '（无）'}",
        ])

    def apply_column_widths(self, view) -> None:
        for i, (_key, _head, width) in enumerate(self.COLUMNS):
            view.setColumnWidth(i, width)


# ════════════════════════════════════════════════════════════
# 功能组织树
# ════════════════════════════════════════════════════════════

#: 「覆盖 / 缺失 / 分支」三种状态色。
#:
#: **刻意是模块常量，不走调色板** —— 与其他写死颜色的处理不同，这里有两个理由：
#:   · 测试用 `is` 身份比较 `COVERED`（`test_casemodel_module.py` 里），改成
#:     返回主题色的函数会断；要保持身份就得在切换主题时原地 `setRgb`，那是把
#:     一个问题换成另一个更隐蔽的问题。
#:   · 深绿 / 红 / 灰这三个语义色在浅色底（白）和深色底（#262b31）上都读得出来，
#:     没有「看不清」的实际问题。
#: 将来若真要它们跟主题走，正确做法是在 `OrgTreeModel` 里按 `theme.current()`
#: 取色，而不是让 ui 层反过来 import 本模块。
COVERED = QColor("#2e7d32")
UNCOVERED = QColor("#c62828")
BRANCH = QColor("#5f6b7a")


class OrgTreeModel(QAbstractItemModel):
    """功能组织树 —— QAbstractItemModel 的树形实现（Hierarchical Model）。

    为什么值得单独写而不是用 QTreeWidget 塞节点：组织树是**数据**，不是控件内容。
    用真正的模型之后，「哪些节点被专题打到」这类信息直接参与 data()，
    着色与排序都在模型里一处决定。

    index/parent 用 OrgNode 自身当 internalPointer —— 节点本来就有 parent 回指，
    所以父索引不用另建映射表。

    列：节点 / 代号 / 打在这里的专题 / case 数 / 覆盖。
    """

    COLUMNS = ("节点", "代号", "打在这里的专题", "case 数", "覆盖")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._roots: List[OrgNode] = []
        self._result = None

    # ── 数据 ──

    def set_result(self, result) -> None:
        self.beginResetModel()
        self._result = result
        self._roots = list(result.model.org_root) if result else []
        self.endResetModel()

    def node_at(self, index: QModelIndex) -> Optional[OrgNode]:
        return index.internalPointer() if index.isValid() else None

    # ── Qt：结构 ──

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else None
        children = parent_node.children if parent_node else self._roots
        return self.createIndex(row, column, children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: OrgNode = index.internalPointer()
        parent_node = node.parent
        if parent_node is None:
            return QModelIndex()                    # 根节点没有父
        return self.createIndex(self._row_of(parent_node), 0, parent_node)

    def _row_of(self, node: OrgNode) -> int:
        siblings = node.parent.children if node.parent else self._roots
        try:
            return siblings.index(node)
        except ValueError:                          # 节点不在当前树里（模型已重置）
            return 0

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else None
        return len(node.children if node else self._roots)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    # ── Qt：取值 ──

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        node: OrgNode = self.node_at(index)
        if node is None:
            return None
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(node, col)
        if role == Qt.ItemDataRole.ForegroundRole:
            # 节点名与「覆盖」列都染色：只染名字的话，扫一眼看不出哪块没被测
            if col not in (0, 4):
                return None
            if not node.is_leaf:
                return BRANCH
            return COVERED if self._cases(node) else UNCOVERED
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(node)
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (1, 3, 4):
            return Qt.AlignmentFlag.AlignCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal \
                and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    # ── 取值细节 ──

    def _cases(self, node: OrgNode) -> List:
        if self._result is None or not node.is_leaf:
            return []
        return self._result.cases_for_node(node.id)

    def _text(self, node: OrgNode, col: int) -> str:
        if col == 0:
            return node.name
        if col == 1:
            return node.code
        if col == 2:
            if not node.is_leaf:
                return "分支（case 由下层叶子承担）"
            themes = sorted({c.theme for c in self._cases(node) if c.theme})
            return "、".join(themes) or "无"
        if col == 3:
            return str(len(self._cases(node))) if node.is_leaf else ""
        if col == 4:
            if not node.is_leaf:
                return "—"
            # 不用 ✓/✗：它们不是每个字体都有，缺字形就成「豆腐块」，
            # 而这一列的全部意义就是这个标记。用字 + 颜色双通道表达。
            return "有" if self._cases(node) else "缺"
        return ""

    def _tooltip(self, node: OrgNode) -> str:
        lines = [f"路径：{node.path_label()}", f"代号：{node.code}"]
        if node.is_leaf:
            cases = self._cases(node)
            themes = sorted({c.theme for c in cases if c.theme})
            lines.append(f"专题：{'、'.join(themes) or '（无 —— 这块结构不会被测到）'}")
            lines.append(f"case：{len(cases)} 个")
        else:
            lines.append(f"分支：下辖 {len(node.leaves())} 个叶子")
        if node.description:
            lines.append(node.description)
        return "\n".join(lines)

    def apply_column_widths(self, view) -> None:
        for i, width in enumerate((380, 80, 420, 80, 70)):
            view.setColumnWidth(i, width)
