"""case 建模模块的 11 个页面。

**页面清单硬编码在这里，而不是从 YAML 清单读** —— 与平台的其他模块不同，
这 11 个页面不是「可插拔的界面」，而是**同一份文档的 11 个视图**：它们共享
模块的编辑器、共享 `AnalysisResult`、点诊断要跳到同一个编辑器里的行。
把它们外置成清单只会制造「有人删掉一页导致跳转断掉」的机会。

要加一页：写一个 `Page` 子类，在下面 `PAGES` 里加一行。模块不用改。
"""
from __future__ import annotations

from typing import List, Type

from ..page import Page
from .cases import CasesPage
from .coverage import CoveragePage
from .editor import EditorPage
from .environment import EnvironmentPage
from .external import ExternalPage
from .matrix import MatrixPage
from .org_themes import OrgThemesPage
from .orthogonality import OrthogonalityPage
from .overview import OverviewPage
from .rules import RulesPage
from .schema_tab import SchemaPage

#: 编辑器页的标题 —— 模块用它取回编辑器（唯一的真相所在）
EDITOR_TITLE = EditorPage.TITLE

#: 阅读顺序：先编辑，再从骨架到取值，最后是诊断与元信息
PAGES: List[Type[Page]] = [
    EditorPage,
    OverviewPage,
    OrgThemesPage,
    OrthogonalityPage,
    MatrixPage,
    CoveragePage,
    EnvironmentPage,
    CasesPage,
    ExternalPage,
    SchemaPage,
    RulesPage,
]

__all__ = ["PAGES", "Page", "EDITOR_TITLE"]
