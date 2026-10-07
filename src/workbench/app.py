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
from .ui.widgets.banner import Banner
from .ui.widgets.console import ConsolePanel

APP_TITLE = "SignOffAI · 验证工作台"
CONSOLE_TITLE = "控制台"

#: 平台自带页签的 id。双下划线打头是刻意的 —— 它们不是清单里的模块，
#: 不能跟模块 id 撞车。
CONSOLE_PIN = "__console__"
NAV_PIN = "__nav__"

#: 项目下拉里那条"就地登记"的哨兵值（不是项目 id）
REGISTER_ACTION = "__register__"


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
    parser.add_argument("--project", default=None,
                        help="项目 id（登记表 ~/.signoffai/projects.yaml）—— "
                             "切到那个项目的工作目录与清单")
    return parser


def apply_project(args) -> None:
    """`--project` → 换工作目录 + 换清单。**必须在建窗口之前调**。

    为什么是"换目录"就等于"换项目"：产物（`output/`）与记忆
    （`.signoffai/*.db`）都是相对工作目录解析的，换了目录，两者天然互不可见
    —— 隔离不用新造机制（见 `projects.py` 的说明）。

    清单没显式给就用项目根下那份；项目目录不存在 → **报错退出**，不静默退化成
    "在当前目录跑另一个项目"（那会往错的目录里写产物）。
    """
    from . import projects as projects_mod

    project = projects_mod.find(str(args.project))
    if project is None:
        raise SystemExit(f"登记表里没有项目 {args.project!r}"
                         f"（找过 {projects_mod.registry_path()}）")
    if not project.exists:
        raise SystemExit(f"项目 {project.id} 的工作目录不存在：{project.root}")
    import os

    os.chdir(project.root)
    if not args.manifest:
        manifest = project.manifest_path
        if manifest is None:
            raise SystemExit(
                f"项目 {project.id} 下找不到界面清单"
                f"（{project.root}/config/workbench.yaml）—— 在登记表里写 manifest: 指一份")
        args.manifest = str(manifest)


def _build_window_class():
    """延迟到导入 Qt 之后才定义 `QMainWindow` 子类。

    这样 `import src.workbench.app` 本身不需要 Qt 已安装（例如只想知道默认
    清单在哪），`build_parser()` 之类也能在无 Qt 环境下测。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QMessageBox,
                                   QVBoxLayout, QWidget)

    from .ui.theme import icons
    from .ui.nav.tree import NavPane
    from .ui.containers.workspace import Workspace

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

            self._apply_pane_defaults()     # 首次布局给停靠区一个合理尺寸
            self._restore_layout()          # 有存过布局的话，它覆盖上面的默认值
            self._report_after_build()

        #: 首次布局的停靠区尺寸（左 / 右 / 下）。放在这里而不是各模块里 ——
        #: 尺寸是**窗口级**的取舍，模块不该关心自己有多宽。
        PANE_DEFAULTS = {"left": 280, "right": 320, "bottom": 200}

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

        def _module_can_close(self, module_id: str) -> bool:
            """子窗口关闭守卫 —— 模块说有未保存改动就先问一句。"""
            return self.manager.can_close(module_id)

        def _on_subwindow_activated(self, module_id: str) -> None:
            """聚焦的子窗口变了 —— 跑模块的 `on_activated`、加粗导航树、换工具栏。"""
            self.manager.notify_activated(module_id)
            self.nav.set_active(module_id)
            # 工具栏跟着当前模块换（动作本来只对它有含义）
            self.set_toolbar_actions(module_id)

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
            # ── 仿真业务下拉（工具栏，紧跟项目切换器）──
            # 回归"跑哪门业务"（覆盖率 / 波形 / 调试…）。默认覆盖率。
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
                "切项目 = 换工作目录重开工作台（产物 output/ 与记忆 .signoffai/*.db "
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

        def _build_sim_mode_picker(self) -> None:
            """「仿真业务」下拉 —— 这次回归跑哪门业务（默认覆盖率）。

            **它只是"下次启动运行带什么"**，不是运行中的开关：已经跑起来的那一轮
            不会追溯生效。这不是偷懒 —— 仿真业务决定命令怎么拼，属于**运行的
            输入**（`RunRequest.sim_modes` → `PipelineState` → 回归框架的
            `MODE_OPTS`），跑完要能回答"这份波形是哪门业务跑出来的"。中途改一个
            界面控件去动已经在跑的命令，那份记录就成了假的。

            词条来自工具层的表（`src/tools/regression_tools/sim_modes.py`），
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
                "回归的仿真业务：选中哪门就只跑哪门（默认覆盖率）。" + chr(10) +
                "词条与取值见 src/tools/regression_tools/sim_modes.py；" + chr(10) +
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

            view_menu = add("视图(&V)")
            view_menu.addAction(self.act_toggle_nav)
            view_menu.addAction(self.act_toggle_console)
            view_menu.addSeparator()
            view_menu.addAction(self.act_workspace_tabs)
            view_menu.addAction(self.act_reset_layout)
            view_menu.addSeparator()
            for action in self._theme_actions:
                view_menu.addAction(action)

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
            # **先看布局版本**：换了外壳形状之后，注册表里那份旧布局是照旧壳
            # 排的，贴上去会把新壳的默认排布整个覆盖（踩过：同区 dock 的 tabify
            # 被旧布局覆盖，用户看不到切换标签条）。版本对不上就走默认排布。
            if self.ctx.settings.layout_is_current():
                self.workspace.restore_layout(
                    self.ctx.settings.restore_dock_state(),
                    self.ctx.settings.restore_mdi_state())
                # 存过布局 → 停靠区尺寸的默认值让位（见 `_resize_panes`）
                self._layout_restored = True
                # **不恢复上次开着的视图** —— 启动就是空的，视图一律等左树点开。
                # 恢复的只有**布局**（dock 停靠与显隐、各视图的位置尺寸），
                # 不是"打开了哪些"。这是刻意的：一个都没点就自己冒出一堆标签，
                # 反而不知道哪些是自己要看的。

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
            self.nav.set_active(self.workspace.active_module_id())

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
                # 先把浮出来的面板收回停靠位 —— 不收的话它们是独立顶层窗口，
                # 主窗口关了它们还在桌面上，进程也退不干净
                self.workspace.dock_all_floating()
                docks, mdi = self.workspace.save_layout()
                self.ctx.settings.save_window(self, theme=theme.current().name)
                self.ctx.settings.save_dock_state(docks)
                self.ctx.settings.save_mdi_state(mdi)
                self.ctx.settings.mark_layout_version()
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
    # `--project` 要**在解析清单路径之前**落地：它换的是工作目录 + 清单
    # （见 `apply_project`）。chdir 也必须早于建窗口 —— 之后起的 agent、记忆库、
    # 运行目录全都按当时的工作目录解析。
    if args.project:
        apply_project(args)
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
