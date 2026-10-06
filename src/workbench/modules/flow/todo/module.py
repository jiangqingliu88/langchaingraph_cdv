"""待办 / 卡点 —— 「现在该干什么」。

**为什么单独一页**：需要人做的事原本散在四个页面里 —— 待审批的在「验证流程」、
待签豁免的在「覆盖率豁免」、要人工确认的在「决策轨迹」、卡住的运行在「运行历史」。
靠人记着去哪看，就是"漏掉"的来源。这一页把它们聚成一张**待办**（不是概览）：
要你动手的排前面，看一眼的排后面，每条都写清"在哪处理"。

数据全是现成的（豁免登记册 / 阶段的 `needs_human` / `harness_triage` / 运行事件），
这一页只做聚合与排序 —— 见 `flow_tools.api:collect_todos`。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

COLUMNS = (
    ("kind", "类别", 110, CENTER),
    ("item", "事项", 420, LEFT),
    ("detail", "细节", 380, LEFT),
    ("action", "在哪处理", 360, LEFT),
)


class TodoModule(ModuleBase):
    """把"需要人做的事"聚成一页。"""

    HINT = ("这一页回答「现在该干什么」：**要你动手的排前面**。"
            "每条都写清在哪处理 —— 不用去四个页面里找。")

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

        self.summary_label = QLabel("", root)
        self.summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.summary_label)

        self.model = RowsModel(COLUMNS, root)
        self.table = table_helpers.configure_table(root, self.model)
        layout.addWidget(self.table, 1)

        self.note_label = QLabel("", root)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.note_label)
        return root

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新待办", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self.load(run_id)

    def load(self, run_id: str) -> None:
        if not run_id:
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        run_dir = str((detail or {}).get("dir", "") or "") if isinstance(detail, dict) else ""
        if not run_dir:
            return
        payload = self.run_tool("flow.todo", quiet=True, run_dir=run_dir)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            self._clear()
            return
        self.run_id = run_id
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        from src.tools.flow_tools.api import TODO_KINDS

        rows = payload.get("rows") or []
        tones = {}
        out = []
        for i, row in enumerate(rows):
            kind = str(row.get("kind", ""))
            title, tone = TODO_KINDS.get(kind, (kind, "info"))
            tones[i] = ("warn" if tone == "warn" else "info")
            out.append({"kind": title, "item": row.get("item", ""),
                        "detail": row.get("detail", ""), "action": row.get("action", "")})
        palette = theme.current()
        colors = {i: QColor(palette.warning if t == "warn" else palette.muted)
                  for i, t in tones.items()}
        self.model.set_rows(out, row_colors=colors)

        act = sum(1 for t in tones.values() if t == "warn")
        self.summary_label.setText(
            f"要你动手 {act} 项　共 {len(out)} 条" if out else "没有待办")
        self.note_label.setText("　".join(str(n) for n in (payload.get("notes") or [])))

    def _clear(self) -> None:
        self.run_id = ""
        self.model.set_rows([])
        self.summary_label.setText("")
        self.note_label.setText("")
