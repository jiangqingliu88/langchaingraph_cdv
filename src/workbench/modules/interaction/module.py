"""PySide6 前端：自然语言、候选计划和进入既有验证流程的入口。

它只调用 modes.interaction / agent_mode_service。验证页面不写第二份：
打开现有 flow.pipeline，并在工作线程内通过 TaskRunner 送达后台调用。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.workbench.modes.interaction import model_configuration_label, pending_text, resume, turn
from src.workbench.modules.base import ModuleBase
from src.workbench.modules.service.common import open_module, publish_run
from src.workbench.ui import theme


class InteractionModule(ModuleBase):
    HINT = (
        "PySide6 桌面前端，与 CLI/REPL 共用 Agent、Harness 和 Workspace。"
        "对话与候选计划不是签核证据。真实验证进入已有「验证流程」视图；"
        "需要执行/写入时，先经过真实人工审批。切换模式会开启新任务，不删旧会话。"
    )

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        self._jobs: set[str] = set()
        self._task_signals_bound = False
        self._wait_started_at = 0.0
        self._wait_warning_was_sent = False
        self.session_id = ""
        self._last_result: dict[str, Any] = {}
        self.agent_caller: Callable[..., dict[str, Any]] | None = None  # 用例注入；不默认调用
        self._mode_options = (("对话 chat", "chat"), ("候选计划 plan", "plan"), ("显式验证 verify", "verify"))

    def create_widget(self) -> QWidget:
        widget = super().create_widget()
        # 真实窗口只通过这里构建本模块。必须自己接收返回 payload，
        # 不能只依赖主窗口把“任务已完成”写进全局控制台。
        if not self._task_signals_bound:
            self.ctx.tasks.finished.connect(self.on_finished)
            self.ctx.tasks.failed.connect(self.on_error)
            self._task_signals_bound = True
        return widget

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(6)
        title = QLabel("三种入口 · 一个验证内核")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        info = QLabel(
            "对话用于解释与探索；计划必须经过人工审查；只有点击验证才进入执行主链。"
            "模型按既有配置调用，不在对话中收集或保存密码/API Key。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addLayout(self._controls())
        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.addWidget(self._conversation_page())
        splitter.addWidget(self._details_page())
        splitter.setSizes([700, 360])
        layout.addWidget(splitter, 1)
        self.approval = self._approval_page()
        layout.addWidget(self.approval)
        self.approval.setVisible(False)
        self.wait_timer = QTimer(root)
        self.wait_timer.setInterval(1000)
        self.wait_timer.timeout.connect(self._show_wait_state)
        return root

    def _controls(self):
        line = QHBoxLayout()
        self.mode = QComboBox()
        for label, key in self._mode_options:
            self.mode.addItem(label, key)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        line.addWidget(self.mode)
        self.workspace = QLineEdit(str(Path.cwd()))
        self.workspace.setToolTip("交给原 agent_mode_service 的项目工作区，当前值由用户明确指定")
        self.workspace.setPlaceholderText("项目工作区绝对路径")
        line.addWidget(self.workspace, 1)
        self.model_status = QLabel(model_configuration_label())
        self.model_status.setWordWrap(False)
        line.addWidget(self.model_status)
        browse = QPushButton("选择工作区")
        browse.clicked.connect(self._browse_workspace)
        line.addWidget(browse)
        self.new_task_button = QPushButton("新任务")
        self.new_task_button.clicked.connect(self.new_task)
        line.addWidget(self.new_task_button)
        self.open_flow_button = QPushButton("打开验证流程")
        self.open_flow_button.clicked.connect(self.open_verification)
        line.addWidget(self.open_flow_button)
        return line

    def _conversation_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setMaximumBlockCount(600)
        self.history.setFont(theme.mono_font())
        layout.addWidget(self.history, 1)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("输入自然语言问题，或切换到显式验证后填写明确目标…")
        self.question.setMaximumHeight(125)
        layout.addWidget(self.question)
        row = QHBoxLayout()
        self.state = QLabel("等待输入")
        self.state.setWordWrap(True)
        row.addWidget(self.state, 1)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self.send_turn)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        return page

    def _details_page(self) -> QWidget:
        tabs = QTabWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumBlockCount(500)
        self.details.setFont(theme.mono_font())
        tabs.addTab(self.details, "真实状态 / 原始结果")
        help_text = QPlainTextEdit()
        help_text.setReadOnly(True)
        help_text.setPlainText(
            "CHAT：同一个 agent_turn()，多轮继续使用原 session。\n"
            "PLAN：要求真实计划检查点，approval=人工确认，不是自动执行。\n"
            "VERIFY：走已有 verify_mode/router，入口动作不等于 PASS。\n\n"
            "终端：vagent、vagent chat、vagent -r <session_id>。\n"
            "GUI：PySide6 QMainWindow；执行与审批详情由 flow.pipeline 承接。\n\n"
            "本前端不宣称秒级流式 LLM 推理。完整响应/失败状态由\n"
            "TaskRunner 在工作线程中返回，避免阻塞 Qt 主线程。"
        )
        tabs.addTab(help_text, "入口与边界")
        return tabs

    def _approval_page(self) -> QFrame:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        root = QVBoxLayout(panel)
        self.pending_label = QLabel("")
        self.pending_label.setWordWrap(True)
        root.addWidget(self.pending_label)
        self.reply = QPlainTextEdit()
        self.reply.setPlaceholderText("补充回答；或在审批计划时填写经过人审的调整版本…")
        self.reply.setMaximumHeight(90)
        root.addWidget(self.reply)
        buttons = QHBoxLayout()
        self.accept_button = QPushButton("批准/回答并继续")
        self.accept_button.clicked.connect(lambda: self.resume_pending(True))
        buttons.addWidget(self.accept_button)
        reject = QPushButton("拒绝")
        reject.clicked.connect(lambda: self.resume_pending(False))
        buttons.addWidget(reject)
        root.addLayout(buttons)
        return panel

    def _workspace_value(self) -> str:
        return self.workspace.text().strip()

    def _submit(self, label: str, operation: Callable[[], dict[str, Any]]) -> None:
        if self._jobs:
            self.state.setText("当前任务仍在工作线程中，请等待结果，避免重复提交。")
            return
        task_id = self.ctx.tasks.submit(label, operation, module_id=self.module_id, operation="interaction.turn")
        self._jobs.add(task_id)
        self.wait_started_at = time.monotonic()
        self.wait_timer.start()
        self.send_button.setEnabled(False)
        self.mode.setEnabled(False)
        self.workspace.setEnabled(False)
        self.state.setText(f"{task_id}：等待原有 Agent/Engine 返回真实状态…")

    def _show_wait_state(self) -> None:
        if not self._jobs:
            self.wait_timer.stop()
            return
        task_id = sorted(self._jobs)[0]
        record = self.ctx.tasks.record(task_id)
        phase = getattr(record, "status", "running") or "running"
        elapsed = max(0, int(time.monotonic() - self._wait_started_at))
        self.state.setText(f"{task_id}：{phase}，已等待 {elapsed}s；尚未收到完成或失败结果。")
        if elapsed >= 15 and not self._wait_warning_was_sent:
            self._wait_warning_was_sent = True
            self.show_warning(
                "等待已超过 15 秒，Agent 没有返回完成或失败结果。请检查模型配置和会话记录；等待本身不代表成功或超时。"
            )

    def send_turn(self) -> None:
        text = self.question.toPlainText().strip()
        if not text:
            self.state.setText("请先输入问题或明确的验证目标。")
            return
        mode = self.mode.currentData()
        workspace = self._workspace_value()
        self.history.appendPlainText(f"\n[用户 / {mode}] {text}")
        self._submit(
            "agent" if mode != "verify" else "verification",
            lambda: turn(
                text,
                mode=mode,
                workspace=workspace,
                session_id=self.session_id or None,
                frontend="gui",
                agent_caller=self.agent_caller,
            ),
        )

    def on_finished(self, task_id: str, result: Any) -> None:
        if task_id not in self._jobs:
            return
        if not isinstance(result, dict):
            self.on_error(task_id, "返回结果不是 dict")
            return
        self._jobs.discard(task_id)
        self._ready_controls()
        self._last_result = result
        self.session_id = str(result.get("session_id") or self.session_id)
        status = str(result.get("status") or result.get("verdict") or "unknown")
        summary = str(result.get("summary") or result.get("reason") or status)
        self.state.setText(f"真实状态：{status}    session={self.session_id or '-'}")
        self.history.appendPlainText(f"\n[{status}] {summary}")
        error = result.get("error")
        if error:
            self.history.appendPlainText(f"错误：{error}")
            self.show_error(str(error))
        elif status in ("blocked", "failed", "error", "invalid"):
            self.show_warning(f"Agent 未完成：{summary}")
        elif status == "proposal":
            self.show_warning("当前结果是候选提案，仍需人工复核，不是验证通过")
        self.details.setPlainText(json.dumps(result, ensure_ascii=False, default=str, indent=2))
        pending = pending_text(result)
        self.approval.setVisible(bool(pending and result.get("pending")))
        self.pending_label.setText(pending)
        if result.get("run_id"):
            # 只发布真实引擎返回的 run_id，不生成视图侧 run。
            publish_run(self.ctx, str(result["run_id"]))

    def on_error(self, task_id: str, message: str) -> None:
        if task_id not in self._jobs:
            return
        self._jobs.discard(task_id)
        self._last_result = {"status": "error", "error": str(message), "session_id": self.session_id}
        self.approval.setVisible(False)
        self.details.setPlainText(json.dumps(self._last_result, ensure_ascii=False))
        self.history.appendPlainText(f"[调用失败] {str(message)[:1000]}")
        self.show_error(f"调用失败：{str(message)[:1000]}")
        self._ready_controls()
        self.state.setText(f"调用失败：{str(message)[:1000]}")

    def _ready_controls(self) -> None:
        self.wait_timer.stop()
        self.workspace.setEnabled(True)
        self.send_button.setEnabled(True)
        self.mode.setEnabled(True)
        if self._wait_warning_was_sent:
            self.clear_banner()
        self._wait_warning_was_sent = False

    def resume_pending(self, approve: bool) -> None:
        pending = self._last_result.get("pending") or {}
        if not self._has_resume_session():
            return
        if pending.get("kind") == "answer" and not self.reply.toPlainText().strip():
            self.state.setText("请先填写需要补充的回答。")
            return
        self._submit(
            "Resume the original harness checkpoint",
            lambda: resume(
                self.session_id,
                workspace=self._workspace_value(),
                approve=approve,
                answer=self.reply.toPlainText(),
                plan=self.reply.toPlainText(),
                frontend="gui",
            ),
        )

    def _has_resume_session(self) -> bool:
        if self.session_id and self._last_result.get("pending"):
            return True
        self.state.setText("没有可恢复的真实 Agent 会话或待审批事项。")
        return False

    def new_task(self) -> None:
        # 清除的是前端关联；Harness 已有 session 文件保持原样。
        self.session_id = ""
        self._last_result = {}
        self.approval.setVisible(False)
        self.history.appendPlainText("\n── 新任务（旧会话仍保留在工作区）──")
        self.state.setText("等待新目标")

    def _mode_changed(self, _index: int) -> None:
        if hasattr(self, "state"):
            self.new_task()
            self.state.setText(f"当前模式：{self.mode.currentData()}")

    def _browse_workspace(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self.content, "选择项目工作区", self.workspace.text())
        if chosen:
            self.workspace.setText(chosen)

    def open_verification(self) -> None:
        if open_module(self.ctx, "flow.pipeline"):
            self.set_status("已打开原有验证流程；运行状态与审批仍以原始证据为准")
        else:
            self.set_status("当前窗口未提供 flow.pipeline，没有伪造第二个验证页面")

    def on_input_changed(self, path) -> None:
        self.question.setPlainText(self.question.toPlainText() + f"\n请分析输入文件：{path}")
