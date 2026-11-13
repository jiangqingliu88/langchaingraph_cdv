"""
VerificationGraph —— 验证知识图（纯 Python 邻接表，无外部图库依赖）

在 L2/L3 之上加一层"认知层"：把需求/功能/模块/信号/bin/测试 串成可遍历的图，
作为 Decision Engine 的 Observation 语义来源。

数据来源：
  1. from_spec(spec) —— 从 spec DSL（verify_dsl）构建
  2. from_db()        —— 从现有持久化表（ReqFeatureMap/FeatureTestpointMap/DesignModule）构建

用法:
    from src.ir_plane.decision.knowledge.graph import VerificationGraph
    g = VerificationGraph.from_spec(spec)
    from src.ir_plane.decision.knowledge.query import trace_uncovered
    path = trace_uncovered(g, signal="acc_value[15]", metric="toggle")
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from .schema import Node, NodeType, EdgeType, Edge, nid


class VerificationGraph:
    """有向邻接图 + 反向索引，支持沿溯源链双向遍历。"""

    def __init__(self):
        self._nodes: Dict[str, Node] = {}
        self._out: Dict[str, List[Edge]] = defaultdict(list)   # src → [edge]
        self._in: Dict[str, List[Edge]] = defaultdict(list)    # dst → [edge]

    # ── 节点 ──
    def add_node(self, type: NodeType, name: str, id: str = None, **props) -> Node:
        node = Node(id=id or nid(type, name), type=type, name=name, props=props)
        self._nodes[node.id] = node
        return node

    def get_node(self, id: str) -> Optional[Node]:
        return self._nodes.get(id)

    def find(self, type: NodeType, name: str = None) -> Optional[Node]:
        """按类型（+名字）查节点。"""
        for node in self._nodes.values():
            if node.type != type:
                continue
            if name is None or node.name == name:
                return node
        return None

    def nodes(self, type: NodeType = None) -> List[Node]:
        nodes = list(self._nodes.values())
        if type:
            nodes = [n for n in nodes if n.type == type]
        return nodes

    # ── 边 ──
    def add_edge(self, src: str, dst: str, type: EdgeType, **props) -> Edge:
        edge = Edge(src=src, dst=dst, type=type, props=props)
        self._out[src].append(edge)
        self._in[dst].append(edge)
        return edge

    def link(self, src: Node, dst: Node, type: EdgeType, **props) -> Edge:
        return self.add_edge(src.id, dst.id, type, **props)

    def neighbors(self, id: str, edge_type: EdgeType = None,
                  direction: str = "out") -> List[Node]:
        """邻居节点。direction: out（下游）/ in（上游）。"""
        edges = self._out.get(id, []) if direction == "out" else self._in.get(id, [])
        if edge_type:
            edges = [e for e in edges if e.type == edge_type]
        seen = set()
        result = []
        for e in edges:
            other = e.dst if direction == "out" else e.src
            node = self._nodes.get(other)
            if node and node.id not in seen:
                seen.add(node.id)
                result.append(node)
        return result

    def edges(self, id: str = None, edge_type: EdgeType = None,
              direction: str = "out") -> List[Edge]:
        if id is None:
            edges = [e for lst in self._out.values() for e in lst]
        else:
            edges = list(self._out.get(id, []) if direction == "out" else self._in.get(id, []))
        if edge_type:
            edges = [e for e in edges if e.type == edge_type]
        return edges

    # ── 统计 / 序列化 ──
    def merge(self, other: "VerificationGraph") -> None:
        """合并另一个图：补缺失节点，补不重复的边（不覆盖已有节点）。"""
        for node in other._nodes.values():
            if node.id not in self._nodes:
                self._nodes[node.id] = node
        for e in other.edges():
            if e.src not in self._nodes or e.dst not in self._nodes:
                continue
            dup = any(x.src == e.src and x.dst == e.dst and x.type == e.type
                      for x in self._out.get(e.src, []))
            if not dup:
                self.add_edge(e.src, e.dst, e.type, **e.props)

    def __len__(self) -> int:
        return len(self._nodes)

    def stats(self) -> Dict[str, int]:
        return {
            "nodes": len(self._nodes),
            "edges": sum(len(v) for v in self._out.values()),
            "by_type": {t.value: len(self.nodes(t)) for t in NodeType},
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self.edges()],
        }

    # ── 构造器 ──
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationGraph":
        """从 to_dict() 的输出重建图（签核证据包导入用）。"""
        g = cls()
        for n in data.get("nodes", []) or []:
            g._nodes[n["id"]] = Node(
                id=n["id"], type=NodeType(n["type"]), name=n["name"],
                props={k: v for k, v in n.items() if k not in ("id", "type", "name")})
        for e in data.get("edges", []) or []:
            g.add_edge(e["src"], e["dst"], EdgeType(e["type"]),
                       **{k: v for k, v in e.items() if k not in ("src", "dst", "type")})
        return g

    @classmethod
    def from_spec(cls, spec: Dict[str, Any]) -> "VerificationGraph":
        """从 verify DSL spec 构建（见 verify_dsl.py）。"""
        g = cls()

        def _props(d: Dict, *reserved) -> Dict:
            return {k: v for k, v in d.items() if k not in reserved}

        # 节点
        for req in spec.get("requirements", []) or []:
            g.add_node(NodeType.REQUIREMENT, req.get("id", ""), **_props(req, "id", "name"))
        for feat in spec.get("features", []) or []:
            g.add_node(NodeType.FEATURE, feat.get("id", feat.get("name", "")), **_props(feat, "id", "name"))
        for mod in spec.get("modules", []) or []:
            g.add_node(NodeType.MODULE, mod.get("name", ""), **_props(mod, "name", "id"))
        for sig in spec.get("signals", []) or []:
            g.add_node(NodeType.SIGNAL, sig.get("name", ""), **_props(sig, "name", "id"))
        for bin_ in spec.get("coverage_bins", []) or []:
            g.add_node(NodeType.COVERAGE_BIN, bin_.get("name", ""), **_props(bin_, "name", "id"))
        for test in spec.get("tests", []) or []:
            g.add_node(NodeType.TEST, test.get("name", ""), **_props(test, "name", "id"))
        # 边（relations 显式声明）
        for rel in spec.get("relations", []) or []:
            src, dst, etype = rel.get("src"), rel.get("dst"), rel.get("type")
            if not src or not dst or not etype:
                continue
            try:
                et = EdgeType(etype)
            except ValueError:
                continue
            # 允许 src/dst 用自然名（req id / feature id / signal name），nid 兜底
            s = g._resolve_id(src)
            d = g._resolve_id(dst)
            if s and d:
                g.add_edge(s, d, et, **{k: v for k, v in rel.items() if k not in ("src", "dst", "type")})
        return g

    def _resolve_id(self, ref: str) -> Optional[str]:
        """把自然引用解析为图内节点 ID：先精确 ID，再按 name 匹配。"""
        if ref in self._nodes:
            return ref
        for node in self._nodes.values():
            if node.name == ref:
                return node.id
        return None
