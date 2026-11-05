"""UVM 自动化验证服务入口。

一个中央工作页，内部按**步骤**导航：项目输入 → 验证配置 → 环境生成 →
仿真 → 交付。每一步都只做两件事：收参数 / 把用户送到已有的专业模块；
**不重写 UVM 生成器、仿真器或报告引擎**。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout,
    QWidget,
)

from ..base import ModuleBase
from .common import open_module, publish_run

STEPS = ("项目输入", "验证配置", "环境生成", "仿真", "交付")


class UVMServiceModule(ModuleBase):
    HINT = "按步骤走完一次 UVM 验证；每一步都复用已有的专业模块。"

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self._run_id = ""

    # ── 页面 ──

    def build_content(self) -> QWidget:
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        self.steps = QListWidget(root)
        self.steps.addItems(list(STEPS))
        self.steps.setFixedWidth(150)
        self.steps.currentRowChanged.connect(self._step_changed)
        outer.addWidget(self.steps)

        self.stack = QStackedWidget(root)
        self.stack.addWidget(self._input_page())
        self.stack.addWidget(self._config_page())
        self.stack.addWidget(self._env_page())
        self.stack.addWidget(self._sim_page())
        self.stack.addWidget(self._deliver_page())
        outer.addWidget(self.stack, 1)
        self.steps.setCurrentRow(0)
        return root

    def _page(self) -> tuple:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        return page, layout

    def _input_page(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(QLabel("选择或填写本次验证的输入。RTL 与 Spec 可以同时给："
                                "RTL 作为 DUT，Spec 作为分析/参考模型输入。"))
        form = QFormLayout()
        self.rtl_edit = QLineEdit()
        self.rtl_edit.setPlaceholderText("./rtl")
        form.addRow("RTL 输入目录", self._with_browse(self.rtl_edit, "dir"))
        self.spec_edit = QLineEdit()
        self.spec_edit.setPlaceholderText("./spec.md")
        form.addRow("Spec 文件", self._with_browse(self.spec_edit, "file"))
        self.config_edit = QLineEdit()
        self.config_edit.setPlaceholderText("可选：case 模型 YAML（复制到 run 的 inputs/casemodel.yaml）")
        form.addRow("Case 模型", self._with_browse(self.config_edit, "file"))
        layout.addLayout(form)
        layout.addWidget(_muted("Case 模型留空时，流水线会找 specs/<module>/casemodel.yaml；"
                                "填了就以这份为准。"))
        row = QHBoxLayout()
        row.addWidget(_button("打开 IP 规格", lambda: open_module(self.ctx, "ide.ip_spec")))
        row.addWidget(_button("下一步：验证配置", lambda: self.steps.setCurrentRow(1)))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _config_page(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(QLabel("验证配置由 case 模型和激励工具承担，本页只做入口。"))
        row = QHBoxLayout()
        row.addWidget(_button("打开 Case 建模", lambda: open_module(self.ctx, "verify.casemodel")))
        row.addWidget(_button("打开 ISA 激励", lambda: open_module(self.ctx, "verify.isa_gen")))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(_muted("编辑的是 YAML/激励输入；保存后回到本服务继续。"))
        layout.addStretch(1)
        return page

    def _env_page(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(QLabel("环境生成与闭环编排在「验证流程」里执行；"
                                "本页不复制生成器。"))
        row = QHBoxLayout()
        row.addWidget(_button("打开验证流程", lambda: open_module(self.ctx, "flow.pipeline")))
        row.addWidget(_button("打开运行历史", lambda: open_module(self.ctx, "flow.runs")))
        row.addStretch(1)
        layout.addLayout(row)
        self.env_label = QLabel("当前运行：未选择")
        layout.addWidget(self.env_label)
        layout.addStretch(1)
        return page

    def _sim_page(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(QLabel("参数确认后启动一次闭环；启动立即返回 run_id，"
                                "运行过程在「验证流程」/「运行历史」里看。"))
        form = QFormLayout()
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0.0, 100.0)
        self.target_spin.setValue(95.0)
        self.target_spin.setSuffix(" %")
        form.addRow("覆盖率目标", self.target_spin)
        self.rounds_spin = QSpinBox()
        self.rounds_spin.setRange(1, 50)
        self.rounds_spin.setValue(5)
        form.addRow("最大轮次", self.rounds_spin)
        self.approval_combo = QComboBox()
        self.approval_combo.addItems(["threshold", "auto", "interactive"])
        form.addRow("审批模式", self.approval_combo)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(_button("启动验证", self._start_run, primary=True))
        row.addWidget(_button("打开验证流程", lambda: open_module(self.ctx, "flow.pipeline")))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _deliver_page(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(QLabel("交付物是 run 目录与证据包；本页只做入口。"))
        row = QHBoxLayout()
        row.addWidget(_button("验证产出", lambda: open_module(self.ctx, "verify.output")))
        row.addWidget(_button("证据 / 产物", lambda: open_module(self.ctx, "flow.evidence")))
        row.addWidget(_button("签核判定", lambda: open_module(self.ctx, "flow.signoff")))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    # ── 行为 ──

    def _with_browse(self, edit: QLineEdit, kind: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        row.addWidget(_button("浏览…", lambda: self._browse(edit, kind)))
        return box

    def _browse(self, edit: QLineEdit, kind: str) -> None:
        if kind == "dir":
            path = QFileDialog.getExistingDirectory(self.content, "选择 RTL 目录")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self.content, "选择 Spec", "", "Spec (*.md *.txt);;All files (*)")
        if path:
            edit.setText(str(Path(path)))

    def _start_run(self) -> None:
        spec_file = self.spec_edit.text().strip()
        rtl_dir = self.rtl_edit.text().strip()
        if not spec_file and not rtl_dir:
            self.show_warning("至少给一个 Spec 或 RTL 目录")
            return
        payload = self.run_tool(
            "pipeline.start", force=True, spec_file=spec_file, rtl_dir=rtl_dir,
            casemodel=self.config_edit.text().strip(),
            target=float(self.target_spin.value()),
            max_rounds=int(self.rounds_spin.value()),
            approval=self.approval_combo.currentText())
        if not isinstance(payload, dict):
            return
        run_id = str(payload.get("run_id") or "")
        if run_id:
            self._run_id = run_id
            self.env_label.setText(f"当前运行：{run_id}")
            publish_run(self.ctx, run_id)
            self.show_info(f"已启动：{run_id}")
            open_module(self.ctx, "flow.pipeline")
        else:
            self.show_error(str(payload.get("error") or "启动失败（没有 run_id）"))

    def on_refresh(self, payload=None) -> None:
        from .common import selected_run
        run_id = selected_run(payload)
        if run_id:
            self._run_id = run_id
            if hasattr(self, "env_label"):
                self.env_label.setText(f"当前运行：{run_id}")

    def _step_changed(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)


def _button(text: str, slot, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(slot)
    if primary:
        button.setDefault(True)
    return button


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6b6b6b;")
    return label
