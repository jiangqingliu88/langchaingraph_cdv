"""
Verification DSL —— 结构化验证规格 → Knowledge Graph（V2 认知层的数据入口）

把 spec 从"regex 提取的扁平 JSON"升级为"可表达语义关系的图"。

两种用法：
  1. 显式 DSL（作者/LLM 手写 relations）：
       VerificationGraph.from_spec(verify_dsl_dict)
  2. 自动推断（从现有 spec.json 的 interfaces/features/registers）：
       g = build_graph_from_spec(spec)

DSL schema（显式模式）:
  requirements:   [{id, description}]
  features:       [{id, name}]
  modules:        [{name}]
  signals:        [{name}]
  coverage_bins:  [{name, metric}]
  tests:          [{name}]
  relations:      [{src, dst, type}]   # type ∈ implements/rtl/signal/coverage/test

自动推断规则（build_graph_from_spec）:
  - interfaces[].protocol（非 Clock/Reset）→ 模块节点
  - interfaces[].name → 信号节点（挂在对应协议模块下）
  - features[] → 功能节点，按关键词匹配到模块（apb/uart/intr...）
  - registers[] → coverage_bin 节点
  - overview 的 requirements 注释 → 需求节点（缺失则默认 REQ_{design}_001）

用法:
    from src.tools.checking.spec_tools.verify_dsl import build_graph_from_spec
    g = build_graph_from_spec(spec)
    from src.layers.l3_decision.knowledge.query import trace_uncovered
    trace_uncovered(g, signal="paddr", metric="register")
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from src.layers.l3_decision.knowledge.graph import VerificationGraph
from src.layers.l3_decision.knowledge.schema import NodeType, EdgeType


# feature 关键词 → 协议（module）映射，用于 feature→module 自动推断
_FEATURE_PROTO_KEYWORDS: List[tuple] = [
    (("apb", "寄存器", "读写", "register", "paddr", "cfg", "配置"), "apb"),
    (("uart", "发送", "接收", "串行", "tx", "rx", "串口"), "uart"),
    (("中断", "irq", "intr", "interrupt"), "intr"),
    (("fifo", "缓冲", "buffer"), "uart"),
]


def _infer_feature_protocol(feature_name: str, protocols: set) -> str:
    """按关键词把 feature 名映射到协议（module），匹配不到返回 None。"""
    n = str(feature_name).lower()
    for kws, proto in _FEATURE_PROTO_KEYWORDS:
        if any(kw in n for kw in kws):
            if proto in protocols:
                return proto
    return None


# 寄存器 → 协议（module）关键词推断
_REG_PROTO_KEYWORDS: List[tuple] = [
    (("tx", "baud", "parity", "rx", "fifo", "data"), "uart"),
    (("irq", "intr", "interrupt"), "intr"),
    # 其余默认 apb（寄存器经 APB 访问）
]


def _infer_reg_protocol(reg_name: str) -> str:
    """按寄存器名关键词推断所属协议（module），默认 apb。"""
    n = str(reg_name).lower()
    for kws, proto in _REG_PROTO_KEYWORDS:
        if any(kw in n for kw in kws):
            return proto
    return "apb"


def _extract_requirements(spec: Dict[str, Any], design_name: str) -> List[dict]:
    """从 overview 的 requirements 注释 / spec 显式字段提取需求，缺失给默认。"""
    reqs = spec.get("requirements", []) or []
    if reqs:
        return reqs if isinstance(reqs[0], dict) else [{"id": str(r)} for r in reqs]
    # 从 overview 注释里抠 requirements: [REQ_xxx]
    overview = spec.get("overview", "") or ""
    m = re.search(r"requirements\s*[:：]\s*\[([^\]]+)\]", overview, re.IGNORECASE)
    if m:
        ids = re.findall(r"([A-Za-z_][\w]*)", m.group(1))
        return [{"id": i} for i in ids if i.lower() != "requirements"]
    return [{"id": f"REQ_{design_name.upper()}_001"}]


def build_graph_from_spec(spec: Dict[str, Any]) -> VerificationGraph:
    """从 spec 构建验证知识图（兼容两种输入格式）。

    1. 显式 DSL（含 relations / modules / signals）→ VerificationGraph.from_spec 直接建图
    2. spec.json（含 interfaces / features / registers）→ 自动推断：
       requirement → feature → module(协议) → signal(接口) → bin(寄存器)
    """
    # 格式检测：有显式 relations 或 modules/signals 即按 DSL 处理
    if spec.get("relations") or spec.get("modules") or spec.get("signals"):
        return VerificationGraph.from_spec(spec)

    design = spec.get("design_name", "dut")
    interfaces = spec.get("interfaces", []) or []
    features = spec.get("features", []) or []
    registers = spec.get("registers", []) or []

    # 协议 → 模块（排除 clock/reset）
    protocols: Dict[str, str] = {}   # protocol_lower → protocol_original
    for i in interfaces:
        proto = str(i.get("protocol", "") or "").strip()
        if not proto or proto.lower() in ("clock", "reset", "clk", "rst"):
            continue
        protocols.setdefault(proto.lower(), proto)

    g = VerificationGraph()

    # 1. 需求节点
    req_id = None
    for req in _extract_requirements(spec, design):
        n = g.add_node(NodeType.REQUIREMENT, req.get("id", ""), **{k: v for k, v in req.items() if k != "id"})
        req_id = req_id or n.id

    # 2. 功能节点
    feat_ids: List[str] = []
    for f in features:
        fname = f.get("name") if isinstance(f, dict) else str(f)
        if not fname:
            continue
        n = g.add_node(NodeType.FEATURE, fname,
                       **({k: v for k, v in f.items() if k != "name"} if isinstance(f, dict) else {}))
        feat_ids.append(n.id)
        # requirement → feature（一个需求实现多个功能）
        if req_id:
            g.link(g.get_node(req_id), n, EdgeType.IMPLEMENTS)

    # 3. 模块节点（协议）
    for proto in protocols.values():
        g.add_node(NodeType.MODULE, proto)

    # 4. 信号节点（接口，非 clock/reset）+ module → signal
    for i in interfaces:
        proto = str(i.get("protocol", "") or "").strip().lower()
        sig_name = str(i.get("name", "")).split("[")[0].strip()
        if not sig_name or proto in ("clock", "reset", "clk", "rst", ""):
            continue
        snode = g.add_node(NodeType.SIGNAL, sig_name,
                           direction=str(i.get("direction", "")).lower(),
                           width=i.get("data_width", 1))
        # 挂到协议模块下
        mod_node = g.find(NodeType.MODULE, protocols.get(proto, proto))
        if mod_node:
            g.link(mod_node, snode, EdgeType.SIGNAL)

    # 5. 覆盖率 bin 节点（寄存器）→ 挂到所属模块（协议）
    for r in registers:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        bnode = g.add_node(NodeType.COVERAGE_BIN, r["name"], metric="register",
                           access=r.get("access", ""))
        # 优先挂同名信号（若寄存器名即信号名）；否则挂到按关键词推断的模块
        sig_node = g.find(NodeType.SIGNAL, r["name"])
        if sig_node:
            g.link(sig_node, bnode, EdgeType.COVERAGE)
        else:
            proto = _infer_reg_protocol(r["name"])
            mod_node = g.find(NodeType.MODULE, protocols.get(proto, proto))
            if mod_node:
                g.link(mod_node, bnode, EdgeType.COVERAGE)

    # 6. feature → module 推断（关键词匹配）
    for fid in feat_ids:
        feat_node = g.get_node(fid)
        proto = _infer_feature_protocol(feat_node.name, set(protocols.keys()))
        if proto:
            mod_node = g.find(NodeType.MODULE, protocols[proto])
            if mod_node:
                g.link(feat_node, mod_node, EdgeType.RTL)

    return g


def spec_to_dsl(spec: Dict[str, Any]) -> Dict[str, Any]:
    """把 spec.json 转成显式 DSL 字典（便于落盘/复用/手改）。"""
    g = build_graph_from_spec(spec)
    return g.to_dict()


def propose_relations(spec: Dict[str, Any]) -> Dict[str, Any]:
    """半自动建图的「Propose」步：推断关系 + 置信度，供工程师 Approve。

    这是文档 15.3「KG 建图是半自动」的落地——AI 提建议（Propose），
    工程师通过 CLI/人工确认或修正（Approve）后再落库。

    置信度规则（粗糙但够用）：
      - rtl 边（feature→module，关键词匹配）= 0.6（低置信，需重点 review）
      - 其余边（implements/signal/coverage，protocol/spec 推导）= 0.9（高置信）

    返回 {relations: [{src, dst, type, confidence}], low_confidence: [...]}
    """
    g = build_graph_from_spec(spec)
    relations = []
    low_conf = []
    for e in g.edges():
        src_node = g.get_node(e.src)
        dst_node = g.get_node(e.dst)
        if not src_node or not dst_node:
            continue
        conf = 0.6 if e.type == EdgeType.RTL else 0.9
        rel = {"src": src_node.name, "dst": dst_node.name,
               "type": e.type.value, "confidence": conf}
        relations.append(rel)
        if conf < 0.8:
            low_conf.append(rel)
    return {
        "relations": relations,
        "low_confidence": low_conf,
        "summary": (f"推断 {len(relations)} 条关系，其中 {len(low_conf)} 条低置信"
                    f"（需工程师 review/修正）"),
    }
