"""通用行表模型 —— 那些「就是几列文本」的表格。

设计模式：**Adapter**（把 Python 的 list[tuple] 适配成 Qt 的 model/view 接口）。

为什么需要它：环境指纹、检查项、专题汇总、规则清单这些页面本质上都是
「表头 + 若干行」；每个都去写一遍 QAbstractTableModel 的样板是浪费。
这里做一个通用的，其余专用模型（诊断 / case / 组织树）才值得单独写 ——
它们的单元格要算颜色、要拼字段、要表达层级。

颜色和图标交给调用方：传 `row_colors`（按行）或 `cell_colors`（按行列），
模型只负责把它们翻成 Qt 的 ForegroundRole —— 判定逻辑不该跑进模型里。

> 本文件原在 `src/layers/l3_decision/casemodel/view/gui/models/rows_model.py`，
> 工作台第一轮上提为平台通用件；旧路径留了一个转发 shim。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import (QAbstractTableModel, QModelIndex,
                            QSortFilterProxyModel, Qt)
from PySide6.QtGui import QColor

#: (键, 表头, 列宽, 对齐)
Column = Tuple[str, str, int, str]

LEFT = "left"
CENTER = "center"
RIGHT = "right"


class RowsModel(QAbstractTableModel):
    """行 = dict（或 tuple），列 = (键, 表头, 宽, 对齐)。"""

    def __init__(self, columns: Sequence[Column], parent=None) -> None:
        super().__init__(parent)
        self.columns: List[Column] = list(columns)
        self._rows: List[Any] = []
        self._row_colors: Dict[int, QColor] = {}
        self._cell_colors: Dict[Tuple[int, int], QColor] = {}

    # ── 数据 ──

    def set_rows(self, rows: Sequence[Any],
                 row_colors: Optional[Dict[int, QColor]] = None,
                 cell_colors: Optional[Dict[Tuple[int, int], QColor]] = None) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._row_colors = dict(row_colors or {})
        self._cell_colors = dict(cell_colors or {})
        self.endResetModel()

    def row_at(self, row: int) -> Any:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    @property
    def rows(self) -> List[Any]:
        return list(self._rows)

    # ── Qt 接口 ──

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        item = self._rows[row]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            value = self._value(item, col)
            text = "" if value is None else str(value)
            if role == Qt.ItemDataRole.ToolTipRole:
                return text or None
            return text
        if role == Qt.ItemDataRole.ForegroundRole:
            return (self._cell_colors.get((row, col))
                    or self._row_colors.get(row))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(self.columns[col][3])
        return None

    def headerData(self, section: int, orientation,
                   role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section][1]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(self.columns[section][3])
        return None

    # ── 取值 ──

    def _value(self, item: Any, col: int):
        key = self.columns[col][0]
        if isinstance(item, dict):
            return item.get(key, "")
        if hasattr(item, key):
            return getattr(item, key)
        return item[col] if isinstance(item, (list, tuple)) else ""

    @staticmethod
    def _alignment(kind: str):
        return {
            LEFT: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            CENTER: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            RIGHT: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        }[kind]

    # ── 给 QTableView 用的列宽 ──

    def apply_column_widths(self, view) -> None:
        for i, (_key, _head, width, _align) in enumerate(self.columns):
            view.setColumnWidth(i, width)


class SortProxy(QSortFilterProxyModel):
    """按列排序的代理。

    为什么放在代理而不是模型的 sort() 里：排序是**视图的事**，
    原始行序（生成顺序、严重度顺序）本身有意义，不该被排序改掉。
    代理只决定「怎么显示」，清掉排序就回到原序。

    排序键的取法：**UserRole 是标量才用它，否则回落 DisplayRole**。
    诊断模型的 UserRole 放的是严重度的语义序（比按中文首字排合理），
    但 case 模型的 UserRole 放的是 CaseAttribute 对象（供详情面板取用）——
    拿对象去比就是在比 dataclass 的 repr，排出来莫名其妙。所以按类型分辨。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDynamicSortFilter(True)

    @staticmethod
    def _key(source, index: QModelIndex):
        value = source.data(index, Qt.ItemDataRole.UserRole)
        if isinstance(value, (int, float, str)) and not isinstance(value, bool):
            return value
        return source.data(index, Qt.ItemDataRole.DisplayRole)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        source = self.sourceModel()
        lv = self._key(source, left)
        rv = self._key(source, right)
        if lv is None or lv == "":
            return True
        if rv is None or rv == "":
            return False
        # 数字按数值比，其余按字符串 —— 否则 "10" < "9"
        try:
            return float(lv) < float(rv)
        except (TypeError, ValueError):
            return str(lv) < str(rv)
