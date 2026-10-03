"""Case 属性表 —— 文档十六节，那张表才是 case 的真正主体。

命名是人读的坐标，属性表才是机器可检索的坐标。选中一行，右侧看完整属性
（含环境指纹与覆盖仓）—— 详情直接取模型里的 UserRole，不回查第二遍。
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QPlainTextEdit, QSplitter, QVBoxLayout, QWidget

from src.workbench.ui import theme

from ..models import CaseTableModel
from ..page import Page

_BASE_HINT = ("按属性组合生成，case_id 形如 TC-<对象>-<节点>-<方法>-<NN>。"
              "选中一行看完整属性（环境指纹与覆盖仓也在里面）。")


class CasesPage(Page):
    TITLE = "Case 属性表"
    HINT = _BASE_HINT

    def build(self) -> None:
        outer = self.frame()
        self.hint = self.hint_label()
        outer.addWidget(self.hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.model = CaseTableModel(self)
        self.view = self.make_table(self.model)
        self.view.selectionModel().currentRowChanged.connect(self._on_row)
        splitter.addWidget(self.view)

        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(self.section_label("case 属性　文档十六节最小字段集"))
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(theme.mono_font())
        detail_layout.addWidget(self.detail, 1)
        splitter.addWidget(detail_box)

        splitter.setSizes([900, 460])
        outer.addWidget(splitter, 1)

    def _on_row(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self.detail.clear()
            return
        # 视图可能套了排序代理 —— 行号要映射回源模型，否则详情会张冠李戴
        source = self.source_index(self.view, current)
        case = self.model.data(source, Qt.ItemDataRole.UserRole)
        if case is None:
            self.detail.setPlainText("")
            return
        lines = [
            f"case_id        : {case.case_id}",
            f"对象 L1        : {case.object}",
            f"专题           : {case.theme or '（无）'}   优先级 {case.priority or '—'}",
            f"树路径 L2      : {case.tree_path or '（不作用功能组织树）'}",
            f"交叉组         : {case.cross_group or '（无）'}",
            "",
            "维度 L3        :",
        ]
        lines += [f"  - {d}" for d in case.dimensions] or ["  - （无）"]
        lines += ["", "字段 L4        :"]
        lines += [f"  {k:<14} = {v}" for k, v in case.fields.items()] or ["  （无）"]
        lines += ["", f"方法 L5        : {case.method} {case.method_name}",
                  "检查 L6        :"]
        lines += [f"  - {c}" for c in case.check_labels()] or ["  - （无）"]
        lines += ["", "覆盖仓         :"]
        lines += [f"  - {b}" for b in case.cover_bins] or ["  - （未映射）"]
        lines += ["", "环境指纹       :"]
        lines += ([f"  {k:<18} = {v}" for k, v in case.environment.items()]
                  or ["  （无）"])
        lines += ["", f"期望结果       : {case.expected_result or '（未声明）'}",
                  f"seed           : {case.seed}"]
        self.detail.setPlainText("\n".join(lines))

    def refresh(self, result) -> None:
        gen = result.generation
        self.model.set_cases(gen.cases)
        tail = f"seed={gen.seed}（同 seed 结果一致）　驱动 {gen.driver}，共 {gen.count} 个"
        if gen.truncated:
            tail += (f"　组合规模 {gen.total_before_cap} 超过上限，"
                     f"已截断丢弃 {gen.dropped} 个")
        self.hint.setText(f"{_BASE_HINT}　　{tail}")

    def clear(self) -> None:
        self.model.set_cases([])
        self.detail.clear()
