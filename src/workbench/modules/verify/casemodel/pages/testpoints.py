"""测试点 IR —— 用例建模到执行/覆盖/签核的那根轴。

## 这页回答什么

「这份 case 模型最终**会变成哪些测试点**、每条测试点**怎么实现**、这次运行
**打中了没有**」。它是 Case 属性表与回归/覆盖率之间的那张对照表：

    tp_id                TP-NPU-D_TYPE-MAC
    维度=取值            D_type = MAC
    实现方式             stimulus: instr_type = 0
    覆盖仓               cp_instr_type.mac
    分级                 p0
    状态                 HIT（来自 coverage/tp_matrix.json）
    需求                 REQ-NPU-002

## 数据从哪来

- **列表**：对当前编辑器里的模型跑框架流水线（`plan.build_bundle`）——
  所以未保存的改动也能立刻看到会生成什么；
- **状态列**：只在「运行历史」里选中某次运行时才有 —— 读那次运行的
  `coverage/tp_matrix.json`。没选运行就留空，**不编一个状态出来**。

观测型维度（`observe`）没有激励通道，状态按 `OBSERVED / UNOBSERVED` 显示，
不混进可激励命中率 —— 那是两种不同的缺口。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QLabel, QPlainTextEdit, QSplitter, QVBoxLayout,
                               QWidget)

from src.tools.generation.casemodel_tools.framework import ascii_slug
from src.tools.generation.casemodel_tools.plan import build_bundle
from src.workbench.ui import theme
from src.workbench.ui.models import CENTER, LEFT, RowsModel

from ..page import Page

_HINT = ("一条测试点 = 一个取值点 + 实现方式 + 覆盖仓 + 执行计划。"
         "实现方式是 stimulus 的会生成属性 test 并约束事务；observe 的没有"
         "输入引脚，只能按 OBSERVE_ONLY 统计。")

_COLUMNS = (
    ("tp_id", "测试点", 200, LEFT),
    ("value", "维度 = 取值", 160, LEFT),
    ("realization", "实现方式", 190, LEFT),
    ("bin", "覆盖仓", 200, LEFT),
    ("stage", "分级", 55, CENTER),
    ("status", "状态", 100, LEFT),
    ("hits", "命中", 55, CENTER),
    ("requirement", "需求", 120, LEFT),
)

_STATUS_COLORS = {
    "HIT": "ok", "MISS": "error", "OBSERVED": "accent",
    "UNOBSERVED": "warning", "UNMAPPED": "error",
}


class TestPointsPage(Page):
    TITLE = "测试点"
    HINT = _HINT

    def build(self) -> None:
        outer = self.frame()
        self.hint = self.hint_label()
        outer.addWidget(self.hint)

        self.summary = QLabel("（还没有可分析的模型）")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color: {theme.current().muted};")
        outer.addWidget(self.summary)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self.model = RowsModel(_COLUMNS, self)
        self.view = self.make_table(self.model)
        self.view.selectionModel().currentRowChanged.connect(self._on_row)
        splitter.addWidget(self.view)

        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(self.section_label("测试点详情（IR + 本次运行命中）"))
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(theme.mono_font())
        detail_layout.addWidget(self.detail, 1)
        splitter.addWidget(detail_box)

        splitter.setSizes([980, 460])
        outer.addWidget(splitter, 1)

        self._tps: List[Any] = []
        self._matrix: Dict[str, Dict[str, Any]] = {}

    # ── 数据 ──

    def refresh(self, result) -> None:
        model = result.model
        env_name, module_name = self._names(model)
        try:
            bundle = build_bundle(model, env_name=env_name, module_name=module_name)
        except Exception as exc:                       # noqa: BLE001 页面不该炸窗口
            self._tps = []
            self.model.set_rows([])
            self.summary.setText(f"测试点生成失败：{exc}")
            self.detail.clear()
            return

        self._tps = list(bundle.testpoints)
        self._matrix = self._load_matrix()
        rows: List[Dict[str, Any]] = []
        colors: Dict[int, QColor] = {}
        palette = theme.current()
        for i, tp in enumerate(self._tps):
            status_row = self._matrix.get(tp.tp_id) or {}
            status = str(status_row.get("status") or "")
            rows.append({
                "tp_id": tp.tp_id,
                "value": f"{tp.dimension} = {tp.value}",
                "realization": _realization_text(tp),
                "bin": f"{tp.coverpoint}.{tp.bin}" if tp.bin else tp.coverpoint,
                "stage": tp.execution.stage,
                "status": status or "—",
                "hits": status_row.get("hits", "") if status else "",
                "requirement": tp.requirement,
            })
            color = _STATUS_COLORS.get(status, "")
            if color:
                colors[i] = QColor(getattr(palette, color))
            elif not status:
                colors[i] = QColor(palette.muted)

        self.model.set_rows(rows, row_colors=colors)
        self.summary.setText(self._summary_text(bundle))

    def clear(self) -> None:
        self._tps = []
        self._matrix = {}
        self.model.set_rows([])
        self.detail.clear()
        self.summary.setText("（还没有可分析的模型）")

    # ── 详情 ──

    def _on_row(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.detail.clear()
            return
        source = self.source_index(self.view, current)
        row = source.row()
        if not 0 <= row < len(self._tps):
            self.detail.clear()
            return
        tp = self._tps[row]
        lines = [json.dumps(tp.to_dict(), ensure_ascii=False, indent=2)]
        status = self._matrix.get(tp.tp_id)
        if status:
            lines += ["", "本次运行：",
                      json.dumps(status, ensure_ascii=False, indent=2)]
        else:
            lines += ["", "本次运行：未选中运行，或该运行没有 coverage/tp_matrix.json"]
        self.detail.setPlainText("\n".join(lines))

    # ── 辅助 ──

    def _names(self, model) -> Tuple[str, str]:
        """环境名 / 模块名 —— 优先从**选中的那次运行**读 env.yaml。"""
        run_dir = getattr(self.module, "_run_dir", "")
        env_name = ""
        if run_dir:
            p = Path(run_dir) / "inputs" / "yaml" / "uvm" / "env.yaml"
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8",
                                                 errors="replace")) or {}
                env_name = str((doc.get("environment") or {}).get("name") or "")
            except (OSError, ValueError):
                env_name = ""
        if env_name.endswith("_env"):
            module_name = env_name[:-len("_env")]
        else:
            module_name = ascii_slug(getattr(model, "object_code", "")
                                     or model.object) or "dut"
            env_name = env_name or f"{module_name}_env"
        return env_name, module_name

    def _load_matrix(self) -> Dict[str, Dict[str, Any]]:
        run_dir = getattr(self.module, "_run_dir", "")
        if not run_dir:
            return {}
        p = Path(run_dir) / "coverage" / "tp_matrix.json"
        try:
            doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return {}
        return {str(r.get("tp_id")): r for r in (doc.get("rows") or [])
                if isinstance(r, dict) and r.get("tp_id")}

    def _summary_text(self, bundle) -> str:
        manifest = bundle.manifest()
        summary = manifest.get("summary") or {}
        kinds = " / ".join(f"{k} {v}" for k, v in sorted((summary.get("by_kind") or {}).items()))
        stages = " / ".join(f"{k} {v}" for k, v in sorted((summary.get("by_stage") or {}).items()))
        digest = ((manifest.get("artifacts") or {}).get("testpoints_yaml") or {}).get("sha256", "")
        text = (f"框架 {manifest.get('framework')} v{manifest.get('version')} · "
                f"{' → '.join(s['name'] for s in manifest.get('stages') or [])}　"
                f"{summary.get('count', 0)} 条测试点（{kinds}）· 分级 {stages}　"
                f"IR {digest[:12]}…")
        if self._matrix:
            counts: Dict[str, int] = {}
            for r in self._matrix.values():
                key = str(r.get("status") or "")
                counts[key] = counts.get(key, 0) + 1
            bits = " / ".join(f"{k} {v}" for k, v in sorted(counts.items()) if k)
            text += f"　本次运行：{bits}"
        else:
            text += "　（未选中运行 —— 状态列为空）"
        return text


def _realization_text(tp) -> str:
    r = tp.realization
    if r.kind == "stimulus":
        return f"stimulus: {r.field} = {r.value}"
    if r.kind == "sequence":
        return f"sequence: {r.sequence}"
    return r.kind
