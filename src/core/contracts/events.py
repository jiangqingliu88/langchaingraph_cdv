"""事件类型 + 产生者注册表。

目的不是替代 `EventStore`，而是**把「谁有资格写这个事件」写进契约**：
一个 pipeline 事实只应有一个 appender（例如 `stage.*` 只由 RunJournal 镜像写），
否则重入/并发时会写出两份互相打架的事实。
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

EVENT_TYPES = frozenset({
    # run / stage（journal 镜像）
    "run.started", "run.resumed", "run.finished", "run.failed",
    "run.cancelled", "run.interrupted",
    "stage.started", "stage.finished", "stage.failed",
    "decision", "approval.requested", "approval.decided", "coverage.updated",
    # 决策评估
    "decision.expected", "decision.evaluated",
    # 轮次事实
    "round.facts",
    # Job / 工具 / 产物
    "job.started", "job.finished", "job.timeout", "job.denied",
    "tool.invoked", "artifact.produced",
    # 收尾证据
    "provenance.built", "quality.gate", "metrics.collected",
})

#: 事件 → 唯一产生者。新增事件必须在这里登记，否则 `validate_event_type`
#: 只回答「类型存在」，不回答「谁能写」。
PRODUCERS: Dict[str, str] = {
    "run.started": "execution|journal",
    "run.resumed": "journal",
    "run.finished": "execution|journal",
    "run.failed": "execution|journal",
    "run.cancelled": "journal",
    "run.interrupted": "journal",
    "stage.started": "journal",
    "stage.finished": "journal",
    "stage.failed": "journal",
    "decision": "journal",
    "approval.requested": "journal",
    "approval.decided": "journal",
    "coverage.updated": "journal",
    "decision.expected": "node:record_decision",
    "decision.evaluated": "node:coverage",
    "round.facts": "round_facts",
    "job.started": "supervisor",
    "job.finished": "supervisor",
    "job.timeout": "supervisor",
    "job.denied": "supervisor",
    "tool.invoked": "toolhub",
    "artifact.produced": "artifact_store",
    "provenance.built": "provenance",
    "quality.gate": "quality",
    "metrics.collected": "metrics",
}


def validate_event_type(event_type: str) -> bool:
    return str(event_type or "") in EVENT_TYPES_MUTABLE


def event_producer(event_type: str) -> str:
    return PRODUCERS.get(str(event_type or ""), "")


def register_producer(event_type: str, producer: str, *,
                      replace: bool = False) -> None:
    """登记新事件/产生者。`replace=False` 时重复登记不同产生者 → ValueError。"""
    event_type = str(event_type or "")
    producer = str(producer or "")
    if not event_type or not producer:
        raise ValueError("event_type / producer 不能为空")
    old = PRODUCERS.get(event_type)
    if old is not None and old != producer and not replace:
        raise ValueError(f"事件 {event_type!r} 已登记产生者 {old!r}，"
                         f"不允许静默改成 {producer!r}")
    PRODUCERS[event_type] = producer
    EVENT_TYPES_MUTABLE.add(event_type)


#: 允许 `register_producer` 扩展的集合（EVENT_TYPES 本身是 frozenset）
EVENT_TYPES_MUTABLE: set = set(EVENT_TYPES)
