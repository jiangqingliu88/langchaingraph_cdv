"""Interface Timing Contract（IR Plane）。

来源、候选绑定与时序规则的所有权在 IR；是否成立由 Engine 决定。
DERIVED 不能由模型自身升级成 CONFIRMED，未知项必须进入 unknowns。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "interface_timing_v1"


class TimingContractError(ValueError):
    """时序契约形状不正确，不能解释为已验证的接口语义。"""


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TimingContractError(f"{name} 必须是对象")
    return value


def _rows(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise TimingContractError(f"{name} 必须是对象列表")
    return value


def source_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class SourceAnchor:
    """原文片段必须能按声明行号复原，不能用 LLM 自报来源代替。"""

    source_id: str
    locator: str
    quote: str
    line_start: int
    line_end: int
    document_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClockSpec:
    name: str
    period_ps: int
    reset: str
    reset_active_high: bool | None = None
    edge: str = "posedge"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalBinding:
    name: str
    role: str
    width: int = 1
    binding_status: str = "DERIVED"
    protocol: str = "valid_ready"
    source_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TimingRule:
    rule_id: str
    kind: str
    valid: str
    ready: str
    stable_signals: tuple[str, ...]
    clock: ClockSpec
    anchor: SourceAnchor | None = None
    status: str = "DERIVED"

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["stable_signals"] = list(self.stable_signals)
        body["clock"] = self.clock.name
        body["anchor"] = self.anchor.to_dict() if self.anchor else None
        return body


@dataclass
class InterfaceTimingIR:
    interface_id: str
    protocol: str
    interface_group: str
    clock: ClockSpec
    signals: list[SignalBinding]
    rules: list[TimingRule]
    unknowns: list[str] = field(default_factory=list)
    status: str = "DERIVED"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "interface_id": self.interface_id,
            "protocol": self.protocol,
            "interface_group": self.interface_group,
            "status": self.status,
            "version": self.version,
            "clock": self.clock.to_dict(),
            "signals": [row.to_dict() for row in self.signals],
            "rules": [row.to_dict() for row in self.rules],
            "unknowns": list(self.unknowns),
            "metadata": self.metadata,
        }

    def content_hash(self) -> str:
        text = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        return "TIM-" + hashlib.sha256(text.encode()).hexdigest()[:24]


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TimingContractError(f"{name} 必须是整数")
    try:
        return int(value, 0) if isinstance(value, str) else value
    except ValueError as exc:
        raise TimingContractError(f"{name} 不是合法整数：{value!r}") from exc


def _clock(row: dict[str, Any]) -> ClockSpec:
    polarity = row.get("reset_active_high")
    return ClockSpec(
        name=str(row.get("name") or ""),
        period_ps=_integer(row.get("period_ps"), "period_ps"),
        reset=str(row.get("reset") or ""),
        reset_active_high=polarity if isinstance(polarity, bool) else None,
        edge=str(row.get("edge") or "posedge"),
    )


def _signal(row: dict[str, Any]) -> SignalBinding:
    return SignalBinding(
        name=str(row.get("name") or ""),
        role=str(row.get("role") or "").upper(),
        width=_integer(row.get("width", 1), "width"),
        binding_status=str(row.get("binding_status") or "DERIVED").upper(),
        protocol=str(row.get("protocol") or "valid_ready"),
        source_id=str(row.get("source_id") or ""),
    )


def _anchor(row: Any) -> SourceAnchor | None:
    if row is None:
        return None
    row = _mapping(row, "anchor")
    return SourceAnchor(
        source_id=str(row.get("source_id") or ""),
        locator=str(row.get("locator") or ""),
        quote=str(row.get("quote") or ""),
        line_start=_integer(row.get("line_start"), "line_start"),
        line_end=_integer(row.get("line_end"), "line_end"),
        document_sha256=str(row.get("document_sha256") or row.get("sha256") or ""),
    )


def temporal_from_dict(doc: dict[str, Any]) -> InterfaceTimingIR:
    """读取**显式结构化输入**，不根据端口名猜角色或时序。"""
    _mapping(doc, "document")
    clock = _clock(_mapping(doc.get("clock"), "clock"))
    rules = []
    for raw in _rows(doc.get("rules"), "rules"):
        raw_clock = raw.get("clock")
        if isinstance(raw_clock, dict):
            if _clock(raw_clock) != clock:
                raise TimingContractError("规则时钟详情必须与声明时钟一致")
        elif str(raw_clock or clock.name) != clock.name:
            raise TimingContractError("本闭环要求 rule.clock 显式匹配声明时钟")
        rules.append(
            TimingRule(
                rule_id=str(raw.get("rule_id") or raw.get("id") or ""),
                kind=str(raw.get("kind") or "valid_ready_stable"),
                valid=str(raw.get("valid") or ""),
                ready=str(raw.get("ready") or ""),
                stable_signals=tuple(str(x) for x in (raw.get("stable_signals") or [])),
                clock=clock,
                anchor=_anchor(raw.get("anchor")),
                status=str(raw.get("status") or "DERIVED").upper(),
            )
        )
    return InterfaceTimingIR(
        interface_id=str(doc.get("interface_id") or doc.get("id") or ""),
        protocol=str(doc.get("protocol") or "").lower(),
        interface_group=str(doc.get("interface_group") or ""),
        clock=clock,
        signals=[_signal(r) for r in _rows(doc.get("signals"), "signals")],
        rules=rules,
        unknowns=[str(x) for x in (doc.get("unknowns") or [])],
        status=str(doc.get("status") or "DERIVED").upper(),
        version=_integer(doc.get("version", 1), "version"),
        metadata=dict(doc.get("metadata") or {}),
    )


__all__ = [
    "ClockSpec",
    "InterfaceTimingIR",
    "SCHEMA",
    "SignalBinding",
    "SourceAnchor",
    "TimingContractError",
    "TimingRule",
    "source_hash",
    "temporal_from_dict",
]
