"""表格的公共观感与交互 —— 「工程工具的表格该长什么样」只在这里定义一次。

从旧 `casemodel_tools/view/gui/tabs/base.py::Tab.make_table` 抽出来，改成
**自由函数**：那边的方法挂在 `Tab.self` 上，一抽就得动 11 个页面；平台这
边没有 `Tab` 这个概念，函数更直接。

三件事值得留意：
  · 默认**可排序**，但排完立刻 `sort(-1)` 复位 —— 原始行序（生成顺序、
    严重度顺序）本身是信息，不该被「打开就是按第一列排的」覆盖掉。
  · 排序走 `ui.models.SortProxy`，视图的 index 是**排序后**的行号。取原始
    数据必须先 `source_index()` 映射，否则会取错行 —— 这个坑很容易踩。
  · 右键菜单有「复制单元格 / 整行 / 全部」：工程工具里截图不如贴文本。
"""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QMenu,
                               QTableView, QWidget)

from ..theme import palette as theme
from ..models.rows import SortProxy


def configure_table(parent: Optional[QWidget] = None, model=None, *,
                    sortable: bool = True, stretch_last: bool = True,
                    select_rows: bool = True,
                    copy_headers: Optional[Sequence[str]] = None) -> QTableView:
    """建一张配置好的 `QTableView`。

    给了 `model` 就同时接上排序代理与列宽；没给也行，事后 `view.setModel()`
    —— 但那样得自己包 `SortProxy`，所以更常见的写法是模型先建好再传进来。
    """
    view = QTableView(parent)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(
        QAbstractItemView.SelectionBehavior.SelectRows if select_rows
        else QAbstractItemView.SelectionBehavior.SelectColumns)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    view.setWordWrap(False)
    view.setShowGrid(True)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
    header = view.horizontalHeader()
    header.setHighlightSections(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(stretch_last)

    if model is not None:
        set_model(view, model, sortable=sortable)

    view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    view.customContextMenuRequested.connect(
        lambda pos, v=view: _context_menu(v, pos, copy_headers))
    return view


def set_model(view: QTableView, model, *, sortable: bool = True) -> None:
    """把模型挂到视图上（可排序时自动包一层 `SortProxy`）。"""
    if sortable:
        proxy = SortProxy(view)
        proxy.setSourceModel(model)
        view.setModel(proxy)
        # setSortingEnabled(True) 会顺手按第 0 列排一次 —— 那会把「生成顺序 /
        # 严重度顺序」这个有意义的信息覆盖掉。所以开完能力立刻 sort(-1) 复位，
        # 等用户点表头才真排。
        view.setSortingEnabled(True)
        view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        proxy.sort(-1)
        view._proxy = proxy                       # 供 source_model/clear 找到源模型
    else:
        view.setModel(model)
    if hasattr(model, "apply_column_widths"):
        model.apply_column_widths(view)


def source_model(view: QTableView):
    """穿过排序代理拿到源模型 —— 取值与清空都该看源模型。"""
    proxy = getattr(view, "_proxy", None)
    return proxy.sourceModel() if proxy else view.model()


def source_index(view: QTableView, index):
    """把视图的 index（可能是排序后的行号）映射到源模型。

    套了代理之后 `view.currentIndex().row()` 是**排序后**的行号，直接拿去
    源模型 `row_at()` 会取错行。凡是「点一行 → 取那行的原始对象」都必须过
    这一层。
    """
    proxy = getattr(view, "_proxy", None)
    return proxy.mapToSource(index) if proxy else index


def clear_table(view: QTableView) -> None:
    """没有结果时把表格清空 —— 留着上一次的行会误导。"""
    model = source_model(view)
    for setter in ("set_rows", "set_issues", "set_cases"):
        if hasattr(model, setter):
            getattr(model, setter)([])
            return
    if hasattr(model, "set_result"):
        model.set_result(None)


def row_text(view: QTableView, row: int) -> str:
    """一行的制表符分隔文本 —— 复制用。"""
    model = view.model()
    return "\t".join(_cell_text(model, row, col)
                     for col in range(model.columnCount()))


def _cell_text(model, row: int, col: int) -> str:
    return str(model.data(model.index(row, col)) or "")


def _context_menu(view: QTableView, pos, copy_headers: Optional[Sequence[str]]) -> None:
    """右键菜单：复制单元格 / 复制整行 / 复制全部。"""
    index = view.indexAt(pos)
    if not index.isValid():
        return
    menu = QMenu(view)
    act_cell = menu.addAction("复制单元格")
    act_row = menu.addAction("复制整行")
    act_all = menu.addAction("复制全部")
    chosen = menu.exec(view.viewport().mapToGlobal(pos))
    if chosen is None:
        return
    clipboard = QGuiApplication.clipboard()
    if chosen is act_cell:
        clipboard.setText(str(index.data() or ""))
    elif chosen is act_row:
        clipboard.setText(row_text(view, index.row()))
    elif chosen is act_all:
        model = view.model()
        headers = copy_headers or [
            str(model.headerData(c, Qt.Orientation.Horizontal))
            for c in range(model.columnCount())]
        lines = ["\t".join(headers)]
        lines += [row_text(view, r) for r in range(model.rowCount())]
        clipboard.setText("\n".join(lines))
