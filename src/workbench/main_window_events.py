"""工作台主窗口的 事件/生命周期 mixin（Phase 4 拆分）。"""
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


class WindowEventsMixin:
        def _module_can_close(self, module_id: str) -> bool:
            """子窗口关闭守卫 —— 模块说有未保存改动就先问一句。"""
            return self.manager.can_close(module_id)

        def _on_subwindow_activated(self, module_id: str) -> None:
            """聚焦的子窗口变了 —— 跑模块的 `on_activated`、加粗导航树、换工具栏。"""
            self.manager.notify_activated(module_id)
            self.nav.set_active(module_id)
            # 工具栏跟着当前模块换（动作本来只对它有含义）
            self.set_toolbar_actions(module_id)

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

        def on_guide(self) -> None:
            from .help_guide import UserGuideDialog

            UserGuideDialog(self).exec()

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

        def _report_after_build(self) -> None:
            manifest = self.ctx.manifest
            count = len(self.manager.modules())
            self.stat_modules.setText(f"模块 {count}")

            # 导航树在模块建完之后才填 —— 失败清单这时才完整
            self.nav.populate(manifest)
            self.nav.set_business_mode(
                getattr(self.ctx, "business_mode", "all") or "all")
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

