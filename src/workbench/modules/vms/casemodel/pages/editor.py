"""编辑 YAML —— 打开 / 改 / 保存模型文件。

**为什么是文本编辑器而不是表单编辑器**：分析管线是 `YAML → CaseModel`，
归一化是有损的（注释、键顺序、别名写法都会变，`RANDOM` 会被改写成 `RND`）。
若从解析后的模型重新生成 YAML 再写盘，用户的注释和格式就没了。
所以这里编辑的是**原文**，保存时原样写回 —— 只有一个真相，就是这段文本；
其它页面都是它的**视图**（分析结果），不会反过来改它。

保存流程：schema 校验 → 有 error 先问 → 写盘 → 重新分析 → 全部页面刷新。
所以「保存即校验、保存即生效」。
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from src.workbench.ui import theme
from src.workbench.ui.yaml_editor import YamlEditor

from ..page import Page
from ..vocabulary import ENUM_VALUES, SKELETON_KEYS


class EditorPage(Page):
    TITLE = "编辑 YAML"
    HINT = ("直接编辑模型原文，保存时原样写回 —— 注释与格式都保留。\n"
            "Ctrl+S 保存　Ctrl+O 打开　Ctrl+R 重新分析　Tab 插两个空格。"
            "保存前会自动跑 schema 校验；保存后自动重新分析并刷新其它页面；"
            "「重新分析」可以让未保存的改动立刻生效。")

    def build(self) -> None:
        outer = self.frame()

        bar = QHBoxLayout()
        for text, slot in (("打开…", self.module.on_open),
                           ("保存", self.module.save_model),
                           ("另存为…", self.module.save_model_as),
                           ("重新分析", self.module.reanalyze)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addSpacing(8)

        self.dirty_label = QLabel("")
        self.dirty_label.setStyleSheet(
            f"color: {theme.SEVERITY['error'].name()}; font-weight: bold;")
        bar.addWidget(self.dirty_label)

        self.file_label = QLabel("（未打开文件）")
        self.file_label.setStyleSheet(f"color: {theme.MUTED.name()};")
        bar.addWidget(self.file_label)
        bar.addStretch(1)
        outer.addLayout(bar)

        outer.addWidget(self.hint_label())

        self.editor = YamlEditor(
            self, skeleton_keys=SKELETON_KEYS, enum_values=ENUM_VALUES,
            placeholder="在此编辑 case 模型 YAML，或按 Ctrl+O 打开文件…")
        self.editor.contentChanged.connect(self._on_content_changed)
        self.editor.cursorPositionChanged.connect(self._sync_cursor)
        outer.addWidget(self.editor, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        bottom.addWidget(self.status)
        bottom.addStretch(1)
        self.cursor_label = QLabel("")
        self.cursor_label.setStyleSheet(f"color: {theme.MUTED.name()};")
        bottom.addWidget(self.cursor_label)
        outer.addLayout(bottom)

        self._sync_cursor()

    # ════════════════════════════════════════════════════════
    # 给模块用的接口
    # ════════════════════════════════════════════════════════

    def set_text(self, text: str) -> None:
        self.editor.set_text(text)
        self._sync_footer()

    def get_text(self) -> str:
        return self.editor.text()

    def mark_clean(self) -> None:
        self.editor.mark_clean()
        self._sync_footer()

    @property
    def dirty(self) -> bool:
        return self.editor.dirty

    def focus_editor(self) -> None:
        self.editor.setFocus()

    def refresh_status(self) -> None:
        """只重画脚下那行 —— 供模块在「提前返回」的路径上调用。"""
        self._sync_footer()

    def goto_line(self, line: int) -> None:
        self.editor.goto_line(line)
        self.editor.setFocus()

    def goto_issue(self, issue) -> None:
        """跳到某条诊断对应的 YAML 行。

        这就是 Verdi 那种「点错误 → 跳到源码」的手感。诊断的 target 形如
        `dimension::D_if` / `field::D_mode.反压模式`，从中取最后一段当线索；
        取不到就退化成找规则名，再找不到就退回文件开头并说明。
        """
        needle = ""
        if getattr(issue, "target", ""):
            needle = issue.target.split("::")[-1].split(".")[-1].strip()
        line = self.editor.find_line(needle) if needle else None
        if line is None:
            line = self.editor.find_line(issue.rule)
        if line is None:
            self.module.set_status(
                f"在 YAML 里没找到 '{needle or issue.rule}' 的位置"
                f"（它可能是从别处推导出来的）")
            return
        self.editor.goto_line(line)
        self.editor.setFocus()
        self.module.set_status(f"已跳到第 {line} 行：{issue.rule}")

    # ════════════════════════════════════════════════════════
    # 事件
    # ════════════════════════════════════════════════════════

    def _on_content_changed(self, _first: bool) -> None:
        self._sync_footer()
        self.module.notify_editor_changed()      # 标签页的 ● 与状态栏跟着变

    def _sync_cursor(self) -> None:
        line, col = self.editor.cursor_position()
        self.cursor_label.setText(f"行 {line}，列 {col}")

    def _sync_footer(self) -> None:
        self.dirty_label.setText("● 未保存" if self.editor.dirty else "")
        self.file_label.setText(str(self.module.path) if self.module.path
                                else "（未打开文件）")
        self._set_status(self.module.schema_issues)

    def _set_status(self, issues) -> None:
        lines = self.editor.blockCount()
        if not issues:
            self.status.setStyleSheet(f"color: {theme.COVERAGE['full'].name()};")
            self.status.setText(f"{lines} 行　schema 校验通过")
            return
        errors = [i for i in issues if i.is_error]
        color = theme.SEVERITY["error"] if errors else theme.SEVERITY["warning"]
        self.status.setStyleSheet(f"color: {color.name()};")
        head = (f"{lines} 行　schema {len(errors)} error / "
                f"{len(issues) - len(errors)} warning")
        self.status.setText(head + (f"　| 首条：{issues[0]}" if issues else ""))

    def refresh(self, result) -> None:
        """只更新状态行 —— **绝不动文本**。

        文本是用户的输入；刷新分析结果时把它覆盖掉是灾难性的。
        这个页面刻意**不实现 `clear()`**：没有结果时也不该清掉用户正编的内容。
        """
        self._sync_footer()
