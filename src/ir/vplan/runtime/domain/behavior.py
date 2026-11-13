"""行为域 —— 状态 / 事件 / 迁移 / 序列 / 时序性质（方法学 v2 的 P1）。

属性域回答"有哪些取值、打没打到"；行为域回答"**在什么状态、经过什么迁移、
满足什么时间关系**才算验证过"。两者并列：行为节点最终也落成 `tp_id`，走同一套
TP 矩阵与证据链。

第一版刻意克制：

  · 状态机只做**平坦状态 + 有向迁移**（层次态 / 并行态先不做）；
  · 序列是线性步骤列表（事件 + repeat），不做任意正则/时序逻辑；
  · 时序只支持 `trigger → within N cycles → response` 这类 SVA 可表达形式。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Transition:
    id: str
    from_state: str
    event: str
    to_state: str
    checks: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class BehaviorSequence:
    id: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    expects: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class TemporalProperty:
    id: str
    trigger: str = ""
    condition: Dict[str, Any] = field(default_factory=dict)
    response: Dict[str, Any] = field(default_factory=dict)
    within: Dict[str, Any] = field(default_factory=dict)
    reset_policy: str = "abort"
    checks: List[str] = field(default_factory=list)


@dataclass
class BehaviorModel:
    id: str
    name: str = ""
    clock: str = ""
    reset: Dict[str, Any] = field(default_factory=dict)
    states: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    transitions: List[Transition] = field(default_factory=list)
    sequences: List[BehaviorSequence] = field(default_factory=list)
    temporal: List[TemporalProperty] = field(default_factory=list)
    #: 行为级默认检查（节点没写时继承）
    checks: List[str] = field(default_factory=list)

    def node_ids(self) -> List[str]:
        return ([t.id for t in self.transitions]
                + [s.id for s in self.sequences]
                + [t.id for t in self.temporal])

    def all_checks(self, node_checks: Optional[List[str]] = None) -> List[str]:
        return list(node_checks or self.checks or [])
