"""
Verification Knowledge Graph —— V2 认知层（L2/L3 之上的语义图）。

把验证语义（需求→功能→模块→信号→bin→测试→缺陷→修复）建模成可遍历的图，
作为 Decision Engine 的 Observation 语义来源，让 coverage gap 从"数字"变成"归因"。

用法:
    from src.layers.l3_decision.knowledge.graph import VerificationGraph
    from src.layers.l3_decision.knowledge.query import trace_uncovered, find_gap_contexts
"""
from .schema import Node, NodeType, EdgeType, Edge, nid
from .graph import VerificationGraph
from .query import trace_uncovered, find_gap_contexts, summarize
from .persistence import save_graph_to_db, load_graph_from_db
from .cross_project import lookup_cross_project_bugs, lookup_cross_project_fixes
from .marketplace import export_signoff_package, load_signoff_package, merge_package_into_graph

__all__ = [
    "Node", "NodeType", "Edge", "EdgeType", "nid",
    "VerificationGraph",
    "trace_uncovered", "find_gap_contexts", "summarize",
    "save_graph_to_db", "load_graph_from_db",
    "lookup_cross_project_bugs", "lookup_cross_project_fixes",
    "export_signoff_package", "load_signoff_package", "merge_package_into_graph",
]
