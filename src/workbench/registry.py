"""模块管理器 —— 把清单里的每一条 `ModuleSpec` 变成真正的窗格页签与菜单项。

这是整个平台唯一「认识清单、也认识 Qt」的地方，两边都不认识对方：`spec`
不知道 Qt，模块不知道清单长什么样。

`ModuleSpec.area` 的四个值是契约（`center/left/right/bottom`），但**渲染方式
变了**：以前 left/right/bottom 各是一个 QDockWidget、还要 tabify 把同区的合
起来；现在 center 是 MDI 子窗口、其余三个区是 QDockWidget（`ui/workspace.py`），
页签 —— `tabify_same_area` 那一步不需要了。

**一个模块坏了不能拖垮整个界面。** 构造模块时抛异常（依赖缺失、类名写错、
第三方库炸了）只影响它自己：控制台记一笔、插一个写着 traceback 的红色页签、
继续建下一个。这条规则是从旧界面沿用的（「构不出模型时保留上一次的结果，
而不是把页面清空」）—— 工程工具最忌讳的就是「一个小错导致一片空白」，
用户根本分不清是自己写错了还是工具坏了。
"""
from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QPlainTextEdit

from .context import AppContext
from .loader import FactoryError, resolve
from .manifest import WorkbenchManifest
from .modules.base import IModule
from .spec import ModuleSpec
from .ui import theme
from .ui.containers.workspace import PANE_AREAS


