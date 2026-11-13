"""人工审批 —— 通道抽象、降级策略，以及**拒绝真的生效**。

最后一类是本文件的重点：`n_approval` 曾经拿 `ApprovalRecord` 与 `ApprovalDecision`
枚举比较，dataclass 的 `__eq__` 对非同类返回 NotImplemented → 恒为 False。
后果是「用户点拒绝」不起任何作用，闭环照常执行高风险动作 ——
对一个把"可治理"当卖点的产品来说，这是最不该有的洞。
"""
from __future__ import annotations

import threading

import pytest

from src.orchestration_plane.l2.governance.approval import (
    ApprovalDecision, ApprovalGate, ApprovalMode, ApprovalRequest,
    AutoChannel, CallbackChannel, ConsoleChannel, EventChannel,
    create_approval_gate,
)


# ═══════════════════════════════════════════════════════════════
# 通道
# ═══════════════════════════════════════════════════════════════

def _feed(*choices):
    """假的 input()：按顺序吐预设按键，用完后抛 EOFError（模拟 stdin 关了）。"""
    it = iter(choices)
    return lambda _prompt="": next(it)


class TestConsoleChannel:
    def _channel(self, *choices):
        out = []
        return ConsoleChannel(_feed(*choices), out.append), out

    @pytest.mark.parametrize("key,expected", [
        ("y", ApprovalDecision.APPROVE),
        ("n", ApprovalDecision.REJECT),
        ("s", ApprovalDecision.SKIP),
        ("r", ApprovalDecision.REVIEW),
    ])
    def test_single_key_mapping(self, key, expected):
        ch, _ = self._channel(key)
        assert ch.ask(ApprovalRequest("rtl", "摘要", "high")) == expected

    def test_accepts_uppercase_and_padding(self):
        ch, _ = self._channel("  Y  ")
        assert ch.ask(ApprovalRequest("rtl", "x", "high")) == ApprovalDecision.APPROVE

    def test_detail_key_shows_context_then_asks_again(self):
        ch, out = self._channel("d", "y")
        assert ch.ask(ApprovalRequest("rtl", "完整上下文在这里", "high")) \
            == ApprovalDecision.APPROVE
        assert any("完整上下文在这里" in line for line in out)

    def test_invalid_key_reprompts(self):
        ch, out = self._channel("zzz", "y")
        assert ch.ask(ApprovalRequest("rtl", "x", "high")) == ApprovalDecision.APPROVE
        assert any("请输入 y/n/s/d/r/q" in line for line in out)

    def test_quit_exits_the_process(self):
        ch, _ = self._channel("q")
        with pytest.raises(SystemExit) as info:
            ch.ask(ApprovalRequest("rtl", "x", "high"))
        assert info.value.code == 0

    def test_prompt_wording_is_unchanged(self):
        """这套按键文案是对外契约（有人已经习惯了），改动即破坏。"""
        ch, out = self._channel("y")
        ch.ask(ApprovalRequest("rtl", "摘要文本", "high"))
        blob = "\n".join(out)
        assert "🔴 审批节点: rtl" in blob
        assert "风险等级: HIGH" in blob
        assert "摘要: 摘要文本" in blob
        assert [c for c in "y/n/s/d/r/q".split("/")] == ["y", "n", "s", "d", "r", "q"]
        assert "[y] 通过" in ConsoleChannel.PROMPT
        assert "[q] 退出" in ConsoleChannel.PROMPT


class TestSimpleChannels:
    def test_auto_channel_returns_its_fixed_decision(self):
        assert AutoChannel().ask(ApprovalRequest("x", "")) == ApprovalDecision.APPROVE
        assert AutoChannel(ApprovalDecision.REJECT).ask(
            ApprovalRequest("x", "")) == ApprovalDecision.REJECT

    def test_callback_channel_delegates(self):
        seen = []

        def decide(req):
            seen.append(req.stage)
            return ApprovalDecision.SKIP

        ch = CallbackChannel(decide)
        assert ch.ask(ApprovalRequest("ops", "")) == ApprovalDecision.SKIP
        assert seen == ["ops"]

    def test_callback_returning_none_means_nobody_answered(self):
        assert CallbackChannel(lambda r: None).ask(ApprovalRequest("x", "")) is None


