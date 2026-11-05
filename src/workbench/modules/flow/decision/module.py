"""决策轨迹 —— 每一轮「为什么这么走」。

闭环每轮都会做一次决策（覆盖率不够就补定向激励、编译炸了就回滚 RTL……），
再经过驾驭层（预算 / 熔断 / 干预）放行或拦下。此前这两件事在界面上**只以
一行行日志文本**存在；这一页把它们摆成一张按轮次排的表。

数据从运行日志的 `decide` / `governor` 阶段**结束事件**里取 —— 节点写回的状态
增量整个挂在 `payload.delta` 里，决策动作在 `pending_action`、驾驭结论在
`governance_outcome`。

> 刻意不去读 `decision` 事件：`RunJournal.decision()` 定义了但**没有任何调用点**，
> 日志里根本没有那种事件。拿它当数据源会画出一张永远空的表。
"""
from __future__ import annotations

from src.workbench.bus import run_id_of

from typing import Any, Dict, List

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

COLUMNS = (
    ("round", "轮次", 60, CENTER),
    ("action", "决策动作", 180, LEFT),
    ("source_label", "来源", 90, CENTER),
    ("reward", "奖励", 140, CENTER),
    ("priority", "优先级", 70, CENTER),
    ("governance", "驾驭裁决", 100, CENTER),
    ("reason", "理由", 300, LEFT),
    ("params", "参数", 300, LEFT),
)


class DecisionTraceModule(ModuleBase):
    """一次运行的逐轮决策轨迹。"""

    HINT = ("选一次运行，这里按轮次列出决策动作、来源（硬规则 / 规则 / RL 采纳 / "
            "RL 被退回 / 终态）、粗连续奖励与驾驭层裁决。"
            "来源是运行日志的 decide / governor / coverage 阶段事件。")

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

        self.model = RowsModel(COLUMNS, root)
        self.table = table_helpers.configure_table(root, self.model)
        layout.addWidget(self.table, 1)

        self.note_label = QLabel("", root)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.note_label)
        return root

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新决策轨迹", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        run_id = run_id_of(payload)
        if run_id and run_id != self.run_id:
            self.load(run_id)

    def load(self, run_id: str) -> None:
        if not run_id:
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        run_dir = str(detail.get("dir", "") or "")
        payload = self.run_tool("flow.decision", quiet=True, run_dir=run_dir)
        if not isinstance(payload, dict):
            return
        if self.report_payload_error(payload):
            self._clear()
            return
        self.run_id = run_id
        self.model.set_rows(list(payload.get("rounds") or []))
        self.note_label.setText(payload.get("note", "") or
                                f"{len(payload.get('rounds') or [])} 轮决策")

    def _clear(self) -> None:
        self.run_id = ""
        self.model.set_rows([])
        self.note_label.setText("")
