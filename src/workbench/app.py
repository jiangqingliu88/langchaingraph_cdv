"""工作台主窗口 —— 命令行界面之外的那个「界面」。

窗口自己几乎不做业务，只做四件事：
  1. 读清单 → 交给 `ModuleManager` 建界面
  2. 摆好中央标签页 + 三面 Dock + 状态栏 + 控制台
  3. 提供模块要用的那几个钩子（`set_tab_suffix` / `set_status` / 窗格开关）
  4. 关窗口时逐个问模块「能关吗」，存/取布局

**中央标签页不可关闭**（Dock 可以）。理由：中央区是「工作区」，标签页对应
一个能干活的模块，关掉它没有语义（不像文档）；Dock 关掉之后菜单里能再打开，
所以给它开关是安全的。两边区别对待是刻意的。

启动：
    python -m src.workbench [清单.yaml] [--module ID] [--input 路径]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .bootstrap import require_pyside6
from .bus import EventBus
from .config import resolve_manifest_path
from .context import AppContext
from .manifest import ManifestError, builtin_manifest, describe, load_manifest
from .registry import ModuleManager
from .settings_store import SettingsStore
from .ui import theme
from .ui.banner import Banner
from .ui.console import ConsolePanel

APP_TITLE = "SignOffAI · 验证工作台"
CONSOLE_TITLE = "控制台"

#: 平台自带页签的 id。双下划线打头是刻意的 —— 它们不是清单里的模块，
#: 不能跟模块 id 撞车。
CONSOLE_PIN = "__console__"
NAV_PIN = "__nav__"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.workbench",
        description="验证工作台 —— 界面由 YAML 清单驱动（默认 config/workbench.yaml）")
    parser.add_argument("manifest", nargs="?", default=None,
                        help="界面清单路径；不给就用 config/workbench.yaml")
    parser.add_argument("--module", "-m", default=None,
                        help="启动后聚焦到这个模块 id（清单里的 id）")
    parser.add_argument("--input", "-i", default=None,
                        help="覆盖指定模块的业务输入路径")
    parser.add_argument("--theme", default=None,
                        help=f"主题名（可选：{'、'.join(theme.PALETTES)}）")
    parser.add_argument("--reset-layout", action="store_true",
                        help="忽略上次保存的窗口布局")
    return parser


def _build_window_class():
    """延迟到导入 Qt 之后才定义 `QMainWindow` 子类。

    这样 `import src.workbench.app` 本身不需要 Qt 已安装（例如只想知道默认
    清单在哪），`build_parser()` 之类也能在无 Qt 环境下测。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QMessageBox,
                                   QVBoxLayout, QWidget)

    from .ui import icons
    from .ui.nav_pane import NavPane
    from .ui.panes import PaneLayout

    class WorkbenchWindowImpl(QMainWindow):
        def __init__(self, app: QApplication, ctx: AppContext) -> None:
            super().__init__()
            self.qt_app = app
            self.ctx = ctx
            ctx.window = self

            self.manager = ModuleManager(self, ctx)

            spec = ctx.manifest.window
            self.setWindowTitle(spec.title or APP_TITLE)
            self._apply_window_size(spec)

            self._build_central()
            self._build_console()
            self._build_actions()
            self._build_status()            # 必须先于建模块：模块失败时要能写状态栏
            self._build_menus()
            # 七个菜单先建好，模块的动作再往里填（调试 / 工具 / 窗口）
            self.manager.build(ctx.manifest)

            self._restore_layout()
            self._report_after_build()

        # ════════════════════════════════════════════════════
        # 布局
        # ════════════════════════════════════════════════════

        #: 夹取窗口尺寸时给屏幕边缘留的余量 —— 免得窗口正好贴边到看不见边框
        SCREEN_MARGIN = 40

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
                width = min(width, max(640, available.width() - self.SCREEN_MARGIN))
                height = min(height, max(480, available.height() - self.SCREEN_MARGIN))
                min_width, min_height = min(min_width, width), min(min_height, height)

            self.setMinimumSize(min_width, min_height)
            self.resize(width, height)

        def _build_central(self) -> None:
            """三窗格 —— Verdi 的形状：左导航 / 中工作区 / 下消息。

            不再用 QDockWidget：dock 的标题栏、浮动、拖拽停靠是 IDE 的形状，
            而 Verdi 的窗格之间只有一条可拖的分割条。
            """
            central = QWidget(self)
            layout = QVBoxLayout(central)
            layout.setContentsMargins(4, 3, 4, 2)
            layout.setSpacing(3)

            self.banner = Banner(central)
            layout.addWidget(self.banner)

            self.panes = PaneLayout(central)
            layout.addWidget(self.panes.outer, 1)
            self.setCentralWidget(central)

            # 左窗格 0 号页签 = 模块导航树。平台自带、关不掉、双击切模块。
            self.nav = NavPane(self._focus_module)
            self.panes.pane("left").add_pinned(self.nav, "模块", NAV_PIN)

            # **`center_tabs` 这个名字保留** —— 它就是中心窗格的标签页容器，
            # 模块与测试都按这个名字找它。
            self.center_tabs = self.panes.pane("center").tabs
            self.center_tabs.currentChanged.connect(self._on_tab_changed)

        def _build_console(self) -> None:
            """内置控制台 —— 底部窗格的 0 号页签，**pin 住关不掉**。

            它和模块页签并排（不占独立一栏），但平台保证它一直在：控制台是
            「发生了什么」的那条时间线，被切走或关掉就等于没有。
            """
            self.console = ConsolePanel()
            self.ctx.console = self.console
            self.panes.pane("bottom").add_pinned(self.console, CONSOLE_TITLE,
                                                 CONSOLE_PIN)
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

        def _build_actions(self) -> None:
            # 清单相关的动作刻意**避开 Ctrl+O / Ctrl+S / Ctrl+R**：那几个留给
            # 业务模块（打开/保存/重新分析一个模型是日常动作，载入界面清单不是）。
            # 两处都绑同一个键的话，Qt 会判定快捷键歧义，两个都不触发 —— 表现为
            # 「按了没反应」，比没有快捷键更糟。
            self.act_open_manifest = QAction("载入清单…", self)
            self.act_open_manifest.setShortcut("Ctrl+Shift+O")
            self.act_open_manifest.setIcon(icons.icon("folder-open"))
            self.act_open_manifest.triggered.connect(self.on_open_manifest)

            self.act_reload = QAction("重新载入清单", self)
            self.act_reload.setShortcut("F5")
            self.act_reload.setIcon(icons.icon("reload"))
            self.act_reload.triggered.connect(self.on_reload_manifest)

            self.act_reset_layout = QAction("重置布局", self)
            self.act_reset_layout.setIcon(icons.icon("layout-reset"))
            self.act_reset_layout.triggered.connect(self.on_reset_layout)

            self.act_quit = QAction("退出", self)
            self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
            self.act_quit.setIcon(icons.icon("quit"))
            self.act_quit.triggered.connect(self.close)

            self.act_toggle_console = QAction(CONSOLE_TITLE, self, checkable=True)
            self.act_toggle_console.setChecked(True)
            self.act_toggle_console.setIcon(icons.icon("terminal"))
            self.act_toggle_console.toggled.connect(
                lambda visible: self.panes.set_pinned_visible(
                    CONSOLE_PIN, bool(visible)))

            self.act_toggle_nav = QAction("模块导航树", self, checkable=True)
            self.act_toggle_nav.setChecked(True)
            self.act_toggle_nav.setIcon(icons.icon("tree"))
            self.act_toggle_nav.toggled.connect(
                lambda visible: self.panes.set_pinned_visible(
                    NAV_PIN, bool(visible)))

            self.act_copy = QAction("复制", self)
            self.act_copy.setShortcut(QKeySequence.StandardKey.Copy)
            self.act_copy.triggered.connect(lambda: self._forward("copy", "复制"))

            self.act_select_all = QAction("全选", self)
            self.act_select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
            self.act_select_all.triggered.connect(
                lambda: self._forward("selectAll", "全选"))

            self.act_clear_console = QAction("清空控制台", self)
            self.act_clear_console.setIcon(icons.icon("clear"))
            self.act_clear_console.triggered.connect(self.console.clear_log)

            self.act_about = QAction("关于本工作台", self)
            self.act_about.setIcon(icons.icon("about"))
            self.act_about.triggered.connect(self.on_about)

            self._theme_actions: List[QAction] = []
            for name in theme.PALETTES:
                action = QAction(name, self, checkable=True)
                action.setChecked(name == theme.current().name)
                action.triggered.connect(lambda _c=False, n=name: self.set_theme(n))
                self._theme_actions.append(action)

            # 图标 + 小字 —— Verdi 的工具栏就是这个样子。纯文字的一排中文按钮
            # 读起来像表单，不像调试工具。
            self.toolbar = self.addToolBar("主工具栏")
            self.toolbar.setObjectName("mainToolbar")
            self.toolbar.setMovable(False)
            self.toolbar.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.toolbar.addAction(self.act_open_manifest)
            self.toolbar.addAction(self.act_reload)
            self.toolbar.addSeparator()
            self.toolbar.addAction(self.act_reset_layout)

        def _build_menus(self) -> None:
            """Verdi 形的七个菜单。

            **业务线不再占顶层菜单** —— 那样每加一条业务线菜单栏就长一节。
            业务线改由左窗格的导航树承载，另外在「窗口」下每条线一个子菜单。
            模块自己的动作按业务线归到「调试」（debug）或「工具」下，见
            `action_menu_for`。
            """
            bar = self.menuBar()
            # **每一个都要存住引用。** `addMenu(字符串)` 返回的包装器如果没人
            # 持有，PySide 会连 C++ 的 QMenu 一起回收 —— 菜单栏上还画着这一项，
            # 但拿到手就是 `Internal C++ object (QMenu) already deleted`，而且
            # 发作时机在构建之后（下次 GC），排查起来极绕。
            self._menus: Dict[str, QMenu] = {}

            def add(title: str) -> QMenu:
                menu = bar.addMenu(title)
                self._menus[title] = menu
                return menu

            file_menu = add("文件(&F)")
            file_menu.addAction(self.act_open_manifest)
            file_menu.addAction(self.act_reload)
            file_menu.addSeparator()
            file_menu.addAction(self.act_quit)

            edit_menu = add("编辑(&E)")
            edit_menu.addAction(self.act_copy)
            edit_menu.addAction(self.act_select_all)
            edit_menu.addSeparator()
            edit_menu.addAction(self.act_clear_console)

            view_menu = add("视图(&V)")
            view_menu.addAction(self.act_toggle_nav)
            view_menu.addAction(self.act_toggle_console)
            view_menu.addSeparator()
            view_menu.addAction(self.act_reset_layout)
            view_menu.addSeparator()
            for action in self._theme_actions:
                view_menu.addAction(action)

            self.debug_menu = add("调试(&D)")
            self.tools_menu = add("工具(&T)")
            self.window_menu = add("窗口(&W)")
            #: 已经在窗口菜单里开过小标题的业务线（见 `add_window_section`）
            self._window_sections: set = set()

            help_menu = add("帮助(&H)")
            help_menu.addAction(self.act_about)

        def menu(self, title: str) -> QMenu:
            """按标题取一级菜单 —— 测试与自查用。"""
            return self._menus[title]

        def action_menu_for(self, group_id: str) -> QMenu:
            """模块的动作进哪个菜单。

            `debug` → 调试（Verdi 的 Trace 菜单就是这个位置）；其余业务线 →
            工具。这样菜单栏的项数**不随业务线数量增长**。
            """
            return self.debug_menu if group_id == "debug" else self.tools_menu

        def add_window_section(self, group_id: str, title: str) -> QMenu:
            """在「窗口」菜单里开一段业务线的小标题（每个业务线只开一次）。

            模块**平铺**在窗口菜单下，用小标题行分组，不做嵌套子菜单 ——
            嵌套 QMenu 在 PySide6 里会把返回的包装器交给 C++ 父对象持有，
            Python 这边拿到的那个过一会儿就成了死对象
            （`RuntimeError: Internal QMenu already deleted`），而且发作时机
            在 `_build_menus` 之后，排查起来很绕。平铺没有这个问题，
            少一层点开也更快。
            """
            if group_id not in self._window_sections:
                self._window_sections.add(group_id)
                self.window_menu.addSeparator()
                header = self.window_menu.addAction(title)
                header.setEnabled(False)          # 只是个分组标签，不是能点的项
            return self.window_menu

        def _forward(self, method: str, label: str) -> None:
            """把「复制 / 全选」转给当前有焦点的控件。

            用标准快捷键而不是自己实现：文本控件（编辑器、控制台）本来就有
            `copy()` / `selectAll()`，转发过去行为一致。表格没有这两个方法
            —— 那就在状态栏说清楚，别让人以为按了没反应是坏了。
            """
            widget = QApplication.focusWidget()
            if widget is not None and hasattr(widget, method):
                getattr(widget, method)()
                self.set_status(f"{label}：{widget.__class__.__name__}")
                return
            self.set_status(f"当前焦点不支持{label}（表格请用右键菜单）")

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

        # ════════════════════════════════════════════════════
        # 给模块用的钩子
        # ════════════════════════════════════════════════════

        def set_tab_suffix(self, module_id: str, suffix: str) -> None:
            """给某个模块的页签标题挂后缀 —— 模块用它标「未保存」。

            让窗格自己找页签、自己记原名：窗口这边不存副本，省得两处不同步
            （踩过：注册表改走窗格之后，窗口那份副本再也没人填，后缀就一直是空的）。
            """
            self.panes.set_suffix(module_id, suffix)

        def focus_center(self, module_id: str) -> bool:
            """兼容名 —— 现在所有窗格都能聚焦，见 `PaneLayout.focus`。"""
            return self.panes.focus(module_id)

        def _focus_module(self, module_id: str) -> bool:
            """导航树双击的落点。"""
            found = self.panes.focus(module_id)
            if not found:
                self.set_status(f"切不过去：{module_id} 不在界面上")
            return found

        def add_toolbar_actions(self, actions: Sequence[QAction]) -> None:
            if actions:
                self.toolbar.addSeparator()
                for action in actions:
                    self.toolbar.addAction(action)

        def _reapply_icons(self) -> None:
            """换主题后重挂平台动作的图标，并通知各模块重挂自己的。

            图标是按**当前主题的正文色**渲染的（见 `ui/icons.py`），换主题时缓存
            已清，但已经 `setIcon` 过的动作手里还捏着旧位图 —— 不重挂的话，深色
            主题下会留着一排黑色的线描图标，糊在深底上。
            """
            self.act_open_manifest.setIcon(icons.icon("folder-open"))
            self.act_reload.setIcon(icons.icon("reload"))
            self.act_reset_layout.setIcon(icons.icon("layout-reset"))
            self.act_quit.setIcon(icons.icon("quit"))
            self.act_toggle_console.setIcon(icons.icon("terminal"))
            for module in self.manager.modules():
                module.on_theme_changed()

        def set_status(self, text: str) -> None:
            self.status_label.setText(text)

        def log(self, text: str, level: str = "info") -> None:
            self.ctx.log(text, level)

        def show_banner(self, text: str, kind: str = "info") -> None:
            self.banner.show_message(text, kind)

        # ════════════════════════════════════════════════════
        # 行为
        # ════════════════════════════════════════════════════

        def set_theme(self, name: str) -> None:
            palette = theme.apply(self.qt_app, name)
            for action in self._theme_actions:
                action.setChecked(action.text() == palette.name)
            self._style_permanent(self.stat_modules)
            # 图标是按「当前主题的正文色」渲染出来的，换了主题要重画一遍 ——
            # 否则深色主题下会留着上一套黑色的线描图标，糊在深底上。
            icons.clear_cache()
            self._reapply_icons()
            # 自己 setFont 过的控件不吃应用级字体，换了主题要显式重设
            self.console.view.setFont(theme.mono_font())
            for module in self.manager.modules():
                _refresh_fonts(module)
            for index in range(self.center_tabs.count()):
                self.center_tabs.widget(index).update()
            self.ctx.settings.set_value("window/theme", palette.name)
            self.set_status(f"主题：{palette.name}")

        def _on_tab_changed(self, index: int) -> None:
            widget = self.center_tabs.widget(index)
            if widget is not None:
                module_id = str(widget.property("module_id") or "")
                self.manager.notify_activated(module_id)
                self.nav.set_active(module_id)

        def on_open_manifest(self) -> None:
            from PySide6.QtWidgets import QFileDialog

            path, _filter = QFileDialog.getOpenFileName(
                self, "选择界面清单", "", "清单 (*.yaml *.yml);;所有文件 (*)")
            if not path:
                return
            self._reload_from(Path(path))

        def on_reload_manifest(self) -> None:
            self._reload_from(self.ctx.manifest_path)

        def _reload_from(self, path: Path) -> None:
            """重新读清单 —— 需要重启窗口，因为窗格与页签的增删不好原地做。

            与其做一套容易出 bug 的增量更新，不如老实说「换个清单要重开」。
            """
            try:
                load_manifest(path)
            except ManifestError as exc:
                QMessageBox.critical(self, "清单读不进来", str(exc))
                self.ctx.log(str(exc), "error")
                return
            QMessageBox.information(
                self, "重新载入清单",
                f"清单已更新：\n{path}\n\n"
                "窗格与页签的增删需要重开窗口，关掉再启动即可生效。")
            self.ctx.log(f"清单已重新校验：{path}", "info")

        def on_reset_layout(self) -> None:
            self.ctx.settings.reset()
            self.set_status("布局已重置 —— 重开窗口后恢复默认排布")
            self.ctx.log("已清除保存的窗口布局", "info")

        def on_about(self) -> None:
            sections = "\n".join(
                f"  · {group.title}：{len(self.manager.manifest.modules_of(group.id))} 个模块"
                for group in self.ctx.manifest.sorted_groups())
            QMessageBox.information(
                self, "关于",
                f"{APP_TITLE}\n\n"
                f"界面由清单驱动：{self.ctx.manifest_path}\n\n"
                f"{sections or '（无业务线）'}\n\n"
                "加一个界面 = 写一个 IModule 子类 + 在清单里加一条。")

        # ════════════════════════════════════════════════════
        # 布局持久化 / 收尾
        # ════════════════════════════════════════════════════

        def _restore_layout(self) -> None:
            if not self.ctx.manifest.window.restore_layout:
                return
            self.ctx.settings.restore_window(self)
            self._clamp_to_screen()
            self.panes.apply_state(self.ctx.settings.restore_panes())
            index = self.ctx.settings.saved_center_tab()
            if 0 <= index < self.center_tabs.count():
                self.center_tabs.setCurrentIndex(index)

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

        def _report_after_build(self) -> None:
            manifest = self.ctx.manifest
            count = len(self.manager.modules())
            self.stat_modules.setText(f"模块 {count}")

            # 导航树在模块建完之后才填 —— 失败清单这时才完整
            self.nav.populate(manifest)
            failures = self.manager.failures()
            self.nav.set_failed(failures)
            self.nav.set_active(self.panes.pane("center").current_module_id())

            if failures:
                detail = "；".join(f"{k}（{v}）" for k, v in failures.items())
                self.show_banner(f"{len(failures)} 个模块加载失败：{detail}", "error")
                self.ctx.log(f"模块加载失败：{detail}", "error")
            elif not manifest.enabled_modules():
                self.show_banner(
                    "清单里没有启用任何模块 —— 「文件 → 载入清单」选一份清单。",
                    "warning")
            self.set_status(describe(manifest))
            self.ctx.log(describe(manifest), "info")

        def closeEvent(self, event) -> None:            # noqa: N802  Qt 接口
            from PySide6.QtWidgets import QMessageBox as Box

            if not self.manager.close_all():
                answer = Box.question(
                    self, "有未保存的改动",
                    "有模块报告未保存的改动。\n\n仍然退出吗？",
                    Box.StandardButton.Yes | Box.StandardButton.No,
                    Box.StandardButton.No)
                if answer != Box.StandardButton.Yes:
                    event.ignore()
                    return
            if self.ctx.manifest.window.restore_layout:
                self.panes.remember_sizes()
                self.ctx.settings.save_window(
                    self, theme=theme.current().name,
                    center_tab=self.center_tabs.currentIndex(),
                    panes=self.panes.state())
            event.accept()

        @property
        def modules(self) -> List:
            """给测试用的便捷入口。"""
            return self.manager.modules()

    return WorkbenchWindowImpl


