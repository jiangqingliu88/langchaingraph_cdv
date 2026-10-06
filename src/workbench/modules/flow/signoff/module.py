"""签核判定 —— 一次运行到底能不能签核。

这是本项目的**第一差异化**在界面上的落点。它回答一个问题，用两个来源：

  · **四道门禁**（`report.json`，audit agent 写）—— 该跑的都跑了吗：
    RTL 在不在、是不是占位、回归全不全过、覆盖率收没收、参考模型真不真。
  · **六层证据链**（`docs/evidence_chain.json`，finalize 写）—— 证据链闭合了吗：
    需求层 / 设计层 / 验证层 / 执行层 / 功能覆盖层 / 签核层，逐层几个检查项通过。

**两个都看**：门禁问"跑没跑"，证据链问"闭没闭"。顶部那行大字给总判定——
**两者都通过才算可签核**；任一缺失都如实说"未知"，不因为文件还没生成就报绿。

订阅 `run.selected`：`runs` 模块里选一次运行，这里跟着切（与 `evidence` 同一机制）。

> 治理状态（预算 / 熔断 / 干预）**刻意不在这里**：`Governor` 是运行线程里
> `Runtime` 的字段（`execution.py:606`），既不落盘也无访问口。拿不到真数据就
> 不画 —— 见 docs/design/agent_gui_business_architecture.md §1.3。
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

#: 门禁表列 —— (键, 表头, 列宽, 对齐)
GATE_COLUMNS = (
    ("title", "门禁", 190, LEFT),
    ("result", "结果", 70, CENTER),
    ("detail", "说明", 460, LEFT),
)
#: 证据链表列
CHAIN_COLUMNS = (
    ("title", "证据层", 120, LEFT),
    ("progress", "通过", 70, CENTER),
    ("description", "说明", 240, LEFT),
    ("checks", "检查项", 480, LEFT),
)


class SignoffModule(ModuleBase):
    """一次运行的签核判定（门禁 + 证据链）。"""

    HINT = ("选一次运行（左边「运行历史」），这里显示它能不能签核："
            "上面是 audit 的四道门禁，下面是六层证据链的逐层闭合情况。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""

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

        self.verdict_label = QLabel("（还没选中运行）", root)
        self.verdict_label.setWordWrap(True)
        layout.addWidget(self.verdict_label)

        splitter = QSplitter(Qt.Orientation.Vertical, root)

        gate_page = QWidget(splitter)
        gate_layout = QVBoxLayout(gate_page)
        gate_layout.setContentsMargins(2, 2, 2, 2)
        gate_layout.setSpacing(2)
        gate_layout.addWidget(self._section("签核门禁（audit · report.json）", gate_page))
        self.gate_model = RowsModel(GATE_COLUMNS, gate_page)
        self.gate_table = table_helpers.configure_table(gate_page, self.gate_model)
        gate_layout.addWidget(self.gate_table, 1)
        splitter.addWidget(gate_page)

        chain_page = QWidget(splitter)
        chain_layout = QVBoxLayout(chain_page)
        chain_layout.setContentsMargins(2, 2, 2, 2)
        chain_layout.setSpacing(2)
        chain_layout.addWidget(self._section("领域证据链（finalize · docs/evidence_chain.json）", chain_page))
        self.chain_model = RowsModel(CHAIN_COLUMNS, chain_page)
        self.chain_table = table_helpers.configure_table(chain_page, self.chain_model)
        chain_layout.addWidget(self.chain_table, 1)
        splitter.addWidget(chain_page)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.count_label = QLabel("", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)
        return root

    @staticmethod
    def _section(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setStyleSheet(f"color: {theme.current().muted};")
        return label

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新签核判定", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者。"""
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
        payload = self.run_tool("flow.signoff", quiet=True, run_dir=run_dir)
        if not isinstance(payload, dict):
            return
        if self.report_payload_error(payload):
            self._clear()
            return

        self.run_id = run_id
        self._fill_header(payload)
        self._fill_gates(payload.get("gates") or {})
        self._fill_chain(payload.get("chain") or {})

    def _fill_header(self, payload: Dict[str, Any]) -> None:
        verdict = payload.get("verdict") or "（无 verdict）"
        self.verdict_label.setText(payload.get("summary", ""))

        ok = (payload.get("gates", {}).get("available")
              and all(g["passed"] for g in payload["gates"]["rows"])
              and payload.get("chain", {}).get("signoff_ready"))
        palette = theme.current()
        color = palette.ok if ok else (palette.error if verdict == "NEEDS_FIX" else palette.warning)
        self.verdict_label.setStyleSheet(f"color: {color}; font-weight: bold;")

        rate = payload.get("pass_rate") or "?"
        cov = payload.get("coverage")
        cov_text = f"{cov:g}%" if isinstance(cov, (int, float)) else "?"
        self.count_label.setText(
            f"{self.run_id}　verdict={verdict}　"
            f"signoff_status={payload.get('signoff_status') or '?'}　"
            f"回归 {rate}　覆盖率 {cov_text}")

    def _fill_gates(self, gates: Dict[str, Any]) -> None:
        if not gates.get("available"):
            self.gate_model.set_rows([{"title": gates.get("note", "（无）"),
                                       "result": "", "detail": ""}])
            return
        rows: List[Dict[str, Any]] = []
        colors: Dict[int, QColor] = {}
        for index, gate in enumerate(gates.get("rows") or []):
            rows.append({"title": gate["title"],
                         "result": "通过" if gate["passed"] else "不通过",
                         "detail": gate.get("detail", "")})
            colors[index] = _color(gate["passed"])
        self.gate_model.set_rows(rows, row_colors=colors)

    def _fill_chain(self, chain: Dict[str, Any]) -> None:
        if not chain.get("available"):
            self.chain_model.set_rows([{"title": chain.get("note", "（无）"),
                                        "progress": "", "description": "", "checks": ""}])
            return
        rows: List[Dict[str, Any]] = []
        colors: Dict[int, QColor] = {}
        for index, layer in enumerate(chain.get("layers") or []):
            fully = layer["total"] > 0 and layer["passed"] == layer["total"]
            rows.append({
                "title": layer["title"],
                "progress": f"{layer['passed']}/{layer['total']}",
                "description": layer.get("description", ""),
                "checks": "、".join(
                    f"{c['title']}{'✓' if c['passed'] else '✗'}"
                    for c in layer.get("checks") or []),
            })
            colors[index] = _color(fully)
        self.chain_model.set_rows(rows, row_colors=colors)

    def _clear(self) -> None:
        self.run_id = ""
        self.verdict_label.setText("（还没选中运行）")
        self.verdict_label.setStyleSheet("")
        self.gate_model.set_rows([])
        self.chain_model.set_rows([])
        self.count_label.setText("")


def _color(passed: bool) -> QColor:
    """通过绿、不通过红 —— 与全局「颜色只是帮助扫读」一致，文字仍承担信息。"""
    palette = theme.current()
    return QColor(palette.ok if passed else palette.error)
