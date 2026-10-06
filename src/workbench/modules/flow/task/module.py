"""验证任务总览 —— 一屏回答「这个任务现在什么情况」。

**为什么要有这一页**：其余视图都是"某个侧面"——`验证流程`看阶段、`签核判定`看门禁、
`进度趋势`看曲线、`决策轨迹`看每轮怎么走。但没有一处在回答最开始那个问题：

    这个验证任务跑到哪了？还差多少？卡住了没有？该不该继续？

它把**一次运行当成一个任务**来看：目标 / 当前覆盖率 / 差距 / 收敛预测 / 阶段通过数 /
卡点。数据来自运行日志与 `manifest.json`（规划器算的 `convergence_forecast` 就在里面）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

METRIC_COLUMNS = (
    ("key", "项", 150, LEFT),
    ("value", "值", 460, LEFT),
)
BLOCKER_COLUMNS = (
    ("title", "卡在哪一步", 220, LEFT),
    ("round", "轮次", 60, CENTER),
    ("error", "错误", 520, LEFT),
)
#: 任务状态 → 主题色字段名。写死颜色的话深色主题下会糊成一片。
_STATE_COLOR = {
    "completed": "ok",
    "completed_with_errors": "warning",
    "failed": "error",
    "cancelled": "warning",
    "waiting": "warning",
    "running": "accent",
}


class TaskModule(ModuleBase):
    """一次运行 = 一个验证任务的总览。"""

    HINT = ("选一次运行，这里把「一个验证任务」的全貌摆在一屏：目标、当前覆盖率、"
            "还差多少、收敛预测、跑到第几步、卡在哪。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT, root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        self.summary_label = QLabel("（还没选中运行）", root)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Orientation.Vertical, root)
        splitter.addWidget(self._page("任务指标", METRIC_COLUMNS, "metric"))
        splitter.addWidget(self._page("卡点", BLOCKER_COLUMNS, "blocker"))
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        return root

    def _page(self, title: str, columns, attr: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        label = QLabel(title, page)
        label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(label)
        model = RowsModel(columns, page)
        view = table_helpers.configure_table(page, model)
        layout.addWidget(view, 1)
        setattr(self, f"{attr}_model", model)
        setattr(self, f"{attr}_table", view)
        return page

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新任务总览", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self.load(run_id)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def load(self, run_id: str) -> None:
        if not run_id:
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        run_dir = str(detail.get("dir", "") or "")
        payload = self.run_tool("flow.task", quiet=True, run_dir=run_dir)
        if not isinstance(payload, dict):
            return
        if self.report_payload_error(payload):
            self._clear()
            return
        self.run_id = run_id
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        state = str(payload.get("state", "unknown"))
        self.summary_label.setText(f"{self.run_id}　{payload.get('summary', '')}")
        palette = theme.current()
        field = _STATE_COLOR.get(state, "muted")
        self.summary_label.setStyleSheet(
            f"color: {getattr(palette, field)}; font-weight: bold;")
        self.metric_model.set_rows(_metric_rows(payload))
        self.blocker_model.set_rows(list(payload.get("blockers") or []))

    def _clear(self) -> None:
        self.run_id = ""
        self.summary_label.setText("（还没选中运行）")
        self.summary_label.setStyleSheet("")
        self.metric_model.set_rows([])
        self.blocker_model.set_rows([])


def _metric_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """任务指标 → 行。**没有的项不编造** —— 直接说"（无）"。"""
    coverage = payload.get("coverage") or {}
    forecast = payload.get("forecast") or {}
    phases = payload.get("phases") or {}
    current = payload.get("current") or {}
    target = payload.get("target")

    def fmt(value, suffix="", empty="（无）"):
        if value is None or value == "":
            return empty
        # 数字用 :g —— 95.0% 读起来是"机器数"，95% 才是人看的
        return f"{value:g}{suffix}" if isinstance(value, (int, float)) else f"{value}{suffix}"

    gap = coverage.get("gap")
    if gap is None:
        gap_text = "（无）"
    elif gap <= 0:
        gap_text = "已达标"
    else:
        gap_text = f"还差 {gap:g} 个点"

    rounds = forecast.get("rounds_to_target")
    if rounds is not None:
        forecast_text = f"还需 {rounds} 轮"
    elif forecast.get("converging") is False:
        # 规划器自己会给一句说明（如"覆盖率停滞，需换策略"）—— 有就用它，别再加前缀
        forecast_text = forecast.get("note") or "覆盖率停滞"
    else:
        forecast_text = "（无预测 —— 至少两轮后才有意义）"

    history = coverage.get("history") or []
    curve = " → ".join(f"R{r} {v:g}%" for r, v in history) if history else "（无逐轮记录）"

    return [
        {"key": "任务状态", "value": fmt(payload.get("state"))},
        {"key": "目标覆盖率", "value": fmt(target, "%")},
        {"key": "当前覆盖率", "value": fmt(coverage.get("final"), "%")},
        {"key": "有效覆盖率", "value": fmt(coverage.get("effective"), "%")},
        {"key": "差距", "value": gap_text},
        {"key": "收敛预测", "value": forecast_text},
        {"key": "阶段", "value": f"{phases.get('passed', 0)}/{phases.get('total', 0)} 过"
                                 + (f"，{phases['failed']} 失败" if phases.get("failed") else "")},
        {"key": "当前步骤", "value": (current.get("title") or "（无）")
                                    + (f"（{current.get('status')}）" if current.get("status") else "")},
        {"key": "逐轮覆盖率", "value": curve},
    ]
