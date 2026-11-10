"""`run_closed_loop_streaming` —— 图流真的被翻译成了可读的运行日志。

这里用一张**假图**（三个节点）替换真图：真图要 LLM 和 EDA 才能跑，而这套测试
要验证的是**翻译这一层**——阶段边界有没有记、失败有没有区分、取消能不能停在
节点边界、返回值与 `run_closed_loop` 是否同构。这些都不需要真 agent。

假图仍然是真的 `StateGraph(PipelineState)`，所以 reducer、`extra="forbid"`、
`result` 字段这些约束都是真的在跑 —— 不是 mock 出来的假设。
"""
from __future__ import annotations

import threading

import pytest

from src.layers.l2_orchestration import execution as execution_mod
from src.agents.supervisor import graph as graph_mod
from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.layers.l2_orchestration.execution_helpers import _result_of
from src.layers.l2_orchestration.run_journal import read_journal
from src.layers.l2_orchestration.state import PipelineState


# ═══════════════════════════════════════════════════════════════
# 假图
# ═══════════════════════════════════════════════════════════════

def _build_fake_graph(checkpointer=None, store=None, *, fail_at: str = ""):
    """三节点图：design → coverage → finalize。节点名取自真实阶段表。"""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)

    def n_design(state):
        if fail_at == "design":
            raise RuntimeError("设计阶段炸了")
        return {"spec": {"name": "demo"},
                "phases": [{"name": "design", "status": "passed", "time": 1}]}

    def n_coverage(state):
        if fail_at == "coverage":
            raise RuntimeError("覆盖率收集炸了")
        return {"coverage": {"line": 0.9}, "functional_coverage": 80.0,
                "round_num": 1}

    def n_finalize(state):
        return {"result": {"status": "PASS", "converged": True,
                           "final_coverage": 90.0, "effective_coverage": 88.0,
                           "iterations": 1, "passed": 30, "total": 32,
                           "phases": [{"name": "design", "status": "passed"}]}}

    g.add_node("design", n_design)
    g.add_node("coverage", n_coverage)
    g.add_node("finalize", n_finalize)
    g.add_edge(START, "design")
    g.add_edge("design", "coverage")
    g.add_edge("coverage", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


@pytest.fixture
def service():
    svc = PipelineExecutionService.get_instance()
    svc._initialized = True          # 跳过真 agent 初始化（本测试不跑真图）
    return svc


@pytest.fixture
def wiring(monkeypatch, tmp_path):
    """把输出目录与图都钉到测试里，不让它真去扫 output/。"""
    root = tmp_path / "run_ut_20261002_120000"

    def _fake_root(_base="output"):
        return str(root)

    monkeypatch.setattr(execution_mod, "make_output_root", _fake_root)
    monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                        lambda **kw: _build_fake_graph(**kw))
    return root


async def _run(service, root, **kw):
    return await service.run_closed_loop_streaming(
        spec_text="# 假规格", output_root=str(root),
        target=95.0, max_rounds=1, **kw)


# ═══════════════════════════════════════════════════════════════
# 基本形状
# ═══════════════════════════════════════════════════════════════

class TestStreamingRun:
    @pytest.mark.asyncio
    async def test_writes_a_journal_with_stage_boundaries(self, service, wiring):
        await _run(service, wiring)
        events = read_journal(wiring)
        kinds = [e.kind for e in events]
        assert "run.started" in kinds
        assert "stage.started" in kinds
        assert "stage.finished" in kinds
        assert kinds[-1] == "run.finished"

    @pytest.mark.asyncio
    async def test_every_graph_node_appears(self, service, wiring):
        await _run(service, wiring)
        stages = {e.stage for e in read_journal(wiring) if e.stage}
        assert {"design", "coverage", "finalize"} <= stages

    @pytest.mark.asyncio
    async def test_stage_events_are_paired(self, service, wiring):
        """每个 started 都该有一个 finished（假图不会中途死）。"""
        events = read_journal(wiring)
        started = [e.stage for e in events if e.kind == "stage.started"]
        finished = [e.stage for e in events if e.kind == "stage.finished"]
        assert sorted(started) == sorted(finished)

    @pytest.mark.asyncio
    async def test_titles_are_resolved(self, service, wiring):
        await _run(service, wiring)
        by_stage = {e.stage: e for e in read_journal(wiring) if e.stage}
        assert by_stage["coverage"].title == "覆盖率收集"
        assert by_stage["coverage"].agent == "coverage"

    @pytest.mark.asyncio
    async def test_round_comes_from_the_state(self, service, wiring):
        """覆盖率节点把 round_num 推到 1 —— 之后的事件该带上这个轮次。"""
        await _run(service, wiring)
        finalize = [e for e in read_journal(wiring) if e.stage == "finalize"]
        assert finalize and finalize[0].round == 1

    @pytest.mark.asyncio
    async def test_coverage_is_recorded_once_per_change(self, service, wiring):
        await _run(service, wiring)
        cov = [e for e in read_journal(wiring) if e.kind == "coverage.updated"]
        assert len(cov) == 1
        assert cov[0].payload["functional"] == 80.0

    @pytest.mark.asyncio
    async def test_return_value_matches_the_plain_path(self, service, wiring):
        """返回结构必须与 run_closed_loop 一致 —— 否则调用方不能按需替换。"""
        result = await _run(service, wiring)
        assert result["status"] == "PASS"
        assert result["converged"] is True
        assert result["final_coverage"] == 90.0

    @pytest.mark.asyncio
    async def test_run_finished_carries_the_verdict(self, service, wiring):
        await _run(service, wiring)
        done = [e for e in read_journal(wiring) if e.kind == "run.finished"]
        assert done and done[0].payload["converged"] is True
        assert done[0].payload["final_coverage"] == 90.0


