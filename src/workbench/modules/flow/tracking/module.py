"""测试点 / 验证资产 跟踪表 —— 两个页签，一张表一个。

它回答的是验证经理每天要问的那个问题：**这条测试点验了没有，用的是哪些
资产？** 所以刻意做成两张表而不是一张：

  · 「测试点」——一个测试点一行，最后一列列出它引用的资产。
  · 「验证资产」——一个资产一行（RTL / UVM 环境 / 用例 / 参考模型 / 报告），
    最后一列反过来列出**哪些测试点引用了它**。

两张表都**只读**：数据源是 `config/tracking/tracking.yaml`（清单的 `input:`）。
改数据改 YAML，然后点「刷新」—— 界面不做写回，判定与数据都不在界面里，
这是全仓库的分层纪律。

选中一张表里的行，另一张表里相关的行会被**着色**：点一条测试点，它引用的
资产亮起来；点一个资产，引用它的测试点亮起来。颜色只是帮助扫读（与
runs / evidence 一致），信息本身仍由文字承担。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (QLabel, QTabWidget, QVBoxLayout, QWidget)

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

#: 表格列 —— (键, 表头, 列宽, 对齐)。键是 `run_tracking` 返回行里的英文键。
TESTPOINT_COLUMNS = (
    ("id", "编号", 150, LEFT),
    ("feature", "功能点", 140, LEFT),
    ("description", "描述", 320, LEFT),
    ("priority", "级别", 60, CENTER),
    ("method", "方法", 60, CENTER),
    ("status", "状态", 80, LEFT),
    ("assets", "关联资产", 280, LEFT),
)
ASSET_COLUMNS = (
    ("id", "资产", 150, LEFT),
    ("type", "类型", 110, LEFT),
    ("path", "路径", 320, LEFT),
    ("hash", "哈希", 130, LEFT),
    ("status", "状态", 80, LEFT),
    ("testpoints", "关联测试点", 220, LEFT),
    ("note", "说明", 260, LEFT),
)


class TrackingModule(ModuleBase):
    """testpoint 与验证资产的只读跟踪表。"""

    HINT = ("数据源是 config/tracking/tracking.yaml —— 界面只读。改了 YAML 点"
            "「刷新」；选一行，另一张表里相关的行会被标出来。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        #: 最近一次成功加载的原始行 —— 重新着色时用它重建，不重新调工具
        self._tp_rows: List[Dict[str, Any]] = []
        self._asset_rows: List[Dict[str, Any]] = []

    # ════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT, root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        self.tabs = QTabWidget(root)
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_testpoint_page(), "测试点")
        self.tabs.addTab(self._build_asset_page(), "验证资产")
        layout.addWidget(self.tabs, 1)

        self.count_label = QLabel("", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)
        return root

    def _build_testpoint_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.tp_model = RowsModel(TESTPOINT_COLUMNS, page)
        self.tp_table = table_helpers.configure_table(page, self.tp_model)
        self.tp_table.selectionModel().selectionChanged.connect(self._on_testpoint_selected)
        layout.addWidget(self.tp_table, 1)
        return page

    def _build_asset_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.asset_model = RowsModel(ASSET_COLUMNS, page)
        self.asset_table = table_helpers.configure_table(page, self.asset_model)
        self.asset_table.selectionModel().selectionChanged.connect(self._on_asset_selected)
        layout.addWidget(self.asset_table, 1)
        return page

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新跟踪表", self.content)
        action.setShortcut("Ctrl+Shift+T")
        action.triggered.connect(self.refresh)
        return [action]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        self.refresh()

    def on_refresh(self, payload: Any = None) -> None:
        self.refresh()

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def refresh(self) -> None:
        path = self.ctx.existing_data_path(self.spec)
        if path is None:
            self._clear()
            self.show_warning(
                f"找不到跟踪表：{self.spec.input or '（清单里没写 input）'}"
                f"（相对清单目录解析）")
            return
        payload = self.run_tool("flow.tracking", path=str(path))
        if payload is None:
            return
        if self.report_payload_error(payload):
            self._clear()
            return

        self._tp_rows = list(payload.get("testpoints") or [])
        self._asset_rows = list(payload.get("assets") or [])
        self._paint_testpoints()
        self._paint_assets()
        self._update_counts(payload)

    def _update_counts(self, payload: Dict[str, Any]) -> None:
        counts = payload.get("counts") or {}
        project = payload.get("project") or "（未命名）"
        text = (f"{project}　——　{counts.get('testpoints', 0)} 个测试点，"
                f"{counts.get('assets', 0)} 个验证资产")
        unresolved = int(counts.get("unresolved", 0) or 0)
        if unresolved:
            # 悬空引用是要看见的信号，不静默
            text += f"，{unresolved} 处资产引用对不上（见「关联资产」列）"
            self.show_warning(f"有 {unresolved} 处测试点引用了没登记的资产。")
        else:
            self.clear_banner()
        self.count_label.setText(text)

    def _clear(self) -> None:
        self._tp_rows = []
        self._asset_rows = []
        self.tp_model.set_rows([])
        self.asset_model.set_rows([])
        self.count_label.setText("")

    # ════════════════════════════════════════════════════════
    # 跨表联动 —— 选中一张表的行，另一张表里相关的行着色
    # ════════════════════════════════════════════════════════

    def _on_testpoint_selected(self) -> None:
        row = self._selected_row(self.tp_table)
        refs = set(row.get("asset_refs") or []) if row else set()
        self._paint_assets(highlight=refs)

    def _on_asset_selected(self) -> None:
        row = self._selected_row(self.asset_table)
        linked = set(row.get("testpoint_refs") or []) if row else set()
        self._paint_testpoints(highlight=linked)

    def _paint_testpoints(self, highlight: set = frozenset()) -> None:
        self.tp_model.set_rows(self._tp_rows, row_colors=self._colors(
            self._tp_rows, "id", highlight))

    def _paint_assets(self, highlight: set = frozenset()) -> None:
        self.asset_model.set_rows(self._asset_rows, row_colors=self._colors(
            self._asset_rows, "id", highlight))

    @staticmethod
    def _colors(rows: List[Dict[str, Any]], key: str, highlight: set) -> Dict[int, QColor]:
        """被高亮的行 → accent 色；其余不设色（走主题默认）。"""
        if not highlight:
            return {}
        color = QColor(theme.current().accent)
        return {i: color for i, row in enumerate(rows)
                if str(row.get(key, "")) in highlight}

    @staticmethod
    def _selected_row(view) -> Dict[str, Any]:
        """当前选中的行（原始 dict）。

        视图挂了排序代理，`currentIndex().row()` 是**排序后**的行号，必须经
        `source_index` 映射回源模型 —— 否则选第 3 行会取到另一个对象的行。
        """
        index = view.currentIndex()
        if not index.isValid():
            return {}
        source = table_helpers.source_index(view, index)
        model = table_helpers.source_model(view)
        row = model.row_at(source.row()) if hasattr(model, "row_at") else None
        return row if isinstance(row, dict) else {}
