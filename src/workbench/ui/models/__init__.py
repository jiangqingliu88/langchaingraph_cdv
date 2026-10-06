"""Qt 模型 —— `QAbstractItemModel` 一族（**不是视图**）。

模型与视图分开是 Qt 的基本做法：数据一变只发 `dataChanged`，视图自己重画。
数据量上万时必须走这条路，`QTableWidget` 那种"一个格子一个控件"的会崩。
"""
from .issues import IssueFilterModel, IssueLike, IssueTableModel
from .rows import CENTER, LEFT, RIGHT, Column, RowsModel, SortProxy

__all__ = ["RowsModel", "SortProxy", "Column", "LEFT", "CENTER", "RIGHT",
           "IssueTableModel", "IssueFilterModel", "IssueLike"]
