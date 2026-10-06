"""工作区 —— 中央 MDI + 侧栏 Dock，按**界面元素**拆成的几个件。

    元素              是什么                        文件
    ────────────────────────────────────────────────────────────
    WorkspaceArea     中央工作区（视图以子窗口承载）  area.py
    ModuleSubWindow   一个视图窗口（就是工作区里的"一页"） subwindow.py
    ModuleDock        一个侧栏面板（可浮动/停靠/叠页签） dock.py
    EmptyState        空工作区那句引导               empty_state.py
    Workspace         把它们组装起来、对外一个门面   workspace.py

**为什么拆**：原来一个 `Workspace` 类（536 行）同时管七件事 —— 造控件、查状态、
聚焦、显隐、排版、布局落盘、空态。改任何一件都要在同一个文件里翻。拆开之后每件
元素管自己那一摊，`Workspace` 退回成"路由 + 记账"，别处只跟它打交道。

**对外的名字不变**：`from ..ui.containers.workspace import Workspace, PANE_AREAS, DOCK_AREAS`
继续可用 —— 改的是内部结构，不是接口。这也是判断"拆对了"的标准：测试原样全绿。
"""
from .area import WorkspaceArea
from .dock import ModuleDock
from .empty_state import EmptyState
from .subwindow import ModuleSubWindow
from .workspace import DOCK_AREAS, PANE_AREAS, Workspace

__all__ = ["Workspace", "WorkspaceArea", "ModuleSubWindow", "ModuleDock",
           "EmptyState", "PANE_AREAS", "DOCK_AREAS"]
