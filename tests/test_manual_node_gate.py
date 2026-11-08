"""触发条件读声明 —— 让 `config/ide/manual_nodes.yaml` 真正生效。

在此之前，`n_approval` 的触发是一行硬编码：

    if not rt.approval_gate or action.action_type not in ("REFACTOR_RTL", "UPDATE_MODEL"):

而声明文件有 schema、有工具、有编辑界面、有测试 —— **闭环却从不读它**。文件自己
的头注释和架构文档 §8 都写着"当前 graph.py 的节点写死，不读本文件"。于是"人工节点"
一直只是一份文档。

现在声明是**主源**，硬编码退化成**兜底**（`_LEGACY_HIGH_RISK_ACTIONS`）—— 治理不能
因为一份配置文件不在就静默失效，但兜底名单刻意只保那两个已知高危动作：名单越长，
它就越像"第二份真相"。

本增量只把**触发**改成读声明，不新增闸门点：声明仍必须写明 `action`。没写 `action`
的是"这个阶段的通用停靠点"（产物闸门的形状），那需要相应的条件路由，属后续增量。
"""
from __future__ import annotations

import asyncio

import pytest

from src.layers.l2_orchestration.governance.approval import (
    ApprovalDecision, ApprovalGate, ApprovalMode, CallbackChannel,
)


def _node(**kw):
    """声明里的一个节点（只写测试关心的键）。"""
    node = {"id": "n1", "kind": "approval", "after": "decide",
            "default": "skip", "required": True, "prompt": "看一眼再放行"}
    node.update(kw)
    return node


class _RT:
    """假的运行时 —— 只放 `n_approval` 会读的那几个字段。

    通道模式（没有检查点）；interrupt 模式由 `TestInterruptPayload` 与
    `tests/test_checkpoint.py` 各自覆盖。
    """

    interrupt_mode = False

    def __init__(self, gate, manual_nodes=None):
        self.approval_gate = gate
        self.manual_nodes = manual_nodes if manual_nodes is not None else []


def _approval_node(gate, action_type="REFACTOR_RTL", manual_nodes=None,
                   output_root=""):
    from src.layers.l2_orchestration.graph import n_approval
    from src.layers.l2_orchestration.state import PipelineState

    rt = _RT(gate, manual_nodes)
    state = PipelineState(run_id="r", output_root=output_root)
    state.pending_action = {"action_type": action_type, "reason": "时序改了"}
    return asyncio.run(n_approval(state, {"configurable": {"rt": rt}}))


def _gate(decision=ApprovalDecision.SKIP, seen=None):
    def answer(request):
        if seen is not None:
            seen["summary"] = request.summary
        return decision

    return ApprovalGate(mode=ApprovalMode.INTERACTIVE, channel=CallbackChannel(answer))


