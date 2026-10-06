"""验证流程 —— 中窗格：启动一次闭环，然后看着它跑。

这个模块存在的理由只有一个：**运行期间没有可观测面**。
在此之前 CLI 是"跑完才打印阶段表"（`commands.py:227`），`watch` 的实时分支
因为 `_runs` 从不被填充而恒返回 None。于是"这次跑到哪了"只能靠等。

实现上刻意选了一条不那么直接的路：**进度来自磁盘上的运行日志**
（`output/{run}/docs/run_events.jsonl`），而不是进程内的信号。

  实时看（QTimer 增量读文件）↔ 历史看（同一条读取路径）
  关掉窗口再打开 → 这次运行还在，还能接着看
  在终端里 `vagent verify` 启动 → 界面里能看见它跑

代价是 500ms 的延迟。对一次跑几分钟的验证流程，这个代价换来的东西太值了。
进程内的 `on_event` 回调仍然接了，但它只是快路径，不是唯一通道。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from .... import bus
from ....ui import theme
from ...base import ModuleBase
from ..run_common import StageTimeline, kind_label, one_line, status_color

#: 默认预设 —— 清单里可以覆盖（`params.presets`）。预设是**参数集合**，
#: 不是控制流：改预设不会让流程走出图之外。
DEFAULT_PRESETS: List[Dict[str, Any]] = [
    {"id": "smoke", "title": "冒烟（1 轮）", "max_rounds": 1, "target": 60.0,
     "approval": "auto"},
    {"id": "full", "title": "全流程（5 轮）", "max_rounds": 5, "target": 95.0,
     "approval": "threshold"},
    {"id": "cover", "title": "只收敛覆盖率", "max_rounds": 8, "target": 95.0,
     "approval": "threshold", "bypass_design_model": True},
]

POLL_MS = 500


class _ApprovalBridge(QObject):
    """运行线程 → GUI 线程的信号编组。

    `on_request` 是在**运行线程**上被调的（审批正在那里阻塞等待）。Qt 的
    跨线程信号会自动排队到接收者所在线程，所以这个 QObject 建在主线程、
    信号一 emit，槽就在主线程跑 —— 与 `tasks.TaskRunner` 同一套机制。
    """

    requested = Signal(object)


class PipelineModule(ModuleBase):
    """闭环流程的启动、观测与审批。"""

    HINT = ("启动一次闭环验证，阶段会随日志一条条亮起来。"
            "进度来自 output/<run>/docs/run_events.jsonl —— 关掉窗口再打开还能接着看。")

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        self.run_id: str = ""
        self._events: List[Dict[str, Any]] = []
        self._seq: int = 0
        self._approval = _ApprovalBridge()
        self._approval.requested.connect(self.on_approval_requested)
        self._timer: Optional[QTimer] = None

    # ════════════════════════════════════════════════════════
    # 界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(self._build_controls(root))

        splitter = QSplitter(Qt.Orientation.Vertical, root)
        self.timeline = StageTimeline(splitter)
        self.timeline.itemSelectionChanged.connect(self._show_selected_stage)
        splitter.addWidget(self.timeline)

        self.tabs = QTabWidget(splitter)
        self.tabs.addTab(self._build_detail_page(), "阶段详情")
        self.tabs.addTab(self._build_log_page(), "实时日志")
        splitter.addWidget(self.tabs)
        splitter.setSizes([320, 260])
        layout.addWidget(splitter, 1)

        self._install_approval_handler()
        self._timer = QTimer(root)
        self._timer.setInterval(int((self.spec.params or {}).get("poll_ms", POLL_MS)))
        self._timer.timeout.connect(self.poll)
        self._timer.start()
        return root

    def _build_controls(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.addWidget(QLabel("规格：", panel))
        self.spec_edit = QLineEdit(panel)
        self.spec_edit.setPlaceholderText("规格文件（spec.md）—— 留空则用启发式")
        row.addWidget(self.spec_edit, 1)
        self.btn_spec = QPushButton("浏览…", panel)
        self.btn_spec.clicked.connect(self.browse_spec)
        row.addWidget(self.btn_spec)
        outer.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("预设：", panel))
        self.preset_box = QComboBox(panel)
        self.preset_box.addItem("（自定义）", None)
        for preset in self._presets():
            self.preset_box.addItem(str(preset.get("title") or preset.get("id")),
                                    preset)
        self.preset_box.currentIndexChanged.connect(self._apply_preset)
        row2.addWidget(self.preset_box)

        row2.addWidget(QLabel("目标：", panel))
        self.target_spin = QDoubleSpinBox(panel)
        self.target_spin.setRange(0, 100)
        self.target_spin.setValue(95.0)
        self.target_spin.setSuffix(" %")
        row2.addWidget(self.target_spin)

        row2.addWidget(QLabel("轮次：", panel))
        self.rounds_spin = QSpinBox(panel)
        self.rounds_spin.setRange(1, 50)
        self.rounds_spin.setValue(5)
        row2.addWidget(self.rounds_spin)

        row2.addWidget(QLabel("审批：", panel))
        self.approval_box = QComboBox(panel)
        for mode, label in (("threshold", "仅高危"), ("interactive", "每次都问"),
                            ("auto", "全自动")):
            self.approval_box.addItem(label, mode)
        row2.addWidget(self.approval_box)
        outer.addLayout(row2)

        row3 = QHBoxLayout()
        self.btn_start = QPushButton("启动", panel)
        self.btn_start.clicked.connect(self.start_run)
        row3.addWidget(self.btn_start)
        self.btn_cancel = QPushButton("停止", panel)
        self.btn_cancel.clicked.connect(self.cancel_run)
        self.btn_cancel.setEnabled(False)
        row3.addWidget(self.btn_cancel)
        self.btn_reload = QPushButton("重新载入日志", panel)
        self.btn_reload.clicked.connect(self.reload_journal)
        row3.addWidget(self.btn_reload)

        self.state_label = QLabel("空闲", panel)
        row3.addWidget(self.state_label, 1)
        outer.addLayout(row3)

        outer.addWidget(self._build_approval_bar(panel))
        return panel

    def _build_approval_bar(self, parent: QWidget) -> QWidget:
        """审批条 —— 平时藏着，运行"卡在等人"时才出现。

        做成**非模态的条**而不是弹框：检查点模式下运行早就结束在这次 astream 上，
        根本没有谁被挂住。弹一个模态框等于假装它还在等，顺手还把界面锁了 ——
        而"可以先去干别的、想好了再来批"正是接检查点换来的东西。

        三个按钮同时服务两种模式（见 `answer_approval`）：检查点的"重入"与通道的
        "回话"对用户是同一件事，不该让他们知道底下有两套。
        """
        bar = QFrame(parent)
        bar.setObjectName("approvalBar")
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)

        self.approval_label = QLabel("", bar)
        self.approval_label.setWordWrap(True)
        layout.addWidget(self.approval_label, 1)

        for text, decision in (("批准", "approve"), ("跳过", "skip"),
                               ("拒绝（终止）", "reject")):
            button = QPushButton(text, bar)
            button.clicked.connect(
                lambda _checked=False, d=decision: self.answer_approval(d))
            layout.addWidget(button)

        bar.setVisible(False)
        self.approval_bar = bar
        return bar

    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self.detail = QPlainTextEdit(page)
        self.detail.setReadOnly(True)
        self.detail.setFont(theme.mono_font())
        self.detail.setPlaceholderText("点时间线上的一条阶段记录，这里显示它的完整内容")
        layout.addWidget(self.detail, 1)
        return page

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self.log_view = QPlainTextEdit(page)
        self.log_view.setReadOnly(True)
        self.log_view.setFont(theme.mono_font())
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setPlaceholderText("运行的事件流会出现在这里")
        layout.addWidget(self.log_view, 1)
        return page

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def create_actions(self) -> List[QAction]:
        start = QAction("启动闭环验证", self.content)
        start.triggered.connect(self.start_run)
        stop = QAction("停止当前运行", self.content)
        stop.triggered.connect(self.cancel_run)
        reload_action = QAction("重新载入运行日志", self.content)
        reload_action.triggered.connect(self.reload_journal)
        return [start, stop, reload_action]

    def on_activated(self) -> None:
        self._refresh_state()

    def on_input_changed(self, path) -> None:
        target = Path(path)
        if target.is_file():
            self.spec_edit.setText(str(target))
            self.set_status(f"规格：{target}")

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者 —— 左窗格换了运行，这里跟着切。"""
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self.follow(run_id)

    # ════════════════════════════════════════════════════════
    # 运行控制
    # ════════════════════════════════════════════════════════

    def start_run(self) -> None:
        preset = self.preset_box.currentData() or {}
        # 仿真业务（工具栏那个下拉）：读**磁盘上的选择**而不是控件 —— 控件在
        # `app.py` 里，这一页够不着它；选择本来就已经落在 `.signoffai/sim_modes.json`
        # （工具层那张表是唯一真相源，见 workbench/sim_modes.py）。
        # 空表 = 选了"无"，**必须原样传**：交给 `start_run` 的默认会变成覆盖率，
        # 那不是人的意思。
        from .... import sim_modes as sim_modes_ui

        args: Dict[str, Any] = {
            "spec_file": self.spec_edit.text().strip(),
            "target": float(self.target_spin.value()),
            "max_rounds": int(self.rounds_spin.value()),
            # 预设里的审批档优先（选中预设时它已经把下拉改过了，
            # 这里再读一次是为了"预设带了但下拉没跟上"的情况）
            "approval": preset.get("approval") or self.approval_box.currentData(),
            "sim_modes": sim_modes_ui.selected_modes(),
        }
        if preset.get("bypass_design_model"):
            args["bypass_design_model"] = True

        payload = self.run_tool("pipeline.start", force=True, **args)
        if payload is None:
            return
        if self.report_payload_error(payload):
            return
        self.run_id = str(payload.get("run_id", ""))
        self._events, self._seq = [], 0
        self.timeline.clear()
        self.log_view.clear()
        self.log(f"已启动运行 {self.run_id}")
        self.log(f"仿真业务：{args['sim_modes'] or ['无']}"
                 "（工具栏下拉可切，改动下次启动生效）")
        self.set_status(f"运行中：{self.run_id}")
        self._refresh_state()
        # **广播出去**：新起的运行要立刻成为"当前运行"，否则订阅 `run.selected`
        # 的那些页（流程视图 / 证据 / 签核判定 / 决策轨迹 / 运行清单 / 七条产出）
        # 全都还停在**上一次**运行上 —— 而此前全工作台只有 `运行历史` 会发这个话题，
        # 还得等你去点一下。表现就是"点了启动，别的页不刷新"。
        # 自己也是订阅者，但 `on_refresh` 有 `run_id != self.run_id` 的守卫，
        # 所以不会绕回来。
        self.ctx.bus.publish(bus.TOPIC_RUN_SELECTED, self.run_id)

    def cancel_run(self) -> None:
        if not self.run_id:
            return
        payload = self.run_tool("pipeline.cancel", force=True, run_id=self.run_id)
        if payload is None:
            return
        if payload.get("cancelled"):
            self.log("已请求取消 —— 当前节点跑完就停在边界上")
            self.set_status("正在取消…")
        else:
            self.show_warning("这次运行已经结束了。")
            self._refresh_state()

    def follow(self, run_id: str) -> None:
        """切到某次运行（可能是历史，也可能是正在跑的）。"""
        self.run_id = run_id
        self._events, self._seq = [], 0
        self.timeline.clear()
        self.log_view.clear()
        self.poll()
        self.log(f"跟随运行 {run_id}")

    def browse_spec(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self.content, "选择规格文件", "", "规格 (*.md *.txt *.yaml);;所有文件 (*)")
        if path:
            self.spec_edit.setText(path)

    def _presets(self) -> List[Dict[str, Any]]:
        raw = (self.spec.params or {}).get("presets")
        return list(raw) if isinstance(raw, list) and raw else DEFAULT_PRESETS

    def _apply_preset(self) -> None:
        preset = self.preset_box.currentData()
        if not preset:
            return
        if preset.get("target") is not None:
            self.target_spin.setValue(float(preset["target"]))
        if preset.get("max_rounds") is not None:
            self.rounds_spin.setValue(int(preset["max_rounds"]))
        mode = preset.get("approval")
        if mode:
            index = self.approval_box.findData(mode)
            if index >= 0:
                self.approval_box.setCurrentIndex(index)

    # ════════════════════════════════════════════════════════
    # 轮询
    # ════════════════════════════════════════════════════════

    def poll(self) -> None:
        """增量读运行日志。**这是整个模块的核心** —— 见模块头。"""
        if not self.run_id:
            self._refresh_state()
            return
        payload = self.run_tool("pipeline.journal", quiet=True,
                                run_id=self.run_id, after_seq=self._seq)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        fresh = payload.get("events") or []
        if fresh:
            self._events.extend(fresh)
            self._seq = int(payload.get("last_seq", self._seq))
            self.timeline.set_events(self._events)
            for event in fresh:
                self._append_log(event)
            self.ctx.bus.publish(bus.TOPIC_RUN_UPDATED, self.run_id)
        self._refresh_state()

    def reload_journal(self) -> None:
        self._events, self._seq = [], 0
        self.timeline.clear()
        self.log_view.clear()
        self.poll()

    def _refresh_state(self) -> None:
        payload = self.run_tool("pipeline.status", quiet=True, run_id=self.run_id)
        state = ""
        if isinstance(payload, dict) and not self.report_payload_error(payload):
            state = str(payload.get("state") or "")
            if payload.get("current"):
                self.btn_cancel.setEnabled(True)
            else:
                self.btn_cancel.setEnabled(False)
        else:
            self.btn_cancel.setEnabled(False)

        # "等人" 单独一档 —— 归进"运行中"的话，一次暂停的运行看起来就像卡住了
        label = {"running": "运行中", "completed": "已完成", "failed": "失败",
                 "cancelled": "已取消", "waiting": "等待审批"}.get(state, "空闲")
        self.state_label.setText(f"{label}　{self.run_id}" if self.run_id else label)
        self.state_label.setStyleSheet(f"color: {status_color(state)};")
        self._sync_approval_bar(state, payload)

    def _sync_approval_bar(self, state: str, status: Any) -> None:
        """运行卡在审批上就把审批条亮出来 —— 两种模式共用这一条。"""
        # 通道模式：运行还活着，挂在别的线程上等人回话。
        # 先看它，因为这时 state 多半还是 "running"，光看日志会漏掉。
        channel = self._channel_approval()
        if channel.get("pending"):
            self.approval_label.setText(
                f"人工审批：{channel.get('stage', '')}　{channel.get('summary', '')}")
            self.approval_bar.setVisible(True)
            return

        # 检查点模式：运行停在检查点上，状态是 waiting
        if state != "waiting":
            self.approval_bar.setVisible(False)
            return

        payload = {}
        if isinstance(status, dict):
            payload = (status.get("last") or {}).get("payload") or {}
        stage = payload.get("stage") or "高风险动作"
        # summary 优先于 reason：声明里写的 prompt 是**给人看的提示语**
        # （"请确认模型改动与规格一致"），reason 是决策引擎的一句话理由。
        # 两者都有时，前者更该摆在人眼前。
        detail = payload.get("summary") or payload.get("reason") or ""
        artifacts = self._artifact_line(payload.get("artifacts"))
        self.approval_label.setText(
            f"等待审批：{stage}"
            + (f"　{detail}" if detail else "")
            + (f"\n{artifacts}" if artifacts else "")
            + "　（运行已停在检查点上，什么时候批都行）")
        self.approval_bar.setVisible(True)

    @staticmethod
    def _artifact_line(artifacts: Any) -> str:
        """审批 payload 里那份产物清单 → 一行话。

        `_interrupt_approval` 带的是**裁剪过**的清单（没有 sha256、没有逐条诊断），
        因为它要进检查点和运行日志。这里只回答一个问题：**哪几份有问题、几处**。
        详情去「产物审查」页看 —— 那里有全文和行号。
        """
        if not isinstance(artifacts, list) or not artifacts:
            return ""
        bad = [a for a in artifacts
               if isinstance(a, dict) and (a.get("errors") or 0) > 0]
        if bad:
            shown = "　".join(f"{a.get('path', '?')} ✗{a.get('errors')} 处" for a in bad[:4])
            more = f"　…还有 {len(bad) - 4} 份" if len(bad) > 4 else ""
            return f"⚠ 产物 {len(bad)} 份 schema 不符：{shown}{more}"
        missing = [a for a in artifacts if isinstance(a, dict) and not a.get("exists")]
        if missing:
            return f"产物 {len(artifacts)} 份，其中 {len(missing)} 份还没生成"
        return f"产物 {len(artifacts)} 份，schema 都过"

    # ── 审批条的两种归属 ──

    def _channel_approval(self) -> Dict[str, Any]:
        payload = self.run_tool("pipeline.pending_approval", quiet=True)
        return payload if isinstance(payload, dict) else {}

    def _channel_approval_pending(self) -> bool:
        return bool(self._channel_approval().get("pending"))

    def answer_approval(self, decision: str = "approve") -> None:
        """审批条上按下某个按钮。

        先问"是不是有人正挂在通道上等"（运行还活着），不是的话就是检查点模式
        （运行早已停下，这一步是**重入**）。对用户是同一件事。
        """
        if not self.run_id:
            return
        if self._channel_approval_pending():
            self.run_tool("pipeline.answer_approval", force=True, quiet=True,
                          decision=decision)
            self.log(f"已回复审批：{decision}")
        else:
            payload = self.run_tool("pipeline.resume", force=True,
                                    run_id=self.run_id, decision=decision)
            if isinstance(payload, dict) and not self.report_payload_error(payload):
                self.log(f"已重入运行：{decision}")
        self.approval_bar.setVisible(False)
        self.poll()

    # ════════════════════════════════════════════════════════
    # 渲染
    # ════════════════════════════════════════════════════════

    def _append_log(self, event: Dict[str, Any]) -> None:
        stage = event.get("title") or event.get("stage") or ""
        head = f"[{kind_label(event.get('kind', ''))}]"
        tail = one_line(event)
        text = f"{head} {stage}{'　' + tail if tail else ''}"
        self.log_view.appendPlainText(text)

    def _show_selected_stage(self) -> None:
        event = self.timeline.selected_event()
        if not event:
            return
        import json
        self.detail.setPlainText(json.dumps(event, ensure_ascii=False, indent=2))

    # ════════════════════════════════════════════════════════
    # 审批
    # ════════════════════════════════════════════════════════

    def _install_approval_handler(self) -> None:
        """把"有人要审批了"接到本模块。

        装在**运行线程**上的是 `self._approval.requested.emit` —— 一个裸 emit。
        真正的对话框在 `on_approval_requested` 里弹，那已经在主线程了。
        """
        payload = self.run_tool("pipeline.approval_handler", force=True, quiet=True,
                                handler=self._approval.requested.emit)
        if payload is None:
            self.log("审批handler 没装上 —— 运行时的审批会走终端通道", "warning")

    def on_approval_requested(self, request: Any) -> None:
        """主线程：弹框问人，然后把答案送回阻塞中的运行线程。"""
        decision = self.confirm_approval(request)
        payload = self.run_tool("pipeline.answer_approval", force=True, quiet=True,
                                decision=decision)
        if isinstance(payload, dict) and not payload.get("answered"):
            # 没人等着了 —— 超时已经降级为 SKIP 并记账
            self.log(f"审批 {getattr(request, 'token', '')} 无人等待（多半已超时）",
                     "warning")
        self.set_status(f"审批结果：{decision}")

    def confirm_approval(self, request: Any) -> str:
        """默认用模态框问人。**测试覆写这个方法**，免得 headless 环境卡在弹框上。

        模态在这里是合理的：流程真的停在那里等这个答案 —— 假装它没停
        （比如做成非阻塞提示条）会让人以为还能继续。
        """
        box = QMessageBox(self.content)
        box.setWindowTitle("人工审批")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"高风险动作需要审批：{getattr(request, 'stage', '')}")
        box.setInformativeText(str(getattr(request, "summary", "")))
        approve = box.addButton("通过", QMessageBox.ButtonRole.AcceptRole)
        reject = box.addButton("拒绝（终止）", QMessageBox.ButtonRole.DestructiveRole)
        skip = box.addButton("跳过此动作", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(approve)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reject:
            return "reject"
        if clicked is skip:
            return "skip"
        return "approve"
