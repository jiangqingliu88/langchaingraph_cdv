"""运行清单 / 证据 —— 这次运行留下了什么可复现的东西。

两页签：

  · **运行清单**（`docs/manifest.json`）—— 架构 / 轮次 / 覆盖率 / 清单自身的
    `manifest_hash` 与 `evidence_hash`。这是「可复现」这条承诺的凭据。
  · **文件变更链**（`docs/file_change_chain.json`）—— 谁、因为什么、改了哪个文件。
    一次运行对代码的改动在这里逐条记着。

**只展示、不校验**：哈希链的完整性校验要调 L2 的 `FileAuditTrail.verify_persisted`
—— 工具层不该反向依赖层代码。校验属于治理动作，留给 P3（见
docs/design/agent_gui_business_architecture.md §6）。
"""
from __future__ import annotations

from src.workbench.bus import run_id_of

from typing import Any, Dict, List

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

MANIFEST_COLUMNS = (
    ("key", "项", 160, LEFT),
    ("value", "值", 520, LEFT),
)
CHAIN_COLUMNS = (
    ("seq", "序号", 60, CENTER),
    ("agent", "agent", 110, LEFT),
    ("file", "文件", 380, LEFT),
    ("reason", "理由", 320, LEFT),
)


class ManifestModule(ModuleBase):
    """一次运行的清单信息与文件变更链。"""

    HINT = ("选一次运行，看它留下了什么：清单里的哈希、以及这次改过哪些文件、"
            "各是为什么改的。")

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

        self.hash_label = QLabel("", root)
        self.hash_label.setWordWrap(True)
        self.hash_label.setFont(theme.mono_font(9))
        layout.addWidget(self.hash_label)

        tabs = QTabWidget(root)
        tabs.setDocumentMode(True)
        tabs.addTab(self._page("运行清单", MANIFEST_COLUMNS, "manifest"), "运行清单")
        tabs.addTab(self._page("文件变更链", CHAIN_COLUMNS, "chain"), "文件变更链")
        layout.addWidget(tabs, 1)

        self.note_label = QLabel("", root)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.note_label)
        return root

    def _page(self, title: str, columns, attr: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        model = RowsModel(columns, page)
        view = table_helpers.configure_table(page, model)
        layout.addWidget(view, 1)
        setattr(self, f"{attr}_model", model)
        setattr(self, f"{attr}_table", view)
        return page

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新运行清单", self.content)
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
        payload = self.run_tool("flow.manifest", quiet=True, run_dir=run_dir)
        if not isinstance(payload, dict):
            return
        if self.report_payload_error(payload):
            self._clear()
            return
        self.run_id = run_id
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        manifest = payload.get("manifest") or {}
        chain = payload.get("change_chain") or {}
        self.manifest_model.set_rows(list(manifest.get("rows") or []))
        self.chain_model.set_rows(list(chain.get("rows") or []))

        hashes = []
        if manifest.get("manifest_hash"):
            hashes.append(f"manifest_hash = {manifest['manifest_hash']}")
        if manifest.get("evidence_hash"):
            hashes.append(f"evidence_hash = {manifest['evidence_hash']}")
        self.hash_label.setText("　".join(hashes) if hashes else "（无清单哈希 —— 运行还没收尾）")

        notes = [str(n) for n in (payload.get("notes") or [])]
        if chain.get("available"):
            notes.insert(0, f"变更链 {chain.get('entries', 0)} 条")
        self.note_label.setText("　".join(notes))

    def _clear(self) -> None:
        self.run_id = ""
        self.manifest_model.set_rows([])
        self.chain_model.set_rows([])
        self.hash_label.setText("")
        self.note_label.setText("")
