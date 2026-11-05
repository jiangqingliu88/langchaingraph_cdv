"""平台配置 / 环境与工具 —— 只读展示当前启动环境。

它回答「这个工作台跑在哪个项目、用哪份清单、EDA 工具在不在」：
不提供热改配置（清单/项目切换需要重启，见 `projects.py`）。
"""
from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from ..base import ModuleBase

_TOOLS = ("vlog", "vopt", "vsim", "vcover")


class PlatformSettingsModule(ModuleBase):
    HINT = "当前项目、清单、Python/Qt 与 EDA 工具的可读视图。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()

        form.addRow("工作目录", _selectable(str(Path.cwd())))
        form.addRow("界面清单", _selectable(str(self.ctx.manifest_path)))
        form.addRow("项目", _selectable(_project_text()))
        form.addRow("Python", _selectable(
            f"{platform.python_version()} · {sys.executable}"))
        form.addRow("PySide6", _selectable(_module_version("PySide6")))
        form.addRow("qdarkstyle", _selectable(_module_version("qdarkstyle")))
        for tool in _TOOLS:
            path = shutil.which(tool) or ""
            form.addRow(f"EDA · {tool}", _selectable(path or "未找到（PATH 里没有）"))
        form.addRow("database/", _selectable(_dir_state("database")))
        form.addRow("config/", _selectable(_dir_state("config")))
        layout.addLayout(form)
        layout.addWidget(_muted("清单/项目切换需要重启工作台；EDA 工具的深度版本"
                                "以真实 `vlog/vsim` 运行为准，本页只查 PATH。"))
        layout.addStretch(1)
        return root


def _selectable(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6b6b6b;")
    return label


def _module_version(name: str) -> str:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return "未安装（可选依赖）"
    try:
        module = __import__(name)
        return str(getattr(module, "__version__", "已安装"))
    except Exception:                       # noqa: BLE001 只展示，不打断
        return "已安装（版本读取失败）"


def _dir_state(name: str) -> str:
    path = Path(name)
    return str(path.resolve()) if path.exists() else f"{path.resolve()}（不存在）"


def _project_text() -> str:
    try:
        from ...projects import current
        project = current()
        return f"{project.name}（{project.root}）" if project else "未登记（按工作目录运行）"
    except Exception:                       # noqa: BLE001
        return "未登记"
