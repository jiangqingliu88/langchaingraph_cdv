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

## 六张表

  · 功能覆盖点 —— 一个覆盖点一行：维度 / 信号 / 类型 / bin 数 / bin 名单 / 实测%
  · 测试点     —— 模型摊平出来的用例（与回归里跑的那份**同一分母**）
  · TP Cov 证据 —— **四层证据按功能契约汇聚**（功能 / 时序 / 数据 / 路径），
                   右栏是选中 TP 的完整证据链（来源、支持用例、不证明什么）
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

import json

from src.workbench.bus import run_id_of

from typing import Any, Dict, List

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QPlainTextEdit,
                               QSplitter, QTabWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

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

#: TP Cov 证据视图 —— **一个功能契约一行**：功能/时序/数据/路径四层状态。
#: 四层是"验证完成"的四类证据，不是"一个用例覆盖了"的并列条件；一个用例可以
#: 只提供其中一部分，多个用例合起来构成完整链（详见 tp_evidence 模块头）。
TP_EVIDENCE_COLUMNS = (
    ("tp_id", "测试点", 210, LEFT),
    ("domain", "域", 80, CENTER),
    ("functional", "功能覆盖", 100, CENTER),
    ("timing", "时序断言", 100, CENTER),
    ("data", "数据比对", 100, CENTER),
    ("path", "路径覆盖", 130, CENTER),
    ("contract_status", "契约状态", 130, CENTER),
    ("signed_off_by", "签核", 180, LEFT),
)

#: Case 关联视图四张表（与 `case_associate_view` 的 builder 同形）。
CASE_COLUMNS = (
    ("name", "用例", 230, LEFT),
    ("feats", "Feat", 130, LEFT),
    ("desc", "说明", 150, LEFT),
    ("coverage", "功能覆盖", 210, LEFT),
    ("sva", "SVA", 200, LEFT),
    ("scoreboard", "Scoreboard", 200, LEFT),
    ("path", "PATH", 180, LEFT),
    ("conclusion", "结论", 200, LEFT),
)
FEATURE_COLUMNS = (
    ("id", "Feat", 120, LEFT),
    ("desc", "描述", 220, LEFT),
    ("functional", "功能覆盖", 100, CENTER),
    ("timing", "SVA", 90, CENTER),
    ("data", "Scoreboard", 110, CENTER),
    ("path", "PATH", 100, CENTER),
    ("status", "状态", 200, LEFT),
)
GAP_COLUMNS = (
    ("type", "类型", 100, LEFT),
    ("item", "项", 240, LEFT),
    ("root", "根因", 320, LEFT),
    ("action", "补齐动作", 300, LEFT),
    ("owner", "责任人", 100, CENTER),
    ("status", "状态", 90, CENTER),
)
#: ── 三集合视图（arch.md：case = groups[] + sva[] + scb[]）──
#:
#: 三张表分开而不是揉成一张：group 看"功能组 × 阶段"，SVA 看"跨拍性质"，
#: SCB 看"值/账本比对"，判据与读者都不同。
GROUP_COLUMNS = (
    ("case_id", "用例", 180, LEFT),
    ("group", "覆盖率组", 140, LEFT),
    ("name", "功能点", 140, LEFT),
    ("coverage_type", "覆盖类型", 100, LEFT),
    ("scope", "作用域（模块/逻辑）", 160, LEFT),
    ("cell", "CELL", 170, LEFT),
    ("functional", "Functional", 95, CENTER),
    ("timing", "Timing", 85, CENTER),
    ("data", "Data", 85, CENTER),
    ("path", "Path", 95, CENTER),
    ("result", "结论", 100, CENTER),
)
SVA_COLUMNS = (
    ("case_id", "用例", 200, LEFT),
    ("id", "SVA", 220, LEFT),
    ("cell", "CELL", 190, LEFT),
    ("fail", "违规", 60, CENTER),
    ("cover_property_hit", "cover_property", 110, CENTER),
    ("status", "状态", 110, CENTER),
)
SCB_COLUMNS = (
    ("case_id", "用例", 200, LEFT),
    ("id", "Scoreboard", 200, LEFT),
    ("cell", "CELL", 190, LEFT),
    ("exec", "exec", 60, CENTER),
    ("matched", "matched", 70, CENTER),
    ("mismatched", "mismatched", 80, CENTER),
    ("evidence_level", "证据粒度", 90, CENTER),
    ("status", "状态", 110, CENTER),
)
CASE_CELL_COLUMNS = (
    ("cell_id", "CELL", 200, LEFT),
    ("cg", "功能组", 150, LEFT),
    ("p", "阶段", 80, CENTER),
    ("color", "颜色", 70, CENTER),
    ("tp_count", "TP 数", 60, CENTER),
    ("declared_cases", "声明用例", 220, LEFT),
    ("observed_cases", "实际用例", 220, LEFT),
)
EVD_COLUMNS = (
    ("evd_id", "EVD", 230, LEFT),
    ("case_id", "CASE", 160, LEFT),
    ("tst_id", "TST", 180, LEFT),
    ("test", "测试", 180, LEFT),
    ("seed", "seed", 70, CENTER),
    ("stage", "阶段", 70, CENTER),
    ("cells", "CELL", 200, LEFT),
    ("legacy", "legacy", 60, CENTER),
)

