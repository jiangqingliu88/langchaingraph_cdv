"""IP 工作区 —— 选中 IP 的规格、RTL、验证入口。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...ui import theme
from ..service.common import open_module
from .common import IpModuleBase


class IpWorkspaceModule(IpModuleBase):
    HINT = "IP 团队视角：选中一个 IP，查看它的 RTL / spec / 验证计划并跳到现有专业模块。"

    #: 刚跑完的 IP run（只对同一个 IP 生效，切走就回退到该 IP 的最近 run）
    _last_run_root: str = ""
    _last_run_ip: str = ""

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("IP"))
        self.combo = QComboBox(root)
        self.combo.setMinimumWidth(320)
        self.combo.currentIndexChanged.connect(self._ip_changed)
        row.addWidget(self.combo, 1)
        refresh = QPushButton("刷新", root)
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)

        self.info = QLabel("", root)
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        label = QLabel("RTL", root)
        label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(label)
        self.table = QTableWidget(0, 2, root)
        self.table.setHorizontalHeaderLabels(["文件", "存在"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        label2 = QLabel("验证 / 发布", root)
        label2.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(label2)
        self.status = QLabel("", root)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.release = QLabel("", root)
        self.release.setWordWrap(True)
        layout.addWidget(self.release)
        self.tp_table = QTableWidget(0, 2, root)
        self.tp_table.setHorizontalHeaderLabels(["测试点", "状态"])
        self.tp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tp_table.verticalHeader().setVisible(False)
        self.tp_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tp_table, 1)

        actions = QHBoxLayout()
        run_btn = QPushButton("运行 IP 回归", root)
        run_btn.clicked.connect(self._run_ip)
        actions.addWidget(run_btn)
        ev_btn = QPushButton("生成 IP 证据", root)
        ev_btn.clicked.connect(self._write_evidence)
        actions.addWidget(ev_btn)
        release_btn = QPushButton("生成发布包", root)
        release_btn.clicked.connect(self._build_release)
        actions.addWidget(release_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        links = QHBoxLayout()
        for text, module_id in (("设计产出", "design.output"), ("验证产出", "verify.output"),
                                ("回归状态", "ops.regression_status"),
                                ("覆盖率", "coverage.output"), ("调试", "debug.output")):
            link = QPushButton(text, root)
            link.clicked.connect(lambda _=False, mid=module_id: open_module(self.ctx, mid))
            links.addWidget(link)
        links.addStretch(1)
        layout.addLayout(links)
        self.refresh()
        return root

    def refresh(self) -> None:
        current = str(self.combo.currentData() or getattr(self.ctx, "selected_ip", "") or "")
        ips = self.load_ips()
        self.combo.blockSignals(True)
        self.combo.clear()
        for ip in ips:
            self.combo.addItem(f"{ip.get('id')} · {ip.get('name')}", ip.get("id"))
        idx = self.combo.findData(current)
        self.combo.setCurrentIndex(idx if idx >= 0 and self.combo.count() else 0)
        self.combo.blockSignals(False)
        self._ip_changed(self.combo.currentIndex())

    def _ip_changed(self, _index: int) -> None:
        ip_id = str(self.combo.currentData() or "")
        if not ip_id:
            self.info.setText("没有 IP 清单（spec/ip_manifest.yaml）")
            return
        ip = self.ip_info(ip_id)
        self.info.setText(self._info_text(ip))
        self._fill_rtl(ip)
        self._show_status(self._load_status(ip_id))
        info = self.run_tool("ip.release_check", quiet=True,
                             root=str(self.project_root), ip_id=ip_id)
        self._show_release(info if isinstance(info, dict) else {})
        self.set_status(f"IP 工作区：{ip_id}")

    @staticmethod
    def _info_text(ip: Dict[str, Any]) -> str:
        return (
            f"{ip.get('id')} · {ip.get('name')}\n"
            f"团队：{ip.get('team') or '?'} · Owner：{ip.get('owner') or '?'} · "
            f"版本：{ip.get('version') or '?'} · 状态：{ip.get('status') or '?'}\n"
            f"RTL hash：{str(ip.get('rtl_hash'))[:16]}… · "
            f"spec：{ip.get('spec') or '-'} · verification：{ip.get('verification') or '-'}\n"
            f"{ip.get('notes') or ''}")

    def _fill_rtl(self, ip: Dict[str, Any]) -> None:
        files = ip.get("rtl_files") or []
        present = set(ip.get("rtl_present") or [])
        self.table.setRowCount(len(files))
        for row, rel in enumerate(files):
            self.table.setItem(row, 0, QTableWidgetItem(str(rel)))
            self.table.setItem(row, 1, QTableWidgetItem("✓" if rel in present else "✗"))

    def _load_status(self, ip_id: str) -> Dict[str, Any]:
        # 刚跑完的 IP run 优先显示；切到别的 IP 时回退到该 IP 自己的最近 run
        # （`ip_status` 内部会先找这个 IP 的 ip_run，再回退 SoC run）。
        run_root = self._last_run_root if self._last_run_ip == ip_id else ""
        st = self.run_tool("ip.status", quiet=True, root=str(self.project_root),
                           ip_id=ip_id, run_root=run_root)
        return st if isinstance(st, dict) else {}

    def _show_status(self, st: Dict[str, Any]) -> None:
        if not st:
            return
        tests = "、".join(f"{t.get('name')}={t.get('status')}"
                          for t in (st.get("tests") or []))
        kind = str(st.get("source_kind") or "")
        suffix = f"（{kind}）" if kind and kind != "none" else ""
        source = Path(str(st.get("source_run") or "")).name or "无"
        self.status.setText(
            f"验证状态：{st.get('status')} · basis={st.get('verification_basis')} · "
            f"release_ready={st.get('release_ready')} · "
            f"来源：{source}{suffix}\n"
            + (f"tests：{tests}" if tests else ""))
        tps = st.get("testpoints") or []
        self.tp_table.setRowCount(len(tps))
        for row, tp in enumerate(tps):
            self.tp_table.setItem(row, 0, QTableWidgetItem(str(tp.get("tp_id"))))
            self.tp_table.setItem(row, 1, QTableWidgetItem(str(tp.get("status"))))

    def _show_release(self, info: Dict[str, Any]) -> None:
        pkg = info.get("package") or {}
        if not pkg:
            self.release.setText("发布包：未生成（spec/ip_releases 里没有这个 IP）")
            return
        state = "✓ released" if info.get("ok") else "✗ 未放行 / 已过期"
        issues = "、".join(str(i.get("check")) for i in (info.get("issues") or []))
        self.release.setText(
            f"发布包：{pkg.get('version')} · {state} · "
            f"sha256 {str(pkg.get('sha256'))[:12]}…"
            + (f"\n问题：{issues}" if issues else ""))

    def _build_release(self) -> None:
        ip_id = str(self.combo.currentData() or "")
        if not ip_id:
            return
        # 发布包是对外交付物 —— 绑定表标了 trigger="approval"，界面这一侧
        # 用一次确认框当"审批"；核心侧的目录/命令/预算约束仍在 Job Supervisor。
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self.content, "生成 IP 发布包",
            f"将为 {ip_id} 生成发布包并写入 spec/ip_releases/。\n"
            "这是对外交付物，确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        run_root = self._last_run_root if self._last_run_ip == ip_id else ""
        result = self.run_tool("ip.release_build", force=True, approval=True,
                               root=str(self.project_root), ip_id=ip_id,
                               run_root=run_root)
        if not isinstance(result, dict):
            return
        if not result.get("ok"):
            self.show_error(str(result.get("error") or "生成失败"))
            return
        if result.get("released"):
            self.show_info(f"发布包已生成：{result.get('path')}")
        else:
            self.show_warning("发布包已生成，但未放行："
                              + "、".join(result.get("blocking") or []))
        self.refresh()

    def _run_ip(self) -> None:
        ip_id = str(self.combo.currentData() or "")
        if not ip_id:
            return
        self.show_info(f"开始跑 {ip_id} 的 IP 回归…")
        result = self.run_tool("ip.run", force=True,
                               project_root=str(self.project_root), ip_id=ip_id)
        if isinstance(result, dict):
            self._last_run_root = str(result.get("output_root") or "")
            self._last_run_ip = ip_id
            self.show_info(f"IP 回归 {result.get('status')} · "
                           f"{self._last_run_root}")
            self.refresh()

    def _write_evidence(self) -> None:
        ip_id = str(self.combo.currentData() or "")
        if not ip_id:
            return
        run_root = self._last_run_root if self._last_run_ip == ip_id else ""
        result = self.run_tool("ip.evidence", force=True,
                               root=str(self.project_root), ip_id=ip_id,
                               run_root=run_root)
        if isinstance(result, dict):
            self.show_info(f"IP 证据：{result.get('path')} · "
                           f"{result.get('status')}")
