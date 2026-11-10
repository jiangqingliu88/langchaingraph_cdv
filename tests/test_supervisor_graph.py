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


def test_default_graph_is_supervisor_with_two_experts():
    graph = build_closed_loop_graph().get_graph()
    names = set(graph.nodes)
    assert {"supervisor", "design_expert", "execution_expert",
            "audit_gate", "finalize"} <= names
    # 子图不是把 24 个节点平铺到主图：主图只有编排节点。
    assert "design" not in names and "ops" not in names


def test_legacy_graph_is_still_available(monkeypatch):
    monkeypatch.setenv("SIGNOFFAI_SUPERVISOR", "off")
    graph = build_closed_loop_graph().get_graph()
    assert "design" in set(graph.nodes)
    assert "supervisor" not in set(graph.nodes)
    assert "design" in set(build_legacy_closed_loop_graph().get_graph().nodes)


def test_supervisor_routes_design_then_execution_then_audit():
    design = asyncio.run(n_supervisor(PipelineState(), {}))
    assert design["next_agent"] == "design"
    assert design["supervisor_visits"] == 1

    execution = asyncio.run(n_supervisor(
        PipelineState(design_done=True), {}))
    assert execution["next_agent"] == "execution"

    audit = asyncio.run(n_supervisor(
        PipelineState(design_done=True, execution_done=True), {}))
    assert audit["next_agent"] == "audit"


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


def test_hard_audit_gate_requires_report_and_evidence(tmp_path, monkeypatch):
    from src.layers.l2_orchestration.supervisor import audit as audit_mod

    async def fake_audit(state, config):
        return {"audit": {"verdict": "READY"}, "phases": []}

    monkeypatch.setattr(audit_mod, "n_audit", fake_audit)
    state = PipelineState(output_root=str(tmp_path))

    (tmp_path / "report.json").write_text(
        '{"verdict": "READY", "signoff_status": "APPROVED"}', encoding="utf-8")
    first = asyncio.run(audit_mod.n_hard_audit_gate(state, {}))
    assert first["audit_gate"]["ok"] is False  # 缺 signoff_evidence

    (tmp_path / "signoff_evidence").mkdir()
    (tmp_path / "signoff_evidence" / "manifest.json").write_text(
        '{"package_hash": "abc"}', encoding="utf-8")
    second = asyncio.run(audit_mod.n_hard_audit_gate(state, {}))
    assert second["audit_gate"]["ok"] is True
    assert second["audit_gate"]["package_hash"] == "abc"
    assert second["audit_gate"]["verdict"] == "READY"


def test_router_only_accepts_known_agents():
    assert r_supervisor(PipelineState(next_agent="design")) == "design"
    assert r_supervisor(PipelineState(next_agent="execution")) == "execution"
    assert r_supervisor(PipelineState(next_agent="audit")) == "audit"
    assert r_supervisor(PipelineState(next_agent="bogus")) == "audit"
