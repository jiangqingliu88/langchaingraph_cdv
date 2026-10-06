"""一个模块视图的子窗口 —— 中央工作区里的「一页」。

它只多一件事：**关之前问一句**。模块可能正编着一份没保存的 YAML，直接关掉
（哪怕是"只是隐藏"）会让人以为改动没了。所以把 `guard` 交给它 ——
守卫说不行就不关。

关掉**不是销毁**（`WA_DeleteOnClose=False`）：模块状态留着，导航树与「窗口」
菜单随时能再打开。所以关的第二条路是 `on_closed` 回调 —— 由工作区把它**摘下去**
（`removeSubWindow`），而不是让 Qt 自己 `hide()`。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMdiSubWindow, QWidget

#: 新子窗口的默认尺寸 —— 只为开的时候有个体面的初值，之后由用户摆
DEFAULT_SIZE = (680, 520)

#: 层叠摆放时每个窗口的错位量
CASCADE_STEP = 24


class ModuleSubWindow(QMdiSubWindow):
    """承载一个模块控件的工作区窗口。"""

    def __init__(self, module_id: str, title: str, widget: QWidget,
                 guard: Optional[Callable[[str], bool]] = None,
                 on_closed: Optional[Callable[[str], None]] = None) -> None:
        super().__init__()
        self._guard = guard
        self._on_closed = on_closed

        self.setProperty("module_id", module_id)
        self.setObjectName(f"subwindow.{module_id}")
        self.setWindowTitle(title)
        # **显式要最小化 / 放大 / 关闭三个按钮** —— 不写全的话标题栏上只有个
        # "关闭"，"放大"得自己去双击标题栏，不好发现。
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowMinimizeButtonHint
                            | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowCloseButtonHint)
        # 关掉不销毁 —— 模块状态留着，随时能再打开
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWidget(widget)
        # **显式 show** —— `setWidget` 只重挂父级，**不会清掉控件原有的
        # "隐藏"状态**。而中心模块的控件在懒加载时是被 `hide()` 挂着的
        # （没点开就不该露面），不清这一下的话：子窗口里一片空白，
        # 而且因为 Qt 布局会跳过隐藏子件，控件尺寸也卡在 640×480 不跟着缩放 ——
        # 表现就是"每页内容都是空的/不全"（真踩过，渲染出来才看见）。
        widget.show()

    # ── 身份 ──

    @property
    def module_id(self) -> str:
        return str(self.property("module_id") or "")

    def set_title(self, title: str) -> None:
        self.setWindowTitle(title)

    def take_widget(self) -> Optional[QWidget]:
        """把承载的控件摘下来（还给调用方），别让它跟着窗口一起没。"""
        widget = self.widget()
        self.setWidget(None)
        return widget

    # ── 生命周期 ──

    def closeEvent(self, event) -> None:                # noqa: N802  Qt 接口
        module_id = self.module_id
        if self._guard is not None and module_id and not self._guard(module_id):
            event.ignore()          # 模块自己已经把话说清楚了（弹了保存/放弃/取消）
            return
        if self._on_closed is not None and module_id:
            # **别让 Qt 自己收** —— 它只是 `hide()`，标签栏上那条标签还在
            # （标签页模式下看着就像"关不掉"）。交给工作区正规地摘掉。
            event.ignore()
            self._on_closed(module_id)
            return
        super().closeEvent(event)


def cascade_offset(index: int) -> int:
    """第 index 个窗口的层叠错位 —— 免得新窗口正好盖住上一个。"""
    return CASCADE_STEP * index