class TestDeclarationDrivesTheTrigger:
    def test_a_declared_action_is_gated(self):
        """**声明是主源**：写进去的动作就门控 —— 哪怕它不在兜底名单里。

        这条是这一刀的核心：不写声明的话 `GENERATE_DIRECTED_TEST` 根本没资格
        要人批，现在它有了。
        """
        out = _approval_node(_gate(), action_type="GENERATE_DIRECTED_TEST",
                             manual_nodes=[_node(action="GENERATE_DIRECTED_TEST")])
        assert out["approval_outcome"] == "skip"       # 触发过（否则是 proceed）

    def test_an_undeclared_action_is_not_gated(self):
        out = _approval_node(_gate(), action_type="GENERATE_DIRECTED_TEST",
                             manual_nodes=[_node(action="EXPAND_SEEDS")])
        assert out["approval_outcome"] == "proceed"

    def test_a_declaration_for_another_stage_does_not_fire_here(self):
        """挂在 `after: verify` 的声明不该在 `decide` 阶段生效。"""
        out = _approval_node(_gate(), action_type="GENERATE_DIRECTED_TEST",
                             manual_nodes=[_node(after="verify",
                                                 action="GENERATE_DIRECTED_TEST")])
        assert out["approval_outcome"] == "proceed"

    def test_a_stage_level_declaration_without_an_action_does_not_fire(self):
        """没写 `action` 的是"这个阶段的通用停靠点"——**本增量不接**。

        把它当成"所有动作都要批"会让每次迭代都停下来等人；那是产物闸门的形状，
        需要相应的条件路由，属后续增量。
        """
        out = _approval_node(_gate(), action_type="GENERATE_DIRECTED_TEST",
                             manual_nodes=[_node()])       # 没有 action
        assert out["approval_outcome"] == "proceed"

    def test_the_declared_prompt_becomes_the_summary(self):
        """声明里的 `prompt` 是**给人看的提示语**，要压过引擎那句 reason。"""
        seen = {}
        _approval_node(_gate(seen=seen), action_type="GENERATE_DIRECTED_TEST",
                       manual_nodes=[_node(action="GENERATE_DIRECTED_TEST",
                                           prompt="看覆盖率缺口再决定")])
        assert seen["summary"] == "看覆盖率缺口再决定"

    def test_without_a_declaration_the_reason_is_used(self):
        seen = {}
        _approval_node(_gate(seen=seen), action_type="REFACTOR_RTL",
                       manual_nodes=[])
        assert seen["summary"] == "时序改了"


class TestLegacyFallback:
    """**声明不存在时的安全网。**

    声明文件丢了、写坏了、或者压根没人写 —— 那两个已知高危动作照样得有人批。
    """

    @pytest.mark.parametrize("action_type", ["REFACTOR_RTL", "UPDATE_MODEL"])
    def test_high_risk_actions_still_gate_without_a_declaration(self, action_type):
        out = _approval_node(_gate(), action_type=action_type, manual_nodes=[])
        assert out["approval_outcome"] == "skip"

    def test_the_fallback_covers_only_the_high_risk_semantics(self):
        """兜底名单越长，它越是"第二份真相"—— 刻意只保**动设计 / 动模型**这两类。

        动作改名之后（`REFACTOR_RTL` → `FIX_*_bug`）每个语义有两个名字，所以断言
        的是**归一后的集合**而不是字面量列表 —— 老名字还得留着，声明文件与历史
        轨迹里写的可能是它。
        """
        from src.layers.l2_orchestration.graph import _LEGACY_HIGH_RISK_ACTIONS
        from src.layers.l3_decision.decision_engine import canonical_action
        assert {canonical_action(a) for a in _LEGACY_HIGH_RISK_ACTIONS} == {
            "FIX_FUNCTIONAL_bug", "FIX_PROTOCOL_bug", "FIX_RESET_bug",
            "FIX_CDC_bug", "FIX_DEADCODE_bug", "FIX_MODEL_bug"}

    def test_another_declaration_does_not_displace_the_fallback(self):
        """声明里写了一条别的动作，不该把两个高危动作的门控挤掉。"""
        out = _approval_node(_gate(), action_type="REFACTOR_RTL",
                             manual_nodes=[_node(action="EXPAND_SEEDS")])
        assert out["approval_outcome"] == "skip"

    def test_no_gate_means_no_approval_at_all(self):
        assert _approval_node(None)["approval_outcome"] == "proceed"


class TestMatchingHelper:
    def test_it_matches_on_both_stage_and_action(self):
        from src.layers.l2_orchestration.graph import _matching_manual_node

        rt = _RT(None, [_node(id="a", after="decide", action="REFACTOR_RTL"),
                        _node(id="b", after="verify", action="REFACTOR_RTL")])
        assert _matching_manual_node(rt, "decide", "REFACTOR_RTL")["id"] == "a"
        assert _matching_manual_node(rt, "verify", "REFACTOR_RTL")["id"] == "b"
        assert _matching_manual_node(rt, "decide", "NOPE") is None

    def test_a_runtime_without_the_attribute_does_not_explode(self):
        """运行时没有 `manual_nodes`（老对象/假对象）时按空声明处理。"""
        from src.layers.l2_orchestration.graph import _matching_manual_node

        class _Bare:
            pass

        assert _matching_manual_node(_Bare(), "decide", "REFACTOR_RTL") is None


