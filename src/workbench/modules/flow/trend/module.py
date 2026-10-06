"""验证阶段进度趋势 —— 两张折线图 + 一张汇总表。

它回答的是「验证现在推进到哪了、还在不在涨」：

  · **面板①「编译构建趋势」** —— 编译 agent / 编译 env 的累计 build 次数。
    两个阶段的量纲是「次数」，和不占百分比的东西分开画。
  · **面板②「验证收敛趋势」** —— sim_loop 的覆盖率 + base / P0–P3 各档通过率。
    这些都是 0–100%，同轴对比才看得出「高优先级先收口」的形状。
  · **汇总表** —— 每阶段最新一轮的值，把 build 数量显式列出来，可右键复制。

数据源是 `config/trend/trend.yaml`（清单的 `input:`），界面**只读**：改 YAML →
点「刷新」。口径与判定都在 `src/tools/trend_tools/`，界面只管画。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ....ui.views.trend import TrendChart
from ...base import ModuleBase

#: 汇总表列 —— (键, 表头, 列宽, 对齐)。键是 `run_trend` 返回 summary 行里的键。
SUMMARY_COLUMNS = (
    ("title", "阶段", 160, LEFT),
    ("kind", "类型", 70, CENTER),
    ("value", "最新值", 90, CENTER),
    ("passed", "通过", 70, CENTER),
    ("total", "总数", 70, CENTER),
    ("pct", "通过率", 90, CENTER),
)


class TrendModule(ModuleBase):
    """各验证阶段的进度趋势（折线 + 汇总表）。"""

    HINT = ("数据源是 config/trend/trend.yaml —— 界面只读。上图画趋势、下表给"
            "最新值；鼠标悬停到折线上的点会显示是哪一轮。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT, root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Vertical, root)

        self.build_chart = TrendChart(splitter, panel_title="编译构建趋势（累计 build 次数）")
        self.build_chart.pointHovered.connect(self._on_point)
        splitter.addWidget(self.build_chart)

        self.test_chart = TrendChart(splitter, panel_title="验证收敛趋势（覆盖率 / 各档通过率）")
        self.test_chart.pointHovered.connect(self._on_point)
        splitter.addWidget(self.test_chart)

        splitter.addWidget(self._build_summary(splitter))
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        layout.addWidget(splitter, 1)

        self.count_label = QLabel("", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)
        return root

    def _build_summary(self, parent: QWidget) -> QWidget:
        page = QWidget(parent)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title = QLabel("最新一轮各阶段", page)
        title.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(title)
        self.summary_model = RowsModel(SUMMARY_COLUMNS, page)
        self.summary_table = table_helpers.configure_table(page, self.summary_model)
        layout.addWidget(self.summary_table, 1)
        return page

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新进度趋势", self.content)
        action.setShortcut("Ctrl+Shift+G")
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
                f"找不到进度模型：{self.spec.input or '（清单里没写 input）'}"
                f"（相对清单目录解析）")
            return
        payload = self.run_tool("flow.trend", path=str(path))
        if payload is None:
            return
        if self.report_payload_error(payload):
            self._clear()
            return

        self.build_chart.set_series(payload.get("build_series") or [],
                                    unit="次",
                                    panel_title="编译构建趋势（累计 build 次数）")
        self.test_chart.set_series(payload.get("test_series") or [], y_max=100,
                                   unit="%",
                                   panel_title="验证收敛趋势（覆盖率 / 各档通过率）")
        self.summary_model.set_rows(payload.get("summary") or [])
        self._update_counts(payload)

    def _update_counts(self, payload: Dict[str, Any]) -> None:
        counts = payload.get("counts") or {}
        project = payload.get("project") or "（未命名）"
        self.count_label.setText(
            f"{project}　——　{counts.get('rounds', 0)} 轮，"
            f"累计 {counts.get('builds_total', 0)} 次 build")
        unresolved = payload.get("unresolved") or []
        if unresolved:
            bad = "、".join(sorted({str(u.get("stage", "")) for u in unresolved}))
            self.show_warning(f"进度模型里有没声明的阶段：{bad}（已忽略，请对照 stages 补上）")
        else:
            self.clear_banner()

    def _clear(self) -> None:
        self.build_chart.set_series([])
        self.test_chart.set_series([])
        self.summary_model.set_rows([])
        self.count_label.setText("")

    def _on_point(self, series_id: str, round_no: int, value: float) -> None:
        """悬停到折线上某个点 —— 用底部标签说清「这是谁、哪一轮、多少」。"""
        self.count_label.setText(f"{series_id}　第 {round_no} 轮：{value:g}")
