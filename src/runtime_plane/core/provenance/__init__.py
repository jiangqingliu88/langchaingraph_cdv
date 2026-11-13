"""产物血缘 DAG —— 回答「这个覆盖率结果是怎么来的」。

节点是产物 / 测试 / 种子 / 覆盖 bin / 测试点 / 决策对象；边是确定性关系。
不跑 EDA、不调 LLM，只读 run 目录里已有的产物。**没有 per-test 覆盖率时，
bin→test 只能标 weak** —— 合并后的 ucdb 无法把功劳归给某一条测试。
"""
from src.runtime_plane.core.provenance.schema import (
    EDGE_TYPES, NODE_KINDS, SCHEMA, bin_node_id, seed_node_id, test_node_id,
    tp_node_id,
)
from src.runtime_plane.core.provenance.graph import ProvenanceGraph, build_provenance, write_provenance
from src.runtime_plane.core.provenance.report import (
    build_attribution_report, write_attribution_report,
)

__all__ = [
    "SCHEMA", "NODE_KINDS", "EDGE_TYPES",
    "bin_node_id", "seed_node_id", "test_node_id", "tp_node_id",
    "ProvenanceGraph", "build_provenance", "write_provenance",
    "build_attribution_report", "write_attribution_report",
]
