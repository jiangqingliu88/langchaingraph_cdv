"""图标 —— 一个动作有没有图标，决定了工具栏像不像工程工具。

Verdi 的工具栏是**图标 + 小字**。只写文字的话，一行中文按钮读起来像表单，
不像调试工具。所以这里做一套最小可用的图标，**不引第三方图标库**（`CLAUDE.md`
的约束是个人级工具、精力放在三件事上，拖一个图标包进来不划算）。

两条来源：
  · Qt 自带的 `QStyle.StandardPixmap` —— 打开/刷新/关闭这类通用语义用它，省事且能
    跟随系统风格
  · 内联 SVG 字符串 —— 通用图标里没有的那些（波形、层次树、重置布局）

**图标跟着主题上色**：SVG 模板里留 `{color}` 占位，渲染时填当前主题的正文色，
所以浅色主题下是黑灰线、深色主题下是浅灰线。缓存键里带上颜色，换主题自然换一套。

HiDPI：按 `devicePixelRatio` 放大渲染再设回去，否则 4K 屏上是糊的。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyle

from . import theme

#: 线条图标都用同一套骨架：16×16 视口、无填充、圆角线帽。
#: `{color}` 由 `icon()` 按当前主题填。
_SVG: Dict[str, str] = {
    # 打开文件夹 —— 对应 Verdi 的 Import Design
    "folder-open": (
        '<path d="M1.5 4.5h4.2l1.4 1.8h7.4v6.2h-13z" fill="none" '
        'stroke="{color}" stroke-width="1.2" stroke-linejoin="round"/>'
        '<path d="M3.2 12.5l1.6-4h9.2l-1.6 4z" fill="none" '
        'stroke="{color}" stroke-width="1.2" stroke-linejoin="round"/>'
    ),
    # 重置布局：两个面板 + 回转箭头
    "layout-reset": (
        '<rect x="1.5" y="2.5" width="5" height="11" fill="none" '
        'stroke="{color}" stroke-width="1.2"/>'
        '<rect x="9.5" y="2.5" width="5" height="5" fill="none" '
        'stroke="{color}" stroke-width="1.2"/>'
        '<path d="M12 9.5v4.5h-2.5" fill="none" stroke="{color}" '
        'stroke-width="1.2" stroke-linecap="round"/>'
        '<path d="M12 14l-1.6-1.6M12 14l1.6-1.6" fill="none" stroke="{color}" '
        'stroke-width="1.2" stroke-linecap="round"/>'
    ),
    # 终端 / 控制台
    "terminal": (
        '<rect x="1.5" y="2.5" width="13" height="11" rx="1" fill="none" '
        'stroke="{color}" stroke-width="1.2"/>'
        '<path d="M4 6l2.5 2.2L4 10.5M8 10.8h4.2" fill="none" stroke="{color}" '
        'stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 层次树
    "tree": (
        '<rect x="1.5" y="6.5" width="4" height="3" fill="none" '
        'stroke="{color}" stroke-width="1.1"/>'
        '<rect x="10.5" y="2.5" width="4" height="3" fill="none" '
        'stroke="{color}" stroke-width="1.1"/>'
        '<rect x="10.5" y="10.5" width="4" height="3" fill="none" '
        'stroke="{color}" stroke-width="1.1"/>'
        '<path d="M5.5 8h2.5V4h2.5M8 8v4h2.5" fill="none" stroke="{color}" '
        'stroke-width="1.1"/>'
    ),
    # 模块（一个方块）—— 导航树里的叶子
    "module": (
        '<rect x="2.5" y="3.5" width="11" height="9" rx="1" fill="none" '
        'stroke="{color}" stroke-width="1.2"/>'
        '<path d="M2.5 6.2h11" fill="none" stroke="{color}" stroke-width="1.1"/>'
    ),
    # 波形 —— Verdi 的 nWave 就是方波
    "wave": (
        '<path d="M1.5 11h3V5h4v6h3V5h3" fill="none" stroke="{color}" '
        'stroke-width="1.3" stroke-linejoin="round"/>'
    ),
    # 复制
    "copy": (
        '<rect x="2.5" y="1.5" width="8" height="9" fill="none" '
        'stroke="{color}" stroke-width="1.2"/>'
        '<rect x="5.5" y="5.5" width="8" height="9" fill="none" '
        'stroke="{color}" stroke-width="1.2"/>'
    ),
    # 查找
    "find": (
        '<circle cx="6.8" cy="6.8" r="4.3" fill="none" stroke="{color}" '
        'stroke-width="1.2"/>'
        '<path d="M10 10l4 4" fill="none" stroke="{color}" stroke-width="1.4" '
        'stroke-linecap="round"/>'
    ),
    # 导出报告：文档 + 向外的箭头
    "export": (
        '<path d="M3.5 1.5h6l3 3v10h-9z" fill="none" stroke="{color}" '
        'stroke-width="1.2" stroke-linejoin="round"/>'
        '<path d="M9.5 1.5v3.2h3.2" fill="none" stroke="{color}" '
        'stroke-width="1.1"/>'
        '<path d="M8 12.5V7.5M5.8 9.7L8 7.5l2.2 2.2" fill="none" '
        'stroke="{color}" stroke-width="1.2" stroke-linecap="round" '
        'stroke-linejoin="round"/>'
    ),
    # 分析 / 重新跑
    "analyze": (
        '<path d="M2.5 12.5V9M6.2 12.5V5.5M9.8 12.5V8M13.5 12.5V3.5" '
        'fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round"/>'
    ),
}

#: 通用语义交给 Qt 的标准图标 —— 跟系统风格一致，也不用自己画
_STANDARD: Dict[str, QStyle.StandardPixmap] = {
    "reload": QStyle.StandardPixmap.SP_BrowserReload,
    "quit": QStyle.StandardPixmap.SP_DialogCloseButton,
    "about": QStyle.StandardPixmap.SP_MessageBoxInformation,
    "folder": QStyle.StandardPixmap.SP_DirIcon,
    "folder-closed": QStyle.StandardPixmap.SP_DirClosedIcon,
    "warning": QStyle.StandardPixmap.SP_MessageBoxCritical,
    "file": QStyle.StandardPixmap.SP_FileIcon,
    "save": QStyle.StandardPixmap.SP_DialogSaveButton,
    "clear": QStyle.StandardPixmap.SP_TrashIcon,
}

#: 画布尺寸。图标按 `size` 逻辑像素显示，内部按 devicePixelRatio 放大渲染。
DEFAULT_SIZE = 16

_cache: Dict[Tuple[str, int, str], QIcon] = {}


def _svg_document(name: str, color: str) -> bytes:
    body = _SVG[name].format(color=color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 16 16" width="16" height="16">{body}</svg>').encode("utf-8")


def render_pixmap(name: str, size: int = DEFAULT_SIZE,
                  color: Optional[str] = None) -> QPixmap:
    """把 SVG 渲成位图。按 devicePixelRatio 放大，避免高分屏发糊。"""
    ratio = _device_ratio()
    pixmap = QPixmap(QSize(int(size * ratio), int(size * ratio)))
    pixmap.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(QByteArray(_svg_document(
        name, color or theme.current().text)))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon(name: str, size: int = DEFAULT_SIZE,
         color: Optional[str] = None) -> QIcon:
    """按名字取图标。名字不认识时返回**空 QIcon**（不是 None）——

    空图标在 Qt 里就是「这个动作没图标」，界面照常工作；返回 None 会让
    `action.setIcon(None)` 之外的调用点（比如自己画的地方）炸掉。
    """
    if name in _STANDARD:
        style = QApplication.style()
        return style.standardIcon(_STANDARD[name]) if style else QIcon()

    if name not in _SVG:
        return QIcon()

    key = (name, size, color or theme.current().text)
    if key not in _cache:
        _cache[key] = QIcon(render_pixmap(name, size, key[2]))
    return _cache[key]


def standard(name: str) -> QIcon:
    """只取 Qt 标准图标；名字不在表里返回空图标。"""
    return icon(name) if name not in _SVG else QIcon()


def names() -> Tuple[str, ...]:
    """全部可用的图标名 —— 测试与自查用。"""
    return tuple(sorted(set(_SVG) | set(_STANDARD)))


def clear_cache() -> None:
    """切主题后调用：缓存键带颜色，不清也不会错，但不清就会越攒越多。"""
    _cache.clear()


def _device_ratio() -> float:
    screen = QApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0
