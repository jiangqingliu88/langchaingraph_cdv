"""标签页注册表。

主窗口只遍历 TABS 建页，不认识任何具体页面 —— 新增一个标签页 =
新增一个模块 + 在这里加一行，app.py 不用改。

顺序与「从骨架到取值」的阅读顺序一致：
概览 → 组织树/专题 → 层级正交性 → 交叉矩阵 → 取值覆盖 → 环境与检查 →
Case 属性表 → 真实 case 核对 → Schema → 规则清单。
"""
from __future__ import annotations

from typing import List, Type

from .base import Tab
from .cases import CasesTab
from .coverage import CoverageTab
from .environment import EnvironmentTab
from .external import ExternalTab
from .matrix import MatrixTab
from .org_themes import OrgThemesTab
from .orthogonality import OrthogonalityTab
from .overview import OverviewTab
from .rules import RulesTab
from .schema_tab import SchemaTab

TABS: List[Type[Tab]] = [
    OverviewTab,
    OrgThemesTab,
    OrthogonalityTab,
    MatrixTab,
    CoverageTab,
    EnvironmentTab,
    CasesTab,
    ExternalTab,
    SchemaTab,
    RulesTab,
]

__all__ = [
    "TABS", "Tab",
    "OverviewTab", "OrgThemesTab", "OrthogonalityTab", "MatrixTab",
    "CoverageTab", "EnvironmentTab", "CasesTab", "ExternalTab",
    "SchemaTab", "RulesTab",
]
