"""工作台主窗口 —— 入口与类骨架；实现拆到 UI / 事件 mixin。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import QApplication, QMainWindow

from .constants import APP_TITLE
from .context import AppContext
from .registry import ModuleManager
from .main_window_actions import WindowActionsMixin
from .main_window_events import WindowEventsMixin
from .main_window_layout import WindowLayoutMixin


class WorkbenchWindowImpl(WindowLayoutMixin, WindowActionsMixin, WindowEventsMixin, QMainWindow):
    """工作台主窗口（组合 UI 构建与事件处理）。"""

    #: 首次布局的停靠区尺寸（左 / 右 / 下）。
    PANE_DEFAULTS = {"left": 280, "right": 320, "bottom": 200}

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


def build_window_class():
    """延迟到导入 Qt 之后才定义 `QMainWindow` 子类（测试/CLI 不依赖 Qt）。"""
    return WorkbenchWindowImpl