# ═══════════════════════════════════════════════════════════════
# 失败与取消
# ═══════════════════════════════════════════════════════════════

class TestStreamingFailure:
    @pytest.mark.asyncio
    async def test_node_error_lands_as_stage_failed(self, service, wiring,
                                                    monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _build_fake_graph(fail_at="coverage", **kw))
        with pytest.raises(Exception):
            await _run(service, wiring)
        events = read_journal(wiring)
        failed = [e for e in events if e.kind == "stage.failed"]
        assert failed and failed[0].stage == "coverage"
        assert "炸了" in failed[0].payload["error"]

    @pytest.mark.asyncio
    async def test_run_failed_is_recorded(self, service, wiring, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _build_fake_graph(fail_at="design", **kw))
        with pytest.raises(Exception):
            await _run(service, wiring)
        kinds = [e.kind for e in read_journal(wiring)]
        assert kinds[-1] == "run.failed"

    @pytest.mark.asyncio
    async def test_cancel_stops_at_a_node_boundary(self, service, wiring):
        """图没有检查点，所以取消只能停在节点边界 —— 行为要如实反映这一点。"""
        cancel = threading.Event()
        cancel.set()                       # 开局就置位 = 一个节点都不跑
        result = await _run(service, wiring, cancel_event=cancel)
        events = read_journal(wiring)
        assert events[-1].kind == "run.cancelled"
        assert not [e for e in events if e.kind == "stage.started"]
        assert result == {}

    @pytest.mark.asyncio
    async def test_cancelled_run_has_no_finish_event(self, service, wiring):
        cancel = threading.Event()
        cancel.set()
        await _run(service, wiring, cancel_event=cancel)
        kinds = [e.kind for e in read_journal(wiring)]
        assert "run.finished" not in kinds


# ═══════════════════════════════════════════════════════════════
# 回调（进程内快路径）
# ═══════════════════════════════════════════════════════════════

class TestOnEventCallback:
    @pytest.mark.asyncio
    async def test_callback_sees_the_same_events(self, service, wiring):
        seen = []
        await _run(service, wiring, on_event=seen.append)
        assert [e.kind for e in seen] == [e.kind for e in read_journal(wiring)]

    @pytest.mark.asyncio
    async def test_a_broken_callback_does_not_kill_the_run(self, service, wiring):
        """观察者坏了不能把运行带崩 —— 它是观测手段，不是流程的一部分。"""
        def boom(_event):
            raise RuntimeError("回调炸了")

        result = await _run(service, wiring, on_event=boom)
        assert result["status"] == "PASS"
        assert read_journal(wiring)[-1].kind == "run.finished"


# ═══════════════════════════════════════════════════════════════
# 内存运行表（让 watch / history 的实时分支活过来）
# ═══════════════════════════════════════════════════════════════

