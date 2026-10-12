"""**功能覆盖率** —— 「建模声明的覆盖点 → 实测命中了没有」这条路，一张页看完。

## 为什么单开一页，而不是并进「回归覆盖率」

「回归覆盖率」答的是**回归执行**的问题：哪条用例跑了、它的覆盖率库在哪、点开看。
它的粒度是**用例**。

这一页答的是**建模**的问题：case 模型声明了哪些覆盖点（维度 / 取值 bin / 交叉），
这些点摊成了哪些用例，以及**仿真真的打到了没有**。粒度是**覆盖点**。

两者会被混为一谈，恰恰因为都叫"覆盖率"—— 而 `analysis/coverage.py` 算的
「用例写全了没有」（模型 vs case 表）和 `vcover` 算的「仿真打到了没有」是
**两个完全不同的问题**，前者的 100% 丝毫不保证后者。所以这一页把两者**分列**
而不是揉成一个数：

    覆盖点表：一列是**声明**（模型的 bin），一列是**实测**（vcover 的百分比）

合成一个数就再也分不出"该测的没测"和"测了的没打中"—— 那正是要分的。

## 五张表

  · 功能覆盖点 —— 一个覆盖点一行：维度 / 信号 / 类型 / bin 数 / bin 名单 / 实测%
  · 测试点     —— 模型摊平出来的用例（与回归里跑的那份**同一分母**）
  · 批次 / 种子 —— 打算怎么测够（每批的 test、种子基线、探索条数、合计）
  · 需求追溯   —— 哪条需求被谁验了（覆盖点 / 交叉 / 批次）
  · 链上文件   —— 这条链上的四份文件（模型 / 计划 / 探针 / 实测文本）

第三张表叫「链上文件」而**不叫「资产」**：它们是这条链落在盘上的四份文件，不是
「验证资产」（RTL / UVM 环境 / 参考模型那类设计产物）—— 两个词混用会让人以为
这里是资产台账。

三张表**只看不写**：数据源是运行目录里已落盘的东西，`flow.fcov` 不重跑生成器、
不重跑 `vcover`（那要几分钟，而那份文本就是当时判定用的那一份）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QLabel, QTabWidget, QVBoxLayout, QWidget)

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import CENTER, LEFT, RowsModel
from ...base import ModuleBase

#: 覆盖点表 —— (键, 表头, 列宽, 对齐)。
#:
#: 前两列是**追溯**那一对：`cover_id` 是文档里的编号（`CP_NPU_QUEUE_001`），
#: `requirement` 是需求编号（`REQ-NPU-001`）。「哪条需求被谁验了」要能一眼串起来 ——
#: 生成器派生的 `cp_<信号>` 是给编译器的，拿它跟人对账要换算一次，所以两列都摆。
COVERPOINT_COLUMNS = (
    ("cover_id", "覆盖点编号", 150, LEFT),
    ("requirement", "需求", 110, LEFT),
    ("dimension", "维度", 130, LEFT),
    ("signal", "覆盖点", 140, LEFT),
    ("type", "类型", 80, CENTER),
    ("bin_count", "bin 数", 70, CENTER),
    ("bins", "bin（取自模型声明）", 320, LEFT),
    ("actual", "实测 %", 80, CENTER),
)

TESTPOINT_COLUMNS = (
    ("name", "用例", 220, LEFT),
    ("dimension", "维度", 130, LEFT),
    ("field", "字段", 110, LEFT),
    ("value", "取值", 90, CENTER),
    ("priority", "级别", 60, CENTER),
    ("coverage_bin", "覆盖点", 200, LEFT),
)

#: 批次 / 种子管理表 —— 回答"**打算怎么测够**"。
#:
#: `base/count/explore` 三列拆开展示，是因为"这一批跑够没有"要一眼看出基线几条、
#: 探索几条 —— 合成一个 `total_runs` 就分不出"基线不足"和"探索补的"。
BATCH_COLUMNS = (
    ("theme", "批次", 90, LEFT),
    ("name", "名称", 170, LEFT),
    ("test", "测试", 170, LEFT),
    ("priority", "级别", 60, CENTER),
    ("method", "方法", 60, CENTER),
    ("base", "种子起点", 80, CENTER),
    ("count", "基线", 60, CENTER),
    ("explore", "探索", 60, CENTER),
    ("total_runs", "合计", 60, CENTER),
    ("dimensions", "打的维度", 260, LEFT),
)

#: 需求追溯表 —— 回答"**哪条需求被谁验了**"（§9.1 的"无孤立需求/覆盖点"就看它）。
TRACE_COLUMNS = (
    ("requirement", "需求", 120, LEFT),
    ("coverpoints", "覆盖点", 200, LEFT),
    ("crosses", "交叉覆盖", 200, LEFT),
    ("batches", "批次", 200, LEFT),
)

ASSET_COLUMNS = (
    ("label", "文件", 170, LEFT),
    ("path", "路径", 320, LEFT),
    ("exists", "在", 50, CENTER),
    ("size_kb", "大小 KB", 90, CENTER),
    ("sha256", "sha256", 150, LEFT),
)


class FunctionalCoverageModule(ModuleBase):
    """case 建模对应的功能覆盖率 —— 覆盖点 / 测试点 / 批次 / 追溯 / 链上文件。"""

    HINT = ("数据源是**本次运行目录里已落盘**的文件（case 模型、功能覆盖率计划、"
            "env_cov 注入、vcover 实测文本）—— 不重跑生成器、不重跑 vcover。"
            "「实测 %」为空 = 那一列还没有数据（旧格式的覆盖率文本，或还没跑到"
            "覆盖率收集），**不是 0**。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id = ""
        self.run_dir = ""
        self._coverpoints: List[Dict[str, Any]] = []

    # ════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.summary_label = QLabel("", root)
        self.summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.summary_label)

        self.notes_label = QLabel("", root)
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.notes_label)

        self.tabs = QTabWidget(root)
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_page(COVERPOINT_COLUMNS, "cp"), "功能覆盖点")
        self.tabs.addTab(self._build_page(TESTPOINT_COLUMNS, "tp"), "测试点")
        self.tabs.addTab(self._build_page(BATCH_COLUMNS, "batch"), "批次 / 种子")
        self.tabs.addTab(self._build_page(TRACE_COLUMNS, "trace"), "需求追溯")
        self.tabs.addTab(self._build_page(ASSET_COLUMNS, "asset"), "链上文件")
        layout.addWidget(self.tabs, 1)
        return root

    def _build_page(self, columns, prefix: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        model = RowsModel(columns, page)
        table = table_helpers.configure_table(page, model)
        layout.addWidget(table, 1)
        setattr(self, f"{prefix}_model", model)
        setattr(self, f"{prefix}_table", table)
        return page

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
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self.load(run_id)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def load(self, run_id: str) -> None:
        if not run_id:
            self._clear()
            self.show_info("先在左边「运行历史」里选一次运行。")
            return
        # run_id → 运行目录：走 `pipeline.detail`（与签核判定/产物审查同一套反解），
        # 不自己再写一遍 —— 两份"哪儿找运行"的逻辑迟早会不一致。
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        self.run_dir = str(detail.get("dir", "") or "")
        if not self.run_dir:
            self.show_warning(f"找不到运行 {run_id} 的目录")
            return

        payload = self.run_tool("flow.fcov", run_dir=self.run_dir)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            self._clear()
            return
        self.run_id = run_id
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        self._coverpoints = list(payload.get("coverpoints") or [])
        self.cp_model.set_rows([self._display_cp(r) for r in self._coverpoints],
                               cell_colors=self._unmeasured_colors())
        self.tp_model.set_rows(list(payload.get("testpoints") or []))
        self.batch_model.set_rows(list(payload.get("batches") or []))
        # 没有覆盖点/交叉认领的需求标灰 —— "孤立需求"是签核要拦的，得看得见
        trace = list(payload.get("traceability") or [])
        self.trace_model.set_rows(trace, cell_colors=self._orphan_colors(trace))
        self.asset_model.set_rows(list(payload.get("assets") or []))
        for model, table in ((self.cp_model, self.cp_table),
                             (self.tp_model, self.tp_table),
                             (self.batch_model, self.batch_table),
                             (self.trace_model, self.trace_table),
                             (self.asset_model, self.asset_table)):
            model.apply_column_widths(table)

        self.summary_label.setText(f"{payload.get('run_id', '')}："
                                   f"{payload.get('summary', '')}")
        self.notes_label.setText("　·　".join(payload.get("notes") or []))

    def _display_cp(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """实测那一列：**没测到就给空**，不写 0。

        `0%` 与 `还没测` 是两件事 —— 一个是"打了没中"，一个是"压根没打"。
        显示成同一个数，人就会去查一个不存在的覆盖率问题。
        """
        actual = row.get("actual")
        return {**row, "actual": "" if actual in (None, "") else f"{actual}%"}

    def _unmeasured_colors(self) -> Dict[tuple, QColor]:
        """没有实测数据的那一格标灰 —— 它不是"这一格没内容"，是"还没有数据"。"""
        muted = QColor(theme.current().muted)
        col = {k: i for i, (k, *_r) in enumerate(COVERPOINT_COLUMNS)}
        return {(i, col["actual"]): muted
                for i, r in enumerate(self._coverpoints) if not r.get("measured")}

    def _orphan_colors(self, trace: list) -> Dict[tuple, QColor]:
        """孤立需求整行标灰 —— §9.1 的「无孤立需求」过不了，页面上要当场看出来。"""
        muted = QColor(theme.current().muted)
        return {(i, 0): muted for i, r in enumerate(trace) if not r.get("covered")}

    def _clear(self) -> None:
        self._coverpoints = []
        for attr in ("cp_model", "tp_model", "batch_model", "trace_model",
                     "asset_model"):
            model = getattr(self, attr, None)
            if model is not None:
                model.set_rows([])
        if getattr(self, "summary_label", None):
            self.summary_label.setText("")
        if getattr(self, "notes_label", None):
            self.notes_label.setText("")
