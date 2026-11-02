"""事件话题契约 —— 话题名与 payload 形状只在这里定义。

模块之间仍只通过 `params.subscribe` 听话题、不互相 import；但**同一话题两侧
对字段的理解必须一致**。以前 payload 是一句 `run_id` 字符串，谁想加一个
`run_kind` 都没有地方写；现在把核心话题的形状固定成 dataclass：

    run.selected      RunSelected(run_id, run_kind, project_root, run_path)
    run.updated       RunUpdated(run_id, run_kind, stage, status)
    run.completed     RunCompleted(run_id, status)
    input.changed     InputChanged(module_id, path)
    task.started      TaskStarted(task_id, module_id, operation, run_id)
    task.completed    TaskCompleted(task_id, status, run_id, error)
    evidence.updated  EvidenceUpdated(run_id, ok, files)
    decision.updated  DecisionUpdated(run_id, action, reason)

**兼容旧载荷**：`run_id_of()` 同时认 `str`（旧的 `run_id` 字符串）、`dict`
与 dataclass —— 旧模块的 `str(payload or "")` 换成它即可，不必一次迁完。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

# ── 话题常量（bus.py 继续 re-export，旧 import 不用改）──
TOPIC_INPUT_CHANGED = "input.changed"
TOPIC_MODULE_ACTIVATED = "module.activated"
TOPIC_STATUS = "status.message"
TOPIC_TOOL_ERROR = "tool.error"
TOPIC_LOG = "log"
TOPIC_RUN_SELECTED = "run.selected"
TOPIC_RUN_UPDATED = "run.updated"
TOPIC_RUN_COMPLETED = "run.completed"
TOPIC_TASK_STARTED = "task.started"
TOPIC_TASK_COMPLETED = "task.completed"
TOPIC_EVIDENCE_UPDATED = "evidence.updated"
TOPIC_DECISION_UPDATED = "decision.updated"


@dataclass(frozen=True)
class RunSelected:
    run_id: str
    run_kind: str = ""            # soc / ip / soc_c / uvm
    project_root: str = ""
    run_path: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunUpdated:
    run_id: str
    run_kind: str = ""
    stage: str = ""
    status: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunCompleted:
    run_id: str
    status: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InputChanged:
    module_id: str
    path: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskStarted:
    task_id: str
    module_id: str = ""
    operation: str = ""
    run_id: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskCompleted:
    task_id: str
    status: str = ""
    run_id: str = ""
    error: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceUpdated:
    run_id: str
    ok: Optional[bool] = None     # None ≠ False：还没校验
    files: int = 0

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionUpdated:
    run_id: str
    action: str = ""
    reason: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


def run_id_of(payload: Any) -> str:
    """话题 payload → run_id。兼容 `str`（旧载荷）、`dict` 与 dataclass。"""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return str(payload.get("run_id") or "")
    return str(getattr(payload, "run_id", "") or "")


def to_payload(event: Any) -> Dict[str, Any]:
    """dataclass → dict；已经是 dict 的原样返回（发布方不必两套写法）。"""
    if isinstance(event, dict):
        return event
    to_dict = getattr(event, "to_payload", None)
    if callable(to_dict):
        return to_dict()
    return asdict(event)