class TestApprovalWiring:
    """审批的两端要进日志 —— 签核时要能回答"谁批的、什么时候问的"。"""

    def test_request_and_decision_land_in_the_journal(self, tmp_path, monkeypatch):
        from src.layers.l2_orchestration.execution_helpers import _wire_approval_events
        from src.layers.l2_orchestration.governance.approval import (
            ApprovalDecision, ApprovalGate, ApprovalMode,
        )
        from src.layers.l2_orchestration.run_journal import (
            RunJournal, read_journal,
        )

        root = tmp_path / "r"
        journal = RunJournal(root, run_id="r")
        emitted = []
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE)
        _wire_approval_events(gate, journal, emitted.append)

        from src.layers.l2_orchestration.governance.approval import CallbackChannel
        gate.channel = CallbackChannel(lambda req: ApprovalDecision.REJECT)
        gate.ask("REFACTOR_RTL", "时序改了", risk_level="high")
        journal.close()

        kinds = [e.kind for e in read_journal(root)]
        assert "approval.requested" in kinds
        assert "approval.decided" in kinds
        decided = [e for e in read_journal(root)
                   if e.kind == "approval.decided"][0]
        assert decided.payload["decision"] == "reject"
        assert decided.payload["token"] == "ap-1"
        # 落盘之外还要走进程内回调 —— GUI 靠它实时弹框
        assert {e.kind for e in emitted} >= {"approval.requested", "approval.decided"}

    def test_an_existing_observer_is_chained_not_replaced(self, tmp_path):
        from src.layers.l2_orchestration.execution_helpers import _wire_approval_events
        from src.layers.l2_orchestration.governance.approval import (
            ApprovalGate, ApprovalMode,
        )
        from src.layers.l2_orchestration.run_journal import RunJournal

        seen = []
        gate = ApprovalGate(mode=ApprovalMode.AUTO, on_decision=seen.append)
        journal = RunJournal(tmp_path / "r", run_id="r")
        _wire_approval_events(gate, journal, lambda e: None)
        gate.ask("REFACTOR_RTL", "x", "high")
        journal.close()
        assert len(seen) == 1          # 原来的观察者还在


class TestResultSurvives:
    """`result` 曾被静默丢弃 —— 本仓库最贵的一类故障。

    PipelineState 是 `extra="forbid"` 的 pydantic 模型，而 LangGraph 对**未声明**
    的键是**静默丢弃**：不报错、不警告。`n_finalize` 写 `{"result": ...}` 写了很久，
    而 `run_closed_loop` 恒返回 `{}` —— CLI 的 run_id / coverage / converged
    全是 None/0/NO。这条测试钉住的是**声明本身**：字段没了，它就红。
    """

    def test_result_is_a_declared_state_field(self):
        assert "result" in PipelineState.model_fields

    def test_a_node_writing_result_lands_in_the_final_state(self):
        """声明字段还不够 —— 要证明它真的能穿过去。"""
        import asyncio
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(PipelineState)
        g.add_node("finalize", lambda s: {"result": {"status": "PASS"}})
        g.add_edge(START, "finalize")
        g.add_edge("finalize", END)
        final = asyncio.run(g.compile().ainvoke(PipelineState(run_id="r"), {}))
        assert _result_of(final) == {"status": "PASS"}

    @pytest.mark.asyncio
    async def test_the_plain_path_returns_a_result_too(self, service, wiring):
        """非流式那条路同样依赖这个字段 —— 一起钉住。"""
        result = await service.run_closed_loop(
            spec_text="# 假规格", output_root=str(wiring), target=95.0, max_rounds=1)
        assert result.get("status") == "PASS"
        assert result.get("final_coverage") == 90.0

    def test_no_node_returns_an_undeclared_state_key(self):
        """静态扫描：`n_*` 里**字面量**返回的键必须都是声明过的状态字段。

        这是防"静默丢弃"的通用网。动态构造的返回值（`return payload`）扫不到，
        但历史上真正踩坑的那一处（`return {"result": ...}`）正是字面量。
        """
        import ast
        from pathlib import Path

        from src.agents.supervisor import graph as graph_mod

        declared = set(PipelineState.model_fields)
        tree = ast.parse(Path(graph_mod.__file__).read_text(encoding="utf-8"))
        offenders: dict = {}

        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("n_"):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
                    continue
                for key in node.value.keys:
                    if not isinstance(key, ast.Constant):
                        continue
                    if isinstance(key.value, str) and key.value not in declared:
                        offenders.setdefault(fn.name, set()).add(key.value)

        assert not offenders, (
            "这些节点返回了 PipelineState 里没声明的键 —— LangGraph 会静默丢掉它们："
            f"{ {k: sorted(v) for k, v in offenders.items()} }")


class TestRunRegistry:
    @pytest.mark.asyncio
    async def test_run_is_registered_and_then_closed(self, service, wiring):
        await _run(service, wiring)
        run_id = wiring.name
        status = service.get_run_status(run_id)
        assert status is not None
        assert status["state"] == "completed"
        assert status["completed_at"]
        assert status["total"] == 32

    @pytest.mark.asyncio
    async def test_failed_run_is_marked_failed(self, service, wiring, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _build_fake_graph(fail_at="design", **kw))
        with pytest.raises(Exception):
            await _run(service, wiring)
        assert service.get_run_status(wiring.name)["state"] == "failed"

    @pytest.mark.asyncio
    async def test_cancelled_run_is_marked_cancelled(self, service, wiring):
        cancel = threading.Event()
        cancel.set()
        await _run(service, wiring, cancel_event=cancel)
        assert service.get_run_status(wiring.name)["state"] == "cancelled"