class TestInterruptPayload:
    """interrupt 的 payload 是**人**看的那一份 —— 判什么、看哪几份文件。

    GUI 的检查点分支读的就是它（经 journal 的 `run.interrupted`），所以产物必须
    加在这里；只加在 `ApprovalRequest` 上界面看不到（那条路只有通道模式走）。
    """

    @staticmethod
    def _capture(rt, action, **kw):
        import langgraph.types as lt

        captured = {}

        def fake_interrupt(payload):
            captured.update(payload)
            return "approve"

        real = lt.interrupt
        lt.interrupt = fake_interrupt
        try:
            from src.layers.l2_orchestration.graph import _interrupt_approval
            _interrupt_approval(rt, action, **kw)
        finally:
            lt.interrupt = real
        return captured

    def test_the_payload_carries_summary_and_artifacts(self):
        class _Action:
            action_type, reason = "REFACTOR_RTL", "时序改了"

        class _R:
            approval_gate = ApprovalGate(mode=ApprovalMode.AUTO)

        payload = self._capture(_R(), _Action(),
                                summary="看覆盖率缺口再决定",
                                artifacts=[{"path": "a.yaml", "errors": 2}])
        assert payload["stage"] == "REFACTOR_RTL"
        assert payload["summary"] == "看覆盖率缺口再决定"
        assert payload["reason"] == "时序改了"
        assert payload["artifacts"] == [{"path": "a.yaml", "errors": 2}]
        assert payload["token"] == "ap-1"

    def test_without_a_summary_it_falls_back_to_the_reason(self):
        class _Action:
            action_type, reason = "REFACTOR_RTL", "时序改了"

        class _R:
            approval_gate = ApprovalGate(mode=ApprovalMode.AUTO)

        payload = self._capture(_R(), _Action())
        assert payload["summary"] == "时序改了"
        assert payload["artifacts"] == []


