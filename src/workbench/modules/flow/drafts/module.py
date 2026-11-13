"""规则草案 —— 「这次运行长出了哪条规则，等人拍板」。

**为什么单独一页**：草案原来只写在 `<run>/docs/rule_drafts.md` 里 —— 得有人
想起来去翻。而它的价值恰恰是"被看见"：机器提议、人提交，中间那一步没人看见，
规则库就还是长不大（这是 `rule_stats` / `rule_draft` 那条链的最后一环）。

三条动作，都**不改代码**：复制粘贴骨架（人自己落进 `semantic_check`）、标记已接受
（记一次人的拍板，可审计）、打开 md。**接受不等于自动生效** —— 一条校验规则会
改变"什么算错"，那是判断不是统计（见 `rule_draft` 的说明）。
"""
from __future__ import annotations

from src.workbench.bus import run_id_of

from typing import Any, Dict, List

from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QWidget

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

COLUMNS = (
    ("rule_id", "规则 id", 200, LEFT),
    ("stage", "该拦在哪", 300, LEFT),
    ("severity", "严重度", 80, CENTER),
    ("fingerprint", "指纹", 110, CENTER),
    ("evidence", "证据", 420, LEFT),
    ("accepted", "状态", 90, CENTER),
)


class DraftsModule(ModuleBase):
    """这次运行起草的规则草案（机器提议，等人拍板）。"""

    HINT = ("**机器提议、人提交**：这些是从真实失败里起草出来的规则。"
            "点「复制骨架」拿去写进 semantic_check，点「标记已接受」记下你接了它。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""
        self.run_dir: str = ""

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT, root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        row = QHBoxLayout()
        self.summary_label = QLabel("", root)
        self.summary_label.setStyleSheet("font-weight: bold;")
        row.addWidget(self.summary_label)
        row.addStretch(1)
        self.copy_btn = QPushButton("复制骨架", root)
        self.accept_btn = QPushButton("标记已接受", root)
        self.copy_btn.clicked.connect(self._copy_skeleton)
        self.accept_btn.clicked.connect(self._mark_accepted)
        row.addWidget(self.copy_btn)
        row.addWidget(self.accept_btn)
        layout.addLayout(row)

        self.model = RowsModel(COLUMNS, root)
        self.table = table_helpers.configure_table(root, self.model)
        layout.addWidget(self.table, 1)

        self.note_label = QLabel("", root)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.note_label)
        return root

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新规则草案", self.content)
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
        run_dir = str((detail or {}).get("dir", "") or "") if isinstance(detail, dict) else ""
        if not run_dir:
            return
        payload = self.run_tool("flow.rule_drafts", quiet=True, run_dir=run_dir)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            self._clear()
            return
        self.run_id, self.run_dir = run_id, run_dir
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        rows = payload.get("rows") or []
        out, colors = [], {}
        for i, r in enumerate(rows):
            accepted = bool(r.get("accepted"))
            colors[i] = QColor(theme.current().ok if accepted else theme.current().warning)
            out.append({
                "rule_id": r.get("rule_id", ""), "stage": r.get("stage", ""),
                "severity": r.get("severity", ""), "fingerprint": r.get("fingerprint", ""),
                "evidence": r.get("evidence", ""),
                "accepted": "已接受" if accepted else "待拍板",
            })
        self.model.set_rows(out, row_colors=colors)
        self._rows = list(rows)
        pending = int(payload.get("pending") or 0)
        self.summary_label.setText(
            f"待拍板 {pending} 条　共 {len(out)} 条" if out else "这次运行没有起草规则")
        self.note_label.setText("　".join(str(n) for n in (payload.get("notes") or [])))

    def _selected(self) -> Dict[str, Any]:
        idx = self.table.currentIndex()
        rows = getattr(self, "_rows", []) or []
        return rows[idx.row()] if idx.isValid() and 0 <= idx.row() < len(rows) else {}

    def _copy_skeleton(self) -> None:
        from PySide6.QtWidgets import QApplication

        row = self._selected()
        if not row:
            self.set_status("先选中一条草案")
            return
        QApplication.clipboard().setText(str(row.get("skeleton", "")))
        self.set_status(f"骨架已复制：{row.get('rule_id')}（粘进 semantic_check 再写判据）")

    def _mark_accepted(self) -> None:
        from src.knowledge_plane.rule_draft import mark_accepted

        row = self._selected()
        if not row or not self.run_dir:
            self.set_status("先选中一条草案")
            return
        if mark_accepted(self.run_dir, str(row.get("rule_id", ""))):
            self.set_status(f"已接受 {row.get('rule_id')} —— 记进 {self.run_dir}/docs/")
            self.load(self.run_id)
        else:
            self.set_status("标记失败（写不进运行目录）")

    def _clear(self) -> None:
        self.run_id = self.run_dir = ""
        self._rows = []
        self.model.set_rows([])
        self.summary_label.setText("")
        self.note_label.setText("")
