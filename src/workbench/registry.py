"""模块管理器 —— 把清单里的每一条 `ModuleSpec` 变成真正的窗格页签与菜单项。

这是整个平台唯一「认识清单、也认识 Qt」的地方，两边都不认识对方：`spec`
不知道 Qt，模块不知道清单长什么样。

`ModuleSpec.area` 的四个值是契约（`center/left/right/bottom`），但**渲染方式
变了**：以前 left/right/bottom 各是一个 QDockWidget、还要 tabify 把同区的合
起来；现在一个区域就是一块窗格（`ui/panes.py`），同区模块天然是同一块窗格里的
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
from .ui.panes import PANE_AREAS, PaneHost


class ModuleManager:
    """清单 → 界面。窗口只跟它打交道，不逐个认模块。"""

    def __init__(self, window: QMainWindow, ctx: AppContext) -> None:
        self.window = window
        self.ctx = ctx
        self.manifest: Optional[WorkbenchManifest] = None
        self._modules: Dict[str, IModule] = {}
        self._failures: Dict[str, str] = {}

    # ════════════════════════════════════════════════════════
    # 构建
    # ════════════════════════════════════════════════════════

    def build(self, manifest: WorkbenchManifest) -> None:
        self.manifest = manifest

        for area in PANE_AREAS:
            for spec in manifest.modules_in(area):
                self._build_one(spec)

        for spec in manifest.enabled_modules():
            self._load_declared_input(spec)

        # 空窗格收起来 —— 清单里没有 left 模块时，左边不该留一条空白带
        # （反向的兜底在 `_restore_layout`：贴回上次尺寸之后要再查一次
        #   「有内容的窗格不能是 0 宽」，那才是 0 宽真正产生的时刻）
        self.window.panes.collapse_empty()          # type: ignore[attr-defined]

        self._build_menus(manifest)
        self.ctx.modules = dict(self._modules)          # 让模块之间能互相找到

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
        module = self._modules.get(spec.id)
        if module is None:                              # 这个模块刚才没起来
            return
        path = self.ctx.data_path(spec)
        if path is None or not path.exists():
            self.ctx.log(f"[{spec.id}] 清单里写的输入不存在，跳过：{path}", "warning")
            return
        module.on_input_changed(path)

    def _build_one(self, spec: ModuleSpec) -> None:
        try:
            module = self._instantiate(spec)
            widget = module.create_widget()
        except Exception as exc:                        # noqa: BLE001  隔离单个模块
            self._report_failure(spec, exc)
            widget = _failure_widget(spec, exc)
            module = None

        if module is not None:
            self._modules[spec.id] = module
            self._wire_subscriptions(spec, module)

        pane = self.window.panes.pane(spec.area)         # type: ignore[attr-defined]
        pane.add_module(widget, spec.title, spec.id)

    def _instantiate(self, spec: ModuleSpec) -> IModule:
        cls = resolve(spec.factory)
        if not callable(cls):
            raise FactoryError(f"{spec.factory} 不是一个可调用的类")
        return cls(self.ctx, spec)

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
                window_menu.addAction(self._menu_action(spec))
                module = self._modules.get(spec.id)
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
                    self.window.add_toolbar_actions(extra)   # type: ignore[attr-defined]

    def _menu_action(self, spec: ModuleSpec) -> QAction:
        if spec.area == "center":
            action = QAction(f"打开「{spec.title}」", self.window)
            action.triggered.connect(lambda _c=False, mid=spec.id: self.focus(mid))
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
        found = list(self._modules.values())
        return [m for m in found if group is None or m.group == group]

    def module(self, module_id: str) -> Optional[IModule]:
        return self._modules.get(module_id)

    def pane_of(self, module_id: str) -> Optional[PaneHost]:
        """模块现在在哪块窗格里。"""
        return self.window.panes.pane_of(module_id)      # type: ignore[attr-defined]

    def _is_visible(self, module_id: str) -> bool:
        pane = self.pane_of(module_id)
        return bool(pane and pane.contains(module_id))

    def set_visible(self, module_id: str, visible: bool) -> bool:
        """显示/隐藏一个模块页签。菜单里的勾选项走这里。"""
        return self.window.panes.set_module_visible(    # type: ignore[attr-defined]
            module_id, visible)

    def failures(self) -> Dict[str, str]:
        """id → 失败原因。界面据此提示「有几个模块没起来」。"""
        return dict(self._failures)

    def focus(self, module_id: str) -> bool:
        """切到某个模块 —— 不管它在哪块窗格。"""
        return self.window.panes.focus(module_id)        # type: ignore[attr-defined]

    def close_all(self) -> bool:
        """关窗口前逐个问一遍 —— 任何一个说「不能关」就整体停下。"""
        return all(module.can_close() for module in self._modules.values())

    def mark_all_clean(self) -> None:
        """把所有模块标成干净的。测试夹具与「放弃改动」之后用。"""
        for module in self._modules.values():
            module.mark_clean()

    def notify_activated(self, module_id: str) -> None:
        module = self._modules.get(module_id)
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
