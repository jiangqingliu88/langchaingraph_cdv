"""运行时知识图 —— gap → bin/test/version/fix 的确定性因果链。

数据只来自已有产物（tp_matrix / testpoints / debug_stats / lineage），
所以测试也不必跑 EDA：造一个最小 run 目录即可。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.layers.l3_decision.decision_engine import Observation
from src.layers.l3_decision.knowledge.persistence import load_runtime_graph
from src.layers.l3_decision.knowledge.query import (
    enrich_observation_history,
    trace_gap,
)
from src.layers.l3_decision.knowledge.runtime import (
    MISS_STATUSES,
    SCHEMA,
    build_runtime_graph,
    graph_digest,
    write_runtime_graph,
)
from src.layers.l3_decision.knowledge.schema import EdgeType, NodeType


@pytest.fixture()
def run_dir(tmp_path: Path, monkeypatch) -> Path:
    """一个只有产物、没有 EDA 的 run 目录。"""
    root = tmp_path / "run_x"
    (root / "coverage").mkdir(parents=True)
    (root / "docs").mkdir()

    (root / "coverage" / "testpoints.json").write_text(json.dumps({
        "testpoints": [
            {"tp_id": "TP1", "execution": {"test": "test_op_zero"}},
            {"tp_id": "TP2", "execution": {"test": "test_op_full"}},
        ]
    }), encoding="utf-8")

    (root / "coverage" / "tp_matrix.json").write_text(json.dumps({
        "rows": [
            {"tp_id": "TP1", "status": "MISS", "dimension": "op",
             "value": "0", "bin": "cg_dut.op_zero", "coverpoint": "cg_dut",
             "hits": 0, "kind": "drivable", "requirement": "REQ_OP"},
            {"tp_id": "TP2", "status": "HIT", "dimension": "op",
             "value": "full", "bin": "cg_dut.op_full", "hits": 12},
            {"tp_id": "", "status": "MISS", "bin": "cg_dut.orphan"},
        ],
    }), encoding="utf-8")

    (root / "docs" / "debug_stats.json").write_text(json.dumps({
        "fixes": [
            {"tp_id": "TP1", "fix_name": "relax_op_zero",
             "fingerprint": "fp_abc", "file_modified": "env/constraints.sv"},
            {"fix_name": "unrelated"},
        ]
    }), encoding="utf-8")

    monkeypatch.setattr(
        "src.layers.l4_memory.lineage.ensure_run_rtl_version",
        lambda output_dir, module="", run_id="": {
            "module": "dut", "version_no": 7, "name": "v7",
            "content_hash": "deadbeef"})
    return root


def test_only_miss_like_rows_become_gaps(run_dir: Path):
    graph = build_runtime_graph(run_dir)
    gaps = graph.nodes(NodeType.GAP)
    # HIT 不算缺口；tp_id 为空的行无法稳定标识，也不建
    assert [g.name for g in gaps] == ["TP1"]
    assert MISS_STATUSES == {"MISS", "UNOBSERVED", "BACKDOOR_MISS", "UNMAPPED"}


def test_gap_edges_are_causal_and_deterministic(run_dir: Path):
    graph = build_runtime_graph(run_dir)
    gap = graph.find(NodeType.GAP, "TP1")
    assert gap is not None
    assert gap.props["bin"] == "cg_dut.op_zero"
    assert gap.props["test"] == "test_op_zero"

    targets = {}
    for edge in graph.edges(gap.id, direction="out"):
        node = graph.get_node(edge.dst)
        targets[(node.type, node.name)] = edge
    assert (NodeType.COVERAGE_BIN, "cg_dut.op_zero") in targets
    assert (NodeType.TEST, "test_op_zero") in targets
    assert (NodeType.REQUIREMENT, "REQ_OP") in targets
    assert (NodeType.RTL_VERSION, "v7") in targets
    assert (NodeType.FIX, "relax_op_zero") in targets
    edge_types = {targets[k].type for k in targets}
    assert EdgeType.COVERED_BY in edge_types
    assert EdgeType.REGRESSED_IN in edge_types
    assert EdgeType.FIXED_BY in edge_types
    assert EdgeType.AFFECTS in edge_types

    # BUG → GAP（causes）与 FIX → BUG（resolves）
    bug = graph.find(NodeType.BUG, "fp_abc")
    fix = graph.find(NodeType.FIX, "relax_op_zero")
    assert bug is not None and fix is not None
    assert any(e.type == EdgeType.CAUSES and e.src == bug.id
               for e in graph.edges(bug.id, direction="out"))
    assert any(e.type == EdgeType.RESOLVES and e.dst == bug.id
               for e in graph.edges(fix.id, direction="out"))


def test_bin_nodes_are_qualified_by_coverpoint(tmp_path: Path, monkeypatch):
    """不同 coverpoint 的同名 bin 不能撞成一个节点。"""
    root = tmp_path / "run_q"
    (root / "coverage").mkdir(parents=True)
    (root / "coverage" / "tp_matrix.json").write_text(json.dumps({"rows": [
        {"tp_id": "TP-A", "status": "MISS", "coverpoint": "cp_a", "bin": "empty"},
        {"tp_id": "TP-B", "status": "MISS", "coverpoint": "cp_b", "bin": "cp_b.empty"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(
        "src.layers.l4_memory.lineage.ensure_run_rtl_version",
        lambda output_dir, module="", run_id="": {})
    graph = build_runtime_graph(root)
    names = sorted(b.name for b in graph.nodes(NodeType.COVERAGE_BIN))
    assert names == ["cp_a.empty", "cp_b.empty"]
    # GAP 上保留报告里的原始 bin（`trace_gap(bin=...)` 按它匹配）
    assert graph.find(NodeType.GAP, "TP-A").props["bin"] == "empty"


def test_same_fix_is_shared_across_gaps(tmp_path: Path, monkeypatch):
    """一条 fix 命中多个缺口时只建一个 FIX 节点、每个缺口一条边。"""
    root = tmp_path / "run_shared"
    (root / "coverage").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "coverage" / "tp_matrix.json").write_text(json.dumps({"rows": [
        {"tp_id": "TP-A", "status": "MISS", "dimension": "op", "bin": "zero"},
        {"tp_id": "TP-B", "status": "MISS", "dimension": "op", "bin": "full"},
    ]}), encoding="utf-8")
    (root / "docs" / "debug_stats.json").write_text(json.dumps({"fixes": [
        {"dimension": "op", "fix_name": "relax_op", "fingerprint": "fp_x"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(
        "src.layers.l4_memory.lineage.ensure_run_rtl_version",
        lambda output_dir, module="", run_id="": {})
    graph = build_runtime_graph(root)
    assert len(graph.nodes(NodeType.FIX)) == 1
    assert len(graph.nodes(NodeType.BUG)) == 1
    fixes = [e for e in graph.edges() if e.type == EdgeType.FIXED_BY]
    assert len(fixes) == 2


def test_unrelated_fix_is_not_linked(run_dir: Path):
    graph = build_runtime_graph(run_dir)
    assert graph.find(NodeType.FIX, "unrelated") is None
    assert len(graph.nodes(NodeType.BUG)) == 1


def test_write_and_load_roundtrip_is_hash_stable(run_dir: Path):
    graph = build_runtime_graph(run_dir)
    first = write_runtime_graph(graph, run_dir)

    doc = json.loads((run_dir / "coverage" / "knowledge_graph.json")
                     .read_text(encoding="utf-8"))
    assert doc["schema"] == SCHEMA
    assert first["sha256"] == doc["sha256"] == graph_digest(graph)
    assert first["schema"] == SCHEMA
    assert first["gaps"] == 1
    assert doc["gaps"][0]["name"] == "TP1"

    loaded = load_runtime_graph(run_dir)
    assert len(loaded) == len(graph)
    assert graph_digest(loaded) == first["sha256"]

    # 同样的输入再跑一次必须得到同一份哈希（证据包靠它绑定图身份）
    assert write_runtime_graph(build_runtime_graph(run_dir), run_dir)["sha256"] \
        == first["sha256"]


def test_trace_gap_by_id_and_by_bin(run_dir: Path):
    graph = build_runtime_graph(run_dir)
    by_id = trace_gap(graph, tp_id="TP1")
    assert by_id["gap"] == "TP1"
    assert by_id["status"] == "MISS"
    assert [t["name"] for t in by_id["tests"]] == ["test_op_zero"]
    assert [b["name"] for b in by_id["bins"]] == ["cg_dut.op_zero"]
    assert [r["name"] for r in by_id["requirements"]] == ["REQ_OP"]
    assert [v["name"] for v in by_id["rtl_versions"]] == ["v7"]
    assert [f["name"] for f in by_id["fixes"]] == ["relax_op_zero"]
    assert len(by_id["bugs"]) == 1

    by_bin = trace_gap(graph, bin="cg_dut.op_zero")
    assert by_bin["gap"] == by_id["gap"]
    assert trace_gap(graph, tp_id="NOPE", bin="nope") == {}


def test_enrich_observation_history_attaches_only_matching_gaps(run_dir: Path):
    write_runtime_graph(build_runtime_graph(run_dir), run_dir)
    obs = Observation(gap_paths=[
        {"bin": "cg_dut.op_zero", "feature": "op"},
        {"bin": "cg_dut.none", "feature": "op"},
    ])
    out = enrich_observation_history(obs, run_dir)
    assert out.gap_paths[0]["history"]["gap"] == "TP1"
    assert out.gap_paths[0]["history"]["rtl_versions"][0]["name"] == "v7"
    assert "history" not in out.gap_paths[1]


def test_semantic_reason_consumes_history(run_dir: Path):
    """图不是孤立的 JSON —— 决策归因真的读到了历史版本与修复。"""
    from src.layers.l3_decision.decision_engine import CoverageDrivenDecisionEngine

    write_runtime_graph(build_runtime_graph(run_dir), run_dir)
    obs = Observation(gap_paths=[{
        "bin": "cg_dut.op_zero", "feature": "op",
        "suggestion": "RELAX_CONSTRAINT",
    }])
    enrich_observation_history(obs, run_dir)
    reason = CoverageDrivenDecisionEngine._semantic_reason(obs.gap_paths)
    assert "op.cg_dut.op_zero" in reason
    assert "@历史版本v7" in reason
    assert "relax_op_zero" in reason


def test_enrich_without_graph_is_a_noop(tmp_path: Path):
    obs = Observation(gap_paths=[{"bin": "x"}])
    out = enrich_observation_history(obs, tmp_path / "nothing")
    assert out is obs
    assert "history" not in obs.gap_paths[0]


def test_evidence_package_carries_runtime_artifacts(run_dir: Path):
    """知识图与奖励必须进证据包，不能只躺在 run 目录里。"""
    from src.layers.l2_orchestration.evidence.signoff_package import write_package

    write_runtime_graph(build_runtime_graph(run_dir), run_dir)
    (run_dir / "coverage" / "sim_reward.json").write_text(
        json.dumps({"total": 0.5, "weakest": "coverage"}), encoding="utf-8")

    manifest = write_package(run_dir, {"run": run_dir.name, "artifacts": {}})
    rels = {f["path"] for f in manifest["files"]}
    assert "execution/coverage/knowledge_graph.json" in rels
    assert "execution/coverage/sim_reward.json" in rels
    assert (run_dir / "signoff_evidence" / "execution" / "coverage"
            / "knowledge_graph.json").is_file()


def test_spec_subgraph_is_merged(run_dir: Path):
    spec = {
        "requirements": [{"id": "REQ_OP"}],
        "features": [{"name": "op"}],
        "coverage_bins": [{"name": "cg_dut.op_zero"}],
        "relations": [
            {"src": "REQ_OP", "dst": "op", "type": "implements"},
            {"src": "op", "dst": "cg_dut.op_zero", "type": "rtl"},
        ],
    }
    graph = build_runtime_graph(run_dir, spec)
    assert graph.find(NodeType.FEATURE, "op") is not None
    assert graph.find(NodeType.GAP, "TP1") is not None
    # 运行时缺口连到 spec 里已有的 bin 节点，而不是再造一个同名节点
    assert len([b for b in graph.nodes(NodeType.COVERAGE_BIN)
                if b.name == "cg_dut.op_zero"]) == 1


def test_build_query_persistence_are_separate_modules():
    """构建 / 查询 / 落盘拆开：query 不再 import runtime（避免职责又耦合回去）。"""
    import src.layers.l3_decision.knowledge.persistence as persistence
    import src.layers.l3_decision.knowledge.query as query
    import src.layers.l3_decision.knowledge.runtime as runtime

    assert runtime.build_runtime_graph.__module__ == runtime.__name__
    assert query.trace_gap.__module__ == query.__name__
    assert persistence.load_runtime_graph.__module__ == persistence.__name__

    # 兼容旧导入路径（行为不变）
    assert runtime.trace_gap is query.trace_gap
    assert runtime.enrich_observation_history is query.enrich_observation_history
    assert runtime.load_runtime_graph is persistence.load_runtime_graph

    src = Path(query.__file__).read_text(encoding="utf-8")
    assert "knowledge.runtime" not in src and "from .runtime" not in src