class TestArtifactCollection:
    """`_approval_artifacts` —— 从运行目录取**紧凑**清单。"""

    def test_it_reads_the_run_artifacts(self, tmp_path):
        from src.layers.l2_orchestration.graph import _approval_artifacts
        from src.layers.l2_orchestration.state import PipelineState

        run = tmp_path / "output_demo"
        (run / "inputs" / "yaml" / "uvm").mkdir(parents=True)
        (run / "spec.json").write_text('{"design_name": "dut"}', encoding="utf-8")
        (run / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(
            "bench:\n  name: x\n  env_name: y\n  agents:\n", encoding="utf-8")

        items = _approval_artifacts(PipelineState(run_id="r", output_root=str(run)))
        assert [i["path"] for i in items] == ["spec.json",
                                              "inputs/yaml/uvm/bench.yaml",
                                              "inputs/yaml/regression.yaml",
                                              # 功能覆盖那一组：同样是"卡住运行的
                                              # 中间产物"，审批时也该看得见
                                              "inputs/vplan/data/execution_meta.csv",
                                              "coverage/coverage_points.json",
                                              "inputs/yaml/uvm/env_cov_bins.yaml"]
        bench = [i for i in items if i["path"].endswith("bench.yaml")][0]
        assert bench["errors"] > 0

    def test_the_list_is_compact(self, tmp_path):
        """**裁剪过的**：带 sha256 / 逐条诊断会把检查点和日志撑肥。"""
        from src.layers.l2_orchestration.graph import _approval_artifacts
        from src.layers.l2_orchestration.state import PipelineState

        run = tmp_path / "output_demo"
        run.mkdir()
        (run / "spec.json").write_text("{}", encoding="utf-8")

        items = _approval_artifacts(PipelineState(run_id="r", output_root=str(run)))
        assert set(items[0]) == {"path", "group", "exists", "errors", "warnings"}

    def test_a_missing_run_dir_is_not_an_error(self, tmp_path):
        """取不到产物**照常审批** —— 产物是给人看的附加信息，不是审批的前提。"""
        from src.layers.l2_orchestration.graph import _approval_artifacts
        from src.layers.l2_orchestration.state import PipelineState

        assert _approval_artifacts(
            PipelineState(run_id="r", output_root=str(tmp_path / "nope"))) == []


class TestAutoApprovalBeatsTheInterruptMechanism:
    """`--approval auto` 必须**赢过** interrupt 机制 —— 否则 CI 会被自己的审批拦住。

    ## 这是实测踩出来的

    `verify` 改走 `run_closed_loop_streaming`（为落检查点）之后，
    `--checkpoint` 默认开 → `rt.interrupt_mode` 为真。而 `n_approval` 原来
    **只判 `interrupt_mode`**，于是**每一个**高危动作都会停下来等人 ——
    包括 CI 显式写 `--approval auto`（无人值守）的那些。

    实测：`verify --rtl specs/npu_sched --no-manual-gate --approval auto`
    跑到 `FIX_FUNCTIONAL_bug` 停住，`auto` 等于没写。**无人值守模式被人为打断，
    是"可治理"那一支柱里最不该出现的一种失败**。

    判据交给门控自己的 `requires_approval`（AUTO → `False`）：**该不该问**是
    门控的事，节点只决定"问"用哪种机制。
    """

    def _state(self):
        from src.layers.l2_orchestration.state import PipelineState

        state = PipelineState(run_id="r", output_root="")
        state.pending_action = {"action_type": "FIX_FUNCTIONAL_bug", "reason": "改了 RTL"}
        return state

    def test_auto_mode_does_not_interrupt_even_with_checkpointing(self, monkeypatch):
        from src.layers.l2_orchestration.graph import n_approval
        from src.layers.l2_orchestration.governance.approval import (
            ApprovalMode, ApprovalGate, AutoChannel,
        )

        rt = _RT(ApprovalGate(mode=ApprovalMode.AUTO,
                              channel=AutoChannel(ApprovalDecision.APPROVE)))
        rt.interrupt_mode = True          # 有检查点（verify 的默认）
        # 真去 interrupt 的话这里会抛 —— 那条路径在测试里没有 checkpointer
        monkeypatch.setattr("langgraph.types.interrupt",
                            lambda payload: pytest.fail(
                                f"auto 模式下不该停下来等人：{payload}"))
        out = asyncio.run(n_approval(self._state(), {"configurable": {"rt": rt}}))
        assert out["approval_outcome"] == "proceed", (
            "auto 模式没放行 —— 无人值守的 CI 会被自己的审批拦住")

    def test_threshold_mode_still_interrupts_a_high_risk_action(self, monkeypatch):
        """反过来：**该问的还得问** —— 修 auto 不等于把审批一起关掉。"""
        from src.layers.l2_orchestration.graph import n_approval
        from src.layers.l2_orchestration.governance.approval import (
            ApprovalMode, ApprovalGate, CallbackChannel,
        )

        rt = _RT(ApprovalGate(mode=ApprovalMode.THRESHOLD,
                              channel=CallbackChannel(lambda r: ApprovalDecision.APPROVE)))
        rt.interrupt_mode = True
        called = {}

        def _fake_interrupt(payload):
            called["payload"] = payload
            return "approve"          # 模拟"人来答了"

        monkeypatch.setattr("langgraph.types.interrupt", _fake_interrupt)
        out = asyncio.run(n_approval(self._state(), {"configurable": {"rt": rt}}))
        assert "payload" in called, "高危动作在 threshold 模式下没停下来问"
        assert called["payload"]["stage"] == "FIX_FUNCTIONAL_bug"
        assert out["approval_outcome"] == "proceed"
