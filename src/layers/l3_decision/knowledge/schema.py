"""
Verification Knowledge Graph —— 节点/边 schema（V2 认知层地基）

把验证领域的语义关系显式建模成图，回答"这个未覆盖的 bin 属于哪个需求/功能/模块/信号/测试"。

节点/边类型与现有持久化表（persistence/models.py）对齐：
  DocRequirement / DesignFeature / DesignModule / ReqFeatureMap / FeatureTestpointMap

链路（对应 signoff 语义）:
  Requirement -implements→ Feature -rtl→ Module -signal→ Signal -coverage→ CoverageBin -test→ Test
  旁路: Bug -affects→ (Signal|Feature)；Fix -resolves→ Bug

用法:
    from src.layers.l3_decision.knowledge.schema import Node, NodeType, EdgeType
    from src.layers.l3_decision.knowledge.graph import VerificationGraph
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class NodeType(str, Enum):
    """图节点类型"""
    REQUIREMENT = "requirement"      # 需求条目（REQ_xxx）
    FEATURE = "feature"              # 功能点（spec features）
    MODULE = "module"                # RTL 模块（DesignModule）
    SIGNAL = "signal"                # 信号（模块内的 reg/wire）
    COVERAGE_BIN = "coverage_bin"    # 覆盖率 bin（CoverageMap 的 bin）
    TEST = "test"                    # 测试用例（testcase_registry）
    BUG = "bug"                      # 缺陷
    FIX = "fix"                      # 修复
    GAP = "gap"                      # 运行时覆盖缺口（tp_matrix 的 MISS/UNOBSERVED）
    RTL_VERSION = "rtl_version"      # RTL 血缘版本（lineage.db）


class EdgeType(str, Enum):
    """图边类型（方向 = 溯源链从需求流向测试）"""
    IMPLEMENTS = "implements"        # requirement → feature（需求由功能点实现）
    RTL = "rtl"                      # feature → module（功能点映射到 RTL 模块）
    SIGNAL = "signal"                # module → signal（模块包含信号）
    COVERAGE = "coverage"            # signal → coverage_bin（信号被 bin 覆盖）
    TEST = "test"                    # coverage_bin → test（bin 由测试激励）
    AFFECTS = "affects"              # bug/gap → (signal|feature)（缺陷/缺口影响）
    RESOLVES = "resolves"            # fix → bug（修复解决）
    # ── 运行时因果（本轮的 gap 溯源）──
    COVERED_BY = "covered_by"        # gap → coverage_bin / test（本应由谁覆盖）
    CAUSES = "causes"                # bug → gap（缺陷导致缺口）
    FIXED_BY = "fixed_by"            # gap → fix（历史上被谁修过）
    REGRESSED_IN = "regressed_in"    # gap → rtl_version（在哪版观察到）


# 溯源链顺序（从 CoverageBin 一路回溯到 Requirement）
TRACE_CHAIN = [
    (EdgeType.COVERAGE, "in"),   # bin ← signal
    (EdgeType.SIGNAL, "in"),     # signal ← module
    (EdgeType.RTL, "in"),        # module ← feature
    (EdgeType.IMPLEMENTS, "in"), # feature ← requirement
]


@dataclass
class Node:
    """图节点"""
    id: str                                    # 全局唯一 ID（见 nid()）
    type: NodeType
    name: str                                  # 可读名（如 acc_value[15]）
    props: Dict[str, Any] = field(default_factory=dict)  # 扩展属性（metric/priority/status...）

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "type": self.type.value, "name": self.name, **self.props}


@dataclass
class Edge:
    """有向边"""
    src: str
    dst: str
    type: EdgeType
    props: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "type": self.type.value, **self.props}


def nid(node_type: NodeType, name: str) -> str:
    """生成稳定全局 ID：type:name（name 里的冒号/空格归一为 _）。"""
    norm = str(name).replace(":", "_").replace(" ", "_").replace("/", "_")
    return f"{node_type.value}:{norm}"
