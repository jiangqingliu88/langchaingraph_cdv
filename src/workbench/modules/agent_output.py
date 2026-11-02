"""某个 agent 在这次运行里做了什么 —— 七条 agent 线共用的那个视图。

**为什么放在 `modules/` 根而不是某条线里**：它被七条线各用一次。`run_common.py`
那类共享件放在**线内**（只服务一条线），而这个是**跨线**的 —— 放在根上，
七条线各自 `output.py` 里几行子类声明即可（模块之间不互相 import，但都可以
向下依赖这个平台级共享件）。

数据来自 `src/tools/flow/flow_tools.api:run_agent_outputs(run_dir, role)`：
  · **阶段** —— 运行日志里 `agent` 等于本角色的那些阶段事件（状态 / 轮次 / 耗时 / 摘要）
  · **产物** —— 本角色写的目录（RTL / 参考模型 / UVM 组件 / 仿真 / 覆盖率）里的文件

它回答的就是一句话：**这个 agent 这次干了什么、东西在哪。**

「这次」从哪来：订阅 `run.selected` —— 在「运行历史」里选一次运行，七条线一起切。
"""
from __future__ import annotations

from src.workbench.bus import run_id_of

from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from ..ui import theme
from ..ui.helpers import tables as table_helpers
from ..ui.models import CENTER, LEFT, RIGHT, RowsModel
from .base import ModuleBase

STAGE_COLUMNS = (
    ("title", "阶段", 170, LEFT),
    ("round", "轮次", 60, CENTER),
    ("status", "状态", 80, LEFT),
    ("duration", "耗时", 80, RIGHT),
    ("summary", "摘要", 420, LEFT),
)
ARTIFACT_COLUMNS = (
    ("title", "产物目录", 150, LEFT),
    ("count", "文件数", 70, CENTER),
    ("files", "文件", 520, LEFT),
)

#: 阶段状态 → 颜色。与 run_common.status_color 同一口径（这里不 import 它 ——
#: 那是 flow 线的线内件，跨线依赖不合适）。
_STATUS_COLORS = {"ok": "ok", "failed": "error", "running": "accent", "waiting": "warning"}


class AgentOutputModule(ModuleBase):
    """一个 agent 的产出总览。子类只需声明 `ROLE`。"""

    #: 子类必须覆盖：本模块代表哪个 agent（`design` / `model` / …）
    ROLE: str = ""

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""
        self.role = self.ROLE or str(self.spec.params.get("role", "") or "")

    # ════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT or self._default_hint(), root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        self.header_label = QLabel("（还没选中运行）", root)
        layout.addWidget(self.header_label)

        splitter = QSplitter(Qt.Orientation.Vertical, root)
        splitter.addWidget(self._table_page("阶段（这次跑过哪些）", STAGE_COLUMNS, "stage"))
        splitter.addWidget(self._table_page("产物（东西在哪）", ARTIFACT_COLUMNS, "artifact"))
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.note_label = QLabel("", root)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet(f"color: {theme.current().warning};")
        layout.addWidget(self.note_label)

        self.count_label = QLabel("", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)
        return root

    def _table_page(self, title: str, columns, attr_prefix: str) -> QWidget:
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
        setattr(self, f"{attr_prefix}_model", model)
        setattr(self, f"{attr_prefix}_table", view)
        return page

    def _default_hint(self) -> str:
        return ("选一次运行（左边「运行历史」），这里显示该 agent 这次跑了哪些阶段、"
                "产出了哪些文件。")

    def create_actions(self) -> List[QAction]:
        action = QAction(f"刷新{self.title}", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        run_id = run_id_of(payload)
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
        payload = self.run_tool("agent.outputs", quiet=True,
                                run_dir=run_dir, role=self.role)
        if not isinstance(payload, dict):
            return
        if self.report_payload_error(payload):
            self._clear()
            return

        self.run_id = run_id
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        title = payload.get("role_title") or self.role
        counts = payload.get("counts") or {}
        self.header_label.setText(f"{self.run_id}　{title}")
        self.count_label.setText(
            f"{counts.get('stages', 0)} 个阶段　{counts.get('files', 0)} 个产物文件")

        self._fill_stages(payload.get("stages") or [])
        self._fill_artifacts(payload.get("artifacts") or [])

        # 记在脚下那行，不弹横幅：这些是「截断了 / 还没跑到」的说明，不是错误
        notes = payload.get("notes") or []
        self.note_label.setText("　".join(str(n) for n in notes))

    def _fill_stages(self, stages: List[Dict[str, Any]]) -> None:
        rows: List[Dict[str, Any]] = []
        colors: Dict[int, QColor] = {}
        for index, stage in enumerate(stages):
            rows.append({
                "title": stage.get("title", ""),
                "round": str(stage.get("round", 0) or ""),
                "status": stage.get("status", ""),
                "duration": f"{stage.get('duration_s', 0):.1f}s",
                "summary": stage.get("summary", ""),
            })
            colors[index] = _status_color(str(stage.get("status", "")))
        self.stage_model.set_rows(rows, row_colors=colors)

    def _fill_artifacts(self, artifacts: List[Dict[str, Any]]) -> None:
        rows: List[Dict[str, Any]] = []
        for artifact in artifacts:
            names = "、".join(f["name"] for f in artifact.get("files") or [])
            rows.append({"title": artifact.get("title", artifact.get("dir", "")),
                         "count": str(artifact.get("file_count", 0)),
                         "files": names})
        self.artifact_model.set_rows(rows)

    def _clear(self) -> None:
        self.run_id = ""
        self.header_label.setText("（还没选中运行）")
        self.stage_model.set_rows([])
        self.artifact_model.set_rows([])
        self.note_label.setText("")
        self.count_label.setText("")


def _status_color(status: str) -> QColor:
    palette = theme.current()
    name = _STATUS_COLORS.get(status, "")
    return QColor(getattr(palette, name) if name else palette.muted)
