"""产物血缘图与确定性落盘。

输出两份文件（都在 `<run>/docs/`）：
    provenance.jsonl         nodes / edges 各一行，排序后写入，**不含时间戳**
    provenance_summary.json  规模、置信度分布、未归因 bin、说明

为什么是 JSONL 而不是 SQLite：证据包要能整目录打包、换机器、被标准库
`replay.py` 读取；每-run 一份 JSONL 满足这三条。跨 run 的索引是 roadmap，
不在这里冒充已实现。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.provenance.attribution import (
    Attribution, classify, read_json, sha256_file,
)
from src.core.provenance.schema import (
    SCHEMA, bin_node_id, seed_node_id, test_node_id, tp_node_id,
)


class ProvenanceGraph:
    """内存图；写入前统一排序，保证同一输入重复构建得到同一串字节。"""

    def __init__(self, run_id: str = ""):
        self.run_id = run_id
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self._edge_keys: set = set()
        self.unattributed_bins: List[str] = []
        self.notes: List[str] = []

    # ── 构建 ──

    def add_node(self, node_id: str, kind: str, *, label: str = "",
                 sha256: str = "", producer: str = "", round: int = 0,
                 **attrs: Any) -> str:
        node = self.nodes.get(node_id)
        if node is None:
            node = {"id": node_id, "kind": kind, "label": label or node_id,
                    "sha256": sha256, "run_id": self.run_id, "round": int(round or 0),
                    "producer": producer, "attrs": {}}
            self.nodes[node_id] = node
        else:
            if sha256:
                node["sha256"] = sha256
            if producer:
                node["producer"] = producer
            if round:
                node["round"] = int(round)
        node["attrs"].update({k: v for k, v in attrs.items()
                              if v not in (None, "", [], {})})
        return node_id

    def add_edge(self, src: str, dst: str, edge_type: str, *,
                 evidence: str = "", confidence: str = "exact") -> None:
        key = (edge_type, src, dst)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append({"schema": SCHEMA, "type": edge_type,
                           "src": src, "dst": dst,
                           "evidence": evidence, "confidence": confidence})

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def has_edge(self, src: str, dst: str, edge_type: str = "") -> bool:
        return any(e["src"] == src and e["dst"] == dst
                   and (not edge_type or e["type"] == edge_type)
                   for e in self.edges)

    # ── 输出 ──

    def _node_list(self) -> List[Dict[str, Any]]:
        return [self.nodes[k] for k in sorted(
            self.nodes, key=lambda n: (self.nodes[n]["kind"], n))]

    def _edge_list(self) -> List[Dict[str, Any]]:
        return sorted(self.edges, key=lambda e: (e["type"], e["src"], e["dst"]))

    def to_jsonl(self) -> str:
        lines: List[str] = []
        for node in self._node_list():
            lines.append(json.dumps(node, ensure_ascii=False, sort_keys=True))
        for edge in self._edge_list():
            lines.append(json.dumps(edge, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines) + ("\n" if lines else "")

    def summary(self) -> Dict[str, Any]:
        by_kind: Dict[str, int] = {}
        for node in self.nodes.values():
            by_kind[node["kind"]] = by_kind.get(node["kind"], 0) + 1
        by_type: Dict[str, int] = {}
        by_conf: Dict[str, int] = {}
        for edge in self.edges:
            by_type[edge["type"]] = by_type.get(edge["type"], 0) + 1
            by_conf[edge["confidence"]] = by_conf.get(edge["confidence"], 0) + 1
        return {
            "schema": SCHEMA,
            "run_id": self.run_id,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "by_kind": dict(sorted(by_kind.items())),
            "by_type": dict(sorted(by_type.items())),
            "by_confidence": dict(sorted(by_conf.items())),
            "unattributed_bins": sorted(self.unattributed_bins),
            "notes": list(self.notes),
        }


# ═══════════════════════════════════════════════════════════════
# 从 run 目录构建
# ═══════════════════════════════════════════════════════════════

_ARTIFACTS: Tuple[Tuple[str, str, str], ...] = (
    ("spec.json", "spec", "front"),
    ("inputs/casemodel.yaml", "casemodel", "front"),
    ("coverage/testpoints.json", "tp_ir", "verify"),
    ("coverage/stimulus_plan.json", "stimulus_plan", "verify"),
    ("coverage/tp_matrix.json", "tp_matrix", "coverage"),
    ("coverage/knowledge_graph.json", "knowledge_graph", "coverage"),
    ("inputs/yaml/uvm/regression.yaml", "regression_plan", "verify"),
    ("docs/verification_quality.json", "verification_quality", "audit"),
)


def _add_artifacts(root: Path, graph: ProvenanceGraph) -> Dict[str, str]:
    """登记关键产物；返回 kind → node_id（缺失的产物不建节点，不伪造）。"""
    ids: Dict[str, str] = {}
    for rel, kind, producer in _ARTIFACTS:
        path = root / rel
        if not path.is_file():
            continue
        node_id = f"artifact:{kind}:{rel}"
        graph.add_node(node_id, "artifact", label=rel, sha256=sha256_file(path),
                       producer=producer, path=rel)
        ids[kind] = node_id
    rtl_dir = root / "rtl"
    if rtl_dir.is_dir():
        parts = []
        for sv in sorted(rtl_dir.rglob("*")):
            if not (sv.is_file() and sv.suffix.lower() in (".v", ".sv", ".svh", ".vh")):
                continue
            rel = sv.relative_to(root).as_posix()
            digest = sha256_file(sv)
            node_id = f"artifact:rtl:{rel}"
            graph.add_node(node_id, "artifact", label=rel, sha256=digest,
                           producer="design", path=rel)
            ids.setdefault("rtl", node_id)
            parts.append(f"{rel}:{digest}")
        if parts:
            aggregate = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
            graph.add_node("artifact:rtl_dir", "artifact", label="rtl/",
                           sha256=aggregate, producer="design",
                           files=len(parts))
            ids["rtl_dir"] = "artifact:rtl_dir"
    return ids


def _add_derivations(graph: ProvenanceGraph, ids: Dict[str, str]) -> None:
    """已知的确定性派生关系（只在两端都存在时建边）。"""
    pairs = (
        ("spec", "tp_ir", "spec → TP IR"),
        ("casemodel", "tp_ir", "case 模型 → TP IR"),
        ("tp_ir", "stimulus_plan", "TP IR → StimulusPlan"),
        ("tp_ir", "tp_matrix", "TP IR → TP 矩阵"),
        ("regression_plan", "tp_matrix", "回归计划 → TP 矩阵"),
        ("tp_matrix", "knowledge_graph", "TP 矩阵 → 运行时知识图"),
    )
    for src_kind, dst_kind, why in pairs:
        if src_kind in ids and dst_kind in ids:
            graph.add_edge(ids[src_kind], ids[dst_kind], "derived_from",
                           evidence=why, confidence="exact")


def _add_execution_chain(graph: ProvenanceGraph, ids: Dict[str, str],
                         attr: Attribution) -> None:
    """把 test 接到 StimulusPlan 与 RTL 快照 —— 补齐用户要的完整链。

    证据是「同一轮共用」：run 级 StimulusPlan 与 RTL 快照对所有 test 成立。
    这是**计划级**关系，不是 per-test 精确输入（那需要编译依赖图）。
    """
    plan_id = ids.get("stimulus_plan")
    rtl_id = ids.get("rtl_dir")
    for test in sorted(attr.tests):
        node = test_node_id(test)
        if plan_id:
            graph.add_edge(node, plan_id, "executed_with",
                           evidence="同一 run 的 StimulusPlan", confidence="exact")
        if rtl_id:
            graph.add_edge(node, rtl_id, "executed_against",
                           evidence="同一 run 的 RTL 快照", confidence="exact")


def _add_attribution(graph: ProvenanceGraph, attr: Attribution) -> None:
    # test 节点 + 种子
    for test, info in sorted(attr.tests.items()):
        node_id = test_node_id(test)
        graph.add_node(node_id, "test", label=test,
                       log_sha256=info.get("log_sha256", ""),
                       dirs=info.get("dirs", []))
        for seed in sorted(info.get("seeds") or []):
            seed_id = seed_node_id(seed)
            graph.add_node(seed_id, "seed", label=str(seed), seed=int(seed))
            graph.add_edge(node_id, seed_id, "seed_derived",
                           evidence=f"test 目录名 _seed_{seed}", confidence="exact")

    # TP 节点 + TP→test / TP→bin
    for tp_id in sorted(set(attr.tp_to_tests) | set(attr.tp_bins)):
        tp_id_node = tp_node_id(tp_id)
        graph.add_node(tp_id_node, "tp", label=tp_id)
        for test in sorted(attr.tp_to_tests.get(tp_id) or set()):
            graph.add_edge(test_node_id(test), tp_id_node, "realizes",
                           evidence="round_manifest: test_name/tp_id",
                           confidence="exact")
        for bin_id in sorted(attr.tp_bins.get(tp_id) or set()):
            graph.add_node(bin_id, "bin", label=bin_id.split("bin:", 1)[-1])
            graph.add_edge(tp_id_node, bin_id, "aggregates",
                           evidence="testpoints.json: coverpoint/bin",
                           confidence="exact")

    # 精确命中 / 弱归因命中
    for bin_id, tests in sorted(attr.bin_tests_exact.items()):
        graph.add_node(bin_id, "bin", label=bin_id.split("bin:", 1)[-1])
        for test in sorted(tests):
            graph.add_node(test_node_id(test), "test", label=test)
            graph.add_edge(bin_id, test_node_id(test), "hit_by",
                           evidence="per-test 覆盖率 sidecar（coverage/per_test_bins.json）",
                           confidence="exact")
    for bin_id, tests in sorted(attr.bin_tests_weak.items()):
        graph.add_node(bin_id, "bin", label=bin_id.split("bin:", 1)[-1])
        for test in sorted(tests):
            graph.add_node(test_node_id(test), "test", label=test)
            graph.add_edge(bin_id, test_node_id(test), "attributed_by",
                           evidence="仅有合并 ucdb；按 round_manifest 的 TP→test 计划映射",
                           confidence="weak")

    graph.unattributed_bins = sorted(attr.unattributed_bins)
    graph.notes.extend(attr.notes)


def _add_decisions(graph: ProvenanceGraph, root: Path) -> None:
    """决策评估记录 → decision_obj 节点（没有文件就什么都不加）。"""
    path = root / "decision" / "evaluations.jsonl"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        action = (doc.get("action") or {}).get("action_type") or "UNKNOWN"
        node_id = f"decision_obj:{doc.get('round', 0)}:{action}"
        graph.add_node(node_id, "decision_obj", label=f"round {doc.get('round', 0)} {action}",
                       round=int(doc.get("round", 0) or 0),
                       action=action, status=doc.get("status", ""),
                       reason=doc.get("reason", ""))
        for evidence in doc.get("actual", {}).get("evidence") or []:
            for node in list(graph.nodes.values()):
                if node["kind"] == "artifact" and node["label"] == evidence:
                    graph.add_edge(node_id, node["id"], "evaluated",
                                   evidence=doc.get("status", ""),
                                   confidence=doc.get("confidence", "weak"))


def build_provenance(run_root: str | Path, *, run_id: str = "",
                     attribution: Optional[Attribution] = None) -> ProvenanceGraph:
    root = Path(run_root)
    graph = ProvenanceGraph(run_id=run_id or root.name)
    ids = _add_artifacts(root, graph)
    attr = attribution or classify(root)
    _add_derivations(graph, ids)
    _add_execution_chain(graph, ids, attr)
    _add_attribution(graph, attr)
    _add_decisions(graph, root)
    return graph


def write_provenance(run_root: str | Path,
                     graph: Optional[ProvenanceGraph] = None,
                     *, event_store=None) -> Dict[str, Any]:
    """落盘 JSONL + summary；返回 {path, jsonl_sha256, summary_path, summary}。"""
    root = Path(run_root)
    graph = graph or build_provenance(root)
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    jsonl_path = docs / "provenance.jsonl"
    body = graph.to_jsonl()
    jsonl_path.write_text(body, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    summary = graph.summary()
    summary_path = docs / "provenance_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    if event_store is not None:
        event_store.append(
            "provenance.built", status="ok",
            payload={"path": jsonl_path.relative_to(root).as_posix(),
                     "sha256": digest, "nodes": summary["nodes"],
                     "edges": summary["edges"]},
            source="provenance",
            dedup_key=f"provenance:{digest}")
    return {"path": str(jsonl_path), "jsonl_sha256": digest,
            "summary_path": str(summary_path), "summary": summary}
