"""工作台主窗口的 布局/状态 mixin（Phase 4 拆分）。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QMessageBox,
                               QVBoxLayout, QWidget)

from .bus import EventBus
from .constants import APP_TITLE, CONSOLE_PIN, CONSOLE_TITLE, NAV_PIN
from .context import AppContext
from .manifest import ManifestError, builtin_manifest, describe, load_manifest
from .registry import ModuleManager
from .topics import TaskCompleted, TaskStarted
from .ui import theme
from .ui.theme import icons
from .ui.widgets.banner import Banner
from .ui.widgets.console import ConsolePanel
from .ui.nav.tree import NavPane
from .ui.containers.workspace import Workspace

#: 窗口不贴屏幕边缘的余量（旧 `app.py` 里的局部常量，拆分时漏了定义）。
SCREEN_MARGIN = 40


class WindowLayoutMixin:
        def _apply_pane_defaults(self) -> None:
            """给停靠区一个不抢戏的初始尺寸。

            不设的话 Qt 按各控件 `sizeHint` 分：底部那两个（控制台 + 错误指纹）
            的 sizeHint 加起来把屏幕吃掉三分之一 —— 实测 940 高的窗口里底部占
            ~320px，而中央工作区空着。**主次颠倒**：工作区该最大，工具面板该够用就好。

            **必须在窗口 `show()` 之后调**：`resizeDocks` 在布局铺开之前是空操作
            （各 dock 还没进布局）。所以这里只负责"排进事件循环"，见 `showEvent`。
            """
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._resize_panes)

        def _resize_panes(self) -> None:
            if getattr(self, "_layout_restored", False):
                return          # 用户存过布局 —— 那是他的排法，不动
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtWidgets import QDockWidget

            by_area = {
                _Qt.DockWidgetArea.LeftDockWidgetArea: (_Qt.Orientation.Horizontal,
                                                        self.PANE_DEFAULTS["left"]),
                _Qt.DockWidgetArea.RightDockWidgetArea: (_Qt.Orientation.Horizontal,
                                                         self.PANE_DEFAULTS["right"]),
                _Qt.DockWidgetArea.BottomDockWidgetArea: (_Qt.Orientation.Vertical,
                                                          self.PANE_DEFAULTS["bottom"]),
            }
            for area, (orientation, size) in by_area.items():
                docks = [d for d in self.findChildren(QDockWidget)
                         if self.dockWidgetArea(d) == area]
                if docks:
                    self.resizeDocks(docks, [size] * len(docks), orientation)
            # 底部默认显示**控制台**。
            # `Workspace._add_dock` 里那句 `existing.raise_()`（"保留先来的那个
            # 在最前"）在这里不生效：模块 dock 是最后一批建的，Qt 把新 tabify 的
            # 那个置了顶 —— 启动看到的是「错误指纹」这个模块页而不是控制台。
            # 控制台是"发生了什么"的时间线，被一个具体模块盖住是本末倒置。
            # **必须在这儿（show 之后）raise** —— 和 `resizeDocks` 一样，
            # 窗口没铺开之前这句是空操作。
            dock = getattr(self, "console_dock", None)
            if dock is not None:
                dock.raise_()

        def _apply_window_size(self, spec) -> None:
            """按清单设窗口大小，但**不许超过屏幕可用区域**。

            这是一道**兜底**，不是修某个已知的越界：默认清单的 1520x940 在
            1707x1019 的可用区里是装得下的，实测 `frameGeometry` 无溢出。
            但清单是用户可编辑的，写个 `size: [3000, 2000]` 就会把窗口推到屏幕
            外 —— 那时右下角的缩放手柄够不着，用户只能去改 YAML，看起来就像
            「工具坏了」。夹一下的成本是一个 min()。

            Qt6 的 `availableGeometry()` 给的是逻辑像素，与清单里的数字同量纲，
            所以直接比。`min_size` 也要跟着夹：最小尺寸大于可用区域的话，窗口会
            被强制撑到屏幕外，夹了等于没夹。

            顺带一个后果：在比清单 `min_size` 还小的屏幕上，夹完的最小尺寸会等于
            窗口尺寸 —— 也就是**缩不小了**。这是无可奈何但正确的：最小尺寸若大于
            当前尺寸，Qt 会立刻把窗口撑大回去。默认清单在小屏上不影响用户（1080x680
            仍小于夹后的 1520x940）。
            """
            from PySide6.QtWidgets import QApplication

            screen = self.screen() or QApplication.primaryScreen()
            width, height = spec.size
            min_width, min_height = spec.min_size

            if screen is not None:
                available = screen.availableGeometry()
                width = min(width, max(640, available.width() - SCREEN_MARGIN))
                height = min(height, max(480, available.height() - SCREEN_MARGIN))
                min_width, min_height = min(min_width, width), min(min_height, height)

            self.setMinimumSize(min_width, min_height)
            self.resize(width, height)

        def _build_central(self) -> None:
            """MDI 中央 + Dock 侧栏 —— IDE 形状。

            **这是对先前「固定四窗格、不用 QDockWidget」决定的反转**（旧理由记在
            已删除的 `ui/panes.py` 里）。现在 center 模块是 QMdiArea 里的子窗口
            （可浮动 / 平铺 / 层叠 / 多开），其余三个区是 QDockWidget（可拖拽停靠）。
            见 `ui/workspace.py` 的模块说明。
            """
            central = QWidget(self)
            layout = QVBoxLayout(central)
            layout.setContentsMargins(4, 3, 4, 2)
            layout.setSpacing(3)

            self.banner = Banner(central)
            layout.addWidget(self.banner)

            self.workspace = Workspace(self, central,
                                       close_guard=self._module_can_close)
            layout.addWidget(self.workspace.mdi, 1)
            self.setCentralWidget(central)

            # **`mdi` 这个名字对外保留** —— 它就是中心工作区，模块与测试找它。
            self.mdi = self.workspace.mdi
            self.workspace.on_activated = self._on_subwindow_activated

            # 左 dock = 模块导航树。平台自带、关不掉、双击切模块。
            self.nav = NavPane(self._focus_module)
            self.workspace.add_pinned(self.nav, "模块", NAV_PIN, "left")

        def _build_console(self) -> None:
            """内置控制台 —— 底部窗格的 0 号页签，**pin 住关不掉**。

            它和模块页签并排（不占独立一栏），但平台保证它一直在：控制台是
            「发生了什么」的那条时间线，被切走或关掉就等于没有。
            """
            self.console = ConsolePanel()
            self.ctx.console = self.console
            self.console_dock = self.workspace.add_pinned(
                self.console, CONSOLE_TITLE, CONSOLE_PIN, "bottom")
            self._wire_tasks()

        def _wire_tasks(self) -> None:
            """把后台任务接到控制台那一行进度上。

            `TaskRunner` 与 `ConsolePanel.begin_task/end_task` 两样都早就写好了，
            但**没人把它们接起来** —— 于是界面上看不到任何后台活动。这里补上，
            顺带把完成/失败写进状态栏。

            槽可以直接碰控件：信号在 `TaskRunner` 里已经转发过一次，到达这里时
            已经在主线程上（见 tasks.py 里那段转发注释）。
            """
            tasks = getattr(self.ctx, "tasks", None)
            if tasks is None:
                return
            tasks.started.connect(self._on_task_started)
            tasks.finished.connect(self._on_task_finished)
            tasks.failed.connect(self._on_task_failed)
            # 任务生命周期也走总线：别的视图（证据/决策/状态）可以订阅，
            # 不必直接认识"是哪个模块起的任务"。发布逻辑在模块级，避免把
            # 分支堆进 `_build_window_class` 的圈复杂度。
            tasks.started.connect(
                lambda tid, label: _publish_task_started(self.ctx, tid, label))
            tasks.finished.connect(
                lambda tid, payload: _publish_task_done(self.ctx, tid))
            tasks.failed.connect(
                lambda tid, message: _publish_task_done(self.ctx, tid))

        def _on_task_started(self, task_id: str, label: str) -> None:
            self.console.begin_task(label)
            self.set_status(f"{label} …")

        def _on_task_finished(self, task_id: str, _result: object) -> None:
            label = self.ctx.tasks.label(task_id)
            self.console.end_task(label, ok=True)
            self.set_status(f"{label} —— 完成")

        def _on_task_failed(self, task_id: str, message: str) -> None:
            label = self.ctx.tasks.label(task_id)
            self.console.end_task(label, ok=False)
            self.console.append(f"[{label}] {message}", "error")
            self.set_status(f"{label} —— 失败")

        def _build_status(self) -> None:
            from PySide6.QtWidgets import QLabel

            bar = self.statusBar()
            self.status_label = QLabel("就绪", self)
            bar.addWidget(self.status_label, 1)
            self.stat_modules = QLabel("", self)
            self._style_permanent(self.stat_modules)
            bar.addPermanentWidget(self.stat_modules)

        @staticmethod
        def _style_permanent(label) -> None:
            label.setMinimumWidth(120)
            label.setStyleSheet(
                f"color: {theme.current().muted};"
                f"border-left: 1px solid {theme.current().border};"
                f"padding-left: 8px;")

        def set_tab_suffix(self, module_id: str, suffix: str) -> None:
            """给某个模块的页签标题挂后缀 —— 模块用它标「未保存」。

            让窗格自己找页签、自己记原名：窗口这边不存副本，省得两处不同步
            （踩过：注册表改走窗格之后，窗口那份副本再也没人填，后缀就一直是空的）。
            """
            self.workspace.set_suffix(module_id, suffix)

        def focus_center(self, module_id: str) -> bool:
            """兼容名 —— 子窗口与 dock 都能聚焦，见 `Workspace.focus`。"""
            return self.workspace.focus(module_id)

        def _focus_module(self, module_id: str) -> bool:
            """导航树双击的落点 —— **没开过的模块在这里才建**（工作区默认是空的）。"""
            found = self.manager.open(module_id)
            if not found:
                self.set_status(f"打不开：{module_id} 不在界面上")
            return found

        def _restore_layout(self) -> None:
            if not self.ctx.manifest.window.restore_layout:
                return
            self.ctx.settings.restore_window(self)
            self._clamp_to_screen()
            # **先看布局版本**：换了外壳形状之后，注册表里那份旧布局是照旧壳
            # 排的，贴上去会把新壳的默认排布整个覆盖（踩过：同区 dock 的 tabify
            # 被旧布局覆盖，用户看不到切换标签条）。版本对不上就走默认排布。
            if self.ctx.settings.layout_is_current():
                self.workspace.restore_layout(
                    self.ctx.settings.restore_dock_state(),
                    self.ctx.settings.restore_mdi_state())
                # 存过布局 → 停靠区尺寸的默认值让位（见 `_resize_panes`）
                self._layout_restored = True

        def _clamp_to_screen(self) -> None:
            """把窗口夹回当前屏幕的可用区域 —— **恢复之后**再夹一次。

            存下来的几何属于「上次那块屏」：换了显示器、改了缩放比例、任务栏
            挪了位置，恢复出来的窗口就可能有一部分在屏幕外。而最容易跑出去、
            又最容易被忽视的恰恰是**底部那一整条**（消息窗格 + 状态栏）——
            它们被切掉时界面看着正常，只是「控制台不见了」，很难联想到窗口尺寸。

            `_apply_window_size` 只夹了清单里写的初始尺寸；这一道管的是恢复出来
            的那份。
            """
            from PySide6.QtWidgets import QApplication

            screen = self.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            available = screen.availableGeometry()
            geometry = self.geometry()

            width = min(geometry.width(), available.width())
            height = min(geometry.height(), available.height())
            x = min(max(geometry.x(), available.left()),
                    available.right() - width + 1)
            y = min(max(geometry.y(), available.top()),
                    available.bottom() - height + 1)
            self.setGeometry(x, y, width, height)

        def set_status(self, text: str) -> None:
            self.status_label.setText(text)

        def log(self, text: str, level: str = "info") -> None:
            self.ctx.log(text, level)

        def show_banner(self, text: str, kind: str = "info") -> None:
            self.banner.show_message(text, kind)

