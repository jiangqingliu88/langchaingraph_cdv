"""Resource / Interaction Model 的数据形状。

四类核心对象：

    Resource           被访问的资源（SRAM / 寄存器 / Buffer / 通道）
    ResourceOperation  某个 owner 对资源的操作（DMA 搬运 / GEMM 读）
    ResourceAccess     一次操作对资源的访问区间
    ResourceInteraction 两个操作之间的关系与策略
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Resource:
    resource_id: str
    resource_type: str = ""
    address_space: str = ""
    base: Optional[int] = None
    size: Optional[int] = None
    granularity: int = 1
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceAccess:
    address: int
    length: int
    access_type: str = ""          # read | write | readwrite
    transaction_id: str = ""
    operation_id: str = ""


@dataclass
class ResourceOperation:
    operation_id: str
    owner_id: str
    operation_type: str = ""
    resource_id: str = ""
    accesses: List[ResourceAccess] = field(default_factory=list)
    start_condition: str = ""
    completion_event: str = ""
    #: **协议级观测规则**：该操作由哪个 agent 的 monitor 观测，以及如何从
    #: 事务里取 address / length / write。没有这一组字段就无法生成 checker
    #: （不猜字段名 —— 猜错会安静地检查一个永远为 0 的地址）。
    agent: str = ""
    watch: Dict[str, str] = field(default_factory=dict)


@dataclass
class ResourceInteraction:
    interaction_id: str
    operation_a: str
    operation_b: str
    relation: str = "UNRESTRICTED"
    policy_id: str = ""


#: 交互关系（Overlap 是事实，Conflict 是策略推导）。
RELATIONS = frozenset({
    "FORBIDDEN_OVERLAP", "ARBITRATED_OVERLAP", "SERIALIZED", "ORDERED",
    "EXCLUSIVE", "DEPENDENT", "UNRESTRICTED",
})

#: 地址区间关系。
OVERLAP_KINDS = frozenset({"NONE", "ADJACENT", "PARTIAL", "FULL", "CONTAINED"})


__all__ = [
    "OVERLAP_KINDS", "RELATIONS", "Resource", "ResourceAccess",
    "ResourceInteraction", "ResourceOperation",
]
