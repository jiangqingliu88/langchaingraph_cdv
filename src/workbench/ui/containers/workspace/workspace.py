"""工作区 —— 把「中央工作区」与「侧栏面板」组装起来，并对外提供一套门面。

**这一层是路由，不是控件**：它记「谁属于哪个区域、显隐是什么」、把控件造出来
交给对应的元素（`WorkspaceArea` / `ModuleDock`）、把面板开关与标题后缀这些
请求转给它们。控件本身长什么样、怎么排版、空了显示什么 —— 都在各自那份里。

控件树：

    QMainWindow
    ├─ 中央 = QWidget
    │    ├─ Banner                     ← 平台横幅
    │    └─ WorkspaceArea              ← `window.mdi`，center 模块 → ModuleSubWindow
    ├─ ModuleDock「模块」   (left)      ← 导航树（pin 住，关不掉）
    ├─ ModuleDock …         (left)      ← flow.runs
    ├─ ModuleDock …         (right)     ← flow.evidence
    ├─ ModuleDock「控制台」 (bottom)    ← 控制台（pin 住）
    └─ ModuleDock …         (bottom)    ← debug.fingerprint

**`area` 契约没变**（`center` / `left` / `right` / `bottom`），变的只是载体：
`center` 在中央工作区里，其余三个是 dock。清单与 `spec.py` 一行都不用改。

**center 模块可多开**：`_subwindows[module_id]` 是一个**列表**，同一个模块能有
多个视图窗口（各自一个模块实例）。dock 模块天然单例 —— 它只有一块停靠位。

**关掉不是销毁**：视图窗口 `WA_DeleteOnClose=False`、dock 只 `setVisible(False)`，
控件都活着。模块的状态（编辑器里的文本、算过的结果）不该因为关一下就没了；
导航树与「窗口」菜单随时能再打开。
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import (QDockWidget, QMainWindow, QMdiSubWindow,
                               QTabBar)

from .area import WorkspaceArea
from .dock import ModuleDock, dock_area_of, first_dock_in
from .subwindow import ModuleSubWindow

#: 四个区域。与清单 `ModuleSpec.area` 一一对应 —— 契约没变，变的只是渲染方式。
PANE_AREAS: Tuple[str, ...] = ("center", "left", "right", "bottom")

#: 除中央之外的三个 = dock 区
DOCK_AREAS: Tuple[str, ...] = ("left", "right", "bottom")


class Workspace:
    """MDI + Dock 的布局门面。窗口只跟它打交道，不逐个认控件。"""

    def __init__(self, window: QMainWindow,
                 parent=None,
                 close_guard: Optional[Callable[[str], bool]] = None) -> None:
        self.window = window
        self.mdi = WorkspaceArea(parent)

        #: center 模块的视图窗口（**可多开**，最新的在最后）
        self._subwindows: Dict[str, List[ModuleSubWindow]] = {}
        #: 非 center 模块的 dock（单例）
        self._docks: Dict[str, ModuleDock] = {}
        #: 平台自带的 dock（导航树、控制台）—— 关不掉
        self._pinned: set = set()
        self._areas: Dict[str, str] = {}
        self._base_titles: Dict[str, str] = {}
        #: **显隐自己记**，不要问 `isVisible()`：窗口还没 `show()` 时它恒为 False，
        #: 那会把"还没显示"误判成"已隐藏"（旧 PaneHost 为同一个坑才自己记 `_collapsed`）。
        self._hidden: set = set()
        #: module_id → 上次存的几何。**center 模块是点了才开的**，所以贴布局时
        #: 那个视图窗口还不存在 —— 先把几何存这儿，等它被打开时再套上。
        self._pending_geometry: Dict[str, tuple] = {}
        #: module_id → 还没开就设过的标题后缀（「● 未保存」那类）。
        #: 模块在**载入输入时**就会同步一次后缀，而那时它的窗口可能还没被打开 ——
        #: 不留着的话，点开之后标题上的文件名就没了。
        self._pending_suffix: Dict[str, str] = {}
        self._close_guard = close_guard

        #: 视图窗口被聚焦时的回调（app 装成 `_on_subwindow_activated`）
        self.on_activated: Optional[Callable[[str], None]] = None
        self.mdi.subWindowActivated.connect(self._subwindow_activated)
        #: 某个 dock 的实际显隐变了 —— 交给调用方去同步菜单勾选（见 `_on_dock_visibility`）
        self.on_visibility_changed: Optional[Callable[[str, bool], None]] = None

    # ════════════════════════════════════════════════════════
    # 加
    # ════════════════════════════════════════════════════════

    def add_module(self, widget, title: str, module_id: str,
                   area: str = "center"):
        """把一个模块控件放进工作区。按 `area` 路由：center→视图窗口，其余→dock。"""
        widget.setProperty("module_id", module_id)
        self._areas[module_id] = area
        self._base_titles.setdefault(module_id, title)
        if area == "center":
            return self._add_subwindow(widget, title, module_id)
        return self._add_dock(widget, title, module_id, area)

    def add_pinned(self, widget, title: str, pin_id: str, area: str = "left"):
        """平台自带的 dock（导航树 / 控制台）—— 与模块的唯一区别是关不掉。"""
        dock = self.add_module(widget, title, pin_id, area)
        self._pinned.add(pin_id)
        return dock

    def _add_subwindow(self, widget, title: str, module_id: str) -> ModuleSubWindow:
        sub = ModuleSubWindow(module_id, title, widget,
                              guard=self._close_guard,
                              on_closed=self._on_subwindow_closed)
        self._subwindows.setdefault(module_id, []).append(sub)
        self.mdi.attach(sub)
        # 贴布局时这个模块还没打开（懒加载）→ 它的几何存在 `_pending_geometry` 里，
        # 在这儿补上。放在 `attach()`（内部 show 过）**之后**：首次 show 会让 Qt
        # 重排一次子窗口，先设的会被冲掉。
        saved = self._pending_geometry.pop(module_id, None)
        if saved is not None:
            sub.setGeometry(*saved)
        # 开之前设过的后缀补上（载入输入发生在窗口被打开之前）
        pending = self._pending_suffix.pop(module_id, None)
        if pending:
            sub.set_title(f"{title}{pending}")
        return sub

    def _add_dock(self, widget, title: str, module_id: str, area: str) -> ModuleDock:
        # **先找同区已有的 dock，再登记自己** —— 反过来会找着自己
        existing = first_dock_in(self._docks, self._areas, area, exclude=module_id)
        dock = ModuleDock(module_id, title, widget, self.window)
        self._docks[module_id] = dock

        self.window.addDockWidget(dock_area_of(area), dock)
        if existing is not None:
            # **同区叠成一组页签**，而不是并排/上下分割。
            # 不 tabify 的话 Qt 会把同区 dock 拆开排列（左边两块各占一半、
            # 谁也看不清）；tabify 之后 Qt 在底部给一条**可点的标签条** ——
            # 那才是"有按钮可以切换"。用户仍可把某一个拖出来浮动。
            self.window.tabifyDockWidget(existing, dock)
            # 保留**先来的那个**在最前：左边默认该看见导航树、底部默认该看见控制台，
            # 而不是刚加进来的模块把常驻面板盖住。
            existing.raise_()
        # **Qt 也有一条关掉 dock 的路**：右键 dock（或工具栏）时 `QMainWindow`
        # 给的 `createPopupMenu()` 里每个 dock 一条勾选项，点它就是直接 `hide()`，
        # **不经过 `set_module_visible`**。不跟上这一下的话：面板没了、而平台
        # 那份记账还写着"开着"——「窗口」菜单的勾照旧亮着，再点它要两下才回来，
        # 用户看到的就是"右键 Close 关不掉"（真踩过）。所以**以 dock 的实际显隐
        # 为准**，反向把记账掰正。
        dock.visibilityChanged.connect(
            lambda visible, mid=module_id: self._on_dock_visibility(mid, bool(visible)))
        dock.show()
        self._install_dock_tab_close()
        return dock

    def _install_dock_tab_close(self) -> None:
        """给**停靠区那条标签栏**也装上 ×。

        Qt 默认不给停靠区的页签关闭按钮 —— 关一个面板只能右键出菜单，很绕；
        用户会以为"关不掉"（真被问过）。中央工作区那条是 `QMdiArea` 自己管的
        （`setTabsClosable(True)` 就够），而停靠区那条是 `QMainWindow` 的
        **内部件**：`objectName` 是空、parent 就是窗口本身 —— 所以按"父是窗口的
        `QTabBar`"来找，不按名字找（PySide6 下那个内部名取不到）。
        """
        for bar in self.window.findChildren(QTabBar):
            if bar.parent() is not self.window or bar.tabsClosable():
                continue
            bar.setTabsClosable(True)
            bar.tabCloseRequested.connect(
                lambda index, b=bar: self._close_dock_tab(b, index))

    def _close_dock_tab(self, bar: QTabBar, index: int) -> None:
        """点了停靠区页签上的 × —— 把那个面板关掉。

        按**标题**找是哪个模块：标题由平台自己维护（清单里的 title + 模块挂的
        后缀），清单里不会重名，所以这个映射是可靠的；反过来按"标签栏顺序"
        去数则依赖 Qt 的内部排布，不稳。
        """
        title = bar.tabText(index)
        for module_id, dock in self._docks.items():
            if dock.windowTitle() != title:
                continue
            if module_id in self._pinned:
                return          # 导航树 / 控制台关不掉（与「视图」菜单同一口径）
            self._set_visible(module_id, False)
            return

    def _on_dock_visibility(self, module_id: str, visible: bool) -> None:
        """dock 真的显/隐了 —— **只用来同步菜单勾选**。

        账不在这里记：`contains()` 是现场问 dock（`isHidden()`）的，没有第二份
        状态可以对不上。这里只负责让「窗口」菜单那条勾跟着变。
        """
        if self.on_visibility_changed is not None:
            self.on_visibility_changed(module_id, visible)

    # ════════════════════════════════════════════════════════
    # 查询
    # ════════════════════════════════════════════════════════

    def pane_of(self, module_id: str) -> Optional[str]:
        """模块归哪个区域管 —— **隐藏的也算**（它随时可以被再打开）。"""
        return self._areas.get(module_id)

    def contains(self, module_id: str) -> bool:
        """这个模块现在是不是打开的。

        两种载体的判据**不一样**，各用各的：

        · **dock 问它自己**（`isHidden()`）。它只反映"是否被显式隐藏"，不受
          父窗口有没有 show 影响 —— 那正是 `isVisible()` 的坑。更重要的是
          **Qt 自己那条关掉 dock 的路**（右键 dock / 工具栏时
          `QMainWindow.createPopupMenu()` 里的勾选项，直接 `hide()`、不经我们），
          问 Qt 才追得上；自己记一份就永远可能对不上。
        · **子窗口用自己记的 `_hidden`**：关它是 `removeSubWindow`（不是 hide），
          Qt 那边没有现成的判据可用。
        """
        dock = self._docks.get(module_id)
        if dock is not None:
            return not dock.isHidden()
        if module_id in self._subwindows:
            return module_id not in self._hidden
        return False

    def _known(self) -> set:
        return set(self._subwindows) | set(self._docks)

    def module_ids(self) -> List[str]:
        """工作区里**当前打开**的模块 id（去重，按加入顺序）。"""
        return [mid for mid in self._known() if self.contains(mid)]

    def subwindow_count(self, module_id: str = "") -> int:
        """某个模块开了几个视图窗口；不给 module_id 就是全部。"""
        if module_id:
            return len(self._subwindows.get(module_id) or [])
        return sum(len(subs) for subs in self._subwindows.values())

    def active_module_id(self) -> str:
        return self.mdi.active_module_id()

    def index_of(self, module_id: str) -> int:
        """兼容旧 `PaneHost.index_of` —— 视图窗口按加入顺序排。"""
        for index, (mid, _subs) in enumerate(self._subwindows.items()):
            if mid == module_id:
                return index
        return -1

    def ordered_module_ids(self) -> List[str]:
        """视图窗口按**创建顺序**的模块 id（不是层叠顺序，见 `WorkspaceArea`）。"""
        return [str(sub.property("module_id") or "")
                for sub in self.mdi.subwindows_in_order()]

    def modules_in(self, area: str) -> List[str]:
        """某个区域里注册过的模块 id（不看显隐）。"""
        return [mid for mid, a in self._areas.items() if a == area]

    def subwindows_of(self, module_id: str) -> List[QMdiSubWindow]:
        """某模块的全部视图窗口（多开时不止一个）。"""
        return list(self._subwindows.get(module_id) or [])

    def dock_of(self, module_id: str) -> Optional[QDockWidget]:
        return self._docks.get(module_id)

    # ════════════════════════════════════════════════════════
    # 聚焦 / 显隐
    # ════════════════════════════════════════════════════════

    def focus(self, module_id: str) -> bool:
        """切到某个模块：dock 抬起来；视图窗口还原 + 激活。

        多开时**抬最新的那个实例** —— 后开的通常是用户正要用的。
        """
        subs = self._subwindows.get(module_id)
        if subs:
            sub = subs[-1]
            if not self.contains(module_id):
                self._set_visible(module_id, True)
            if sub.isMinimized():
                sub.showNormal()
            self.mdi.setActiveSubWindow(sub)
            return True
        dock = self._docks.get(module_id)
        if dock is not None:
            # 走 `_set_visible` 而不是直接 `dock.setVisible(True)` —— 显隐是**自己记**
            # 的（`_hidden`），漏掉那一句就会"看着抬起来了，但平台仍认为它是关的"。
            if not self.contains(module_id):
                self._set_visible(module_id, True)
            dock.raise_()
            return True
        return False

    def activate(self, module_id: str) -> bool:
        """兼容旧 `PaneHost.activate` 的名字 —— 就是 focus。"""
        return self.focus(module_id)

    def current_module_id(self) -> str:
        return self.active_module_id()

    def set_module_visible(self, module_id: str, visible: bool) -> bool:
        if module_id in self._pinned:
            return False            # 导航树 / 控制台关不掉
        return self._set_visible(module_id, visible)

    def set_pinned_visible(self, pin_id: str, visible: bool) -> bool:
        return self._set_visible(pin_id, visible)

    def _set_visible(self, module_id: str, visible: bool) -> bool:
        if module_id not in self._known():
            return False
        if self.contains(module_id) == visible:      # 判据与 contains 同一处
            return False
        for sub in self._subwindows.get(module_id) or []:   # 多开的实例一起显隐
            if visible:
                self.mdi.reattach(sub)
            else:
                self.mdi.detach(sub)
        dock = self._docks.get(module_id)
        if dock is not None:
            dock.setVisible(visible)
            if visible:
                # 同区的 dock 是叠着的 —— 从菜单打开它必须**抬到前面**，
                # 否则"打开了但看不见"，用户以为开关坏了。
                dock.raise_()
        # `_hidden` **只给子窗口记账**：dock 的显隐由 `contains()` 现场问它自己
        if module_id in self._subwindows:
            self._hidden.discard(module_id) if visible else self._hidden.add(module_id)
        self.mdi.sync_chrome()
        return True

    def set_suffix(self, module_id: str, suffix: str) -> None:
        """给模块的标题挂后缀（「● 未保存」）。

        每次都从**原名**重新拼 —— 直接往当前标题后面接会让后缀越叠越长
        （切一次主题、改一次内容就叠一层）。
        """
        if module_id not in self._known():
            # **还没开** —— 先记着，等它被打开时补上（见 `_add_subwindow`）。
            # 这一步必须在查 `_base_titles` **之前**：原名表是"打开时"才填的，
            # 而模块往往在载入输入时就同步了一次后缀（那时还没被点开）。
            self._pending_suffix[module_id] = suffix
            return
        base = self._base_titles.get(module_id)
        if base is None:
            return
        title = f"{base}{suffix}"
        for sub in self._subwindows.get(module_id) or []:
            sub.set_title(title)
        dock = self._docks.get(module_id)
        if dock is not None:
            dock.set_title(title)

    # ════════════════════════════════════════════════════════
    # 排版（转发给中央工作区）
    # ════════════════════════════════════════════════════════

    def tile(self) -> None:
        self.mdi.tile()

    def cascade(self) -> None:
        self.mdi.cascade()

    def activate_next(self) -> None:
        self.mdi.activate_next()

    def set_view_mode(self, tiled: bool) -> None:
        self.mdi.set_view_mode(tiled)

    def is_tiled_view(self) -> bool:
        return self.mdi.is_tiled_view()

    # ════════════════════════════════════════════════════════
    # 布局持久化
    # ════════════════════════════════════════════════════════

    def dock_all_floating(self) -> None:
        """把**浮出来的面板收回停靠位** —— 关窗口前调一次。

        浮动的 dock 是**独立顶层窗口**：主窗口关掉它并不会跟着关（实测：
        `win.close()` 之后它还在桌面上，进程也退不干净）。收回停靠位之后它才
        随主窗口一起消失，而且存下来的布局是"停靠着"的、不是"浮着"的。
        """
        for dock in self._docks.values():
            if dock.isFloating():
                dock.setFloating(False)

    def save_layout(self) -> Tuple[QByteArray, str]:
        """(dock 布局, 视图窗口布局)。

        dock 那半走 Qt 原生的 `QMainWindow.saveState()`（QByteArray）。
        视图窗口那半**必须自己存** —— `QMdiArea` 没有 `saveState()`
        （它和 `QMainWindow` 不是一回事，别混）。存的是每个模块第一个窗口的
        几何 + 是否打开，够用且可读。
        """
        subwindows = []
        for module_id, subs in self._subwindows.items():
            geo = subs[0].geometry()
            subwindows.append({"module": module_id, "x": geo.x(), "y": geo.y(),
                               "w": geo.width(), "h": geo.height(),
                               "open": module_id not in self._hidden})
        return self.window.saveState(), json.dumps(
            {"view": "tabs" if self.mdi.is_tiled_view() else "windows",
             "subwindows": subwindows}, ensure_ascii=False)

    def restore_layout(self, docks=None, subwindows: str = "") -> None:
        """贴回上次的 dock 与视图布局。坏的就整段忽略 —— 存坏不该让界面起不来。

        **只恢复布局，不恢复"打开了哪些"** —— 视图一律等左树点开。一个都没点
        就自己冒出一堆标签，反而不知道哪些是要看的。
        """
        if isinstance(docks, (bytes, bytearray, QByteArray)) and docks:
            try:
                self.window.restoreState(docks)
            except Exception:                       # noqa: BLE001
                pass
        if not isinstance(subwindows, str) or not subwindows:
            return
        try:
            saved = json.loads(subwindows)
        except (ValueError, TypeError):
            return
        # 新格式是 {"view": ..., "subwindows": [...]}；更早存过一份纯列表，
        # 读回来也要认（否则用户升一次级布局就丢）
        if isinstance(saved, dict):
            self.mdi.set_view_mode(saved.get("view") != "windows")
            saved = saved.get("subwindows")
        if not isinstance(saved, list):
            return
        for item in saved:
            if not isinstance(item, dict):
                continue
            module_id = str(item.get("module", ""))
            try:
                box = (int(item["x"]), int(item["y"]),
                       int(item["w"]), int(item["h"]))
            except (KeyError, TypeError, ValueError):
                continue
            subs = self._subwindows.get(module_id)
            if not subs:
                # **还没打开** —— 几何存着，等它被点开时再套（懒加载的必然结果）
                self._pending_geometry[module_id] = box
                continue
            subs[0].setGeometry(*box)
            if item.get("open") is False:
                self._set_visible(module_id, False)
        self._install_dock_tab_close()      # 贴完布局 Qt 可能重建过标签栏

    # ════════════════════════════════════════════════════════
    # 内部
    # ════════════════════════════════════════════════════════

    def _on_subwindow_closed(self, module_id: str) -> None:
        """用户点了视图窗口的关闭按钮 —— 摘掉标签（控件留着，随时能再开）。"""
        self._set_visible(module_id, False)

    def _subwindow_activated(self, sub: Optional[QMdiSubWindow]) -> None:
        """视图窗口聚焦变化 → 通知外部（app 据此跑 `on_activated` 与导航树加粗）。

        dock 不参与：dock 的抬升不改变「我正在看哪个模块」这件事 ——
        点一下运行历史不该把编辑器的焦点语义抢走。
        """
        if sub is None or self.on_activated is None:
            return
        module_id = str(sub.property("module_id") or "")
        if module_id:
            self.on_activated(module_id)
