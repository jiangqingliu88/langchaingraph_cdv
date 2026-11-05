"""测试用的假模块 —— 清单测试不该依赖真模块的存在。

真模块会 import `src/tools/**`（拖 langchain、拖文件系统），那会让「清单
能不能正确落成界面」这件事被无关的依赖影响。这里的假模块只做最少的事：
返回一个控件、可能带一个动作、可能故意炸掉。
"""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QWidget

from ..modules.base import ModuleBase


class StubModule(ModuleBase):
    """什么都不做的模块：内容是一个写着自己 id 的标签。"""

    def build_content(self) -> QWidget:
        self.label = QLabel(f"stub:{self.module_id}")
        return self.label


class StubModuleWithAction(StubModule):
    """带一个自有动作 —— 用来验证动作会被挂进业务线菜单与工具栏。"""

    def create_actions(self):
        action = QAction("假动作", self.content)
        self.action = action
        return [action]


class StubDirtyModule(StubModule):
    """永远报告「有未保存改动」—— 用来验证关窗口时的整体询问。"""

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.clean = False

    def can_close(self) -> bool:
        return self.clean

    def mark_clean(self) -> None:
        self.clean = True


class StubSubscriber(StubModule):
    """记录收到的总线事件 —— 验证 `params.subscribe` 真的接上了。"""

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.payloads = []

    def on_refresh(self, payload=None) -> None:
        self.payloads.append(payload)


class StubPlaceholderModule(StubModule):
    """占位模块：清单里标了 placeholder，平台上必须自动多一条常驻横幅。"""


#: 清单里指向一个不存在的类 —— 用来验证「一个模块坏了不拖垮其它」
MISSING_FACTORY = "src.workbench.tests.stub_modules:NoSuchModuleAnywhere"