class TestEventChannel:
    def test_answer_from_another_thread_wakes_the_waiter(self):
        ch = EventChannel()
        box = {}

        def run():
            box["decision"] = ch.ask(ApprovalRequest("rtl", "x", timeout_s=5.0))

        t = threading.Thread(target=run)
        t.start()
        # 等待 request 真正挂上，再回答 —— 不靠 sleep 猜时机
        for _ in range(200):
            if ch.pending is not None:
                break
            threading.Event().wait(0.01)
        ch.answer(ApprovalDecision.REJECT)
        t.join(timeout=5)
        assert box["decision"] == ApprovalDecision.REJECT

    def test_timeout_returns_none(self):
        ch = EventChannel()
        assert ch.ask(ApprovalRequest("rtl", "x", timeout_s=0.05)) is None

    def test_callbacks_fire(self):
        asked, answered = [], []
        ch = EventChannel(on_request=asked.append,
                          on_answer=lambda req, d: answered.append(d))

        def run():
            ch.ask(ApprovalRequest("rtl", "x", timeout_s=5.0))

        t = threading.Thread(target=run)
        t.start()
        for _ in range(200):
            if ch.pending is not None:
                break
            threading.Event().wait(0.01)
        ch.answer(ApprovalDecision.APPROVE)
        t.join(timeout=5)

        assert len(asked) == 1 and asked[0].stage == "rtl"
        assert answered == [ApprovalDecision.APPROVE]

    def test_callbacks_see_none_on_timeout(self):
        answered = []
        ch = EventChannel(on_answer=lambda req, d: answered.append(d))
        ch.ask(ApprovalRequest("rtl", "x", timeout_s=0.05))
        assert answered == [None]

    def test_an_answer_for_the_previous_question_does_not_carry_over(self):
        """上次的答复不能套用到这次的问题上 —— 这是 ask 开头要 clear 的原因。"""
        ch = EventChannel()
        ch.answer(ApprovalDecision.APPROVE)
        assert ch.ask(ApprovalRequest("rtl", "x", timeout_s=0.05)) is None

    def test_pending_is_cleared_once_answered(self):
        ch = EventChannel()

        def run():
            ch.ask(ApprovalRequest("rtl", "x", timeout_s=5.0))

        t = threading.Thread(target=run)
        t.start()
        for _ in range(200):
            if ch.pending is not None:
                break
            threading.Event().wait(0.01)
        ch.answer(ApprovalDecision.SKIP)
        t.join(timeout=5)
        assert ch.pending is None


# ═══════════════════════════════════════════════════════════════
# 门控
# ═══════════════════════════════════════════════════════════════

class TestRequiresApproval:
    @pytest.mark.parametrize("mode,risk,expected", [
        (ApprovalMode.AUTO, "critical", False),
        (ApprovalMode.INTERACTIVE, "low", True),
        (ApprovalMode.THRESHOLD, "low", False),
        (ApprovalMode.THRESHOLD, "medium", False),
        (ApprovalMode.THRESHOLD, "high", True),
        (ApprovalMode.THRESHOLD, "critical", True),
    ])
    def test_matrix(self, mode, risk, expected):
        gate = ApprovalGate(mode=mode)
        assert gate.requires_approval("x", risk) is expected


class TestGateAsk:
    def test_returns_a_record_whose_decision_is_the_enum(self):
        """回归：曾经有人拿 record 当枚举用 —— 这条钉住它是个 Record。"""
        gate = ApprovalGate(mode=ApprovalMode.AUTO)
        record = gate.ask("rtl", "x", "high")
        assert not isinstance(record, ApprovalDecision)
        assert record.decision == ApprovalDecision.APPROVE

    def test_auto_pass_records_the_mode(self):
        gate = ApprovalGate(mode=ApprovalMode.AUTO)
        record = gate.ask("rtl", "x", "high")
        assert "自动通过" in record.reason

    def test_channel_decision_becomes_the_record(self):
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.REJECT))
        assert gate.ask("rtl", "x", "high").decision == ApprovalDecision.REJECT

    def test_no_answer_degrades_to_skip_and_says_so(self):
        """超时不能静默放行 —— 「没人管」不等于「同意」。"""
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: None))
        record = gate.ask("rtl", "x", "high")
        assert record.decision == ApprovalDecision.SKIP
        assert "超时" in record.reason

    def test_tokens_are_sequential_and_reproducible(self):
        """用递增编号而不是 uuid：同一个输入跑两次该得到同一份审计。

        自动通过的记录也要编号 —— 审计里出现"没有编号的那一条"最难解释。
        """
        gate = ApprovalGate(mode=ApprovalMode.AUTO)
        gate.ask("a", "", "high")
        gate.ask("b", "", "high")
        assert [r.token for r in gate.records] == ["ap-1", "ap-2"]

    def test_on_request_and_on_decision_fire(self):
        requests, decisions = [], []
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.SKIP),
                            on_request=requests.append,
                            on_decision=decisions.append)
        gate.ask("rtl", "摘要", "high")
        assert requests[0].stage == "rtl" and requests[0].risk_level == "high"
        assert decisions[0].decision == ApprovalDecision.SKIP

    def test_a_broken_observer_does_not_break_governance(self):
        def boom(_record):
            raise RuntimeError("观察者炸了")

        gate = ApprovalGate(mode=ApprovalMode.AUTO, on_decision=boom)
        assert gate.ask("rtl", "x", "high").decision == ApprovalDecision.APPROVE

    def test_summary_counts(self):
        gate = ApprovalGate(mode=ApprovalMode.AUTO)
        gate.ask("a", "", "high")
        s = gate.summary()
        assert s["total_gates"] == 1 and s["approved"] == 1
        assert s["records"][0]["token"]