def _refresh_fonts(module) -> None:
    """换主题后把自设字体的控件重设一遍 —— 应用级字体对它们无效。"""
    for value in vars(module).values():
        if hasattr(value, "setFont") and hasattr(value, "document"):
            value.setFont(theme.mono_font())
    content = getattr(module, "content", None)
    if content is not None:
        content.update()


# ════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════

def build_workbench(argv: Optional[Sequence[str]] = None):
    """建 QApplication 与主窗口，**不跑事件循环** —— 测试与 `main` 共用。

    清单坏了不阻断启动：用内置的空清单兜底 + 顶上一句红条。让人看到「清单
    写错了」远比让他看到闪退有用。
    """
    code = require_pyside6()
    if code is not None:
        raise SystemExit(code)

    from PySide6.QtWidgets import QApplication

    from .bridge.catalog import default_registry
    from .tasks import TaskRunner

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    app = QApplication.instance() or QApplication(list(sys.argv[:1]))

    manifest_path = resolve_manifest_path(args.manifest)
    manifest, error = _load_or_fallback(manifest_path)

    settings = SettingsStore()
    if args.reset_layout:
        settings.reset()

    # 主题的优先级：命令行 > 清单里写死的 > **上次用的** > 平台默认。
    # 中间那一档要有：清单明确写了主题就该听清单的（它是作者意图）；
    # 清单留空时才轮到用户的最后一次选择 —— 不然在视图里切了主题、
    # 下次开又回去了（`saved_theme()` 写进去却从来没人读，就是这么来的）。
    theme.apply(app, args.theme or manifest.window.theme
                or settings.saved_theme() or theme.DEFAULT_THEME)

    ctx = AppContext(
        manifest=manifest,
        manifest_path=manifest_path,
        tools=default_registry(),
        bus=EventBus(),
        # 任务运行器要先于窗口建好：模块在构造期就可能提交后台任务
        tasks=TaskRunner(),
        settings=settings,
    )

    window = _build_window_class()(app, ctx)

    if error is not None:
        window.show_banner(
            f"清单读不进来，先用一个空的界面顶着：\n{error}", "error")
        window.ctx.log(str(error), "error")

    if args.input and args.module:
        _push_input(ctx, args.module, args.input)
    if args.module:
        window.manager.focus(args.module)
    return app, window, ctx


def _load_or_fallback(manifest_path: Path):
    try:
        return load_manifest(manifest_path), None
    except ManifestError as exc:
        return builtin_manifest(), exc


def _push_input(ctx: AppContext, module_id: str, path: str) -> None:
    module = ctx.modules.get(module_id)
    if module is None:
        ctx.log(f"--input 指定的模块不存在：{module_id}", "warning")
        return
    module.on_input_changed(Path(path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    app, window, _ctx = build_workbench(argv)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
