"""运行时知识图 —— 把本轮的覆盖率缺口接进 `VerificationGraph`。

设计时子图（`build_graph_from_spec`）回答“需求 → 功能 → 模块 → 信号 → bin →
测试”。本模块补**运行时因果**：

    GAP ──covered_by→ coverage_bin / test
    GAP ──regressed_in→ rtl_version（lineage）
    GAP ──fixed_by→ fix（debug 记录，若有）
    BUG ──causes→ GAP

数据只来自已有产物：`coverage/tp_matrix.json`、`coverage/testpoints.json`、
`docs/debug_stats.json`、`database/lineage.db`。**不跑 EDA、不调 LLM。**

落盘：`<run>/coverage/knowledge_graph.json`，带 `sha256`，供决策/证据包引用。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .graph import VerificationGraph
from .schema import EdgeType, NodeType, QUERY_CONTRACT

SCHEMA = "knowledge_graph_runtime_v1"
MISS_STATUSES = {"MISS", "UNOBSERVED", "BACKDOOR_MISS", "UNMAPPED"}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_testpoints(output_dir: Path) -> List[Dict[str, Any]]:
    doc = _read_json(output_dir / "coverage" / "testpoints.json")
    items = doc.get("testpoints") or doc.get("items") or []
    if isinstance(items, list) and items:
        return [x for x in items if isinstance(x, dict)]
    # 老 run 只有 YAML
    try:
        import yaml

        y = yaml.safe_load((output_dir / "coverage" / "testpoints.yaml")
                           .read_text(encoding="utf-8", errors="replace")) or {}
        items = y.get("testpoints") or []
        return [x for x in items if isinstance(x, dict)]
    except Exception:                              # noqa: BLE001
        return []


def _ensure(graph: VerificationGraph, node_type: NodeType, name: str,
            **props):
    node = graph.find(node_type, name)
    return node or graph.add_node(node_type, name, **props)


def _rtl_version_node(graph: VerificationGraph, output_dir: Path):
    """这一轮 RTL 版本 → 图节点（没有 RTL 就什么都不加）。"""
    try:
        from src.layers.l4_memory.lineage import ensure_run_rtl_version

        info = ensure_run_rtl_version(output_dir, run_id=output_dir.name)
    except Exception:                              # noqa: BLE001
        return None
    if not info:
        return None
    name = str(info.get("name") or f"v{info.get('version_no')}")
    return _ensure(graph, NodeType.RTL_VERSION, name,
                   content_hash=info.get("content_hash", ""),
                   version_no=info.get("version_no"))


def _load_debug_fixes(output_dir: Path) -> List[Dict[str, Any]]:
    doc = _read_json(output_dir / "docs" / "debug_stats.json")
    fixes = doc.get("fixes") or []
    return [f for f in fixes if isinstance(f, dict)]


def build_runtime_graph(output_dir: str | Path,
                        spec: Optional[Dict[str, Any]] = None) -> VerificationGraph:
    """设计时子图 + 本轮 gap/版本/fix 的运行时子图。"""
    root = Path(output_dir)
    graph = VerificationGraph()
    if spec:
        try:
            from src.tools.checking.spec_tools.verify_dsl import build_graph_from_spec

            graph.merge(build_graph_from_spec(spec))
        except Exception:                          # noqa: BLE001 spec 不完整就只建运行时
            pass

    tp_by_id = {str(t.get("tp_id") or ""): t for t in _load_testpoints(root)}
    matrix = _read_json(root / "coverage" / "tp_matrix.json")
    version_node = _rtl_version_node(graph, root)
    fixes = _load_debug_fixes(root)

    for row in matrix.get("rows") or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if status not in MISS_STATUSES:
            continue
        tp_id = str(row.get("tp_id") or "")
        if not tp_id:
            continue
        gap = _ensure(graph, NodeType.GAP, tp_id,
                      status=status, dimension=row.get("dimension", ""),
                      value=row.get("value", ""), bin=row.get("bin", ""),
                      coverpoint=row.get("coverpoint", ""),
                      hits=row.get("hits", 0), kind=row.get("kind", ""),
                      test=(tp_by_id.get(tp_id, {}).get("execution") or {}).get("test", ""))

        bin_name = str(row.get("bin") or "")
        coverpoint = str(row.get("coverpoint") or "")
        # 不同 coverpoint 常有同名 bin（如 `empty`）—— 按 `coverpoint.bin`
        # 建节点避免撞名；报告里已经带前缀的不重复拼。
        if bin_name and coverpoint and not bin_name.startswith(f"{coverpoint}."):
            bin_name = f"{coverpoint}.{bin_name}"
        if bin_name:
            bin_node = _ensure(graph, NodeType.COVERAGE_BIN, bin_name,
                               dimension=row.get("dimension", ""),
                               coverpoint=coverpoint)
            graph.link(gap, bin_node, EdgeType.COVERED_BY)

        test_name = str((tp_by_id.get(tp_id, {}).get("execution") or {}).get("test") or "")
        if test_name:
            graph.link(gap, _ensure(graph, NodeType.TEST, test_name),
                       EdgeType.COVERED_BY)

        req = str(row.get("requirement") or "")
        if req:
            req_node = graph.find(NodeType.REQUIREMENT, req) or graph.add_node(
                NodeType.REQUIREMENT, req)
            graph.link(gap, req_node, EdgeType.AFFECTS)

        if version_node is not None:
            graph.link(gap, version_node, EdgeType.REGRESSED_IN)

        # debug 记录里如果显式带了 tp_id / dimension，才连 fix；不靠猜。
        for fix in fixes:
            target = str(fix.get("tp_id") or fix.get("dimension") or "")
            if not target or target not in (tp_id, row.get("dimension", "")):
                continue
            # 同一条 fix 可能命中多个 gap —— 节点复用，别每个 gap 造一个。
            fix_node = _ensure(
                graph, NodeType.FIX,
                str(fix.get("fix_name") or fix.get("fingerprint") or "fix"),
                file=fix.get("file_modified", ""), source=fix.get("source", ""))
            graph.link(gap, fix_node, EdgeType.FIXED_BY)
            if fix.get("fingerprint"):
                bug = _ensure(graph, NodeType.BUG, str(fix["fingerprint"]))
                graph.link(bug, gap, EdgeType.CAUSES)
                graph.link(fix_node, bug, EdgeType.RESOLVES)

    return graph


def graph_digest(graph: VerificationGraph) -> str:
    payload = json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_runtime_graph(graph: VerificationGraph, output_dir: str | Path) -> Dict[str, Any]:
    """落 `coverage/knowledge_graph.json`，返回带 sha256 的摘要。"""
    root = Path(output_dir)
    payload = {
        "schema": SCHEMA,
        "query_contract": QUERY_CONTRACT,
        "sha256": graph_digest(graph),
        "summary": graph.stats(),
        "gaps": [n.to_dict() for n in graph.nodes(NodeType.GAP)],
        "graph": graph.to_dict(),
    }
    path = root / "coverage" / "knowledge_graph.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path), "schema": SCHEMA, "sha256": payload["sha256"],
            "nodes": payload["summary"].get("nodes", 0),
            "edges": payload["summary"].get("edges", 0),
            "gaps": len(payload["gaps"])}


# ═══════════════════════════════════════════════════════════════
# 兼容 re-export —— 读取/查询已按职责搬到 persistence / query。
# ═══════════════════════════════════════════════════════════════

from .persistence import load_runtime_graph  # noqa: E402,F401
from .query import trace_gap, enrich_observation_history  # noqa: E402,F401
