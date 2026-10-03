"""窗口状态的持久化 —— 位置、大小、窗格布局、主题、当前标签页。

用 `QSettings`（Windows 上落注册表，Linux 上落 ~/.config）：`windowGeometry()`
输出的是二进制，交给 Qt 自己管最省事。

**窗格布局是自己存的**，不再是 `saveState()` —— 那一套只认 QDockWidget，而
工作台改成了三窗格分割条（见 `ui/panes.py`）。所以这里存的是每个分割条的
尺寸数组 + 各窗格是否收起，用 JSON 落成字符串。

**清单漂移**是唯一需要动脑的地方：保存过的窗格尺寸数组长度可能与当前的窗格
数对不上（清单里删掉了一个区域）。那种情况整段忽略、按默认排布来 —— 与其
硬套一串对不上的数字，不如退回一个能看的界面。
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
KEY_CENTER = "window/center_tab"
KEY_PANES = "window/panes"

#: 旧版（Dock 时代）存过的 QDockWidget 布局 —— 读不回也不用管，但 `reset()`
#: 该把它清掉，免得注册表里留一串没人认的二进制。
KEY_LEGACY_STATE = "window/state"


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
                    center_tab: int = -1, panes: Optional[Dict] = None) -> None:
        self.set_value(KEY_GEOMETRY, window.saveGeometry())
        if theme:
            self.set_value(KEY_THEME, theme)
        if center_tab >= 0:
            self.set_value(KEY_CENTER, int(center_tab))
        if panes:
            self.set_value(KEY_PANES, json.dumps(panes, ensure_ascii=False))
        self.sync()

    def restore_window(self, window: QMainWindow) -> None:
        """把上次的几何贴回去。没有记录就什么都不做。"""
        geometry = self._bytes(self.value(KEY_GEOMETRY))
        if geometry is not None:
            window.restoreGeometry(geometry)

    # ── 窗格布局 ──

    def save_panes(self, panes: Dict) -> None:
        self.set_value(KEY_PANES, json.dumps(panes, ensure_ascii=False))
        self.sync()

    def restore_panes(self) -> Dict:
        """上次的窗格快照。没有 / 坏了都返回 `{}` —— 布局存坏不该让界面起不来。"""
        raw = self.value(KEY_PANES)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw if isinstance(raw, str) else str(raw))
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def saved_theme(self) -> str:
        return str(self.value(KEY_THEME, "") or "")

    def saved_center_tab(self) -> int:
        try:
            return int(self.value(KEY_CENTER, -1))
        except (TypeError, ValueError):
            return -1

    def reset(self) -> None:
        """「视图 → 重置布局」的落点：清掉布局相关键，保留其它设置（如主题）。"""
        for key in (KEY_GEOMETRY, KEY_CENTER, KEY_PANES, KEY_LEGACY_STATE):
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