class ModuleManager:
    """清单 → 界面。窗口只跟它打交道，不逐个认模块。"""

    def __init__(self, window: QMainWindow, ctx: AppContext) -> None:
        self.window = window
        self.ctx = ctx
        self.manifest: Optional[WorkbenchManifest] = None
        #: module_id → 实例列表。center 模块可多开（列表会长），dock 恒 1 个。
        self._instances: Dict[str, List[IModule]] = {}
        #: module_id → 清单里的模板（开新实例时照它建）
        self._specs: Dict[str, ModuleSpec] = {}
        #: module_id → 它在「窗口」菜单里的那条勾选项（可勾的才进）
        self._menu_actions: Dict[str, QAction] = {}
        #: center 模块**建好但还没进工作区**的控件（`(widget, title)`）。
        #: 左树点一下才从这儿取出来加载进 MDI —— 工作区因此默认是空的。
        self._unopened: Dict[str, tuple] = {}
        self._failures: Dict[str, str] = {}

    # ════════════════════════════════════════════════════════
    # 构建
    # ════════════════════════════════════════════════════════

    def build(self, manifest: WorkbenchManifest) -> None:
        """建界面。

        **center 模块的控件不进工作区** —— 工作区默认是**空的**，左树点一下才
        把它的视图加载进 MDI（见 `open`）。

        但模块**实例照旧在这一步建**：它们的「工具 / 调试」菜单动作、以及清单
        声明的输入载入都挂在这一步。只把控件挪到 `_unopened` 里存着，等 `open`
        再交给工作区 —— 否则打开界面时那几个菜单会是空的，看着像坏了。
        侧栏模块（`left`/`right`/`bottom`）是常驻面板，照旧立刻进工作区。
        """
        self.manifest = manifest
        self._specs = {spec.id: spec for spec in manifest.enabled_modules()}

        for area in PANE_AREAS:
            for spec in manifest.modules_in(area):
                self._build_one(spec)
        for spec in manifest.enabled_modules():
            self._load_declared_input(spec)

        self._build_menus(manifest)
        # dock 的实际显隐 → 菜单勾选跟着变（Qt 自己的右键菜单也能关 dock，
        # 不跟上的话菜单上的勾就是假的）
        self.window.workspace.on_visibility_changed = self._sync_menu_check   # type: ignore[attr-defined]
        self.ctx.modules = {mid: insts[-1]                          # 让模块之间能互相找到
                            for mid, insts in self._instances.items() if insts}

    def _load_declared_input(self, spec: ModuleSpec) -> None:
        """清单里写了 `input` 就替模块把那份业务输入载进去。

        **文件不存在只记一笔，不算失败**：清单是跟着仓库走的，而业务输入
        （某次仿真的 output 目录、某份模型）经常在别的机器上 —— 因为找不到
        输入就不让模块起来，会把「少了一份数据」升级成「界面打不开」。

        在**所有模块建完之后**统一做，而不是边建边载：模块之间可能有依赖
        （一个模块的输入要靠另一个先就位），而且失败了也不该打断建界面。
        """
        if not spec.input:
            return
        module = self.module(spec.id)
        if module is None:                              # 这个模块刚才没起来
            return
        path = self.ctx.data_path(spec)
        if path is None or not path.exists():
            self.ctx.log(f"[{spec.id}] 清单里写的输入不存在，跳过：{path}", "warning")
            return
        module.on_input_changed(path)

    def _build_one(self, spec: ModuleSpec) -> bool:
        try:
            module = self._instantiate(spec)
            widget = module.create_widget()
        except Exception as exc:                        # noqa: BLE001  隔离单个模块
            self._report_failure(spec, exc)
            widget = _failure_widget(spec, exc)
            module = None

        self._specs[spec.id] = spec
        if module is not None:
            self._instances.setdefault(spec.id, []).append(module)
            self._wire_subscriptions(spec, module)

        if spec.area == "center":
            # **先不塞进工作区** —— 存着，等用户点它（见 `open`）。
            #
            # 但必须**挂回窗口做隐藏子件**，不能让它没有 parent：没有 parent 的
            # QWidget 就是一个**顶层窗口** —— 全局换主题（`theme.apply` 刷样式表）
            # 要遍历每个顶层控件，于是这些"还没开就存着"的控件把换主题拖成分钟级、
            # 内存一路涨（实测 1.63GB 卡死）。挂上去之后它随窗口销毁，也不在顶层之列。
            widget.setProperty("module_id", spec.id)
            widget.setParent(self.window)
            widget.hide()
            self._unopened[spec.id] = (widget, spec.title)
        else:
            self.window.workspace.add_module(             # type: ignore[attr-defined]
                widget, spec.title, spec.id, spec.area)
        return module is not None

    def _show_center(self, module_id: str) -> bool:
        """把 `_build_one` 存着的那个控件**加载进工作区**。"""
        held = self._unopened.pop(module_id, None)
        if held is None:
            return False
        widget, title = held
        self.window.workspace.add_module(                 # type: ignore[attr-defined]
            widget, title, module_id, "center")
        return True

    def _instantiate(self, spec: ModuleSpec) -> IModule:
        cls = resolve(spec.factory)
        if not callable(cls):
            raise FactoryError(f"{spec.factory} 不是一个可调用的类")
        return cls(self.ctx, spec)

    def open(self, module_id: str) -> bool:
        """**左树 / 窗口菜单点一下的落点**：没开就建，开了就抬起来。

        这是 center 模块的唯一入口 —— 它们不在 `build()` 里建（工作区默认是空的），
        第一次 `open` 才实例化控件、挂进 MDI，之后每次 `open` 只是聚焦。
        """
        if module_id not in self._specs:
            return False
        self._show_center(module_id)            # 还没进工作区就加载进去
        return self.window.workspace.focus(module_id)   # type: ignore[attr-defined]

    def is_open(self, module_id: str) -> bool:
        """这个模块的视图**加载进工作区了没有**。"""
        if module_id in self._unopened:
            return False
        return self.window.workspace.contains(module_id)  # type: ignore[attr-defined]

    def open_new(self, module_id: str) -> bool:
        """**再开一个同模块的窗口**（MDI 的价值所在）。

        只对 center 模块有意义 —— dock 模块（运行历史 / 证据 / 错误指纹）各自
        只有一块 dock 位，"开两个"没有承载它的地方，所以直接拒绝。

        新实例是**独立的模块对象**：自己的控件、自己的订阅。两个编辑器窗口各编
        各的，互不干扰（这正是"多开"与"多标签"的区别）。
        """
        spec = self._specs.get(module_id)
        if spec is None or module_id in self._failures:
            return False
        if spec.area != "center":
            return False
        try:
            module = self._instantiate(spec)
            widget = module.create_widget()
        except Exception as exc:                        # noqa: BLE001
            self._report_failure(spec, exc)
            return False
        self._instances.setdefault(module_id, []).append(module)
        self._wire_subscriptions(spec, module)
        self.window.workspace.add_module(                 # type: ignore[attr-defined]
            widget, spec.title, module_id, spec.area)
        # 新窗口也要载上清单声明的输入 —— 否则开出来的编辑器是空的
        if spec.input:
            path = self.ctx.existing_data_path(spec)
            if path is not None:
                module.on_input_changed(path)
        return True

    def open_new_for_active(self) -> bool:
        """给「窗口 → 在新窗口打开」用：对当前聚焦的 center 模块开一个。"""
        return self.open_new(self.window.workspace.active_module_id())  # type: ignore[attr-defined]

    def _wire_subscriptions(self, spec: ModuleSpec, module: IModule) -> None:
        """按 `params.subscribe` 把总线话题接到模块的 `on_refresh`。

        订阅写在**清单**里而不是模块代码里，是为了让「谁在听谁」一目了然：
        读一遍 yaml 就知道模块之间的数据流向，不用追 import。
        """
        topics = spec.params.get("subscribe") or []
        if isinstance(topics, str):
            topics = [topics]
        for topic in topics:
            self.ctx.bus.subscribe(str(topic), module.on_refresh)

    def _report_failure(self, spec: ModuleSpec, exc: Exception) -> None:
        detail = traceback.format_exc()
        self._failures[spec.id] = f"{type(exc).__name__}: {exc}"
        self.ctx.log(f"[{spec.id}] 模块加载失败：{exc}\n{detail}", "error")
        self.ctx.status(f"模块 {spec.title} 加载失败 —— 见控制台")

    # ════════════════════════════════════════════════════════
    # 菜单
    # ════════════════════════════════════════════════════════

    def _build_menus(self, manifest: WorkbenchManifest) -> None:
        """把模块清单与模块动作填进已经建好的七个菜单里。

        · **窗口**菜单下按业务线**平铺**列出全部模块（业务线用小标题行分隔）。
          这是业务线在菜单栏里的落点 —— 它不再占顶层菜单，否则加一条线菜单栏
          就长一节。
        · 模块自己的动作按业务线进 **调试**（debug）或 **工具**
        · 模块条目对 center 是「打开「x」」；对其余区域是**可勾选**的显隐开关
          （关掉一个页签之后总得有地方能再打开）

        `group.menu: false` 的业务线不进窗口菜单 —— 那是清单说了算的。
        """
        for group in manifest.sorted_groups():
            if not group.menu:
                continue
            entries = manifest.modules_of(group.id)
            window_menu = self.window.add_window_section(       # type: ignore[attr-defined]
                group.id, group.title)
            if not entries:
                window_menu.addAction("（本业务线还没有模块）").setEnabled(False)
                continue

            action_menu = self.window.action_menu_for(group.id)   # type: ignore[attr-defined]
            for spec in entries:
                action = self._menu_action(spec)
                window_menu.addAction(action)
                if action.isCheckable():        # 侧栏的显隐开关 —— 要跟着 dock 实际状态走
                    self._menu_actions[spec.id] = action
                module = self.module(spec.id)
                if module is None:
                    continue
                extra = module.create_actions()
                if extra:
                    # 分隔线加在**块之间**，不是每块后面 —— 后者会在菜单末尾
                    # 留一条悬空的分隔线
                    if action_menu.actions():
                        action_menu.addSeparator()
                    # 模块标题当一条禁用的分隔行 —— 否则工具菜单里一串动作
                    # 分不清是谁的
                    header = action_menu.addAction(spec.title)
                    header.setEnabled(False)
                    for action in extra:
                        action_menu.addAction(action)
                    # 工具栏**按模块登记**，不立刻挂 —— 激活哪个模块才挂哪个。
                    # 全挂上去的话：同名分组重复出现，而且总长超出窗口被截断。
                    self.window.add_toolbar_actions(                   # type: ignore[attr-defined]
                        extra, spec.id)

    def _sync_menu_check(self, module_id: str, visible: bool) -> None:
        """把「窗口」菜单里那条勾选项掰成 dock 的实际状态。

        `blockSignals` 是必须的：`setChecked` 会触发 `toggled` → `set_visible`
        → 又去动 dock —— 一圈下来就成了"自己关自己"。
        """
        action = self._menu_actions.get(module_id)
        if action is None or not action.isCheckable():
            return
        action.blockSignals(True)
        action.setChecked(visible)
        action.blockSignals(False)

    def _menu_action(self, spec: ModuleSpec) -> QAction:
        if spec.area == "center":
            action = QAction(f"打开「{spec.title}」", self.window)
            action.triggered.connect(lambda _c=False, mid=spec.id: self.open(mid))
        else:
            action = QAction(spec.title, self.window, checkable=True)
            action.setChecked(self._is_visible(spec.id))
            action.toggled.connect(
                lambda visible, mid=spec.id: self.set_visible(mid, visible))

        if spec.id in self._failures:
            action.setEnabled(False)
            action.setText(f"{spec.title}（加载失败）")
        return action

    # ════════════════════════════════════════════════════════
    # 查询与操作
    # ════════════════════════════════════════════════════════

    def modules(self, group: Optional[str] = None) -> List[IModule]:
        """全部活着的实例（多开时一个模块会出现多次）。"""
        found = [m for insts in self._instances.values() for m in insts]
        return [m for m in found if group is None or m.group == group]

    def module(self, module_id: str) -> Optional[IModule]:
        """某模块的实例 —— 多开时给**最新的那个**（界面各处按 id 找模块都走这里）。"""
        insts = self._instances.get(module_id) or []
        return insts[-1] if insts else None

    def pane_of(self, module_id: str) -> Optional[str]:
        """模块现在归哪个区管（`center`/`left`/`right`/`bottom`）。"""
        return self.window.workspace.pane_of(module_id)  # type: ignore[attr-defined]

    def _is_visible(self, module_id: str) -> bool:
        return self.window.workspace.contains(module_id)  # type: ignore[attr-defined]

    def set_visible(self, module_id: str, visible: bool) -> bool:
        """显示/隐藏一个模块（dock 勾选项走这里）。"""
        return self.window.workspace.set_module_visible(  # type: ignore[attr-defined]
            module_id, visible)

    def failures(self) -> Dict[str, str]:
        """id → 失败原因。界面据此提示「有几个模块没起来」。"""
        return dict(self._failures)

    def focus(self, module_id: str) -> bool:
        """切到某个模块 —— 还没加载进工作区就先加载（见 `open`）。

        **切完顺手换工具栏**：工具栏上的模块动作是"跟着当前模块走"的，而
        `workspace.focus` 在**目标已经是当前子窗口**时不会发激活信号 —— 光靠
        `_on_subwindow_activated` 会漏掉这一类（测试就是这么撞上的：show() 之后
        第一个模块已经当前了，focus 它没有信号）。
        """
        if module_id in self._unopened:
            found = self.open(module_id)
        else:
            found = self.window.workspace.focus(module_id)  # type: ignore[attr-defined]
        if found:
            self.window.set_toolbar_actions(module_id)      # type: ignore[attr-defined]
        return found

    def close_all(self) -> bool:
        """关窗口前逐个问一遍 —— 任何一个说「不能关」就整体停下。

        遍历**所有实例**：多开的两个编辑器各自可能有未保存改动。
        """
        return all(m.can_close() for m in self.modules())

    def can_close(self, module_id: str) -> bool:
        """单个模块能不能关（子窗口的关闭守卫用）。"""
        module = self.module(module_id)
        return module.can_close() if module is not None else True

    def mark_all_clean(self) -> None:
        """把所有模块标成干净的。测试夹具与「放弃改动」之后用。"""
        for module in self.modules():
            module.mark_clean()

    def notify_activated(self, module_id: str) -> None:
        module = self.module(module_id)
        if module is not None:
            module.on_activated()


def _failure_widget(spec: ModuleSpec, exc: Exception) -> QPlainTextEdit:
    """坏掉的模块在界面上的样子 —— traceback 直接给出来，别让人去翻控制台。"""
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setFont(theme.mono_font())
    view.setPlainText(
        f"模块 {spec.id}（{spec.title}）加载失败。\n\n"
        f"清单里写的是：\n  factory: {spec.factory}\n\n"
        f"{type(exc).__name__}: {exc}\n\n"
        f"{traceback.format_exc()}\n"
        "—— 其余模块不受影响，可以照常用。")
    return view


def describe_module(module: Any) -> str:
    """一行摘要 —— 日志与测试用。"""
    return f"{module.module_id}（{module.title}）"
