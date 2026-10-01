"""标签页的基类。

设计模式：**Template Method** —— 每个标签页只实现 build()（搭控件）与
refresh()（填数据），「什么时候刷新、刷新前先检查有没有结果」由基类定。
这样新增一个标签页只要写一个类并在 tabs/__init__.py 登记，
主窗口不用改（它遍历 TABS 建页）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import tkinter as tk
from tkinter import ttk

if TYPE_CHECKING:                       # 避免与 app 循环 import
    from ..app import CaseModelApp
    from ....analysis import AnalysisResult


class Tab(ABC):
    """一个标签页。"""
    title: str = ""
    hint: str = ""

    def __init__(self, master: "tk.Misc", app: "CaseModelApp") -> None:
        self.app = app
        self.frame = ttk.Frame(master)
        self.build()

    @abstractmethod
    def build(self) -> None:
        """搭控件。只建一次。"""

    @abstractmethod
    def refresh(self, result: "AnalysisResult") -> None:
        """填数据。每次分析后调用。"""

    # ── 给子类用的小工具 ──

    def hint_label(self, parent: "tk.Misc", wraplength: int = 1180) -> ttk.Label:
        label = ttk.Label(parent, text=self.hint, foreground="#5f6b7a",
                          justify=tk.LEFT, wraplength=wraplength)
        label.pack(fill=tk.X, pady=(0, 6))
        return label
