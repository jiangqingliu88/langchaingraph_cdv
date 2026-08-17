"""
Knowledge Graph 查询 —— 把"未覆盖的 bin"溯源成语义路径。

核心函数 trace_uncovered：给定 signal/bin/metric，沿图回溯出
  requirement ← feature ← module ← signal ← bin ← test
并给出语义化建议（而非泛泛 "generate test"）。

用 BFS 上游找"最近的同类节点"，不依赖固定的边链顺序——
bin 可以挂 signal 也可以直接挂 module（寄存器 bin 常见），都能正确溯源。

用法:
    from src.layers.l3_decision.knowledge.query import trace_uncovered, find_gap_contexts
    ctx = trace_uncovered(g, signal="acc_value[15]", metric="toggle")
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional

from .schema import NodeType, EdgeType
from .graph import VerificationGraph


def _nearest_up(graph: VerificationGraph, node_id: str,
                node_type: NodeType, max_depth: int = 8) -> Optional[object]:
    """BFS 沿上游边找最近的指定类型节点（不限定边类型）。"""
    if not node_id:
        return None
    seen = {node_id}
    q = deque([node_id])
    depth = 0
    while q and depth < max_depth:
        for _ in range(len(q)):
            cur = q.popleft()
            if cur != node_id:
                node = graph.get_node(cur)
                if node and node.type == node_type:
                    return node
            for up in graph.neighbors(cur, direction="in"):
                if up.id not in seen:
                    seen.add(up.id)
                    q.append(up.id)
        depth += 1
    return None


def _locate_bin(graph: VerificationGraph, signal: str = None,
                bin: str = None, metric: str = None) -> Optional[str]:
    """定位 coverage_bin 节点 ID。"""
    if bin:
        node = graph.find(NodeType.COVERAGE_BIN, bin)
        if node:
            return node.id
    if signal:
        sig_node = graph.find(NodeType.SIGNAL, signal)
        if sig_node:
            bins = graph.neighbors(sig_node.id, EdgeType.COVERAGE, direction="out")
            if bins:
                if metric:
                    for b in bins:
                        if b.props.get("metric") == metric:
                            return b.id
                return bins[0].id
    return None


def trace_uncovered(graph: VerificationGraph, signal: str = None,
                    bin: str = None, metric: str = None) -> Dict[str, Any]:
    """给定未覆盖的 signal（或 bin），溯源语义路径。

    返回 {requirement, feature, module, signal, bin, metric, test, path, suggestion}
    缺失层级为 None（图不完整时降级）。
    """
    result: Dict[str, Any] = {
        "requirement": None, "feature": None, "module": None,
        "signal": None, "bin": None, "metric": metric,
        "test": None, "path": [], "suggestion": None,
    }

    bin_id = _locate_bin(graph, signal=signal, bin=bin, metric=metric)
    if bin_id:
        bnode = graph.get_node(bin_id)
        result["bin"] = bnode.name
        result["metric"] = bnode.props.get("metric", metric) or metric
        result["path"].append(bin_id)

    # 信号节点：显式给 signal 直接用；否则从 bin 上游找最近的 signal
    sig_node = None
    if signal:
        sig_node = graph.find(NodeType.SIGNAL, signal)
    if bin_id and not sig_node:
        sig_node = _nearest_up(graph, bin_id, NodeType.SIGNAL)
    if sig_node:
        result["signal"] = sig_node.name
        result["path"].append(sig_node.id)

    # 上游锚点：bin（优先）或 signal，从这里找 module/feature/requirement
    anchor = bin_id or (sig_node.id if sig_node else None)

    mod_node = _nearest_up(graph, anchor, NodeType.MODULE) if anchor else None
    if mod_node:
        result["module"] = mod_node.name
        result["path"].append(mod_node.id)

    feat_node = _nearest_up(graph, anchor, NodeType.FEATURE) if anchor else None
    if feat_node:
        result["feature"] = feat_node.name
        result["path"].append(feat_node.id)

    req_node = _nearest_up(graph, anchor, NodeType.REQUIREMENT) if anchor else None
    if req_node:
        result["requirement"] = req_node.name
        result["path"].append(req_node.id)

    # 下游：已有测试（bin → test）
    if bin_id:
        tests = graph.neighbors(bin_id, EdgeType.TEST, direction="out")
        if tests:
            result["test"] = tests[0].name
            result["path"].append(tests[0].id)

    result["suggestion"] = _suggest(result)
    return result


def _suggest(ctx: Dict[str, Any]) -> str:
    """根据语义路径给出动作建议（与 decision_engine 动作空间对齐）。"""
    if ctx.get("test"):
        return "RELAX_CONSTRAINT"          # 已有测试没命中 bin → 约束太紧
    if ctx.get("feature") or ctx.get("requirement"):
        return "GENERATE_DIRECTED_TEST"     # 有语义归属无测试 → 定向补测
    return "INVESTIGATE"                    # 无语义归属（死代码/未映射）


def find_gap_contexts(graph: VerificationGraph, gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量：给 CoverageMap 的 uncovered bins（或 gap 向量）补语义上下文。"""
    contexts = []
    for gap in gaps or []:
        ctx = trace_uncovered(
            graph,
            signal=gap.get("signal"),
            bin=gap.get("bin") or gap.get("location"),
            metric=gap.get("metric") or gap.get("type"),
        )
        merged = dict(gap)
        merged.update(ctx)
        contexts.append(merged)
    return contexts


def summarize(graph: VerificationGraph, gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """给决策层一行可读摘要：每个 gap 的语义归因。"""
    contexts = find_gap_contexts(graph, gaps)
    by_suggestion: Dict[str, int] = {}
    for c in contexts:
        s = c.get("suggestion", "INVESTIGATE")
        by_suggestion[s] = by_suggestion.get(s, 0) + 1
    return {
        "total_gaps": len(contexts),
        "by_suggestion": by_suggestion,
        "contexts": contexts,
    }
