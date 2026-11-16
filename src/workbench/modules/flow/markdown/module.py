"""Markdown 产物 —— 一次运行里「人该读、也该能改」的 .md 文件。

这是「PySide6 UI / TUI 是交互前端」这条口径的落点之一：

  · 左边列出 run 目录下所有 `.md`（spec 摘要、mental model、summary、
    rule drafts…），按所在目录分组；
  · 右边「编辑 / 预览」两页签，编辑原文、预览 Markdown；
  · 保存写回原文件，并调用 `record_human_edit()` 记进证据链（带 run_id）。

边界与「产物审查」页一致：**保存不会自动重跑**；改的是那次运行目录里的文件。
只列 `.md`，二进制/大文件不在这一页处理。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from src.workbench.bus import run_id_of
from src.workbench.ui import theme

from ...base import ModuleBase

FILE_ROLE = Qt.ItemDataRole.UserRole + 1
MAX_BYTES = 2_000_000          # 单文件预览/编辑上限，避免界面被超大 md 拖死
PREVIEW_MS = 250


class MarkdownArtifactsModule(ModuleBase):
    """浏览与编辑一次运行产出的 Markdown 文件。"""

    HINT = ("左边列出这次运行的全部 .md 产物；右边编辑原文、预览渲染结果。"
            "保存会写回文件并记进证据链，但**不会自动重跑**。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""
        self.run_dir: str = ""
        self.path: Optional[Path] = None
        self._dirty = False
        self._files: List[Path] = []
        self._preview_timer: Optional[QTimer] = None

    # ── 界面 ──────────────────────────────────────────────────

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        self.summary = QLabel("（还没选中运行 —— 在「运行历史」里选一次）")
        self.summary.setStyleSheet(f"color: {theme.current().muted};")
        bar.addWidget(self.summary, 1)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_btn)
        self.open_btn = QPushButton("用系统程序打开")
        self.open_btn.clicked.connect(self.open_external)
        self.open_btn.setEnabled(False)
        bar.addWidget(self.open_btn)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.addWidget(self._build_tree())
        splitter.addWidget(self._build_editor())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([280, 760])
        layout.addWidget(splitter, 1)

        self._preview_timer = QTimer(root)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_MS)
        self._preview_timer.timeout.connect(self._refresh_preview)
        return root

    def _build_tree(self) -> QWidget:
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addWidget(QLabel("Markdown 产物"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件", "大小"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setUniformRowHeights(True)
        self.tree.itemSelectionChanged.connect(self._on_selected)
        outer.addWidget(self.tree, 1)
        return box

    def _build_editor(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.head = QLabel("（从左边选一份 Markdown）")
        self.head.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.head)

        self.tabs = QTabWidget()
        self.editor = QPlainTextEdit()
        self.editor.setFont(theme.mono_font())
        self.editor.setPlaceholderText("从左边选一份 Markdown 产物")
        self.editor.textChanged.connect(self._on_text_changed)
        self.tabs.addTab(self.editor, "编辑")

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.setPlaceholderText("Markdown 预览")
        self.tabs.addTab(self.preview, "预览")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("理由："))
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("为什么改（会记进证据链）")
        row.addWidget(self.reason, 1)
        self.reload_btn = QPushButton("重载")
        self.reload_btn.clicked.connect(self.reload)
        self.reload_btn.setEnabled(False)
        row.addWidget(self.reload_btn)
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self.save)
        self.save_btn.setEnabled(False)
        row.addWidget(self.save_btn)
        layout.addLayout(row)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.status)
        self.editor.setReadOnly(True)
        return box

    # ── 平台钩子 ──────────────────────────────────────────────

    def on_activated(self) -> None:
        self.refresh()

    def on_refresh(self, payload: Any = None) -> None:
        run_id = run_id_of(payload)
        if run_id and run_id != self.run_id:
            self.run_id = run_id
            self.path = None
            self._clear()
            self.refresh()

    def can_close(self) -> bool:
        return not self._dirty

    def mark_clean(self) -> None:
        self._set_dirty(False)

    def on_theme_changed(self) -> None:
        self.summary.setStyleSheet(f"color: {theme.current().muted};")
        self.head.setStyleSheet(f"color: {theme.current().muted};")
        self.status.setStyleSheet(f"color: {theme.current().muted};")
        self.editor.setFont(theme.mono_font())

    # ── 数据 ──────────────────────────────────────────────────

    def refresh(self) -> None:
        if not self.run_id:
            self._clear()
            self.summary.setText("（还没选中运行 —— 在「运行历史」里选一次）")
            return
        if self._dirty and not self._confirm_discard():
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=self.run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        self.run_dir = str(detail.get("dir", "") or "")
        if not self.run_dir or not Path(self.run_dir).is_dir():
            self.show_warning(f"找不到运行 {self.run_id} 的目录")
            return
        self._scan()
        self.summary.setText(f"{self.run_id}：{len(self._files)} 个 Markdown 文件"
                             f"　·　{self.run_dir}")

    def _scan(self) -> None:
        keep = self.path
        root = Path(self.run_dir)
        files: List[Path] = []
        try:
            for path in root.rglob("*.md"):
                if any(part.startswith(".") for part in path.relative_to(root).parts):
                    continue
                try:
                    if path.stat().st_size <= MAX_BYTES:
                        files.append(path)
                except OSError:
                    continue
        except OSError as exc:
            self.show_error(f"扫描 Markdown 失败：{exc}")
            return
        self._files = sorted(files, key=lambda p: str(p.relative_to(root)).lower())
        self._fill_tree(root)
        target = keep if keep in self._files else (self._files[0] if self._files else None)
        if target is not None:
            self.load(target)
            self._select_path(target)
        else:
            self._clear()

    def _fill_tree(self, root: Path) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: Dict[str, QTreeWidgetItem] = {}
        for path in self._files:
            rel = path.relative_to(root)
            group_name = str(rel.parent).replace("\\", "/")
            if group_name == ".":
                group_name = "（根目录）"
            parent = groups.get(group_name)
            if parent is None:
                parent = QTreeWidgetItem(self.tree, [group_name, ""])
                parent.setFirstColumnSpanned(True)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                parent.setExpanded(True)
                groups[group_name] = parent
            try:
                size = f"{path.stat().st_size / 1024:.1f} KB"
            except OSError:
                size = ""
            node = QTreeWidgetItem(parent, [rel.name, size])
            node.setData(0, FILE_ROLE, str(path))
            node.setToolTip(0, str(rel).replace("\\", "/"))
        self.tree.blockSignals(False)

    def _select_path(self, path: Path) -> None:
        self.tree.blockSignals(True)
        try:
            for group in range(self.tree.topLevelItemCount()):
                parent = self.tree.topLevelItem(group)
                for index in range(parent.childCount()):
                    child = parent.child(index)
                    if child.data(0, FILE_ROLE) == str(path):
                        child.setSelected(True)
                        self.tree.scrollToItem(child)
                        return
        finally:
            self.tree.blockSignals(False)

    # ── 选中 / 编辑 ───────────────────────────────────────────

    def _selected(self) -> Optional[Path]:
        items = self.tree.selectedItems()
        if items and items[0].data(0, FILE_ROLE):
            return Path(items[0].data(0, FILE_ROLE))
        return None

    def _on_selected(self) -> None:
        target = self._selected()
        if target is None:
            self._clear()
            return
        if self._dirty and not self._confirm_discard():
            self._select_path(self.path) if self.path else None
            return
        self.load(target)

    def load(self, path: Path) -> None:
        try:
            if path.stat().st_size > MAX_BYTES:
                self.show_warning(f"{path.name} 超过 {MAX_BYTES // 1_000_000} MB，"
                                  "这一页不打开；请用系统程序查看。")
                return
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.show_error(f"读不了 {path.name}：{exc}")
            return
        self.path = path
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self.editor.setReadOnly(False)
        self._set_dirty(False)
        self.save_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        self.head.setText(str(path).replace("\\", "/"))
        self._refresh_preview()
        self.status.setText("")

    def _on_text_changed(self) -> None:
        if self.path is None:
            return
        self._set_dirty(True)
        if self._preview_timer is not None:
            self._preview_timer.start()

    def _on_tab_changed(self, _index: int) -> None:
        if self.tabs.currentIndex() == 1:
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.preview.setMarkdown(self.editor.toPlainText())

    def reload(self) -> None:
        if self.path is None:
            return
        if self._dirty and not self._confirm_discard():
            return
        self.load(self.path)

    def save(self) -> None:
        if self.path is None:
            return
        text = self.editor.toPlainText()
        try:
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            self.show_error(f"保存失败：{exc}")
            return
        self._set_dirty(False)
        record = self.record_human_edit(self.path, reason=self.reason.text(),
                                        run_id=self.run_id)
        self.status.setText("已保存" + ("，并记入证据链" if record else ""))
        self.set_status(f"Markdown 已保存：{self.path.name}")
        self.refresh()

    def open_external(self) -> None:
        if self.path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))

    # ── 小工具 ────────────────────────────────────────────────

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = bool(dirty)
        if hasattr(self, "save_btn"):
            self.save_btn.setEnabled(self.path is not None)
        self.set_tab_suffix(" ●" if dirty else "")

    def _confirm_discard(self) -> bool:
        answer = QMessageBox.question(
            self.content, "有未保存的修改",
            "当前 Markdown 有未保存的修改。放弃这些修改？")
        return answer == QMessageBox.StandardButton.Yes

    def _clear(self) -> None:
        self.path = None
        self._set_dirty(False)
        self.editor.blockSignals(True)
        self.editor.setPlainText("")
        self.editor.blockSignals(False)
        self.editor.setReadOnly(True)
        self.preview.clear()
        self.save_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.head.setText("（从左边选一份 Markdown）")
        self.status.setText("")
