"""一个侧栏面板 —— 左 / 右 / 底 三边的那个可浮动 Dock。

它是**一个模块的常驻面板**（运行历史、证据、错误指纹、导航树、控制台）。
与中央的视图不同，dock 天然单例 —— 它只有一块停靠位，"开两个"没地方放。

**配置只在这里写一遍**：可拖动、可浮动、可关闭、可停到任意边。不写全的话
用户既拖不动也浮不出来 —— 那"用 Dock"就白用了。
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

#: 区域名 → Qt 的停靠位置。区域名与清单 `ModuleSpec.area` 一致。
QT_DOCK_AREA: Dict[str, Qt.DockWidgetArea] = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    "right": Qt.DockWidgetArea.RightDockWidgetArea,
    "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
}


class ModuleDock(QDockWidget):
    """一个模块面板 —— 可拖、可浮、可关、可停任意边。"""

    def __init__(self, module_id: str, title: str, widget: QWidget,
                 window: QMainWindow) -> None:
        super().__init__(title, window)
        self.setObjectName(f"dock.{module_id}")
        self.setProperty("module_id", module_id)
        self.setWidget(widget)
        # 允许拖到任意边、也允许拖出来浮动 —— 这是上 Dock 的意义所在
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                         | QDockWidget.DockWidgetFeature.DockWidgetClosable)

    @property
    def module_id(self) -> str:
        return str(self.property("module_id") or "")

    def set_title(self, title: str) -> None:
        self.setWindowTitle(title)


def dock_area_of(area: str) -> Qt.DockWidgetArea:
    """区域名 → Qt 停靠位置。认不出的名字回落到左，不丢面板。"""
    return QT_DOCK_AREA.get(area, Qt.DockWidgetArea.LeftDockWidgetArea)


def first_dock_in(docks: Dict[str, "ModuleDock"], areas: Dict[str, str],
                  area: str, *, exclude: str = "") -> Optional["ModuleDock"]:
    """这个区域里**已经有的**第一个 dock —— 用来决定跟谁叠成一组。

    `exclude` 排除正在登记的那个：调用方往往先把新 dock 记进表里再问，
    不排除的话会问到自己。
    """
    for module_id, dock in docks.items():
        if module_id != exclude and areas.get(module_id) == area:
            return dock
    return None
