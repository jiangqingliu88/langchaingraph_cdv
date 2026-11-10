"""Supervisor 主图 + 子图的结构守卫。

不跑 EDA：只验证“默认入口是 Supervisor”“子图挂载成功”“路由只读状态”。
真正的执行仍由现有 executors 承担，测试用 fake runtime 覆盖在别处。
"""
from __future__ import annotations

import asyncio

from src.layers.l2_orchestration.graph import (
    build_closed_loop_graph, build_legacy_closed_loop_graph,
)
from src.layers.l2_orchestration.state import PipelineState
from src.layers.l2_orchestration.supervisor.graph import n_supervisor, r_supervisor


def test_default_graph_is_supervisor_with_four_experts():
    graph = build_closed_loop_graph().get_graph()
    names = set(graph.nodes)
    assert {"supervisor", "design_expert", "verify_expert", "debug_expert",
            "coverage_expert", "human_review", "audit_gate",
            "finalize"} <= names
    # 子图不是把 24 个节点平铺到主图：主图只有 9 个编排节点。
    assert "design" not in names and "ops" not in names
    assert len(names - {"__start__", "__end__"}) == 9


def test_legacy_graph_is_still_available(monkeypatch):
    monkeypatch.setenv("SIGNOFFAI_SUPERVISOR", "off")
    graph = build_closed_loop_graph().get_graph()
    assert "design" in set(graph.nodes)
    assert "supervisor" not in set(graph.nodes)
    assert "design" in set(build_legacy_closed_loop_graph().get_graph().nodes)


def test_supervisor_routes_through_four_experts_then_audit():
    design = asyncio.run(n_supervisor(PipelineState(), {}))
    assert design["next_agent"] == "design"
    assert design["supervisor_visits"] == 1

    verify = asyncio.run(n_supervisor(
        PipelineState(design_done=True), {}))
    assert verify["next_agent"] == "verify"

    debug = asyncio.run(n_supervisor(
        PipelineState(design_done=True, verify_done=True), {}))
    assert debug["next_agent"] == "debug"

    coverage = asyncio.run(n_supervisor(
        PipelineState(design_done=True, verify_done=True, debug_done=True), {}))
    assert coverage["next_agent"] == "coverage"

    audit = asyncio.run(n_supervisor(
        PipelineState(design_done=True, verify_done=True, debug_done=True,
                      coverage_done=True, execution_done=True), {}))
    assert audit["next_agent"] == "audit"


def test_supervisor_asks_human_after_five_debug_attempts():
    out = asyncio.run(n_supervisor(PipelineState(
        design_done=True, verify_done=True, debug_done=True,
        debug_attempts=5), {}))
    assert out["next_agent"] == "human_review"

    reviewed = asyncio.run(n_supervisor(PipelineState(
        design_done=True, verify_done=True, debug_done=True,
        debug_attempts=5, human_reviewed=True), {}))
    assert reviewed["next_agent"] == "coverage"


def test_human_review_without_checkpoint_degrades_loudly(monkeypatch):
    from types import SimpleNamespace
    from src.layers.l2_orchestration.supervisor.human import n_human_review

    out = asyncio.run(n_human_review(
        PipelineState(debug_attempts=5),
        {"configurable": {"rt": SimpleNamespace(interrupt_mode=False)}}))
    assert out["human_decision"] == "auto_no_checkpoint"
    assert out["human_reviewed"] is True


def test_supervisor_routes_interrupted_to_audit():
    out = asyncio.run(n_supervisor(
        PipelineState(interrupted=True, terminal_reason="eda_missing"), {}))
    assert out["next_agent"] == "audit"


def test_design_subgraph_propagates_completion_marker(monkeypatch):
    """子图真的能跑：嵌套图的 state 更新会回到主图（不是只编译不执行）。"""
    from src.layers.l2_orchestration.supervisor import subgraphs

    async def fake(state, config):
        if state is None:
            return {}
        return {}

    for name in ("n_front", "n_design", "n_model", "n_verify",
                 "n_env_arch_check"):
        monkeypatch.setattr(subgraphs, name, fake)
    graph = subgraphs.build_design_subgraph()
    out = asyncio.run(graph.ainvoke(PipelineState(), {}))
    assert out["design_done"] is True


def test_all_expert_subgraphs_compile():
    from src.layers.l2_orchestration.supervisor import subgraphs

    assert "design" in subgraphs.build_design_subgraph().get_graph().nodes
    assert "verify" in subgraphs.build_verify_subgraph().get_graph().nodes
    debug = subgraphs.build_debug_subgraph().get_graph()
    assert {"round_bump", "ops", "debug_functional",
            "mark_debug_attempt"} <= set(debug.nodes)
    coverage = subgraphs.build_coverage_subgraph().get_graph()
    assert {"coverage", "decide", "governor", "approval"} <= set(coverage.nodes)


def test_hard_audit_gate_requires_report_and_evidence(tmp_path, monkeypatch):
    from src.layers.l2_orchestration.supervisor import audit as audit_mod

    async def fake_audit(state, config):
        return {"audit": {"verdict": "READY"}, "phases": []}

    monkeypatch.setattr(audit_mod, "n_audit", fake_audit)
    monkeypatch.setattr(audit_mod, "verify_package",
                        lambda path: {"ok": True, "issues": []})
    state = PipelineState(output_root=str(tmp_path))

    (tmp_path / "report.json").write_text(
        '{"verdict": "READY", "signoff_status": "APPROVED"}', encoding="utf-8")
    first = asyncio.run(audit_mod.n_hard_audit_gate(state, {}))
    assert first["audit_gate"]["ok"] is False  # 缺 signoff_evidence
    assert first["interrupted"] is True
    assert first["terminal_reason"] == "audit_gate_failed"

    (tmp_path / "signoff_evidence").mkdir()
    (tmp_path / "signoff_evidence" / "manifest.json").write_text(
        '{"package_hash": "abc"}', encoding="utf-8")
    second = asyncio.run(audit_mod.n_hard_audit_gate(state, {}))
    assert second["audit_gate"]["ok"] is True
    assert second["audit_gate"]["package_hash"] == "abc"
    assert second["audit_gate"]["verdict"] == "READY"
    assert "interrupted" not in second


def test_finalize_status_prefers_audit_blocked():
    from src.layers.l2_orchestration.nodes.pure.lifecycle import _run_status

    blocked = PipelineState(audit_gate={"ok": False}, eda_blocked=True,
                            effective_coverage=99.0, target=95.0)
    assert _run_status(blocked) == "AUDIT_BLOCKED"
    assert _run_status(PipelineState(audit_gate={"ok": True},
                                     effective_coverage=99.0,
                                     target=95.0)) == "CONVERGED"


def test_router_only_accepts_known_agents():
    for name in ("design", "verify", "debug", "coverage", "audit"):
        assert r_supervisor(PipelineState(next_agent=name)) == name
    assert r_supervisor(PipelineState(next_agent="execution")) == "audit"
    assert r_supervisor(PipelineState(next_agent="bogus")) == "audit"
