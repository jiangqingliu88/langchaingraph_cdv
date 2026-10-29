"""签核判定 —— 一次运行到底能不能签核。

这是本项目的**第一差异化**在界面上的落点。它回答一个问题，用两个来源：

  · **四道门禁**（`report.json`，audit agent 写）—— 该跑的都跑了吗：
    RTL 在不在、是不是占位、回归全不全过、覆盖率收没收、参考模型真不真。
  · **六层证据链**（`docs/evidence_chain.json`，finalize 写）—— 证据链闭合了吗：
    需求层 / 设计层 / 验证层 / 执行层 / 功能覆盖层 / 签核层，逐层几个检查项通过。

**两个都看**：门禁问"跑没跑"，证据链问"闭没闭"。顶部那行大字给总判定——
**两者都通过才算可签核**；任一缺失都如实说"未知"，不因为文件还没生成就报绿。

第三块是**合同级证据包 v2**（`signoff_evidence/manifest.json`）：哈希、caveat
码、计划/单测覆盖率、种子多样性、参考模型/基线、审批历史、Freeze 状态与
离线回放命令。老 run 没有 v2 时如实标"未生成"，不拿 v1 冒充。

订阅 `run.selected`：`runs` 模块里选一次运行，这里跟着切（与 `evidence` 同一机制）。

> 治理状态（预算 / 熔断 / 干预）**刻意不在这里**：`Governor` 是运行线程里
> `Runtime` 的字段（`execution.py:606`），既不落盘也无访问口。拿不到真数据就
> 不画 —— 见 docs/design/agent_gui_business_architecture.md §1.3。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QApplication, QLabel, QSplitter, QVBoxLayout,
                               QWidget)

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
            "上面是 audit 的门禁，中间是六层证据链，下面是证据包 v2 "
            "（哈希 / caveat / 覆盖率 / 种子 / 审批 / Freeze / 回放）。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""
        self.evidence_dir: str = ""
        self.replay_cmd: str = ""

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

        # 测试点口径：**签核按测试点说话，不只看百分比**。
        # 「可激励命中 / 观测到达 / 未命中」三栏分开 —— 观测型不是缺口。
        self.tp_label = QLabel("", root)
        self.tp_label.setWordWrap(True)
        self.tp_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.tp_label)

        # 软缺口：硬门禁过了、但"绿得不够实在"的地方（约束部分生效、TP 未命中等）
        self.caveat_label = QLabel("", root)
        self.caveat_label.setWordWrap(True)
        self.caveat_label.setStyleSheet(f"color: {theme.current().warning};")
        layout.addWidget(self.caveat_label)

        self.count_label = QLabel("", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)

        # 合同级证据包（v2）：哈希 / caveat / 种子 / 基线 / 审批 / Freeze / 回放
        self.evidence_label = QLabel("", root)
        self.evidence_label.setWordWrap(True)
        self.evidence_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.evidence_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.evidence_label)
        return root

    @staticmethod
    def _section(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setStyleSheet(f"color: {theme.current().muted};")
        return label

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新签核判定", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        copy_dir = QAction("复制证据包路径", self.content)
        copy_dir.triggered.connect(
            lambda: QApplication.clipboard().setText(self.evidence_dir))
        copy_replay = QAction("复制回放命令", self.content)
        copy_replay.triggered.connect(
            lambda: QApplication.clipboard().setText(self.replay_cmd))
        return [action, copy_dir, copy_replay]

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
        self._fill_testpoints(payload.get("testpoints") or {},
                              payload.get("caveats") or [])
        self._fill_evidence(payload.get("evidence") or {},
                            payload.get("run_dir") or "")

    def _fill_testpoints(self, tp: Dict[str, Any], caveats: List[str]) -> None:
        """测试点口径 + 软缺口。

        `drivable_hit / drivable` 是**可激励**命中率；观测型单列
        `observed / observe_only` —— 混在一起会让"不可激励"看起来像"没测"。
        """
        if tp:
            self.tp_label.setText(
                f"测试点：可激励 {tp.get('drivable_hit', 0)}/{tp.get('drivable', 0)}"
                f"（{tp.get('drivable_pct', 0)}%）· "
                f"观测 {tp.get('observed', 0)}/{tp.get('observe_only', 0)} · "
                f"未命中 {tp.get('missed', 0)}")
        else:
            self.tp_label.setText("测试点：这一轮没有 TP IR（没有 case 模型或没跑覆盖率）")
        self.caveat_label.setText(
            "；".join(str(c) for c in caveats[:6]) if caveats else "")

    def _fill_evidence(self, ev: Dict[str, Any], run_dir: str) -> None:
        """合同级证据包 v2 视图（哈希 / caveat / 种子 / 基线 / 审批 / Freeze）。

        读不到就如实说"未生成"——老 run 没有 v2 是事实，不拿 v1 冒充。
        """
        self.evidence_dir = str(Path(run_dir) / "signoff_evidence") if run_dir else ""
        self.replay_cmd = str(ev.get("replay_cmd") or "")
        if not ev.get("available"):
            self.evidence_label.setText(
                "证据包 v2：未生成（老 run，或这次还没跑到 audit）")
            self.evidence_label.setStyleSheet(f"color: {theme.current().muted};")
            return

        cov = ev.get("coverage") or {}
        tp = ev.get("tp_matrix") or {}
        sd = ev.get("seed_diversity") or {}
        reward = ev.get("sim_reward") or {}
        kg = ev.get("knowledge_graph") or {}
        rm = ev.get("reference_models") or {}
        lin = ev.get("lineage") or {}
        cst = ev.get("constraint_status") or {}
        freeze = ev.get("freeze") or {}
        appr = ev.get("latest_approval") or {}
        pkg = str(ev.get("package_hash") or "")
        seeds = sd.get("seeds") or []
        effective = ev.get("effective_codes") or []
        accepted = ev.get("accepted_codes") or []
        counts = tp.get("counts") or {}

        def _pct(v):
            return f"{v:g}%" if isinstance(v, (int, float)) else "?"

        lines = [
            f"证据包 v2：{ev.get('schema') or '?'} · 文件 {ev.get('file_count', 0)} · "
            f"package_hash {pkg[:16]}{'…' if len(pkg) > 16 else ''}",
            f"判定：hard_ok={ev.get('hard_ok')} · verdict={ev.get('verdict') or '?'} · "
            f"生效 caveat {('、'.join(effective) or '无')}"
            + (f" · 已接受 {('、'.join(accepted))}" if accepted else ""),
            f"覆盖率：计划 {_pct(cov.get('plan_pct'))} / 单测 {_pct(cov.get('single_test_pct'))} · "
            f"TP {counts or '{}'}",
            f"种子：{sd.get('verdict') or '?'}（{len(seeds)} seeds · "
            f"稳定 {sd.get('stable_bins', '?')} / 种子敏感 {sd.get('variable_bins', '?')}）",
            f"奖励：{reward.get('total', '?')}（最弱层 {reward.get('weakest') or '?'}）"
            if reward else "奖励：未计算（老 run）",
            (f"知识图：{kg.get('summary', {}).get('nodes', '?')} 节点 / "
             f"{kg.get('summary', {}).get('edges', '?')} 边 · "
             f"sha256 {(kg.get('sha256') or '?')[:12]}…")
            if kg else "知识图：未生成（老 run）",
            f"约束：{cst.get('backed_policy_count', '?')}/{cst.get('policy_count', '?')} backed · "
            f"参考模型：{'unavailable' if not rm.get('available') else 'available'} · "
            f"基线：{lin.get('name') or '?'}",
            f"审批：{ev.get('approval_count', 0)} 条"
            + (f"（最新 {appr.get('action')} by {appr.get('approver') or '?'}）"
               if appr else "")
            + f" · Freeze：{'present' if freeze.get('present') else 'missing'}",
            f"回放：{self.replay_cmd or '（无）'}",
        ]
        self.evidence_label.setText("\n".join(lines))
        self.evidence_label.setStyleSheet(f"color: {theme.current().muted};")

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
        self.tp_label.setText("")
        self.caveat_label.setText("")
        self.count_label.setText("")
        self.evidence_label.setText("")
        self.evidence_dir = ""
        self.replay_cmd = ""


def _color(passed: bool) -> QColor:
    """通过绿、不通过红 —— 与全局「颜色只是帮助扫读」一致，文字仍承担信息。"""
    palette = theme.current()
    return QColor(palette.ok if passed else palette.error)
