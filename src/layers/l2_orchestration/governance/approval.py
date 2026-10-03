"""
人工审批门控模块

借鉴原型设计的 input() 审批，升级为多模式可配置版本。
支持 interactive / auto / threshold 三种模式，完整审计记录。

用法:
  gate = create_approval_gate("interactive")
  if gate.requires_approval("rtl", "medium"):
      record = gate.ask("rtl", summary, "medium")
      if record.decision == ApprovalDecision.REJECT:
          raise PipelineTerminatedError(...)
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════
# 审批决策
# ═══════════════════════════════════════════════════════════════

class ApprovalDecision(str, Enum):
    APPROVE = "approve"     # 通过，继续
    REJECT = "reject"       # 拒绝，终止流程
    SKIP = "skip"           # 跳过此阶段，继续后续
    REVIEW = "review"       # 查看详情后再决定


# ═══════════════════════════════════════════════════════════════
# 审批记录
# ═══════════════════════════════════════════════════════════════

@dataclass
class ApprovalRecord:
    stage: str
    decision: ApprovalDecision
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    reviewer: str = "human"
    reason: str = ""
    context_snapshot: Optional[Dict] = None
    token: str = ""


@dataclass
class ApprovalRequest:
    """一次待决策的审批。

    比 ApprovalRecord 多的是**为什么问**与**等多久**：GUI 弹框要有摘要，
    无人的线程不能无限期挂着。
    """

    stage: str
    summary: str
    risk_level: str = "low"
    token: str = ""
    timeout_s: float = 0.0        # 0 = 不超时（终端交互的默认）


# ═══════════════════════════════════════════════════════════════
# 审批通道 —— 「怎么问」与「问了之后干什么」分开
# ═══════════════════════════════════════════════════════════════
#
# 为什么要有这一层：`ApprovalGate.ask()` 原本直接调 `input()`。这在终端里没问题，
# 但在**服务层**是致命的 —— `n_approval` 是 async 节点，同步阻塞的 input() 会把
# 整个事件循环卡死，GUI 那边看到的是界面假死。
#
# 抽成通道之后：
#   · ConsoleChannel —— 今天的终端行为，逐字节保留
#   · AutoChannel    —— 无人值守
#   · EventChannel   —— GUI：跨线程等待，**阻塞的是运行线程，不是 GUI 线程**


class ApprovalChannel(Protocol):
    """返回 None 表示"没人回答"（超时/通道不可用），由调用方决定降级策略。"""

    def ask(self, request: ApprovalRequest) -> Optional[ApprovalDecision]:
        ...


class ConsoleChannel:
    """终端交互 —— 复刻 ApprovalGate 原本的提示文案与按键语义。

    这一段的行为是**对外契约**（有人习惯了 y/n/s/d/r/q），所以照抄，不"优化"。
    """

    PROMPT = ("  确认通过并继续？\n"
              "  [y] 通过  [n] 拒绝(终止)  [s] 跳过此阶段  [d] 查看详情\n"
              "  [r] 转人工复核(本次不执行该动作)  [q] 退出\n"
              "  选择: ")

    _CHOICES = {"y": ApprovalDecision.APPROVE, "n": ApprovalDecision.REJECT,
                "s": ApprovalDecision.SKIP, "r": ApprovalDecision.REVIEW}

    def __init__(self, input_func: Callable = input, output_func: Callable = print):
        self._input = input_func
        self._output = output_func

    def ask(self, request: ApprovalRequest) -> Optional[ApprovalDecision]:
        self._output(f"\n{'='*60}")
        self._output(f"🔴 审批节点: {request.stage}")
        self._output(f"   风险等级: {request.risk_level.upper()}")
        self._output(f"   摘要: {request.summary}")
        self._output(f"{'='*60}")

        while True:
            choice = (self._input(self.PROMPT) or "").strip().lower()
            if choice in self._CHOICES:
                decision = self._CHOICES[choice]
                if decision == ApprovalDecision.REVIEW:
                    self._output("  ⏸️ 已标记待人工复核；本次不执行该动作，闭环继续但跳过它。")
                return decision
            if choice == "d":
                self._output(f"  📋 完整上下文: {request.summary}")
                continue
            if choice == "q":
                self._output("🛑 用户退出流程")
                sys.exit(0)
            self._output("  请输入 y/n/s/d/r/q")


class AutoChannel:
    """无人值守 —— 固定返回一个决策（`--approval auto` 走这里）。"""

    def __init__(self, decision: ApprovalDecision = ApprovalDecision.APPROVE):
        self.decision = decision

    def ask(self, request: ApprovalRequest) -> Optional[ApprovalDecision]:
        return self.decision


class CallbackChannel:
    """把"怎么问"交给调用方的一个函数（CLI 自定义 / 测试用）。

    回调返回 None 视为"没人回答"，与超时同义。
    """

    def __init__(self, fn: Callable[[ApprovalRequest], Optional[ApprovalDecision]]):
        self._fn = fn

    def ask(self, request: ApprovalRequest) -> Optional[ApprovalDecision]:
        return self._fn(request)


class EventChannel:
    """GUI 用：运行线程挂起等待，主线程来回答。

    时序：
        运行线程  ask(req) ──emit(requested)──> 主线程弹框
                  Event.wait(timeout)           │
        运行线程  <── set(answer) ──────────────┘

    **阻塞的是运行线程**（`RunService` 那条），不是 GUI 线程 —— 所以界面照常
    能滚日志、能看别的运行。超时返回 None，由 Gate 降级成 SKIP 并记账：
    「没人回答」默认放行是不能接受的，那等于治理形同虚设。
    """

    def __init__(self, on_request: Optional[Callable[[ApprovalRequest], None]] = None,
                 on_answer: Optional[Callable[[ApprovalRequest,
                                               Optional[ApprovalDecision]], None]] = None):
        self._on_request = on_request
        self._on_answer = on_answer
        self._event = threading.Event()
        self._answer: Optional[ApprovalDecision] = None
        self._request: Optional[ApprovalRequest] = None

    def ask(self, request: ApprovalRequest) -> Optional[ApprovalDecision]:
        # 每次问之前先清干净：上一次的答案不能套用到这一次的问题上
        self._event.clear()
        self._answer = None
        self._request = request
        try:
            if self._on_request is not None:
                self._on_request(request)
            if request.timeout_s and request.timeout_s > 0:
                answered = self._event.wait(request.timeout_s)
            else:
                answered = self._event.wait()
            answer = self._answer if answered else None
            if self._on_answer is not None:
                self._on_answer(request, answer)
            return answer
        finally:
            # 问完了就不再是"待答" —— 界面据此收起弹框
            self._request = None

    # ── 主线程侧 ──

    def answer(self, decision: ApprovalDecision) -> None:
        """由 GUI 线程调用，唤醒等待中的运行线程。"""
        self._answer = decision
        self._event.set()

    @property
    def pending(self) -> Optional[ApprovalRequest]:
        """当前正在等的那一条（没有就是 None）—— 界面据此决定要不要弹框。"""
        return self._request


# ═══════════════════════════════════════════════════════════════
# 审批模式
# ═══════════════════════════════════════════════════════════════

class ApprovalMode(str, Enum):
    INTERACTIVE = "interactive"   # 终端交互：等待 y/n
    AUTO = "auto"                 # 全自动：全部通过（CI 模式）
    THRESHOLD = "threshold"       # 阈值模式：风险 > threshold 才审批


# ═══════════════════════════════════════════════════════════════
# 审批门控
# ═══════════════════════════════════════════════════════════════

class ApprovalGate:
    """审批门控 — 决定「要不要问」，通道决定「怎么问」。

    `input_func` / `output_func` 保留是为了向后兼容（老调用方按位置传参）；
    它们现在被用来构造默认的 `ConsoleChannel`。要换交互方式就传 `channel`。
    """

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.THRESHOLD,
        risk_threshold: str = "high",
        input_func: Callable = input,
        output_func: Callable = print,
        channel: Optional[ApprovalChannel] = None,
        on_request: Optional[Callable[[ApprovalRequest], None]] = None,
        on_decision: Optional[Callable[[ApprovalRecord], None]] = None,
        timeout_s: float = 0.0,
    ):
        self.mode = mode
        self.risk_threshold = risk_threshold
        self._input = input_func
        self._output = output_func
        self.channel: ApprovalChannel = channel or ConsoleChannel(input_func, output_func)
        self.on_request = on_request
        self.on_decision = on_decision
        self.timeout_s = float(timeout_s or 0.0)
        self.records: List[ApprovalRecord] = []

    def requires_approval(self, stage_name: str, risk_level: str = "low") -> bool:
        """判断阶段是否需要审批"""
        if self.mode == ApprovalMode.AUTO:
            return False
        if self.mode == ApprovalMode.INTERACTIVE:
            return True
        if self.mode == ApprovalMode.THRESHOLD:
            risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            return risk_order.get(risk_level, 0) >= risk_order.get(self.risk_threshold, 1)
        return False

    def ask(self, stage_name: str, summary: str,
            risk_level: str = "low") -> ApprovalRecord:
        """执行一次审批：决定要不要问 → 用通道问 → 记账 → 通知观察者。

        返回 `ApprovalRecord`（**不是** ApprovalDecision）。调用方要比对的是
        `record.decision` —— 历史上 `n_approval` 直接拿 record 与枚举比，
        恒为 False，于是拒绝/跳过两条分支从来没生效过（见 tests/test_approval.py）。
        """
        if not self.requires_approval(stage_name, risk_level):
            record = ApprovalRecord(
                stage=stage_name,
                decision=ApprovalDecision.APPROVE,
                reason=f"自动通过 (模式: {self.mode.value})",
                token=self._next_token(),      # 自动通过的也要有审计编号
            )
            self.records.append(record)
            self._notify_decision(record)
            return record

        request = ApprovalRequest(
            stage=stage_name, summary=summary, risk_level=risk_level,
            token=self._next_token(),
            timeout_s=self.timeout_s,
        )
        if self.on_request is not None:
            self.on_request(request)

        decision = self.channel.ask(request)

        if decision is None:
            # 通道说不出话（超时/界面关了）—— 降级为 SKIP 并**记账**。
            # 静默变成 APPROVE 是不能接受的：那等于「没人管 = 全放行」。
            decision = ApprovalDecision.SKIP
            reason = "审批超时/无人应答 → 跳过该动作"
        else:
            reason = f"用户手动选择: {decision.value}"

        record = ApprovalRecord(stage=stage_name, decision=decision,
                                reason=reason, token=request.token)
        self.records.append(record)
        self._notify_decision(record)

        if decision == ApprovalDecision.REJECT:
            approved = len([r for r in self.records
                            if r.decision == ApprovalDecision.APPROVE])
            self._output(f"⛔ 用户拒绝 {stage_name}，流程终止。")
            self._output(f"   已通过的审批: {approved} 条")

        return record

    def _next_token(self) -> str:
        """审批编号：递增而非 uuid —— 同一个输入跑两次该得到同一份审计。"""
        return f"ap-{len(self.records) + 1}"

    def _notify_decision(self, record: ApprovalRecord) -> None:
        if self.on_decision is None:
            return
        try:
            self.on_decision(record)
        except Exception:                    # noqa: BLE001
            # 观察者坏了不能影响治理本身
            pass

    def summary(self) -> Dict:
        """输出审批摘要（对标原型的 spa['approvals']）"""
        return {
            "total_gates": len(self.records),
            "approved": len([r for r in self.records
                           if r.decision == ApprovalDecision.APPROVE]),
            "rejected": len([r for r in self.records
                           if r.decision == ApprovalDecision.REJECT]),
            "skipped": len([r for r in self.records
                          if r.decision == ApprovalDecision.SKIP]),
            "records": [
                {
                    "stage": r.stage,
                    "decision": r.decision.value,
                    "timestamp": r.timestamp,
                    "reason": r.reason,
                    "token": r.token,
                }
                for r in self.records
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.summary(), indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 管道终止异常
# ═══════════════════════════════════════════════════════════════

class PipelineTerminatedError(Exception):
    """用户审批拒绝导致管道终止"""
    pass


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

def create_approval_gate(mode: str, channel: Optional[ApprovalChannel] = None,
                         **kwargs: Any) -> ApprovalGate:
    """从 CLI 参数创建审批门控。

    channel 不传时的默认行为与改动前**完全一致**（终端 input()）。
    GUI / 服务层传 `EventChannel`；无人值守想要"拒绝一切"传 `AutoChannel(REJECT)`。
    """
    mode_map = {
        "interactive": ApprovalMode.INTERACTIVE,
        "auto": ApprovalMode.AUTO,
        "threshold": ApprovalMode.THRESHOLD,
    }
    # 未知取值回落到 THRESHOLD 而非 AUTO：宁可多问一次，也不要静默全放行
    return ApprovalGate(mode=mode_map.get(mode, ApprovalMode.THRESHOLD),
                        channel=channel, **kwargs)
