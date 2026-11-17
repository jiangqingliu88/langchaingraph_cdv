"""行为域编译 —— `behavior:` 块 → 行为测试点（P1）。

每个行为节点落一条 TP，沿用同一个主键前缀，进同一份 TP IR：

| 节点 | TP 形态 | realization |
|---|---|---|
| 迁移 | `TP-<obj>-BEH-<id>-TR-<id>` | `observe`（覆盖面：边到达） |
| 序列 | `TP-<obj>-BEH-<id>-SEQ-<id>` | `sequence`（步骤是事件序列） |
| 时序 | `TP-<obj>-BEH-<id>-TMP-<id>` | `observe`（触发-响应命中） |

第一版（P1a）只做**建模与 IR**：TP 进 `testpoints` 与计数，执行后端（把事件
序列编译成 UVM sequence）是 P1b。`execution.stage = "behavior"` 把它和属性
测试点分开；`notes` 里如实写明"执行后端待接"，不冒充可执行。
"""
from __future__ import annotations

from typing import Any, List

from .model import Execution, Realization, TestPoint
from .naming import derive_code, unique_tp_id

KIND_OBSERVE = "observe"
KIND_SEQUENCE = "sequence"

_BEHAVIOR_NOTE = "行为域 P1a：已进 TP IR；执行后端（事件序列 → UVM）在 P1b"


def _safe(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in str(text or ""))
    return out.strip("_") or "NODE"


def _label(behavior: Any) -> str:
    """行为 id 已带 `BEH-` 前缀时不重复加。"""
    name = _safe(behavior.id)
    return name if name.upper().startswith("BEH") else f"BEH-{name}"


def _response_text(response: Any) -> str:
    if not isinstance(response, dict) or not response:
        return str(response or "response")
    return ", ".join(f"{key}={value}" for key, value in response.items())


def _tp(model: Any, code: str, behavior: Any, dimension: str, value: str,
        kind: str, used: set, *, checks: List[str], sequence: str = "",
        node_id: str = "") -> TestPoint:
    raw = f"TP-{code}-{_label(behavior)}-{node_id}"
    tp_id = unique_tp_id(raw, used)
    return TestPoint(
        tp_id=tp_id,
        object=str(getattr(model, "object", "")),
        dimension=_label(behavior),
        dimension_name=behavior.name or behavior.id,
        value=value,
        field="",
        checks=list(checks or behavior.checks or []),
        themes=[],
        realization=Realization(kind=kind, sequence=sequence),
        execution=Execution(stage="behavior"),
        notes=[_BEHAVIOR_NOTE],
    )


def compile_behavior(model: Any) -> List[TestPoint]:
    """`CaseModel.behavior` → 行为测试点。没有行为块返回空列表。"""
    behavior = getattr(model, "behavior", None)
    if behavior is None:
        return []
    code = (getattr(model, "object_code", "") or derive_code(model.object)
            or "OBJ")
    used: set = set()
    out: List[TestPoint] = []

    for transition in behavior.transitions:
        out.append(_tp(
            model, code, behavior, transition.id,
            f"{transition.from_state}->{transition.event}->{transition.to_state}",
            KIND_OBSERVE, used, checks=transition.checks,
            node_id=_safe(transition.id)))

    for item in behavior.sequences:
        events = " > ".join(str(step.get("event") or "") for step in item.steps
                            if step.get("event"))
        out.append(_tp(
            model, code, behavior, item.id, events or item.id,
            KIND_SEQUENCE, used, checks=item.expects,
            sequence=item.id, node_id=_safe(item.id)))

    for prop in behavior.temporal:
        out.append(_tp(
            model, code, behavior, prop.id,
            f"{prop.trigger}->{_response_text(prop.response)}",
            KIND_OBSERVE, used, checks=prop.checks,
            node_id=_safe(prop.id)))

    return out
