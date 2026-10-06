"""窗口状态的持久化 —— 位置、大小、dock/MDI 布局、主题。

用 `QSettings`（Windows 上落注册表，Linux 上落 ~/.config）：`saveGeometry()` /
`saveState()` 输出的是二进制，交给 Qt 自己管最省事。

外壳改成 MDI + Dock 之后（见 `ui/workspace.py`），布局持久化**回到了 Qt 原生**：
  · `window/saveState()` 记住 dock 的位置与可见性
  · `mdi/saveState()`   记住子窗口的位置、大小、层叠顺序
两者都是 QByteArray，与 `windowGeometry` 同样的存法（`_bytes` 统一读回）。

**清单漂移**不再是问题 —— Qt 的 restoreState 自带版本与结构校验，对不上就
原样不动。旧版（分割条时代）存的 `window/panes` 是 JSON，`reset()` 会一并清掉。
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtWidgets import QMainWindow

ORG = "SignOffAI"
APP = "Workbench"

KEY_GEOMETRY = "window/geometry"
KEY_THEME = "window/theme"
#: QMainWindow.saveState() —— dock 的停靠位置与显隐（二进制）
KEY_DOCKS = "window/docks"
#: QMdiArea.saveState() —— 子窗口的位置与大小（二进制）
KEY_MDI = "window/mdi"
#: 旧版（分割条时代）的布局 —— 现在没人读，但 reset() 该清掉
KEY_PANES = "window/panes"

#: 更早的版本存过的 key —— 读不回也不用管，但 `reset()` 该清掉，
#: 免得注册表里留一串没人认的二进制。
KEY_LEGACY_STATE = "window/state"

#: 布局版本。**换了外壳形状就要 +1** —— 旧布局是照旧壳排的，贴到新壳上
#: 会把新壳的默认排布整个覆盖掉（踩过：MDI/dock 改造后，注册表里那份
#: "两个 dock 并排"的旧布局把同区 tabify 覆盖了，用户看不到切换标签条）。
KEY_LAYOUT_VERSION = "window/layout_version"
LAYOUT_VERSION = 2


class SettingsStore:
    """窗口状态的读写门面。传 `QSettings` 实例进来是为了测试能用临时文件。"""

    def __init__(self, settings: Optional[QSettings] = None) -> None:
        self._settings = settings if settings is not None else QSettings(ORG, APP)

    # ── 原始读写 ──

    def value(self, key: str, default=None):
        return self._settings.value(key, default)

    def set_value(self, key: str, value) -> None:
        self._settings.setValue(key, value)

    def sync(self) -> None:
        self._settings.sync()

    # ── 窗口 ──

    def save_window(self, window: QMainWindow, *, theme: str = "",
                    ) -> None:
        self.set_value(KEY_GEOMETRY, window.saveGeometry())
        if theme:
            self.set_value(KEY_THEME, theme)
        self.sync()

    def restore_window(self, window: QMainWindow) -> None:
        """把上次的几何贴回去。没有记录就什么都不做。"""
        geometry = self._bytes(self.value(KEY_GEOMETRY))
        if geometry is not None:
            window.restoreGeometry(geometry)

    # ── 布局版本 ──

    def layout_is_current(self) -> bool:
        """存下来的布局是不是**这一版外壳**排的。

        不是就别贴 —— 旧壳的排布贴到新壳上是错的。返回 False 时窗口会走
        清单驱动的默认排布（那才是对新壳有意义的布局）。
        """
        try:
            return int(self.value(KEY_LAYOUT_VERSION, 0) or 0) == LAYOUT_VERSION
        except (TypeError, ValueError):
            return False

    def mark_layout_version(self) -> None:
        self.set_value(KEY_LAYOUT_VERSION, LAYOUT_VERSION)

    # ── dock / MDI 布局 ──

    def save_dock_state(self, state: QByteArray) -> None:
        """存 dock 的停靠位置与显隐（`QMainWindow.saveState()` 的产物）。"""
        self.set_value(KEY_DOCKS, state)

    def restore_dock_state(self) -> Optional[QByteArray]:
        return self._bytes(self.value(KEY_DOCKS))

    def save_mdi_state(self, state: str) -> None:
        """存子窗口的位置与大小。

        是 **JSON 字符串**不是 QByteArray —— `QMdiArea` 没有 `saveState()`
        （它和 `QMainWindow` 不是一回事），那份快照是 `Workspace` 自己拼的。
        """
        self.set_value(KEY_MDI, state)

    def restore_mdi_state(self) -> str:
        raw = self.value(KEY_MDI)
        return raw if isinstance(raw, str) else ""

    def saved_theme(self) -> str:
        return str(self.value(KEY_THEME, "") or "")

    def reset(self) -> None:
        """「视图 → 重置布局」的落点：清掉布局相关键，保留其它设置（如主题）。"""
        for key in (KEY_GEOMETRY, KEY_DOCKS, KEY_MDI, KEY_PANES,
                    KEY_LEGACY_STATE, KEY_LAYOUT_VERSION):
            self._settings.remove(key)
        self.sync()

    @staticmethod
    def _bytes(value) -> Optional[QByteArray]:
        """QSettings 在个别平台上会把 QByteArray 读回成 `str`，统一一下。"""
        if value is None or value == "":
            return None
        if isinstance(value, QByteArray):
            return value
        return QByteArray(value)