_STATUS_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "—"}

#: 三集合证据状态 → 颜色（与 `_STATUS_THEME` 同一套主题色）。
_CHECKER_THEME = {"PROVEN": "ok", "PARTIAL": "warning", "PENDING_BACKEND": "muted",
                  "NOT_APPLICABLE": "muted", "NOT_EXECUTED": "error",
                  "MISSING": "error", "UNMAPPED": "error"}
_STATUS_TEXT = {"green": "通过", "yellow": "部分", "red": "缺失", "na": "不适用"}
_STATUS_THEME = {"green": "ok", "yellow": "warning", "red": "error",
                 "na": "muted"}

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
        self.tabs.addTab(self._build_case_evidence_page(), "Case 证据")
        self.tabs.addTab(self._build_page(BATCH_COLUMNS, "batch"), "批次 / 种子")
        self.tabs.addTab(self._build_page(TRACE_COLUMNS, "trace"), "需求追溯")
        self.tabs.addTab(self._build_page(ASSET_COLUMNS, "asset"), "链上文件")
        layout.addWidget(self.tabs, 1)
        return root

    def _build_case_evidence_page(self) -> QWidget:
        """「Case 证据」——四张人类可读表 + TP 明细。

        数据来自 `case_view`（`case_associate_view` builder）：用例 × 证据层、
        功能契约 × 证据层、功能组 × 路径、缺口与豁免。状态用颜色/emoji 标出，
        和 CLI 的 `coverage case-evidence` 是同一份数据。
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        # Case Gate 状态条：blocker / warning / info 计数（数据在 coverage/gates.json）
        self.ce_gate_label = QLabel("", page)
        self.ce_gate_label.setWordWrap(True)
        layout.addWidget(self.ce_gate_label)
        inner = QTabWidget(page)
        inner.setDocumentMode(True)

        self.ce_case_model = RowsModel(CASE_COLUMNS, page)
        self.ce_case_table = table_helpers.configure_table(page, self.ce_case_model)
        inner.addTab(self.ce_case_table, "用例 × 证据层")

        # ── 三集合（arch.md）：Groups / SVA / SCB，一张表一列判据 ──
        self.ce_groups_model = self._rows_tab(inner, page, GROUP_COLUMNS,
                                              "ce_groups", "Groups")
        self.ce_sva_model = self._rows_tab(inner, page, SVA_COLUMNS,
                                           "ce_sva", "SVA")
        self.ce_scb_model = self._rows_tab(inner, page, SCB_COLUMNS,
                                           "ce_scb", "SCB")
        self.ce_cell_model = self._rows_tab(inner, page, CASE_CELL_COLUMNS,
                                            "ce_cell", "Case × CELL")
        self.ce_evd_model = self._rows_tab(inner, page, EVD_COLUMNS,
                                           "ce_evd", "执行证据")

        self.ce_feat_model = RowsModel(FEATURE_COLUMNS, page)
        self.ce_feat_table = table_helpers.configure_table(page, self.ce_feat_model)
        inner.addTab(self.ce_feat_table, "功能契约 × 证据层")

        self.ce_matrix = QTableWidget(0, 1, page)
        self.ce_matrix.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ce_matrix.verticalHeader().setVisible(False)
        self.ce_matrix.horizontalHeader().setStretchLastSection(True)
        inner.addTab(self.ce_matrix, "功能组 × 路径")

        self.ce_gap_model = RowsModel(GAP_COLUMNS, page)
        self.ce_gap_table = table_helpers.configure_table(page, self.ce_gap_model)
        inner.addTab(self.ce_gap_table, "缺口与豁免")

        # 逐 TP 的完整证据链保留为最后一个子页 —— 评审从四张表下钻到单条 TP
        inner.addTab(self._build_tp_evidence_page(), "TP 明细")
        layout.addWidget(inner, 1)
        self._case_view: Dict[str, Any] = {}
        return page

    def _rows_tab(self, inner: QTabWidget, page: QWidget, columns, prefix: str,
                  title: str) -> RowsModel:
        """建一个「模型 + 表格 + Tab」三件套，并挂到 self 上（`<prefix>_model`）。"""
        model = RowsModel(columns, page)
        table = table_helpers.configure_table(page, model)
        inner.addTab(table, title)
        setattr(self, f"{prefix}_model", model)
        setattr(self, f"{prefix}_table", table)
        return model

    def _status_colors(self, rows: List[Dict[str, Any]], columns, keys) -> Dict[tuple, QColor]:
        """把三集合状态列染成主题色（PROVEN 绿 / PARTIAL 黄 / MISSING 红）。"""
        cols = {key: i for i, (key, *_rest) in enumerate(columns)}
        palette = theme.current()
        out: Dict[tuple, QColor] = {}
        for index, row in enumerate(rows):
            for key in keys:
                color = _CHECKER_THEME.get(str(row.get(key)))
                if color and key in cols:
                    out[(index, cols[key])] = QColor(getattr(palette, color))
        return out

    def _fill_case_evidence(self, cv: Dict[str, Any],
                            gates: Dict[str, Any] = None) -> None:
        self._case_view = cv or {}
        self._fill_gate_label(gates or {})
        self._fill_three_sets(cv.get("cases") or [])
        self._fill_cell_and_evd(cv)
        cases = self._case_display_rows(cv.get("cases") or [])
        self.ce_case_model.set_rows(cases, cell_colors=self._case_colors(cases))
        features = self._feature_display_rows(cv.get("features") or [])
        self.ce_feat_model.set_rows(features,
                                    cell_colors=self._feature_colors(features))
        self._fill_matrix(cv.get("matrix") or {})
        self.ce_gap_model.set_rows(list(cv.get("gaps") or []))
        for model, table in ((self.ce_case_model, self.ce_case_table),
                             (self.ce_groups_model, self.ce_groups_table),
                             (self.ce_sva_model, self.ce_sva_table),
                             (self.ce_scb_model, self.ce_scb_table),
                             (self.ce_cell_model, self.ce_cell_table),
                             (self.ce_evd_model, self.ce_evd_table),
                             (self.ce_feat_model, self.ce_feat_table),
                             (self.ce_gap_model, self.ce_gap_table)):
            model.apply_column_widths(table)

    def _fill_gate_label(self, gates: Dict[str, Any]) -> None:
        """Case Gate 状态条 —— 没生成就说没生成，不显示成"通过"。"""
        label = getattr(self, "ce_gate_label", None)
        if label is None:
            return
        verdict = str(gates.get("verdict") or "")
        if not verdict:
            label.setText("Case Gate：还没有门禁产物（跑一轮覆盖率或 "
                          "`vagent coverage case-gate -o <run>`）")
            label.setStyleSheet(f"color: {theme.current().muted};")
            return
        counts = gates.get("counts") or {}
        label.setText(f"Case Gate：{verdict}　·　"
                      f"blocker {counts.get('blocker', 0)}　"
                      f"warning {counts.get('warning', 0)}　"
                      f"info {counts.get('info', 0)}")
        color = (theme.current().warning if verdict == "BLOCKED"
                 else theme.current().ok)
        label.setStyleSheet(f"color: {color};")

    @staticmethod
    def _three_set_rows(cases: List[Dict[str, Any]]) -> tuple:
        """`case_view.cases[]` → `(groups, sva, scb)` 三张平表。"""
        groups: List[Dict[str, Any]] = []
        svas: List[Dict[str, Any]] = []
        scbs: List[Dict[str, Any]] = []
        for case in cases:
            cid = case.get("case_id") or case.get("task")
            for g in case.get("groups_evidence") or []:
                groups.append({
                    "case_id": cid, "group": g.get("group"),
                    # 覆盖描述：功能点 / 覆盖类型 / 作用域 —— 只给 CG 编号看不出
                    # "这条用例证明的是哪块逻辑"。
                    "name": g.get("name") or "",
                    "coverage_type": g.get("coverage_type") or "",
                    "scope": g.get("scope") or "",
                    "cell": g.get("cell"),
                    **{key: str((g.get(key) or {}).get("status") or "")
                       for key in ("functional", "timing", "data", "path")},
                    "result": str(g.get("result") or ""),
                })
            for s in case.get("sva_items") or []:
                svas.append({
                    "case_id": cid, "id": s.get("id"), "cell": s.get("cell"),
                    "fail": s.get("fail"),
                    "cover_property_hit": s.get("cover_property_hit"),
                    "status": str(s.get("status") or ""),
                })
            for s in case.get("scb_items") or []:
                scbs.append({
                    "case_id": cid, "id": s.get("id"), "cell": s.get("cell"),
                    "exec": s.get("exec"), "matched": s.get("matched"),
                    "mismatched": s.get("mismatched"),
                    "evidence_level": str(s.get("evidence_level") or ""),
                    "status": str(s.get("status") or ""),
                })
        return groups, svas, scbs

    def _fill_three_sets(self, cases: List[Dict[str, Any]]) -> None:
        groups, svas, scbs = self._three_set_rows(cases)
        self.ce_groups_model.set_rows(
            groups, cell_colors=self._status_colors(
                groups, GROUP_COLUMNS,
                ("functional", "timing", "data", "path", "result")))
        self.ce_sva_model.set_rows(
            svas, cell_colors=self._status_colors(svas, SVA_COLUMNS, ("status",)))
        self.ce_scb_model.set_rows(
            scbs, cell_colors=self._status_colors(scbs, SCB_COLUMNS, ("status",)))

    def _fill_cell_and_evd(self, cv: Dict[str, Any]) -> None:
        cell_rows = [{
            "cell_id": r.get("cell_id"), "cg": r.get("cg"), "p": r.get("p"),
            "color": f"{_STATUS_EMOJI.get(r.get('color'), '?')} "
                     f"{_STATUS_TEXT.get(r.get('color'), '')}",
            "tp_count": r.get("tp_count"),
            "declared_cases": "、".join(r.get("declared_cases") or []),
            "observed_cases": "、".join(r.get("observed_cases") or []),
            "_color": r.get("color"),
        } for r in ((cv.get("case_cell") or {}).get("rows") or [])]
        cols = {key: i for i, (key, *_rest) in enumerate(CASE_CELL_COLUMNS)}
        palette = theme.current()
        colors = {(i, cols["color"]): QColor(getattr(palette, theme_key))
                  for i, r in enumerate(cell_rows)
                  for theme_key in [_STATUS_THEME.get(str(r.get("_color")))]
                  if theme_key}
        self.ce_cell_model.set_rows(cell_rows, cell_colors=colors)

        evd_rows = [{
            "evd_id": r.get("evd_id"), "case_id": r.get("case_id") or "—",
            "tst_id": r.get("tst_id"), "test": r.get("test"), "seed": r.get("seed"),
            "stage": r.get("stage"), "cells": "、".join(r.get("cells") or []),
            "legacy": "是" if r.get("legacy") else "否",
        } for r in (cv.get("case_runs") or [])]
        self.ce_evd_model.set_rows(evd_rows)

    @staticmethod
    def _case_display_rows(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for c in cases:
            out.append({
                "name": c.get("name"),
                "feats": "、".join(c.get("feats") or []),
                "desc": c.get("desc"),
                **{key: f"{_STATUS_EMOJI.get((c.get(key) or {}).get('status'), '?')} "
                        f"{(c.get(key) or {}).get('detail', '')}"
                   for key in ("coverage", "sva", "scoreboard", "path")},
                **{f"{key}_status": (c.get(key) or {}).get("status")
                   for key in ("coverage", "sva", "scoreboard", "path")},
                "conclusion": c.get("conclusion"),
            })
        return out

    def _case_colors(self, rows: List[Dict[str, Any]]) -> Dict[tuple, QColor]:
        pairs = tuple((key, f"{key}_status")
                      for key in ("coverage", "sva", "scoreboard", "path"))
        cols = {key: i for i, (key, *_rest) in enumerate(CASE_COLUMNS)}
        palette = theme.current()
        out = {}
        for index, row in enumerate(rows):
            for key, status_key in pairs:
                color = _STATUS_THEME.get(str(row.get(status_key)))
                if color:
                    out[(index, cols[key])] = QColor(getattr(palette, color))
        return out

    @staticmethod
    def _feature_display_rows(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for f in features:
            row = {"id": f.get("id"), "desc": f.get("desc"), "status": f.get("status")}
            for key in ("functional", "timing", "data", "path"):
                status = f.get(key)
                row[key] = f"{_STATUS_EMOJI.get(status, '?')} {_STATUS_TEXT.get(status, '')}"
                row[f"{key}_status"] = status
            out.append(row)
        return out

    def _feature_colors(self, rows: List[Dict[str, Any]]) -> Dict[tuple, QColor]:
        cols = {key: i for i, (key, *_rest) in enumerate(FEATURE_COLUMNS)}
        palette = theme.current()
        out = {}
        for index, row in enumerate(rows):
            for key in ("functional", "timing", "data", "path"):
                color = _STATUS_THEME.get(str(row.get(f"{key}_status")))
                if color:
                    out[(index, cols[key])] = QColor(getattr(palette, color))
        return out

    def _fill_matrix(self, matrix: Dict[str, Any]) -> None:
        groups = list(matrix.get("groups") or [])
        rows = list(matrix.get("rows") or [])
        palette = theme.current()
        self.ce_matrix.clear()
        self.ce_matrix.setColumnCount(len(groups) + 1)
        self.ce_matrix.setRowCount(len(rows))
        self.ce_matrix.setHorizontalHeaderLabels(["路径"] + groups)
        for i, row in enumerate(rows):
            self.ce_matrix.setItem(i, 0, QTableWidgetItem(str(row.get("path") or "")))
            cells = row.get("cells") or {}
            for j, group in enumerate(groups, start=1):
                status = str(cells.get(group, "na"))
                item = QTableWidgetItem(
                    f"{_STATUS_EMOJI.get(status, '?')} {_STATUS_TEXT.get(status, '')}")
                color = getattr(palette, _STATUS_THEME.get(status, "muted"))
                item.setBackground(QColor(color))
                self.ce_matrix.setItem(i, j, item)
        self.ce_matrix.resizeColumnsToContents()

    def _build_tp_evidence_page(self) -> QWidget:
        """「TP Cov 证据」—— 左表四层状态，右栏该 TP 的完整证据 JSON。

        右栏不是重复左表，而是**评审要追溯的那个东西**：每一层的来源
        （bin/断言/SCB/PATH 序列）、支持它的用例、不证明什么。点哪行看哪行。
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        splitter = QSplitter(Qt.Orientation.Horizontal, page)
        self.te_model = RowsModel(TP_EVIDENCE_COLUMNS, page)
        self.te_table = table_helpers.configure_table(page, self.te_model)
        self.te_table.selectionModel().currentRowChanged.connect(
            self._on_tp_evidence_row)
        splitter.addWidget(self.te_table)
        self.te_detail = QPlainTextEdit()
        self.te_detail.setReadOnly(True)
        self.te_detail.setFont(theme.mono_font())
        splitter.addWidget(self.te_detail)
        splitter.setSizes([900, 520])
        layout.addWidget(splitter, 1)
        self._tp_evidence: Dict[str, Any] = {}
        return page

    def _on_tp_evidence_row(self, current: QModelIndex,
                            _previous: QModelIndex) -> None:
        if not current.isValid():
            self.te_detail.clear()
            return
        row = table_helpers.source_index(self.te_table, current).row()
        tps = (self._tp_evidence or {}).get("tps") or []
        if not 0 <= row < len(tps):
            self.te_detail.clear()
            return
        self.te_detail.setPlainText(
            json.dumps(tps[row], ensure_ascii=False, indent=2))

    def _tp_evidence_rows(self) -> List[Dict[str, Any]]:
        out = []
        for tp in (self._tp_evidence or {}).get("tps") or []:
            layers = tp.get("evidence_layers") or {}
            out.append({
                "tp_id": tp.get("tp_id"),
                "domain": tp.get("domain"),
                **{key: (layers.get(key) or {}).get("status")
                   for key in ("functional", "timing", "data", "path")},
                "contract_status": tp.get("contract_status"),
                "signed_off_by": tp.get("signed_off_by") or "",
            })
        return out

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
        run_id = run_id_of(payload)
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
        self._tp_evidence = payload.get("tp_evidence") or {}
        self.te_model.set_rows(self._tp_evidence_rows())
        self._fill_case_evidence(payload.get("case_view") or {},
                                 payload.get("case_gates") or {})
        self.batch_model.set_rows(list(payload.get("batches") or []))
        # 没有覆盖点/交叉认领的需求标灰 —— "孤立需求"是签核要拦的，得看得见
        trace = list(payload.get("traceability") or [])
        self.trace_model.set_rows(trace, cell_colors=self._orphan_colors(trace))
        self.asset_model.set_rows(list(payload.get("assets") or []))
        for model, table in ((self.cp_model, self.cp_table),
                             (self.tp_model, self.tp_table),
                             (self.te_model, self.te_table),
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
        self._tp_evidence = {}
        self._case_view = {}
        for attr in ("cp_model", "tp_model", "te_model", "ce_case_model",
                     "ce_groups_model", "ce_sva_model", "ce_scb_model",
                     "ce_cell_model", "ce_evd_model",
                     "ce_feat_model", "ce_gap_model", "batch_model",
                     "trace_model", "asset_model"):
            model = getattr(self, attr, None)
            if model is not None:
                model.set_rows([])
        if getattr(self, "ce_matrix", None):
            self.ce_matrix.clear()
            self.ce_matrix.setRowCount(0)
        if getattr(self, "te_detail", None):
            self.te_detail.clear()
        if getattr(self, "summary_label", None):
            self.summary_label.setText("")
        if getattr(self, "notes_label", None):
            self.notes_label.setText("")
