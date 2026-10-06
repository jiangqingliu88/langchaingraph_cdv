"""运行对比 —— 「这次比上次差在哪、是谁改坏的」。

**为什么要有这一页**：单次报告只告诉你**这次**的结论。而"修好一个、改坏三个"
这种事只有**两次并排**才看得见 —— 它恰好是「可审计」这条定位最贵的那个问题
（谁改坏了 / 什么时候开始坏的），而数据早就落盘了（每次运行都留了报告、回归
产物、覆盖率），所以这一页**不重跑、不碰进程，只做对齐**。

和 `refactor_guard` 是同一个故事的**人机两面**：守卫是机器在改完 RTL 之后自动
比对"原先通过的现在还过吗"；这一页是人手动挑两次运行做同样的事。

取向：**变坏优先**。`newly_failing`（基线通过、现在没通过）排在表顶，并在顶部
单独给一个数 —— 那是这一页存在的理由，不该混在一堆变化里。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

#: 变化类别 → （中文名, 用什么颜色）。**变坏用 error、修复用 ok** —— 一眼分得出
CHANGE_KINDS = (
    ("newly_failing", "变坏", "error"),
    ("fixed", "修复", "ok"),
    ("added", "新增用例", "muted"),
    ("removed", "消失用例", "muted"),
)
CHANGE_COLUMNS = (
    ("kind", "变化", 90, CENTER),
    ("case", "用例", 420, LEFT),
    ("baseline", "基线", 110, CENTER),
    ("current", "当前", 110, CENTER),
)
COV_COLUMNS = (
    ("label", "覆盖率", 140, LEFT),
    ("baseline", "基线", 100, CENTER),
    ("current", "对比", 100, CENTER),
    ("delta", "变化", 100, CENTER),
)


class CompareModule(ModuleBase):
    """两次运行的逐项对比。"""

    HINT = ("挑两次运行做对比：**变坏的用例**排在最上面 —— 那是「谁改坏了」的直接"
            "答案。默认拿当前选中的运行和它前面那次比。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""            # 当前（对比侧）
        self._runs: List[Dict[str, Any]] = []

    # ════════════════════════════════════════════════════════
    # 界面
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

        # 两个下拉：基线 / 对比。放在一行，一眼看出"谁跟谁比"
        picks = QHBoxLayout()
        picks.setContentsMargins(0, 0, 0, 0)
        self.base_box = QComboBox(root)
        self.cur_box = QComboBox(root)
        for label, box in (("基线：", self.base_box), ("对比：", self.cur_box)):
            picks.addWidget(QLabel(label, root))
            box.setMinimumWidth(240)
            box.currentIndexChanged.connect(self._reload)
            picks.addWidget(box, 1)
        picks.addStretch(1)
        layout.addLayout(picks)

        self.headline = QLabel("", root)
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)

        self.case_model = RowsModel(CHANGE_COLUMNS, root)
        self.case_table = table_helpers.configure_table(root, self.case_model)
        self.cov_model = RowsModel(COV_COLUMNS, root)
        self.cov_table = table_helpers.configure_table(root, self.cov_model)

        layout.addWidget(QLabel("用例变化（变坏在最上面）", root))
        layout.addWidget(self.case_table, 3)
        layout.addWidget(QLabel("覆盖率", root))
        layout.addWidget(self.cov_table, 1)

        self.note_label = QLabel("", root)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.note_label)
        return root

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新运行列表", self.content)
        action.triggered.connect(lambda: self._load_runs(select=self.run_id))
        return [action]

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        self._load_runs(select=self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者 —— 选中的那次当"对比侧"，基线自动取它前一次。"""
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self._load_runs(select=run_id)

    def _load_runs(self, select: str = "") -> None:
        payload = self.run_tool("pipeline.runs", quiet=True)
        runs = payload if isinstance(payload, list) else (payload or {}).get("runs") or []
        self._runs = [r for r in runs if isinstance(r, dict) and r.get("run_id")]
        if not self._runs:
            self.headline.setText("还没有运行记录 —— 先在「验证流程」里起一次")
            self._clear_tables()
            return
        # 列表是**新到旧**（运行历史页同款口径），下拉里按时间正序更好读
        ordered = list(reversed(self._runs))
        for box in (self.base_box, self.cur_box):
            box.blockSignals(True)
            box.clear()
            for run in ordered:
                box.addItem(str(run["run_id"]), str(run["run_id"]))
            box.blockSignals(False)
        self.run_id = select or self.run_id or str(ordered[-1]["run_id"])
        ids = [str(r["run_id"]) for r in ordered]
        cur_index = ids.index(self.run_id) if self.run_id in ids else len(ids) - 1
        self.cur_box.setCurrentIndex(cur_index)
        self.base_box.setCurrentIndex(max(0, cur_index - 1))
        self._reload()

    def _reload(self) -> None:
        base = self.base_box.currentData()
        cur = self.cur_box.currentData()
        if not base or not cur:
            return
        payload = self.run_tool("flow.compare", quiet=True, baseline=base, current=cur)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            self._clear_tables()
            return
        self._fill(payload)

    # ════════════════════════════════════════════════════════
    # 渲染
    # ════════════════════════════════════════════════════════

    def _fill(self, payload: Dict[str, Any]) -> None:
        summary = payload.get("summary") or {}
        bad = int(summary.get("newly_failing") or 0)
        fixed = int(summary.get("fixed") or 0)
        delta = summary.get("coverage_delta")
        delta_txt = "—" if delta is None else f"{delta:+.1f}%"
        color = theme.current().error if bad else theme.current().ok
        self.headline.setText(
            f"<span style='color:{color}'><b>变坏 {bad}</b></span>　"
            f"修复 {fixed}　覆盖率 {delta_txt}　"
            f"判定：{payload['baseline'].get('verdict') or '-'} → "
            f"{payload['current'].get('verdict') or '-'}")

        cases = payload.get("cases") or {}
        b_cases = payload["baseline"].get("cases") or {}
        c_cases = payload["current"].get("cases") or {}
        rows, colors = [], {}
        for kind, label, tone in CHANGE_KINDS:            # 顺序即优先级：变坏在最前
            for name in cases.get(kind) or []:
                colors[len(rows)] = _tone_color(tone)
                rows.append({"kind": label, "case": name,
                             "baseline": b_cases.get(name, "-"),
                             "current": c_cases.get(name, "-")})
        self.case_model.set_rows(rows, row_colors=colors)

        cov_rows, cov_colors = [], {}
        for value in (payload.get("coverage") or {}).values():
            delta = value.get("delta")
            cov_colors[len(cov_rows)] = _tone_color(_delta_tone(delta))
            cov_rows.append({"label": value["label"],
                             "baseline": _pct(value["baseline"]),
                             "current": _pct(value["current"]),
                             "delta": "—" if delta is None else f"{delta:+.1f}"})
        self.cov_model.set_rows(cov_rows, row_colors=cov_colors)
        self.note_label.setText("　".join(str(n) for n in (payload.get("notes") or [])))

    def _clear_tables(self) -> None:
        self.case_model.set_rows([])
        self.cov_model.set_rows([])
        self.note_label.setText("")


def _pct(value: Any) -> str:
    return "—" if value is None else f"{value}%"


def _tone_color(tone: str) -> QColor:
    """语义色 → 当前主题的颜色（**从主题取，不写死 hex**）。"""
    palette = theme.current()
    return QColor({"error": palette.error, "ok": palette.ok}.get(tone, palette.muted))


def _delta_tone(delta: Any) -> str:
    """变好/变坏/没动 —— 颜色跟着走（涨=ok、跌=error、持平=muted）。"""
    if delta is None:
        return "muted"
    if delta > 0:
        return "ok"
    if delta < 0:
        return "error"
    return "muted"
