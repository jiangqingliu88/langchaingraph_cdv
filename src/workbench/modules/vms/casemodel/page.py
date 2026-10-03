"""页面基类 —— case 建模模块内部的 11 个视图。

设计模式：**Template Method**。每个页面只实现 `build()`（搭控件）与
`refresh(result)`（填数据）；「什么时候刷新、刷新前先判有没有结果」由模块定。

页面只拿 `AnalysisResult` 与只读的 `model`，不自己算任何东西 —— 判定逻辑全在
`src/tools/casemodel_tools/analysis/`，所以能脱离窗口单独测。

> 这 11 个页面**嵌在模块内部的一个 QTabWidget 里**，不摊成平台的中央标签页。
> 理由是它们都是同一份文本的只读视图：摊开之后用户能把「概览」拖到别的
> 标签页去，而它跟「编辑 YAML」本来是一体的（点诊断跳源码靠的就是这个关系）。
"""
# 跨层引用一律用绝对路径：本文件在 casemodel/pages/ 底下，相对路径要数五层点，
# 数错一次就是 ImportError 且看不出错在哪。
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QTableView, QVBoxLayout, QWidget

from src.workbench.ui import table_helpers, theme

#: 工程工具的边距感 —— 比「消费级 App」紧一档，一屏多放几行
MARGIN = 5
SPACING = 3


class Page(QWidget):
    """一个页面。"""

    TITLE: str = ""
    HINT: str = ""

    def __init__(self, module, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.module = module
        self.build()

    # ── 子类实现 ──

    def build(self) -> None:
        """搭控件。只建一次。"""

    def refresh(self, result) -> None:
        """填数据。每次分析后调用。"""

    def clear(self) -> None:
        """没有结果时清空 —— 留着上次的行会误导。默认什么都不做。"""

    # ════════════════════════════════════════════════════════
    # 给子类用的小工具
    # ════════════════════════════════════════════════════════

    def frame(self) -> QVBoxLayout:
        """页面的标准外层布局 —— 紧凑边距。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.setSpacing(SPACING)
        return layout

    def hint_label(self, text: Optional[str] = None) -> QLabel:
        label = QLabel(text if text is not None else self.HINT)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.current().muted};")
        return label

    def section_label(self, text: str) -> QLabel:
        """小节标题 —— 工程工具用一条细线 + 小字分隔区域，不用大标题。"""
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {theme.current().text}; font-weight: bold;"
            f"border-bottom: 1px solid {theme.current().border};"
            f"padding-bottom: 2px;")
        return label

    # ── 表格 ──

    def make_table(self, model=None, **kwargs) -> QTableView:
        """配置好的 QTableView —— 观感与交互统一在 `ui/table_helpers.py`。"""
        return table_helpers.configure_table(self, model, **kwargs)

    @staticmethod
    def source_index(view: QTableView, index):
        """把视图（可能套了排序代理）的 index 映射到源模型。

        套了代理之后 `view.currentIndex()` 的行号是**排序后**的行号，
        直接拿去源模型取数会取错行。
        """
        return table_helpers.source_index(view, index)

    def clear_table(self, view: QTableView) -> None:
        table_helpers.clear_table(view)
