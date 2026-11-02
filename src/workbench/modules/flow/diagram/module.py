"""流程视图 —— 把验证闭环画成一张图：走到哪了、卡在哪一段。

横向一条主线：
    流程控制 → 设计与建模 → 验证构建 → 编译与仿真 → 覆盖率与调试
             → 决策与收敛 → 审查与签核
下面一条虚线**回边**标出"不达标就再来一轮" —— 那是这个流程最要紧的形状，
时间线 `验证流程` 页里摊平了看，这条回路就没了。

**结构和状态分两路**：
  · 结构来自 `flow.stages` 绑定 —— 它读的是领域自己的 `stages.py`。
    界面**不另抄一份阶段清单**：抄了就是第二份真相，改了图没改界面没人发现。
  · 状态来自所选运行的日志。**没选运行就是一片灰**，不编造。

**状态是活的**：自己带一个定时器增量读运行日志（与 `验证流程` 页同一套做法）。
此前只有两个刷新时机 —— 切到这一页、以及有人发 `run.selected`。于是"点了启动
然后切过来看"看到的是一片灰：新运行的 run_id 从来没广播过，而全工作台只有
`运行历史` 会发那个话题（还得等你点一下）。**不靠别人的定时器**：`验证流程`
页是懒加载的，它不开就没有 `run.updated`，所以这里的进度得自己盯。

流程比中窗格宽，所以套在 `QScrollArea` 里横着滚 —— 硬压成窗口宽度会让
每块的字都糊掉。
"""
from __future__ import annotations

from src.workbench.bus import run_id_of

from typing import Any, Dict, List

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ....ui import theme
from ....ui.views import FlowMap
from ...base import ModuleBase

#: 从运行日志里取阶段状态 —— 与 `run_common` 同一口径（同一条线内的共享件）
from ..run_common import stage_statuses

#: 轮询间隔。比 `验证流程` 页的 500ms 松一档：那张图是"逐条亮起来"的看头，
#: 这张图只看每段的落点，1 秒足够，也省得每次都去读日志尾巴。
POLL_MS = 1000

#: 读到这些事件就说明这次运行不会再动了 —— 定时器随之收工
_TERMINAL_KINDS = ("run.finished", "run.failed", "run.cancelled")

#: `journal_summary()` 里表示"已经跑完"的几个 state
_FINISHED_STATES = ("completed", "failed", "cancelled")


class DiagramModule(ModuleBase):
    """闭环流程的结构图 + 本次运行的状态着色。"""

    HINT = ("横向一条主线是流程的七段，下面虚线是「不达标再来一轮」的回边。"
            "选了运行之后，每段按这次的实际状态着色（绿=过了 / 红=失败 / "
            "蓝=在跑 / 灰=还没到），运行期间自己跟着日志走。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""
        #: 增量游标 —— 轮询只取新事件，不重读整份日志
        self._seq: int = 0
        #: `{stage_id: status}` 累积，增量合并
        self._status: Dict[str, str] = {}
        #: 这次运行已经结束 —— 结束了就别再轮询
        self._finished: bool = False
        self._timer: QTimer | None = None

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

        self.count_label = QLabel("（还没选中运行 —— 结构照画，状态先留灰）", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)

        # 流程图比中窗格宽 —— 套滚动区，横着滚比压扁好
        scroll = QScrollArea(root)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(
            scroll.alignment().__class__.AlignLeft | scroll.alignment().__class__.AlignTop)
        self.chart = FlowMap(scroll)
        scroll.setWidget(self.chart)
        layout.addWidget(scroll, 1)

        self._timer = QTimer(root)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        return root

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新流程视图", self.content)
        action.triggered.connect(self.refresh)
        return [action]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        self.refresh()

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者 —— 换一次运行就重取状态。"""
        run_id = run_id_of(payload)
        if run_id and run_id != self.run_id:
            self.run_id = run_id
            self._load_status(run_id)

    def refresh(self) -> None:
        """结构每次都重取（清单/流程改了要跟上）；状态跟着当前选中的运行。"""
        self._load_flow()
        if self.run_id:
            self._load_status(self.run_id)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def _load_flow(self) -> None:
        model = self.run_tool("flow.stages")
        if not isinstance(model, dict) or self.report_payload_error(model):
            if model is not None:
                self.chart.set_flow({})
            return
        self.chart.set_flow(model)

    def _load_status(self, run_id: str) -> None:
        """换了一次运行 —— 整份重取（游标、状态、是否已结束都要重置）。

        **这里也记下 `run_id`**：状态和"当前看的是哪次运行"必须一起变。分开写
        的话迟早会出现"画面按 r2 上色、计数标签却写着 r1"这种自相矛盾的状态。
        """
        self.run_id = run_id
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        events = detail.get("events") or []
        self._seq = max((int(e.get("seq", 0) or 0) for e in events), default=0)
        self._status = dict(stage_statuses(events))
        # 已经跑完的运行不必再轮询 —— 它不会再动
        self._finished = str(detail.get("state") or "") in _FINISHED_STATES
        if self._finished:
            self._timer.stop()          # 别每秒空转一次
        else:
            self._timer.start()
        self.chart.set_status(self._status)
        self._update_count()

    def _tick(self) -> None:
        """运行期间跟着日志走 —— 增量读，只取新增的那几条。"""
        if not self.run_id or self._finished:
            return
        payload = self.run_tool("pipeline.journal", quiet=True,
                                run_id=self.run_id, after_seq=self._seq)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        fresh = payload.get("events") or []
        if not fresh:
            return
        self._seq = int(payload.get("last_seq", self._seq) or self._seq)
        # 后出现的覆盖先出现的 —— 与 `stage_statuses` 同一口径
        self._status.update(stage_statuses(fresh))
        self.chart.set_status(self._status)
        self._update_count()
        if any(e.get("kind") in _TERMINAL_KINDS for e in fresh):
            self._finished = True
            self._timer.stop()          # 跑完了，收工

    def _update_count(self) -> None:
        if not self.run_id:
            self.count_label.setText("（还没选中运行 —— 结构照画，状态先留灰）")
            return
        done = sum(1 for s in self._status.values() if s in ("ok", "passed"))
        bad = sum(1 for s in self._status.values() if s in ("failed", "error"))
        text = f"{self.run_id}：{done} 个阶段已过"
        if bad:
            text += f"，{bad} 个失败"
        if self._finished:
            text += "　（已结束）"
        self.count_label.setText(text)
