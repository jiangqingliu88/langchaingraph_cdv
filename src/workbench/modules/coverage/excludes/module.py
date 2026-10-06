"""覆盖率豁免审批 —— 自动发现提出的"这个洞结构不可达"，等人签字。

**为什么必须是人签。** 一个覆盖率洞到底是不是结构不可达，是**设计知识**：
FIFO 深度固定所以某个波特率组合永远走不到、某个 FSM 状态不可达 —— 这些判断
AI 给不出可信答案（实测那条铁律：LLM 对"最后一公里"根本性不足）。所以覆盖率
阶段的"自动发现"只敢**提议**（`graph.py` 那句「已提议（待审批）」），签字的必须是人。

**为什么这一页的核心不是列表。** 批准一条豁免会把那个覆盖点从**分母**里拿掉 ——
等于**放行一个原本没覆盖的点**。这个动作会改变签核结论。所以界面的重点不是
"有哪些提议"，而是**让人看清自己在签什么**：

  · 提议的**理由**与**证据**（不提证据的批准是拍脑袋）；
  · 签完之后**谁签的**、**哈希指纹是哪一串** —— 那一串就是"这条豁免接进了证据链"
    的凭证，不是装饰。

在此之前**只有 CLI** 能批（`vagent exclude approve`），工作台里连"有提议待批"
都看不到。于是这些东西的现状是：提议一直攒，没人批。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from src.workbench.modules.base import ModuleBase
from src.workbench.ui import theme
from src.workbench.ui.helpers import tables as table_helpers
from src.workbench.ui.models import CENTER, LEFT, RowsModel


class ExcludesModule(ModuleBase):
    """待批 / 已批的覆盖率豁免 + 签字。"""

    HINT = ("自动发现提出的「这个洞结构不可达」在这里等人签字。\n"
            "**批准会把该点从覆盖率分母里拿掉** —— 等于放行一个原本没覆盖的点，"
            "签核结论会跟着变。所以先看理由和证据，再签。\n"
            "签名会连同**哈希指纹**一起入链：谁批的、批的是哪条，都查得到。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.pending: List[Dict[str, Any]] = []
        self.approved: List[Dict[str, Any]] = []

    # ════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addLayout(self._build_bar(root))

        splitter = QSplitter(Qt.Orientation.Vertical, root)
        splitter.addWidget(self._build_pending(root))
        splitter.addWidget(self._build_detail(root))
        splitter.addWidget(self._build_approved(root))
        splitter.setSizes([220, 200, 200])
        layout.addWidget(splitter, 1)
        return root

    def _build_bar(self, parent: QWidget) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新", parent)
        self.refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_btn)

        self.summary = QLabel("（还没读）", parent)
        self.summary.setStyleSheet(f"color: {theme.current().muted};")
        bar.addWidget(self.summary, 1)
        return bar

    def _build_pending(self, parent: QWidget) -> QWidget:
        pane = QWidget(parent)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(QLabel("待审批", pane))

        columns = (("exclude_id", "编号", 90, LEFT),
                   ("coverage_point", "覆盖点", 220, LEFT),
                   ("type_title", "类型", 100, LEFT),
                   ("reason", "理由", 420, LEFT))
        self.pending_model = RowsModel(columns)
        self.pending_view = table_helpers.configure_table(pane, self.pending_model)
        self.pending_view.selectionModel().selectionChanged.connect(
            self._on_pending_selected)
        layout.addWidget(self.pending_view, 1)
        return pane

    def _build_detail(self, parent: QWidget) -> QWidget:
        """选中一条提议之后，这一块回答"我在签什么"。"""
        pane = QWidget(parent)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(QLabel("提议详情", pane))

        self.detail = QPlainTextEdit(pane)
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("在上面选中一条提议，这里显示它的理由与证据")
        layout.addWidget(self.detail, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("签名：", pane))
        self.approver_edit = QLineEdit(pane)
        self.approver_edit.setPlaceholderText("留空取 PLATFORM_USER_NAME 或系统登录名")
        row.addWidget(self.approver_edit, 1)

        self.approve_btn = QPushButton("批准", pane)
        self.approve_btn.clicked.connect(self.approve)
        self.approve_btn.setEnabled(False)
        row.addWidget(self.approve_btn)

        self.reject_btn = QPushButton("拒绝（该点仍需覆盖）", pane)
        self.reject_btn.clicked.connect(self.reject)
        self.reject_btn.setEnabled(False)
        row.addWidget(self.reject_btn)
        layout.addLayout(row)
        return pane

    def _build_approved(self, parent: QWidget) -> QWidget:
        pane = QWidget(parent)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(QLabel("已批准（不计入覆盖率分母）", pane))

        columns = (("exclude_id", "编号", 90, LEFT),
                   ("coverage_point", "覆盖点", 220, LEFT),
                   ("approver", "签名", 110, LEFT),
                   ("audit_hash", "哈希指纹", 300, LEFT),
                   ("updated_at", "签于", 150, LEFT))
        self.approved_model = RowsModel(columns)
        self.approved_view = table_helpers.configure_table(pane, self.approved_model)
        layout.addWidget(self.approved_view, 1)
        return pane

    def create_actions(self) -> List[QAction]:
        refresh = QAction("刷新覆盖率豁免", self.content)
        refresh.triggered.connect(self.refresh)
        return [refresh]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        self.refresh()

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def refresh(self) -> None:
        payload = self.run_tool("coverage.excludes")
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        self.pending = payload.get("pending") or []
        self.approved = payload.get("approved") or []

        self.pending_model.set_rows(self.pending)
        # 已批那一列给哈希留长位 —— 它长得很快，截断了就失去"可核对"的意义
        self.approved_model.set_rows([
            {**row, "audit_hash": str(row.get("audit_hash", ""))[:32]} for row in self.approved
        ])
        self.summary.setText(str(payload.get("summary", "")))
        self._sync_buttons()

    def _selected(self) -> Optional[Dict[str, Any]]:
        """当前选中的那条提议 —— 经代理映射回**源模型**的行号。

        表格是带排序代理的：视图里的行号 ≠ 源模型的行号，不映射就会拿到错的那条
        （排序之后尤其明显）。没选中时 `currentIndex()` 是无效索引，先挡掉。
        """
        view_index = self.pending_view.currentIndex()
        if not view_index.isValid():
            return None
        source_row = table_helpers.source_index(self.pending_view, view_index).row()
        return self.pending_model.row_at(source_row)

    def _on_pending_selected(self) -> None:
        row = self._selected()
        if row is None:
            self.detail.setPlainText("")
            self._sync_buttons()
            return
        self.detail.setPlainText(
            f"覆盖点　{row.get('coverage_point', '')}\n"
            f"类型　　{row.get('type_title', '')}（{row.get('exclude_type', '')}）\n"
            f"编号　　{row.get('exclude_id', '')}\n"
            f"提议于　{row.get('created_at', '')}\n"
            f"\n理由\n{row.get('reason') or '（提议没写理由）'}\n"
            f"\n证据\n{row.get('evidence') or '（没带证据 —— 凭什么说它不可达？）'}\n"
            f"\n批准之后：这个点从**分母**里拿掉，覆盖率会按剩下的点重算。")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        enabled = self._selected() is not None
        self.approve_btn.setEnabled(enabled)
        self.reject_btn.setEnabled(enabled)

    # ════════════════════════════════════════════════════════
    # 签字
    # ════════════════════════════════════════════════════════

    def approve(self) -> None:
        row = self._selected()
        if row is None:
            return
        if not self._confirm(row):
            return
        payload = self.run_tool("coverage.approve_exclude", force=True,
                                exclude_id=row.get("exclude_id", ""),
                                approver=self.approver_edit.text().strip())
        self._after(payload, "批准", row)

    def reject(self) -> None:
        row = self._selected()
        if row is None:
            return
        payload = self.run_tool("coverage.reject_exclude", force=True,
                                exclude_id=row.get("exclude_id", ""),
                                approver=self.approver_edit.text().strip())
        self._after(payload, "拒绝", row)

    def _after(self, payload: Any, action: str, row: Dict[str, Any]) -> None:
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        ok = payload.get("approved") if action == "批准" else payload.get("rejected")
        if not ok:
            self.show_warning(f"{action}失败：{payload.get('error', '未知原因')}")
            return
        who = payload.get("approver", "")
        tail = ""
        if action == "批准" and payload.get("audit_hash"):
            tail = f"　哈希指纹 {str(payload['audit_hash'])[:12]}…"
        self.log(f"{action}豁免 {row.get('exclude_id')}（{who}）{tail}")
        self.set_status(f"已{action} {row.get('exclude_id')}"
                        f"（{row.get('coverage_point')}）　签名 {who}{tail}")
        self.refresh()

    def _confirm(self, row: Dict[str, Any]) -> bool:
        """**按下之前把后果说清楚。** 批准会改动覆盖率分母 —— 那可能正好让一次
        没达标的运行看起来达标了。这句话不说，签字就是走过场。"""
        box = QMessageBox(self.content)
        box.setWindowTitle("批准这条豁免？")
        box.setText(
            f"覆盖点：{row.get('coverage_point', '')}\n"
            f"理由：{row.get('reason') or '（没写理由）'}\n\n"
            "批准之后这个点会从**覆盖率分母**里拿掉 —— 原本算作没覆盖的点不再\n"
            "拉低覆盖率。签核结论可能因此改变。\n\n确认批准吗？")
        yes = box.addButton("批准", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("再想想", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes
