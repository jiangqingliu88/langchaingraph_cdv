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

from src.workbench.bus import run_id_of

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QApplication, QLabel, QMessageBox, QScrollArea,
                               QTabWidget, QVBoxLayout, QWidget)

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
#: Case 证据在签核产出里的清单（三集合）
CASE_COLUMNS = (
    ("label", "Case 产物", 280, LEFT),
    ("state", "已生成", 80, CENTER),
    ("in_package", "进包", 70, CENTER),
    ("path", "路径", 330, LEFT),
)
#: OS 账本：每条义务当前状态（判据来自 derive，页面只呈现）
OS_COLUMNS = (
    ("obligation_id", "义务", 330, LEFT),
    ("kind", "类型", 90, CENTER),
    ("case", "用例", 190, LEFT),
    ("status", "状态", 120, CENTER),
)


class SignoffModule(ModuleBase):
    """一次运行的签核判定（门禁 + 证据链）。"""

    HINT = ("选一次运行（左边「运行历史」），这里显示它能不能签核。五个标签页："
            "签核门禁 / 领域证据链 / Case 证据（四集合 + 非绿 CELL 缺口）/ "
            "证据包 v2（哈希 / caveat / 覆盖率 / 种子 / 奖励 / 知识图 / 审批 / 回放）/ "
            "OS 账本（义务 / 账本 / 两级对账 / 建议重跑的 test）。"
            "工具栏「校验证据包」会重算 Tier A 并检查 replay recipe。")

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

        # ── 顶部只留**判定与口径**（紧凑几行）──
        self.count_label = QLabel("", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)

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

        # ── 明细表放进 Tab：一次看一张，用标签页切换 ──
        #
        # 原来是三张表纵向堆在一个 splitter 里：每张都被压在几十像素高，
        # 谁都看不清。签核要的是"先看哪一块"，不是"一块里塞下全部"。
        self.tabs = QTabWidget(root)
        self.tabs.setDocumentMode(True)

        gate_page = QWidget(self.tabs)
        gate_layout = QVBoxLayout(gate_page)
        gate_layout.setContentsMargins(2, 2, 2, 2)
        gate_layout.setSpacing(2)
        gate_layout.addWidget(self._section("签核门禁（audit · report.json）", gate_page))
        self.gate_model = RowsModel(GATE_COLUMNS, gate_page)
        self.gate_table = table_helpers.configure_table(gate_page, self.gate_model)
        gate_layout.addWidget(self.gate_table, 1)
        self.tabs.addTab(gate_page, "签核门禁")

        chain_page = QWidget(self.tabs)
        chain_layout = QVBoxLayout(chain_page)
        chain_layout.setContentsMargins(2, 2, 2, 2)
        chain_layout.setSpacing(2)
        chain_layout.addWidget(self._section("领域证据链（finalize · docs/evidence_chain.json）", chain_page))
        self.chain_model = RowsModel(CHAIN_COLUMNS, chain_page)
        self.chain_table = table_helpers.configure_table(chain_page, self.chain_model)
        chain_layout.addWidget(self.chain_table, 1)
        self.tabs.addTab(chain_page, "领域证据链")

        # ── Case 证据（三集合）：签核产出的第 4 块 ──
        # 它回答"这条用例证明了哪些组 / 哪条 SVA / 哪个 scoreboard"，
        # 与 TP 矩阵同级 —— 所以在这里，而不是只留在覆盖率页。
        case_page = QWidget(self.tabs)
        case_layout = QVBoxLayout(case_page)
        case_layout.setContentsMargins(2, 2, 2, 2)
        case_layout.setSpacing(2)
        case_layout.addWidget(self._section(
            "Case 证据（签核产出 · groups / sva / scb）", case_page))
        self.case_label = QLabel("", case_page)
        self.case_label.setWordWrap(True)
        self.case_label.setStyleSheet(f"color: {theme.current().muted};")
        case_layout.addWidget(self.case_label)
        self.case_model = RowsModel(CASE_COLUMNS, case_page)
        self.case_table = table_helpers.configure_table(case_page, self.case_model)
        case_layout.addWidget(self.case_table, 1)
        self.tabs.addTab(case_page, "Case 证据")

        # 合同级证据包（v2）：哈希 / caveat / 种子 / 基线 / 审批 / Freeze / 回放。
        # 这段是多行长文本，单独一页 + 可滚动，不挤占表格的高度。
        ev_page = QWidget(self.tabs)
        ev_layout = QVBoxLayout(ev_page)
        ev_layout.setContentsMargins(2, 2, 2, 2)
        ev_layout.setSpacing(2)
        ev_layout.addWidget(self._section(
            "合同级证据包 v2（signoff_evidence/manifest.json）", ev_page))
        self.evidence_label = QLabel("", ev_page)
        self.evidence_label.setWordWrap(True)
        self.evidence_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.evidence_label.setStyleSheet(f"color: {theme.current().muted};")
        self.evidence_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea(ev_page)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.evidence_label)
        ev_layout.addWidget(scroll, 1)
        self.tabs.addTab(ev_page, "证据包 v2")

        # Verification OS：义务清单 + 状态（只呈现 derive 的结论）
        self.tabs.addTab(self._build_os_page(), "OS 账本")

        layout.addWidget(self.tabs, 1)
        return root

    def _build_os_page(self) -> QWidget:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.os_label = QLabel("", page)
        self.os_label.setWordWrap(True)
        self.os_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.os_label)
        self.os_model = RowsModel(OS_COLUMNS, page)
        self.os_table = table_helpers.configure_table(page, self.os_model)
        layout.addWidget(self.os_table, 1)
        return page

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
        check = QAction("校验证据包", self.content)
        check.triggered.connect(self._check_evidence)
        return [action, copy_dir, copy_replay, check]

    def _check_evidence(self) -> None:
        """跑一次证据包自校验（Tier A 重算 + recipe schema）。纯读。"""
        if not self.evidence_dir:
            QMessageBox.information(self.content, "证据包校验",
                                    "还没选中运行或这次运行没有证据包。")
            return
        payload = self.run_tool("evidence.check_package", quiet=True,
                                package_dir=self.evidence_dir)
        if not isinstance(payload, dict):
            return
        if not payload.get("available"):
            QMessageBox.information(self.content, "证据包校验",
                                    str(payload.get("note") or "没有 manifest.json"))
            return
        verify = payload.get("verify") or {}
        replay = payload.get("replay") or {}
        issues = payload.get("recipe_issues") or []
        text = (
            f"完整性：{'✓' if verify.get('ok') else '✗'}  "
            f"package_hash {str(verify.get('package_hash') or '')[:16]}…\n"
            f"Tier A：{'✓' if replay.get('ok') else '✗'}  "
            f"{replay.get('recorded_verdict')} → {replay.get('recomputed_verdict')}\n"
            f"recipe：{(payload.get('recipe') or {}).get('schema') or '?'}"
            + (f"\n配置问题：{len(issues)} 条（{issues[0]}）" if issues else "")
        )
        QMessageBox.information(self.content, "证据包校验", text)

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者。"""
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
        self._fill_case_view(payload.get("case_view") or {},
                             payload.get("os") or {})
        self._fill_os(payload.get("os") or {})

    def _fill_os(self, os_status: Dict[str, Any]) -> None:
        """OS 账本：义务状态表 + "未清偿 / 建议重跑"摘要。"""
        model = getattr(self, "os_model", None)
        if model is None:
            return
        obligations = list(os_status.get("obligations") or [])
        model.set_rows([{
            "obligation_id": o.get("obligation_id"),
            "kind": o.get("kind"),
            "case": o.get("case"),
            "status": o.get("status"),
        } for o in obligations])
        model.apply_column_widths(self.os_table)
        if not obligations:
            self.os_label.setText("OS 账本：这一轮没有契约产物（老 run，或没跑到 coverage）")
            self._tab_meta(4, "OS 账本")
            return
        open_n = sum(1 for o in obligations
                     if o.get("status") not in ("PROVEN", "NOT_APPLICABLE"))
        worklist = os_status.get("worklist") or {}
        self.os_label.setText(
            f"义务 {len(obligations)} 条 · 未清偿 {open_n} 条 · "
            f"建议重跑 {worklist.get('count', 0)} 条 test"
            f"（worklist 打开时只跑这些）")
        self._tab_meta(4, f"OS 账本 {len(obligations) - open_n}/{len(obligations)}")

    def _fill_case_view(self, cv: Dict[str, Any],
                        os_status: Dict[str, Any] = None) -> None:
        """Case 证据：生成没有、进没进证据包、Gate 与 CELL 读数（+ OS 账本）。"""
        if not getattr(self, "case_model", None):
            return
        if not cv.get("available"):
            self.case_label.setText(
                "Case 证据：这一轮没有三集合产物（改造前的 run，或没跑到 coverage）"
                + self._os_text(os_status))
            self.case_label.setStyleSheet(f"color: {theme.current().muted};")
            self.case_model.set_rows([])
            self._tab_meta(2, "Case 证据（无产物）")
            return
        gate = cv.get("gate") or {}
        counts = gate.get("counts") or {}
        cells = cv.get("cells") or {}
        cases = cv.get("cases") or {}
        evd = cv.get("evd") or {}
        verdict = str(gate.get("verdict") or "—")
        self.case_label.setText(
            f"Case Gate：{verdict}（blocker {counts.get('blocker', 0)} / "
            f"warning {counts.get('warning', 0)}）　·　"
            f"CELL 绿 {cells.get('green', 0)} / 黄 {cells.get('yellow', 0)} / "
            f"红 {cells.get('red', 0)} / na {cells.get('na', 0)}　·　"
            f"用例 {cases.get('cases', 0)}（组 {cases.get('groups', 0)} / "
            f"SVA {cases.get('sva', 0)} / SB {cases.get('scb', 0)}）　·　"
            f"EVD {evd.get('total', 0)}　·　case_cov {cv.get('case_cov_files', 0)} 份"
            + self._os_text(os_status))
        palette = theme.current()
        self.case_label.setStyleSheet(
            f"color: {palette.warning if verdict == 'BLOCKED' else palette.muted};")

        self._tab_meta(2, f"Case 证据 {cells.get('green', 0)}绿/"
                          f"{cells.get('yellow', 0)}黄/{cells.get('red', 0)}红")
        rows = [{
            "label": a.get("label"), "path": a.get("path"),
            "state": "是" if a.get("exists") else "否",
            "in_package": "是" if a.get("in_package") else "否",
            "_in_package": bool(a.get("in_package")),
        } for a in (cv.get("artifacts") or [])]
        self.case_model.set_rows(rows)
        self.case_model.apply_column_widths(self.case_table)

    @staticmethod
    def _os_text(os_status: Dict[str, Any] = None) -> str:
        """OS 账本一行（契约 / 事实数 / 两级对账）；没有 OS 产物就不提。"""
        data = os_status or {}
        contract = data.get("contract") or {}
        if not contract.get("ok"):
            return ""
        case_shadow = data.get("case_shadow") or {}
        tp_shadow = data.get("tp_shadow") or {}
        return (f"　·　OS：{contract.get('obligations', 0)} 条义务 · "
                f"账本 {(data.get('ledger') or {}).get('facts', 0)} 条事实 · "
                f"对账 {'一致' if case_shadow.get('ok') and tp_shadow.get('ok') else '有差异'}")

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
        self._tab_meta(3, _evidence_tab_title(bool(ev.get("available"))))
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
        recipe = ev.get("recipe") or {}
        stimulus = ev.get("stimulus_plan") or {}
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
            f"覆盖率：功能 计划 {_pct(cov.get('plan_pct'))} / 单测 {_pct(cov.get('single_test_pct'))} · "
            f"代码 计划 {_pct(cov.get('code_plan_pct'))} / 单测 {_pct(cov.get('code_single_pct'))} · "
            f"TP {counts or '{}'}",
            f"种子：{sd.get('verdict') or '?'}（{len(seeds)} seeds · "
            f"稳定 {sd.get('stable_bins', '?')} / 种子敏感 {sd.get('variable_bins', '?')}）",
            _reward_text(reward),
            (f"知识图：{kg.get('summary', {}).get('nodes', '?')} 节点 / "
             f"{kg.get('summary', {}).get('edges', '?')} 边 · "
             f"sha256 {(kg.get('sha256') or '?')[:12]}…")
            if kg else "知识图：未生成（老 run）",
            _stimulus_text(stimulus),
            f"约束：{cst.get('backed_policy_count', '?')}/{cst.get('policy_count', '?')} backed · "
            f"参考模型：{'unavailable' if not rm.get('available') else 'available'} · "
            f"基线：{lin.get('name') or '?'}",
            f"审批：{ev.get('approval_count', 0)} 条"
            + (f"（最新 {appr.get('action')} by {appr.get('approver') or '?'}）"
               if appr else "")
            + f" · Freeze：{'present' if freeze.get('present') else 'missing'}",
            _replay_text(self.replay_cmd, recipe),
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
        self._tab_meta(0, f"签核门禁 {sum(1 for g in gates.get('rows') or [] if g['passed'])}"
                          f"/{len(rows)}")

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
        done = sum(1 for layer in chain.get("layers") or []
                   if layer["total"] > 0 and layer["passed"] == layer["total"])
        self._tab_meta(1, f"领域证据链 {done}/{len(rows)}")

    def _tab_meta(self, index: int, text: str) -> None:
        """标签页标题带上"这一页有没有东西"—— 不用点进去才知道。"""
        tabs = getattr(self, "tabs", None)
        if tabs is None or index >= tabs.count():
            return
        tabs.setTabText(index, text)

    def _clear(self) -> None:
        self.run_id = ""
        self.verdict_label.setText("（还没选中运行）")
        self.verdict_label.setStyleSheet("")
        self.gate_model.set_rows([])
        self.chain_model.set_rows([])
        if getattr(self, "case_model", None):
            self.case_model.set_rows([])
            self.case_label.setText("")
        if getattr(self, "os_model", None):
            self.os_model.set_rows([])
            self.os_label.setText("")
        self.tp_label.setText("")
        self.caveat_label.setText("")
        self.count_label.setText("")
        self.evidence_label.setText("")
        self.evidence_dir = ""
        self.replay_cmd = ""
        for index, title in enumerate(("签核门禁", "领域证据链", "Case 证据",
                                       "证据包 v2", "OS 账本")):
            self._tab_meta(index, title)


def _evidence_tab_title(available: bool) -> str:
    """证据包那一页的标签文案（有包 / 没包 一眼看出）。"""
    return "证据包 v2 ✓" if available else "证据包 v2（未生成）"


def _reward_text(reward: Dict[str, Any]) -> str:
    if not reward:
        return "奖励：未计算（老 run）"
    text = (f"奖励：{reward.get('total', '?')}"
            f"（最弱层 {reward.get('weakest') or '?'}）")
    if reward.get("weights"):
        text += f" · 权重 {reward.get('weights')}"
    issues = reward.get("weight_issues") or []
    if issues:
        text += f" · 配置问题 {len(issues)} 条"
    return text


def _stimulus_text(plan: Dict[str, Any]) -> str:
    if not plan:
        return "激励计划：未生成（老 run）"
    stats = plan.get("stats") or {}
    return (f"激励计划：{stats.get('planned', '?')} 可激励 / "
            f"{stats.get('unsupported', '?')} 不适用 · "
            f"backend {plan.get('backend') or '?'} · "
            f"sha256 {(plan.get('sha256') or '?')[:12]}…")


def _replay_text(command: str, recipe: Dict[str, Any]) -> str:
    text = f"回放：{command or '（无）'}"
    if not recipe:
        return text + " · recipe 未生成（老 run）"
    tools = "、".join((recipe.get("tier_b") or {}).get("eda_tools") or [])
    return text + (f" · recipe {recipe.get('schema') or '?'}"
                   f" · Tier B 需 {tools or '?'}")


def _color(passed: bool) -> QColor:
    """通过绿、不通过红 —— 与全局「颜色只是帮助扫读」一致，文字仍承担信息。"""
    palette = theme.current()
    return QColor(palette.ok if passed else palette.error)