class TestFactory:
    def test_known_modes(self):
        assert create_approval_gate("interactive").mode == ApprovalMode.INTERACTIVE
        assert create_approval_gate("auto").mode == ApprovalMode.AUTO

    def test_unknown_mode_falls_back_to_threshold_not_auto(self):
        """宁可多问一次，也不要静默全放行。"""
        assert create_approval_gate("nonsense").mode == ApprovalMode.THRESHOLD

    def test_channel_is_passed_through(self):
        ch = AutoChannel(ApprovalDecision.REJECT)
        assert create_approval_gate("threshold", channel=ch).channel is ch

    def test_default_channel_is_console(self):
        assert isinstance(create_approval_gate("threshold").channel, ConsoleChannel)


# ═══════════════════════════════════════════════════════════════
# 图里的审批节点 —— 拒绝必须真的改变控制流
# ═══════════════════════════════════════════════════════════════

def _approval_node(gate, action_type="REFACTOR_RTL"):
    """本文件只验「拒绝/跳过真的生效」这条线；**触发条件**（读声明、兜底）
    由 `tests/test_manual_node_gate.py` 覆盖。

    这里的假 Runtime 没有 `manual_nodes` 属性 —— 于是走的是兜底名单那条路，
    正好也是这些用例要的语义（REFACTOR_RTL 本来就在兜底名单里）。
    """
    from src.orchestration_plane.nodes.pure.approval import n_approval
    from src.orchestration_plane.l2.state import PipelineState

    class _RT:
        approval_gate = gate
        # 通道模式（没有检查点）。interrupt 模式由 tests/test_checkpoint.py 覆盖。
        interrupt_mode = False

    state = PipelineState(run_id="r")
    state.pending_action = {"action_type": action_type, "reason": "时序改了"}
    config = {"configurable": {"rt": _RT()}}
    import asyncio
    return asyncio.run(n_approval(state, config))


class TestApprovalNode:
    def test_reject_actually_rejects(self):
        """回归：这条分支曾经永远走不到（record 与枚举比较恒 False）。"""
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.REJECT))
        out = _approval_node(gate)
        assert out["approval_outcome"] == "reject"
        assert out["phases"][0]["status"] == "rejected"

    def test_skip_actually_skips(self):
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.SKIP))
        assert _approval_node(gate)["approval_outcome"] == "skip"

    def test_review_is_recorded_distinctly_from_skip(self):
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.REVIEW))
        out = _approval_node(gate)
        assert out["approval_outcome"] == "skip"
        assert out["phases"][0]["status"] == "review"

    def test_approve_proceeds(self):
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.APPROVE))
        out = _approval_node(gate)
        assert out["approval_outcome"] == "proceed"
        assert out["phases"][0]["status"] == "passed"

    def test_low_risk_actions_bypass_the_gate(self):
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.REJECT))
        assert _approval_node(gate, "CONVERGE")["approval_outcome"] == "proceed"

    def test_no_gate_means_proceed(self):
        out = _approval_node(None)
        assert out["approval_outcome"] == "proceed"

    def test_gate_failure_is_fail_closed(self):
        """审批**故障**不是"没人反对"。原先故障走 proceed = 治理一坏就静默失效。"""
        class Broken:
            def ask(self, *a, **kw):
                raise RuntimeError("通道坏了")
        out = _approval_node(Broken())
        assert out["approval_outcome"] == "skip"
        assert out["phases"][0]["status"] == "error"

    def test_token_reaches_the_phase_record(self):
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE,
                            channel=CallbackChannel(lambda r: ApprovalDecision.APPROVE))
        assert _approval_node(gate)["phases"][0]["token"] == "ap-1"
