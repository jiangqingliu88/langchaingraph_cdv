"""工作台主窗口的 动作/菜单 mixin（Phase 4 拆分）。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QMessageBox,
                               QVBoxLayout, QWidget)

from .bus import EventBus
from .constants import APP_TITLE, CONSOLE_TITLE
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


class WindowActionsMixin:
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

            # 工作区两种视图：
            #   子窗口（默认）—— 每个模块一个可拖的窗口，真正的 MDI 手感
            #   标签页        —— 子窗口铺成一条标签栏，点标签切（VMware/浏览器的样子）
            # 两种 Qt 都原生支持，切换只是 `setViewMode`，不需要两套代码。
            self.act_workspace_tabs = QAction("工作区标签页模式", self, checkable=True)
            self.act_workspace_tabs.setChecked(self.workspace.is_tiled_view())
            self.act_workspace_tabs.setStatusTip(
                "开：模块铺成一条标签栏，点标签切换（默认）；"
                "关：每个模块一个独立窗口，可并排比较 / 平铺 / 层叠")
            self.act_workspace_tabs.toggled.connect(self.workspace.set_view_mode)

            self.act_quit = QAction("退出", self)
            self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
            self.act_quit.setIcon(icons.icon("quit"))
            self.act_quit.triggered.connect(self.close)

            self.act_toggle_console = QAction(CONSOLE_TITLE, self, checkable=True)
            self.act_toggle_console.setChecked(True)
            self.act_toggle_console.setIcon(icons.icon("terminal"))
            self.act_toggle_console.toggled.connect(
                lambda visible: self.workspace.set_pinned_visible(
                    CONSOLE_PIN, bool(visible)))

            self.act_toggle_nav = QAction("模块导航树", self, checkable=True)
            self.act_toggle_nav.setChecked(True)
            self.act_toggle_nav.setIcon(icons.icon("tree"))
            self.act_toggle_nav.toggled.connect(
                lambda visible: self.workspace.set_pinned_visible(
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

            self.act_guide = QAction("使用指南", self)
            self.act_guide.setIcon(icons.icon("help"))
            self.act_guide.setShortcut("F1")
            self.act_guide.setStatusTip("业务怎么跑、输入是什么、输出去哪看")
            self.act_guide.triggered.connect(self.on_guide)

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
            # ── 项目切换器（工具栏最左）──
            # 切项目 = **换工作目录重开一个进程**（产物与记忆都相对工作目录，
            # 见 projects.py）。不热切换的理由也在那儿写着了。
            self.project_box = None
            self._build_project_picker()
            # ── 业务模式：SoC 团队 / IP 团队（只切换导航可见性）──
            self.business_box = None
            self._build_business_mode_picker()
            # ── 仿真业务下拉（工具栏，紧跟项目切换器）──
            # 回归"跑哪门业务"（覆盖率 / 波形 / 调试…）。默认取工具层的 `DEFAULT_MODE`（`cov+wave`）。
            self.sim_mode_box = None
            self._build_sim_mode_picker()
            # ── 人工节点开关（工具栏，紧跟仿真业务）──
            # 分级回归在 loopback 全过之后要不要**停下等人放行**。
            self.manual_gate_box = None
            self._build_manual_gate_toggle()
            self.toolbar.addAction(self.act_open_manifest)
            self.toolbar.addAction(self.act_reload)
            self.toolbar.addSeparator()
            self.toolbar.addAction(self.act_reset_layout)
            #: 工具栏上**常驻的那几条**（与当前模块无关）—— 重挂模块动作时要留着。
            self._toolbar_global_actions = list(self.toolbar.actions())
            #: 每个模块自己的动作，按模块 id 存着，激活谁挂谁（见 `set_toolbar_actions`）。
            self._toolbar_actions: Dict[str, List[QAction]] = {}
            #: 当前挂在工具栏上的模块段（含那条分隔线），换模块时整段摘掉。
            self._toolbar_module_actions: List[QAction] = []

        def _build_project_picker(self) -> None:
            """工具栏最左的项目下拉 —— **永远显示**。

            第一版在"登记表为空"时直接不画这个控件（当时的理由是"不占地方"），
            结果第一个用户（就是你）在界面上**一根毛都看不到**：登记表是用户级
            文件，本来就不存在，于是功能在、入口不在。这不是"省地方"，是把功能
            藏起来了。所以现在：哪怕一个项目都没登记，也显示当前目录 + 一条
            「登记当前目录为项目…」——功能得先被人发现，才谈得上好不好用。
            """
            from PySide6.QtWidgets import QComboBox, QLabel

            from . import projects as projects_mod

            self._projects = projects_mod.load_projects()
            current = projects_mod.current()
            self.project_box = QComboBox(self)
            self.project_box.setToolTip(
                "切项目 = 换工作目录重开工作台（产物 output/ 与记忆 database/*.db "
                "都按工作目录隔离）" + chr(10) +
                f"登记表：{projects_mod.registry_path()}")
            if current is None:
                # 没登记也照用 —— 如实标"未登记"，别假装是个项目
                self.project_box.addItem(
                    f"（未登记：{Path.cwd().name}）", "")
            for project in self._projects:
                label = project.name if project.exists else f"{project.name}（目录不存在）"
                self.project_box.addItem(label, project.id)
            if current is not None:
                index = self.project_box.findData(current.id)
                if index >= 0:
                    self.project_box.setCurrentIndex(index)
            # 永远留一个"就地登记"的出口 —— 不然新人不知道登记表在哪
            self.project_box.insertSeparator(self.project_box.count())
            self.project_box.addItem("＋ 登记当前目录为项目…", REGISTER_ACTION)
            self.project_box.currentIndexChanged.connect(self._on_project_picked)
            self.toolbar.addWidget(QLabel("项目：", self))
            self.toolbar.addWidget(self.project_box)
            self.toolbar.addSeparator()

        def _build_business_mode_picker(self) -> None:
            """「业务模式」下拉 —— SoC 团队 / IP 团队。

            只切换导航树里的团队业务线，不重建模块、不改数据：
            SoC 模式收起 IP 团队入口，IP 模式收起 SoC 团队入口；
            共享的流程/证据/专业工具始终可见。
            """
            from PySide6.QtWidgets import QComboBox, QLabel

            self.business_box = QComboBox(self)
            self.business_box.addItem("全部业务", "all")
            self.business_box.addItem("SoC 业务", "soc")
            self.business_box.addItem("IP 业务", "ip")
            saved = str(self.ctx.settings.value("business/mode", "all") or "all")
            idx = self.business_box.findData(saved)
            self.business_box.setCurrentIndex(idx if idx >= 0 else 0)
            self.ctx.business_mode = saved if idx >= 0 else "all"
            self.business_box.currentIndexChanged.connect(
                self._on_business_mode_picked)
            self.toolbar.addWidget(QLabel("业务：", self))
            self.toolbar.addWidget(self.business_box)
            self.toolbar.addSeparator()
            self.nav.set_business_mode(saved if idx >= 0 else "all")

        def _on_business_mode_picked(self, _index: int) -> None:
            mode = str(self.business_box.currentData() or "all")
            self.ctx.business_mode = mode
            self.nav.set_business_mode(mode)
            self.ctx.settings.set_value("business/mode", mode)
            self.set_status(f"业务模式：{self.business_box.currentText()}")

        def _build_sim_mode_picker(self) -> None:
            """「仿真业务」下拉 —— 这次回归跑哪门业务（默认 `cov+wave`）。

            **它只是"下次启动运行带什么"**，不是运行中的开关：已经跑起来的那一轮
            不会追溯生效。这不是偷懒 —— 仿真业务决定命令怎么拼，属于**运行的
            输入**（`RunRequest.sim_modes` → `PipelineState` → 回归框架的
            `MODE_OPTS`），跑完要能回答"这份波形是哪门业务跑出来的"。中途改一个
            界面控件去动已经在跑的命令，那份记录就成了假的。

            词条来自工具层的表（`src/layers/l2_orchestration/regression_tools/sim_modes.py`），
            这里不另抄一份；选择记在项目级 `.signoffai/sim_modes.json`。
            """
            from PySide6.QtWidgets import QComboBox, QLabel

            from . import sim_modes as sim_modes_ui

            self.sim_mode_box = QComboBox(self)
            for item in sim_modes_ui.mode_items():
                self.sim_mode_box.addItem(item["label"], item["mode"])
                if item.get("note"):
                    self.sim_mode_box.setItemData(
                        self.sim_mode_box.count() - 1, item["note"],
                        Qt.ItemDataRole.ToolTipRole)
            self.sim_mode_box.setToolTip(
                "回归的仿真业务：选中哪门就只跑哪门（默认 cov+wave）。" + chr(10) +
                "词条与取值见 src/layers/l2_orchestration/regression_tools/sim_modes.py；" + chr(10) +
                "标「本后端无开关」的项在当前 EDA 后端没有对应参数，"
                "选中会被告警忽略（不会把不存在的选项塞进命令行）。")
            # 先把选中项摆好、**再接信号** —— 反过来的话，这个"回到上次选择"的
            # 初始化动作会被当成用户改选，白白往磁盘上回写一遍（值虽然一样）。
            index = self.sim_mode_box.findData(sim_modes_ui.load())
            self.sim_mode_box.setCurrentIndex(max(0, index))
            self.sim_mode_box.currentIndexChanged.connect(self._on_sim_mode_picked)
            self.toolbar.addWidget(QLabel("仿真业务：", self))
            self.toolbar.addWidget(self.sim_mode_box)

        def _build_manual_gate_toggle(self) -> None:
            """「人工节点」开关 —— 分级回归在 **loopback 全过之后**要不要停车等人放行。

            开 = 拦截：那一级证的是"TB 自身自洽"（driver 发出的 == slave monitor
            看到的），要不要接着烧 P0 的机时由人拍；停下后 `status=WAITING_APPROVAL`，
            放行用 `vagent regression approve`（也可在「回归」页看到停在哪儿）。
            关 = 放行：不拦，一口气跑完（`run_regression_staged(auto_approve=True)`）。

            **它和「仿真业务」一样只是"下次启动运行带什么"**，不是运行中的开关 ——
            它决定闭环跑不跑得过那道放行点，属运行的输入，跑完要能回答"这一轮为什么
            没停"。选择记在项目级 `.signoffai/manual_gate.json`。

            默认**开**：门是默认该在的，默认关等于这个机制默认不存在。
            """
            from PySide6.QtWidgets import QCheckBox

            from . import manual_gate as ui

            self.manual_gate_box = QCheckBox(ui.ON_LABEL, self)
            self.manual_gate_box.setToolTip(
                "分级回归的人工节点：loopback 全过之后要不要停下等人放行。" + chr(10) +
                "开（拦截）：停下，用 `vagent regression approve` 放行；" + chr(10) +
                "关（放行）：不拦，一口气跑完。" + chr(10) +
                f"选择记在 {ui.STORE}（**用户级**：换项目也是同一个答案 ——"
                "要不要被拦是操作者的事，不是项目的事）。改动下次启动生效。")
            # 先摆好选中态、**再接信号** —— 同 `_build_sim_mode_picker`：反过来的话
            # 这个"回到上次选择"的初始化动作会被当成用户改选，白白回写一遍磁盘。
            enabled = ui.load()
            self.manual_gate_box.setChecked(enabled)
            self.manual_gate_box.setText(ui.label(enabled))
            self.manual_gate_box.toggled.connect(self._on_manual_gate_toggled)
            self.toolbar.addWidget(self.manual_gate_box)
            self.toolbar.addSeparator()

        def _on_manual_gate_toggled(self, checked: bool) -> None:
            """改了即记住（**下次启动运行生效**，见 `_build_manual_gate_toggle`）。"""
            from . import manual_gate as ui

            ui.save(checked)
            self.manual_gate_box.setText(ui.label(checked))
            self.set_status(f"{self.manual_gate_box.text()}"
                            "（下次启动运行生效）")

        def _on_sim_mode_picked(self, index: int) -> None:
            """选中即记住（**下次启动运行生效**，见 `_build_sim_mode_picker`）。"""
            from . import sim_modes as sim_modes_ui

            mode = str(self.sim_mode_box.itemData(index) or "")
            sim_modes_ui.save(mode)
            self.set_status(f"仿真业务：{self.sim_mode_box.currentText()}"
                            "（下次启动运行生效）")

        def _on_project_picked(self, index: int) -> None:
            """选中另一个项目 → 确认 → 用那个目录重开进程，自己退出。"""
            from PySide6.QtCore import QProcess
            from PySide6.QtWidgets import QInputDialog, QMessageBox

            from . import projects as projects_mod

            project_id = self.project_box.itemData(index)
            if project_id == REGISTER_ACTION:
                self._register_current_dir()
                return
            current = projects_mod.current()
            if not project_id or (current is not None and project_id == current.id):
                return
            project = projects_mod.find(project_id, self._projects)
            if project is None or not project.exists:
                QMessageBox.warning(self, "切不了项目",
                                    f"项目 {project_id} 的工作目录不存在："
                                    f"{getattr(project, 'root', '?')}")
                return
            pivot = QMessageBox.question
            if pivot(
                    self, "切换项目",
                    f"切到「{project.name}」会重开工作台（工作目录 "
                    f"{project.root}）。" + chr(10) + chr(10) +
                    "未保存的改动请先处理。继续吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                # 选回来了 —— 不然下拉停在新项目上，看着像已经切了
                if current is not None:
                    self.project_box.setCurrentIndex(
                        max(0, self.project_box.findData(current.id)))
                return
            argv = projects_mod.relaunch_command(project)
            QProcess.startDetached(argv[0], argv[1:], project.root)
            self.close()

        def _register_current_dir(self) -> None:
            """把当前工作目录登记成项目（就地写登记表，不用去改 YAML）。"""
            from PySide6.QtWidgets import QInputDialog, QMessageBox

            from . import projects as projects_mod

            here = Path.cwd()
            name, ok = QInputDialog.getText(
                self, "登记当前目录为项目",
                f"给 {here} 起个项目名（写进 {projects_mod.registry_path()}）：",
                text=here.name)
            # 下拉要退回去，不然它停在"＋ 登记…"那一行上
            self.project_box.setCurrentIndex(0)
            if not ok or not name.strip():
                return
            try:
                project = projects_mod.register(name.strip(), str(here))
            except Exception as exc:                       # noqa: BLE001
                QMessageBox.warning(self, "登记失败", str(exc))
                return
            self._rebuild_project_picker(select=project.id)
            self.set_status(f"已登记项目「{project.name}」→ {project.root}")

        def _rebuild_project_picker(self, select: str = "") -> None:
            """重挂下拉里的项目条目（登记完不用重启就看得见）。"""
            from . import projects as projects_mod

            self.project_box.blockSignals(True)
            keep = [self.project_box.itemData(i) for i in range(self.project_box.count())]
            self._projects = projects_mod.load_projects()
            while self.project_box.count():
                self.project_box.removeItem(0)
            current = projects_mod.current() or projects_mod.find(select, self._projects)
            if current is None:
                self.project_box.addItem(f"（未登记：{Path.cwd().name}）", "")
            for project in self._projects:
                label = project.name if project.exists else f"{project.name}（目录不存在）"
                self.project_box.addItem(label, project.id)
            pick = projects_mod.find(select, self._projects) or current
            if pick is not None:
                index = self.project_box.findData(pick.id)
                if index >= 0:
                    self.project_box.setCurrentIndex(index)
            self.project_box.insertSeparator(self.project_box.count())
            self.project_box.addItem("＋ 登记当前目录为项目…", REGISTER_ACTION)
            self.project_box.blockSignals(False)
            del keep

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

            # 持有引用：清单里 `pin_to_view: true` 的模块，它的显隐开关
            # 会在 `manager.build()` 之后插进这个菜单（见 `add_view_toggle`）。
            self.view_menu = add("视图(&V)")
            self._view_toggles: List[QAction] = []
            self.view_menu.addAction(self.act_toggle_nav)
            self.view_menu.addAction(self.act_toggle_console)
            self.view_menu.addSeparator()
            self.view_menu.addAction(self.act_workspace_tabs)
            self.view_menu.addAction(self.act_reset_layout)
            self.view_menu.addSeparator()
            for action in self._theme_actions:
                self.view_menu.addAction(action)

            self.debug_menu = add("调试(&D)")
            self.tools_menu = add("工具(&T)")
            self.window_menu = add("窗口(&W)")
            # MDI 编排动作放在**最前**：它们是"窗口"这个词最直接的意思，
            # 模块清单（业务线小标题那一段）从下一节开始
            self.act_new_window = QAction("在新窗口打开当前模块", self)
            self.act_new_window.setShortcut("Ctrl+Shift+O")
            self.act_new_window.setStatusTip("把这个模块再开一个窗口（多开，各编各的）")
            self.act_new_window.triggered.connect(
                lambda: self.manager.open_new_for_active())
            self.act_tile = QAction("平铺窗口", self)
            self.act_tile.triggered.connect(self.workspace.tile)
            self.act_cascade = QAction("层叠窗口", self)
            self.act_cascade.triggered.connect(self.workspace.cascade)
            self.act_next_window = QAction("下一个窗口", self)
            self.act_next_window.setShortcut("Ctrl+Tab")
            self.act_next_window.triggered.connect(self.workspace.activate_next)

            for action in (self.act_new_window, self.act_tile,
                           self.act_cascade, self.act_next_window):
                self.window_menu.addAction(action)
            self.window_menu.addSeparator()

            #: 已经在窗口菜单里开过小标题的业务线（见 `add_window_section`）
            self._window_sections: set = set()

            help_menu = add("帮助(&H)")
            help_menu.addAction(self.act_guide)
            help_menu.addSeparator()
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

        def add_view_toggle(self, action: QAction) -> None:
            """把一个模块的显隐开关也挂到「视图」菜单（清单里 `pin_to_view: true`）。

            为什么要有这条：**视图菜单列的是窗格**（导航树 / 控制台 / 布局 / 主题）。
            「错误指纹」这类模块本质就是一个底部窗格 —— 用户想收起它时会来视图里
            找，而不是去「窗口」那份"模块清单"里翻。两边挂的是同一个 QAction，
            勾选状态由 Qt 同步，不会打架。

            插在**窗格那一组**（导航树 / 控制台）后面，追加到末尾 ——
            视图菜单末尾是主题，把模块开关塞到主题后面就分不清它属于哪一类。
            所以插在「工作区标签页」之前；分隔线只在第一条时补，
            否则多个模块会出现一串连续的分隔线。
            """
            if not self._view_toggles:
                self.view_menu.insertAction(self.act_workspace_tabs, action)
                self.view_menu.insertSeparator(self.act_workspace_tabs)
            else:
                self.view_menu.insertAction(self.act_workspace_tabs, action)
            self._view_toggles.append(action)

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

        def add_toolbar_actions(self, actions: Sequence[QAction],
                                module_id: str = "") -> None:
            """登记**某个模块**的动作 —— 工具栏不立刻挂，等它被激活时再挂。

            原来是把所有模块的动作一股脑加到全局工具栏：25 个模块里有 5 个带
            动作，其中"IP 规格"和"人工节点"各有一套「保存 / 另存为 / 立即校验」
            —— 工具栏上就出现两条同名的三段，而且总长超出窗口被截断（实测
            1520 宽也放不下，右边挂一个溢出箭头）。
            动作本来就只对**当前这个模块**有意义，所以按上下文挂。
            """
            if not actions:
                return
            self._toolbar_actions[module_id] = list(actions)

        def set_toolbar_actions(self, module_id: str) -> None:
            """只挂**当前激活模块**的动作（工具栏的模块段整段替换）。

            **不能用 `QToolBar.clear()`** —— 它连 `QAction` 一起销毁，而全局那几条
            是窗口自己的（菜单里也挂着），下一轮 `addAction` 就会撞上
            `RuntimeError: Internal C++ object (QAction) already deleted`（实测）。
            所以走 `removeAction`：只从工具栏上摘下来，动作本身留着。
            """
            for action in self._toolbar_module_actions:
                self.toolbar.removeAction(action)
            self._toolbar_module_actions = []
            actions = self._toolbar_actions.get(module_id) or []
            if actions:
                separator = self.toolbar.addSeparator()
                self._toolbar_module_actions.append(separator)
                for action in actions:
                    self.toolbar.addAction(action)
                    self._toolbar_module_actions.append(action)

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

        def set_theme(self, name: str) -> None:
            palette = theme.apply(self.qt_app, name)
            for action in self._theme_actions:
                action.setChecked(action.text() == palette.name)
            self._style_permanent(self.stat_modules)
            # 工作区底色与空态文字色走的是**显式设色**那条路，不在样式表里 ——
            # 换主题时它俩不会自己跟上，得点名喊一声（理由见 `WorkspaceArea.apply_theme`）。
            self.mdi.apply_theme()
            # 图标是按「当前主题的正文色」渲染出来的，换了主题要重画一遍 ——
            # 否则深色主题下会留着上一套黑色的线描图标，糊在深底上。
            icons.clear_cache()
            self._reapply_icons()
            # 自己 setFont 过的控件不吃应用级字体，换了主题要显式重设
            self.console.view.setFont(theme.mono_font())
            for module in self.manager.modules():
                _refresh_fonts(module)
            for sub in self.mdi.subWindowList():
                widget = sub.widget()
                if widget is not None:
                    widget.update()
            self.ctx.settings.set_value("window/theme", palette.name)
            self.set_status(f"主题：{palette.name}")

