"""窗格 —— Verdi 式的无缝分割，取代原来的 QDockWidget。

Verdi 的主窗口是**三块可调分割窗格**（左层次树 / 中源码 / 下消息），窗格之间是
一条可拖的分割条，**没有 Dock 标题栏**。Dock 那套（标题栏、浮动、拖拽停靠）是
IDE 的形状 —— 这正是「不像 Verdi」的根因，所以这里整个换掉，**不留并行路径**：

    两套布局 = 两套持久化 = 最难维护的状态

控件树：

    QSplitter(Vertical)          objectName="pane.outer"
    ├─ QSplitter(Horizontal)     objectName="pane.top"
    │  ├─ PaneHost("left")       标签页 0 通常是模块导航树
    │  ├─ PaneHost("center")     它的 QTabWidget 就是 window.center_tabs
    │  └─ PaneHost("right")      没有 right 模块时折叠
    └─ PaneHost("bottom")        标签页 0 通常是控制台

**空窗格必须塌陷**：QSplitter 会把隐藏的子控件从尺寸计算里去掉，分割条也随之
消失 —— 于是「清单里没有 left 模块」不会在界面左边留一条 200px 的空带。

**页签栏与标题条互斥**：页签 ≥ 2 时页签栏本身就是说明，把标题条隐掉；只剩 1 个
页签时页签栏没意义（隐掉），用标题条说明这是哪块窗格。少占一行是一行。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLabel, QSplitter, QTabWidget, QVBoxLayout,
                               QWidget)

from . import theme

#: 四个区域。与清单 `ModuleSpec.area` 一一对应 —— 契约没变，变的只是渲染方式。
PANE_AREAS: Tuple[str, ...] = ("center", "left", "right", "bottom")

#: 各窗格的标题条文案。center 用不到（它总有两个以上页签）。
PANE_TITLES = {
    "left": "层次 / 导航",
    "center": "工作区",
    "right": "属性 / 详情",
    "bottom": "消息 / 控制台",
}

#: 中心窗格不可折叠 —— 它是主工作区，收起来界面就空了
NEVER_COLLAPSE = ("center",)

#: 塌陷后恢复用的默认尺寸
DEFAULT_SIZES = {"left": 260, "center": 900, "right": 320, "bottom": 240}


class PaneHeader(QLabel):
    """窗格顶部的标题条。样式在 `ui/theme.py` 的 `QLabel#paneHeader` 里。"""

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("paneHeader")


class PaneHost(QWidget):
    """一块窗格：一个标题条 + 一个标签页容器。

    同区的模块就是同一块窗格里的页签 —— 不再需要 `tabifyDockWidget` 那种
    「把两个 dock 合起来」的动作，因为它们本来就在一起。
    """

    def __init__(self, area: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("paneHost")
        self.area = area

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = PaneHeader(PANE_TITLES.get(area, area), self)
        self.header.setVisible(False)
        layout.addWidget(self.header)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        layout.addWidget(self.tabs, 1)

        #: module_id → 原始下标。隐藏再显示时要插回原来的位置，
        #: 否则「关掉又打开」会把页签顺序打乱 —— 顺序本身是信息。
        self._order: Dict[str, int] = {}
        #: module_id → 原始标题。挂后缀（● 未保存）时从它重新拼，
        #: 不直接往当前标题上接 —— 那样后缀会越叠越长。
        self._base_titles: Dict[str, str] = {}
        #: 被隐藏的模块控件。`removeTab` 不会删控件，但要自己拿着引用，
        #: 否则 Python 侧没人指向它就会被回收，再显示就崩了。
        self._hidden: Dict[str, QWidget] = {}
        #: 平台自带的页签（控制台、导航树）—— 关不掉
        self._pinned: set = set()
        #: **自己记折叠状态**，不要问 `isHidden()`：没显示过的顶层控件
        #: `isHidden()` 也是 True，那会把「还没显示」误判成「已折叠」。
        self._collapsed = False
        self._last_size = DEFAULT_SIZES.get(area, 200)

        self.tabs.currentChanged.connect(self._sync_header)

    # ════════════════════════════════════════════════════════
    # 加 / 取
    # ════════════════════════════════════════════════════════

    def add_module(self, widget: QWidget, title: str, module_id: str) -> int:
        """加一个模块页签。返回下标。"""
        widget.setProperty("module_id", module_id)
        index = self.tabs.addTab(widget, title)
        self.tabs.setTabToolTip(index, f"{title}（{module_id}）")
        self._order[module_id] = index
        self._base_titles[module_id] = title
        self._sync_header()
        return index

    def set_suffix(self, module_id: str, suffix: str) -> None:
        """给某个页签的标题挂后缀（模块用它标「未保存」）。

        原名存在这里，后缀每次都从原名重新拼 —— 直接往当前标题后面接会让
        后缀越叠越长（切一次主题、改一次内容就叠一层）。

        模块被隐藏时页签不在容器里，这时什么都不做：等它显示回来，模块自己
        会再同步一次。
        """
        base = self._base_titles.get(module_id)
        if base is None:
            return
        index = self.index_of(module_id)
        if index >= 0:
            self.tabs.setTabText(index, f"{base}{suffix}")

    def add_pinned(self, widget: QWidget, title: str, pin_id: str) -> int:
        """加一个**平台自带的**页签（控制台 / 导航树）。

        与模块的区别只有一点：它不能被关掉。实现上就是不走 `set_module_visible`
        那条路 —— 它不在 `_order` 里。
        """
        widget.setProperty("module_id", pin_id)
        index = self.tabs.addTab(widget, title)
        self.tabs.setTabToolTip(index, title)
        self._pinned.add(pin_id)
        self._sync_header()
        return index

    def index_of(self, module_id: str) -> int:
        for index in range(self.tabs.count()):
            if self._module_id_at(index) == module_id:
                return index
        return -1

    def contains(self, module_id: str) -> bool:
        return self.index_of(module_id) >= 0

    def module_ids(self) -> List[str]:
        return [self._module_id_at(i) for i in range(self.tabs.count())]

    def activate(self, module_id: str) -> bool:
        index = self.index_of(module_id)
        if index < 0:
            return False
        self.tabs.setCurrentIndex(index)
        return True

    def current_module_id(self) -> str:
        return self._module_id_at(self.tabs.currentIndex())

    def _module_id_at(self, index: int) -> str:
        if index < 0:
            return ""
        widget = self.tabs.widget(index)
        return str(widget.property("module_id") or "") if widget else ""

    # ════════════════════════════════════════════════════════
    # 显隐 / 折叠
    # ════════════════════════════════════════════════════════

    def is_empty(self) -> bool:
        return self.tabs.count() == 0

    def set_module_visible(self, module_id: str, visible: bool) -> bool:
        """显示/隐藏一个模块页签。返回是否真的改变了状态。

        隐藏是**把页签摘下来**而不是 `setVisible(False)` —— Qt 的页签没有
        「隐藏但保留位置」这回事。控件本身留着（在 `_hidden` 里），所以模块的
        状态（编辑器里的文本、算过的结果）不会因为关了一下就丢。
        """
        if module_id in self._pinned:
            return False            # 平台自带的页签（控制台、导航树）模块关不掉
        return self._set_tab_visible(module_id, visible)

    def set_pinned_visible(self, pin_id: str, visible: bool) -> bool:
        """平台开关**自己的**页签（控制台、导航树）。

        与 `set_module_visible` 的唯一区别：它允许动 pin 住的页签。
        """
        return self._set_tab_visible(pin_id, visible)

    def _set_tab_visible(self, module_id: str, visible: bool) -> bool:
        index = self.index_of(module_id)
        if visible:
            widget = self._hidden.pop(module_id, None)
            if widget is None:
                return False
            at = min(self._order.get(module_id, self.tabs.count()),
                     self.tabs.count())
            self.tabs.insertTab(at, widget,
                                self._base_titles.get(module_id, module_id))
            self._sync_header()
            return True

        if index < 0:
            return False
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget is not None:
            self._hidden[module_id] = widget
        self._sync_header()
        return True

    def set_collapsed(self, collapsed: bool) -> None:
        """整块窗格收起。中心窗格不参与 —— 收起来界面就空了。"""
        if self.area in NEVER_COLLAPSE:
            return
        self._collapsed = bool(collapsed)
        self.setVisible(not self._collapsed)
        self._sync_header()

    def is_collapsed(self) -> bool:
        return self._collapsed

    # ── 内部 ──

    def _sync_header(self) -> None:
        """页签栏与标题条互斥，见模块文档。"""
        many = self.tabs.count() >= 2
        self.tabs.tabBar().setVisible(many)
        self.header.setVisible(not many and not self._collapsed)


class PaneLayout:
    """窗格树 —— 建一次，之后只管往窗格里塞模块。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self.outer = QSplitter(Qt.Orientation.Vertical, parent)
        self.outer.setObjectName("pane.outer")
        self.top = QSplitter(Qt.Orientation.Horizontal, self.outer)
        self.top.setObjectName("pane.top")

        self.panes: Dict[str, PaneHost] = {
            area: PaneHost(area, self.top if area in ("left", "center", "right")
                           else self.outer)
            for area in PANE_AREAS
        }
        self.top.addWidget(self.panes["left"])
        self.top.addWidget(self.panes["center"])
        self.top.addWidget(self.panes["right"])
        self.outer.addWidget(self.top)
        self.outer.addWidget(self.panes["bottom"])

        self._reset_sizes()

    def _reset_sizes(self) -> None:
        self.top.setSizes([DEFAULT_SIZES["left"], DEFAULT_SIZES["center"],
                           DEFAULT_SIZES["right"]])
        self.outer.setSizes([700, DEFAULT_SIZES["bottom"]])

    # ════════════════════════════════════════════════════════
    # 查询
    # ════════════════════════════════════════════════════════

    def pane(self, area: str) -> PaneHost:
        """取某块窗格。区域名认不出时回落到中心 —— 宁可放错也不丢模块。"""
        return self.panes.get(area) or self.panes["center"]

    def pane_of(self, module_id: str) -> Optional[PaneHost]:
        """模块归哪块窗格管 —— **被隐藏的也算**。

        隐藏之后它的页签已经摘下来了，`contains()` 找不到；但它仍然是那块窗格
        的模块（再显示时要插回原位）。调用方问「它归谁管」时两者都该算数，
        所以这里回落去查各窗格记着的隐藏项。
        """
        for pane in self.panes.values():
            if pane.contains(module_id):
                return pane
        for pane in self.panes.values():
            if module_id in pane._hidden:                 # noqa: SLF001
                return pane
        return None

    def focus(self, module_id: str) -> bool:
        """切到某个模块：先让它所在窗格展开，再把那个页签抬起来。"""
        pane = self.pane_of(module_id)
        if pane is None:
            return False
        if pane.is_collapsed():
            pane.set_collapsed(False)
            self.restore_size(pane.area)
        return pane.activate(module_id)

    def set_suffix(self, module_id: str, suffix: str) -> None:
        """给某个模块的页签标题挂后缀 —— 模块不自己找页签，平台替它找。"""
        pane = self.pane_of(module_id)
        if pane is not None:
            pane.set_suffix(module_id, suffix)

    def set_module_visible(self, module_id: str, visible: bool) -> bool:
        pane = self.pane_of(module_id)
        if pane is None:
            return False
        return self._after_visibility_change(pane,
                                             pane.set_module_visible(module_id, visible))

    def set_pinned_visible(self, pin_id: str, visible: bool) -> bool:
        """平台开关自己的页签 —— 左窗格收起就是通过它。"""
        pane = self.pane_of(pin_id)
        if pane is None:
            return False
        return self._after_visibility_change(
            pane, pane.set_pinned_visible(pin_id, visible))

    def _after_visibility_change(self, pane: PaneHost, changed: bool) -> bool:
        """显隐之后窗格该收还是该放。"""
        if not changed:
            return False
        if pane.is_empty():
            self.remember_sizes()
            pane.set_collapsed(True)
        elif pane.is_collapsed():
            pane.set_collapsed(False)
            self.restore_size(pane.area)
        return True

    def collapse_empty(self) -> None:
        """把所有空窗格收起来 —— 建完之后调一次。"""
        for pane in self.panes.values():
            if pane.is_empty():
                pane.set_collapsed(True)

    def repair_saved_sizes(self, sizes, areas: Sequence[Optional[str]]):
        """把「有内容却存成 0 宽」的那几项换回默认尺寸 —— 纯函数，改的是**存的数**。

        来历：上次保存布局时某块窗格可能是空的，存下来就是 0。这次它装了模块
        却仍旧 0 宽，界面上表现为「模块加了但看不见」，用户猜不到要去
        「视图 → 重置布局」。

        **必须在贴回之前改这组数字，而不是贴完之后去改几何**：窗口还没 show
        的时候 `QSplitter.sizes()` 给的是尚未布局的占位值（实测是几十像素的
        等比缩水），拿它做读-改-写会把刚贴回去的正确尺寸整个冲掉。

        判据只用 `is_collapsed()` 这个显式标志与 `is_empty()`，不用 `isVisible()` ——
        同一类坑本模块踩过一次（`isHidden()` 把"还没显示"当成"已折叠"）。
        """
        if not isinstance(sizes, (list, tuple)) or len(sizes) != len(areas):
            return sizes
        out = list(sizes)
        for index, area in enumerate(areas):
            if not area:
                continue
            pane = self.panes.get(area)
            if pane is None:
                continue
            if out[index] <= 1 and not pane.is_empty() and not pane.is_collapsed():
                out[index] = DEFAULT_SIZES.get(area, 200)
        return out

    # ════════════════════════════════════════════════════════
    # 尺寸
    # ════════════════════════════════════════════════════════

    def remember_sizes(self) -> None:
        """把当前尺寸记到各自的窗格上 —— 塌陷前调用。"""
        sizes = self.top.sizes()
        for area, index in (("left", 0), ("center", 1), ("right", 2)):
            if index < len(sizes) and sizes[index] > 0:
                self.panes[area]._last_size = sizes[index]        # noqa: SLF001
        outer = self.outer.sizes()
        if len(outer) > 1 and outer[1] > 0:
            self.panes["bottom"]._last_size = outer[1]            # noqa: SLF001

    def restore_size(self, area: str) -> None:
        """按记住的尺寸把那块窗格放回去。"""
        pane = self.panes[area]
        want = pane._last_size or DEFAULT_SIZES.get(area, 200)    # noqa: SLF001
        if area == "bottom":
            total = sum(self.outer.sizes()) or 900
            self.outer.setSizes([max(1, total - want), want])
            return
        index = ("left", "center", "right").index(area)
        sizes = self.top.sizes()
        total = sum(sizes) or 1200
        others = [s for i, s in enumerate(sizes) if i != index and s > 0]
        left = max(1, total - want - sum(others))
        new = list(sizes)
        new[index] = want
        if index == 1:
            # 中心窗格吸收差值，否则三个数加起来不等于总宽
            new[index] = max(1, total - new[0] - new[2])
        else:
            new[1] = left
        self.top.setSizes(new)

    def state(self) -> dict:
        """可序列化的布局快照 —— 交给 `SettingsStore` 落盘。"""
        return {
            "splitters": {"pane.top": list(self.top.sizes()),
                          "pane.outer": list(self.outer.sizes())},
            "visible": {area: not pane.is_collapsed()
                        for area, pane in self.panes.items()},
        }

    def apply_state(self, saved: dict) -> None:
        """贴回上次的布局。形状不对就整段忽略 —— 布局存坏了不该让界面起不来。"""
        if not isinstance(saved, dict):
            return
        visible = saved.get("visible")
        if isinstance(visible, dict):
            for area, shown in visible.items():
                pane = self.panes.get(area)
                if pane is not None:
                    pane.setVisible(bool(shown))
                    pane._sync_header()                       # noqa: SLF001
        splitters = saved.get("splitters")
        if isinstance(splitters, dict):
            self._apply_sizes(self.top, self.repair_saved_sizes(
                splitters.get("pane.top"), ("left", "center", "right")))
            self._apply_sizes(self.outer, self.repair_saved_sizes(
                splitters.get("pane.outer"), (None, "bottom")))

    @staticmethod
    def _apply_sizes(splitter: QSplitter, sizes) -> None:
        if not isinstance(sizes, (list, tuple)):
            return
        if len(sizes) != splitter.count() or sum(sizes) <= 0:
            return          # 清单变了（窗格数对不上）就按默认来，不硬套
        splitter.setSizes([int(s) for s in sizes])
