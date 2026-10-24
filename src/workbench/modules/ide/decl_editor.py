"""声明式 YAML 编辑器 —— 「集成设计环境」下那几份声明**共用**的编辑界面。

**为什么提成基类**：人工节点与 IP 规格要的是同一件事 —— 左边写原文、下面列
schema 诊断、双击诊断跳到出事那一行、Ctrl+S 原样写回、保存前把「为什么改」
记进证据链。差别只有 schema 与几个名词。复制一份 360 行的模块出来，两份迟早
会漂移（仓库已有前科：`VerificationOS` 的签名就因为写死参数列表掉过队）。

**为什么是文本编辑器而不是表单**：从解析结果反向生成 YAML 是有损的（注释、
键顺序都会丢），那等于悄悄改掉用户写的东西。这里编辑的是**原文**，保存原样
写回 —— 文本是唯一真相，诊断只是它的视图。

**它不改闭环**：这些声明是声明/规划性质的，闭环图（`graph.py`）的节点写死，
不读它们；设计文档 `docs/design/gui_pipeline_architecture.md` §8 也明确
「不在 GUI 里编辑流程拓扑」。本模块只负责「把它编辑对、校验过」。

子类只需要给三样东西（见文件末尾的用法）：
    DECL               ide_tools.api 里的声明描述符（决定 schema 与高亮词表）
    NOUN               界面文案里的名词（"人工节点" / "IP 规格"）
    DEFAULT_FILENAME   「另存为」的默认文件名
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from src.tools.integration.ide_tools.api import Decl, MANUAL_NODES, load_decl_issues
from src.workbench.modules.base import ModuleBase
from src.workbench.ui import theme
from src.workbench.ui.editors.yaml import YamlEditor
from src.workbench.ui.widgets.panels import IssuePanel

#: 打字停下来多久之后跑一次校验 —— 每敲一个字都跑会闪，太久又不像「实时」
REVALIDATE_MS = 500

#: 拆 json_path 的段：`nodes[0].kind` → ["nodes", "kind"]（数组下标丢掉）
_PATH_SPLIT = re.compile(r"[\.\[\]]+")


def _needle_of(target: str) -> str:
    """诊断 target → 去 YAML 里找行的线索（最后一段有意义的键名）。

    `manual_nodes.yaml::nodes[0].kind` → `kind`；`…::nodes[0]` → `nodes`。
    取「最后一段非数字」，是因为下标 `0` 在 YAML 里没有可搜的字面量。
    """
    if not target:
        return ""
    segments = [s for s in _PATH_SPLIT.split(target.split("::")[-1])
                if s and not s.isdigit()]
    return segments[-1] if segments else ""


class DeclEditorModule(ModuleBase):
    """一份声明 YAML 的编辑器 + 校验器。子类给 DECL / NOUN / DEFAULT_FILENAME。"""

    #: 子类必须覆盖 —— 哪一份声明（决定 schema 与高亮词表）
    DECL: Decl = MANUAL_NODES
    #: 界面文案里的名词，如 "人工节点"
    NOUN: str = "声明"
    #: 「另存为」的默认文件名
    DEFAULT_FILENAME: str = "decl.yaml"

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.path: Optional[Path] = None
        self.issues: List[Any] = []
        # 模块不是 QObject（ModuleBase 不是），QTimer 不能挂它做 parent ——
        # 由 self 持有引用即可，Python 侧活得和模块一样久。
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(REVALIDATE_MS)
        self._timer.timeout.connect(self._revalidate)

    # ════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addLayout(self._build_bar())

        hint = QLabel(self.HINT, root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Vertical, root)

        self.editor = YamlEditor(splitter,
                                 skeleton_keys=self.DECL.skeleton_keys,
                                 enum_values=self.DECL.enum_values,
                                 placeholder=f"在此编辑{self.NOUN} YAML，"
                                             f"或按 Ctrl+O 打开文件…")
        self.editor.contentChanged.connect(self._on_content_changed)
        self.editor.cursorPositionChanged.connect(self._sync_cursor)
        splitter.addWidget(self.editor)

        self.panel = IssuePanel(hint="", empty_hint="（还没有校验结果）", parent=splitter)
        self.panel.issueActivated.connect(self.goto_issue)
        splitter.addWidget(self.panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        bottom.addWidget(self.status)
        bottom.addStretch(1)
        self.cursor_label = QLabel("")
        self.cursor_label.setStyleSheet(f"color: {theme.current().muted};")
        bottom.addWidget(self.cursor_label)
        layout.addLayout(bottom)

        self._sync_cursor()
        return root

    def _build_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        for text, slot in (("打开…", self.on_open),
                           ("保存", self.save_model),
                           ("另存为…", self.save_model_as),
                           ("立即校验", self._revalidate)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addSpacing(8)
        # 「修改理由」—— 它会随这次编辑一起进证据链，是链上最有价值的一栏：
        # "谁在什么时候改了什么" git diff 答得了，"为什么改" 只有人填得出来。
        # **留空不阻断保存**（工作流优先），链里会如实写「（未填理由）」，
        # 不编一个像样的理由顶上去 —— 那会让读链的人分不清哪句是人写的。
        bar.addWidget(QLabel("理由："))
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("为什么改（会记进证据链）")
        self.reason_edit.setMaximumWidth(260)
        bar.addWidget(self.reason_edit)
        bar.addSpacing(8)
        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet(f"color: {theme.current().error}; font-weight: bold;")
        bar.addWidget(self._dirty_label)
        self._file_label = QLabel("（未打开文件）")
        self._file_label.setStyleSheet(f"color: {theme.current().muted};")
        bar.addWidget(self._file_label)
        bar.addStretch(1)
        return bar

    # ════════════════════════════════════════════════════════
    # 平台接口
    # ════════════════════════════════════════════════════════

    def create_actions(self) -> List[QAction]:
        def act(text, slot, shortcut=None):
            action = QAction(text, self.content)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            return action

        return [act(f"打开{self.NOUN}…", self.on_open, QKeySequence.StandardKey.Open),
                act(f"保存{self.NOUN}", self.save_model, QKeySequence.StandardKey.Save),
                act("另存为…", self.save_model_as, QKeySequence.StandardKey.SaveAs),
                act("立即校验", self._revalidate, "Ctrl+R")]

    def on_activated(self) -> None:
        self.editor.setFocus()

    def on_input_changed(self, path) -> None:
        """清单的 `input` 或 `--input` 指过来时：载入这份文件。"""
        target = Path(path)
        if target.is_dir():
            candidates = sorted(target.glob("*.yaml")) + sorted(target.glob("*.yml"))
            if not candidates:
                self.show_warning(f"{target} 下没有 .yaml 文件。")
                return
            target = candidates[0]
        self.load(str(target))

    def on_theme_changed(self) -> None:
        self.editor.rehighlight()

    def can_close(self) -> bool:
        """有未保存的改动就拦一道 —— 关窗口/换清单之前问一句。"""
        if not self.editor.dirty:
            return True
        return self._confirm_discard()

    def mark_clean(self) -> None:
        self.editor.mark_clean()
        self._sync_footer()

    # ════════════════════════════════════════════════════════
    # 打开 / 保存
    # ════════════════════════════════════════════════════════

    def on_open(self) -> None:
        if not self._confirm_discard():
            return
        path, _filter = QFileDialog.getOpenFileName(
            self.content, f"选择{self.NOUN} YAML", "",
            "YAML 文件 (*.yaml *.yml);;所有文件 (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        target = Path(path)
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self.content, "打开失败", str(exc))
            self.set_status(f"打开失败：{exc}")
            return
        self.path = target
        self.editor.set_text(text)
        self._sync_footer()
        self._revalidate()

    def save_model(self) -> bool:
        if self.path is None:
            return self.save_model_as()
        text = self.editor.text()
        errors = [i for i in load_decl_issues(text, self.DECL, self.path.name)
                  if i.is_error]
        if errors:
            detail = "\n".join(f"· {i.message}" for i in errors[:8])
            if len(errors) > 8:
                detail += f"\n…共 {len(errors)} 条"
            answer = QMessageBox.question(
                self.content, f"schema 有 {len(errors)} 处错误",
                f"保存前校验没通过：\n\n{detail}\n\n仍然保存吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.set_status("保存已取消 —— 先按提示修好 schema 错误。")
                return False
        try:
            self.path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self.content, "保存失败", str(exc))
            self.set_status(f"保存失败：{exc}")
            return False

        self.editor.mark_clean()
        self._sync_footer()
        self._revalidate()
        # 写盘之后立刻记账 —— 这一步漏了，这次编辑就等于没发生过（见基类的说明）
        recorded = self.record_human_edit(self.path, self.reason_edit.text())
        self.reason_edit.clear()          # 理由跟着这次保存走，不留给下一次
        tail = f"　schema {len(errors)} 处错误仍在。" if errors else ""
        if recorded:
            tail += f"　已记账 #{recorded['seq']}（{recorded['author']}）"
        self.set_status(f"已保存 {self.path}{tail}")
        return True

    def save_model_as(self) -> bool:
        path, _filter = QFileDialog.getSaveFileName(
            self.content, f"保存{self.NOUN} YAML",
            self.path.name if self.path else self.DEFAULT_FILENAME,
            "YAML 文件 (*.yaml *.yml);;所有文件 (*)")
        if not path:
            return False
        self.path = Path(path)
        self.editor.mark_clean()         # 先清脏，避免 save_model 里再问一次
        return self.save_model()

    def _confirm_discard(self) -> bool:
        """有未保存改动时问一句 —— 返回 True 表示可以继续。"""
        if not self.editor.dirty:
            return True
        box = QMessageBox(self.content)
        box.setWindowTitle("有未保存的改动")
        box.setText("当前文件有未保存的改动。\n\n要保存吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Save
                               | QMessageBox.StandardButton.Discard
                               | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_model()
        return True                      # 不保存，继续

    # ════════════════════════════════════════════════════════
    # 校验
    # ════════════════════════════════════════════════════════

    def refresh(self) -> None:
        """`on_refresh` / 平台刷新 —— 就是重跑一次校验。"""
        self._revalidate()

    def _on_content_changed(self, _first: bool) -> None:
        """用户改了文本 —— 标脏、起防抖定时器。**不在每次按键就跑校验**。"""
        self._sync_footer()
        self._timer.start()

    def _revalidate(self) -> None:
        """拿编辑器当前文本跑 schema 校验（不落盘）。"""
        if self._timer.isActive():
            self._timer.stop()
        text = self.editor.text()
        if not text.strip():
            self.issues = []
            self.panel.set_issues([])
            self._sync_footer()
            # 空文本不是「校验通过」—— 把脚下那行也说清楚，别报一个假的绿灯
            self.status.setStyleSheet(f"color: {theme.current().muted};")
            self.status.setText("（编辑器是空的 —— 没有可校验的内容）")
            self.set_status("编辑器是空的 —— 没有可校验的内容。")
            return
        name = self.path.name if self.path else "<编辑器>"
        self.issues = load_decl_issues(text, self.DECL, name)
        self.panel.set_issues(self.issues)
        self._sync_footer()
        errors = [i for i in self.issues if i.is_error]
        if errors:
            self.set_status(f"schema 校验：{len(errors)} 处错误 —— 见下方诊断。")
        else:
            self.set_status(f"schema 校验通过（{len(self.issues)} 条提示）。")

    def _sync_footer(self) -> None:
        self._dirty_label.setText("● 未保存" if self.editor.dirty else "")
        self._file_label.setText(str(self.path) if self.path else "（未打开文件）")
        lines = self.editor.blockCount()
        if not self.issues:
            self.status.setStyleSheet(f"color: {theme.current().ok};")
            self.status.setText(f"{lines} 行　schema 校验通过")
            return
        errors = [i for i in self.issues if i.is_error]
        color = theme.current().error if errors else theme.current().warning
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(f"{lines} 行　schema {len(errors)} error / "
                            f"{len(self.issues) - len(errors)} warning")
        self.set_tab_suffix(f" — {self.path.name if self.path else '未命名'}"
                            f"{' ●' if self.editor.dirty else ''}")

    def _sync_cursor(self) -> None:
        line, col = self.editor.cursor_position()
        self.cursor_label.setText(f"行 {line}，列 {col}")

    # ════════════════════════════════════════════════════════
    # 诊断跳转
    # ════════════════════════════════════════════════════════

    def goto_issue(self, issue) -> None:
        """双击诊断 → 跳到 YAML 对应行。

        Issue 的 target 形如 `ip_spec.yaml::ips[0].name`，只有 json_path、
        **没有行/列**（jsonschema 对 safe_load 后的数据不产生位置信息）。所以取
        路径最后一段当线索去 `find_line`，取不到就退化成找规则名。
        """
        needle = _needle_of(getattr(issue, "target", ""))
        line = self.editor.find_line(needle) if needle else None
        if line is None:
            line = self.editor.find_line(issue.rule)
        if line is None:
            self.set_status(f"在 YAML 里没找到 '{needle or issue.rule}' 的位置"
                            f"（它可能是从别处推导出来的）")
            return
        self.editor.goto_line(line)
        self.editor.setFocus()
        self.set_status(f"已跳到第 {line} 行：{issue.rule}")
