"""Supervisor 的状态视图 —— 主图只拿它需要的字段。

`PipelineState` 是整条流水线的超集（checkpoint 需要完整状态）；Supervisor
不应该读 `coverage`/`gaps`/`debug` 这些专家内部产物。这里用不可变视图把它们
挡在路由层之外：

    PipelineState（可序列化超集）
        └── SupervisorView（只读投影：设计/执行是否完成、终止信号、访问次数）

专家子图仍然吃 `PipelineState`（LangGraph 子图的状态必须兼容父图），但它们只
在节点内部读写自己的字段；**“下一步派谁”只由 SupervisorView 决定**。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SupervisorView:
    design_done: bool = False
    verify_done: bool = False
    debug_done: bool = False
    coverage_done: bool = False
    execution_done: bool = False
    interrupted: bool = False
    eda_blocked: bool = False
    awaiting_approval: bool = False
    terminal_reason: str = ""
    visits: int = 0

    @classmethod
    def from_state(cls, state: Any) -> "SupervisorView":
        return cls(
            design_done=bool(getattr(state, "design_done", False)),
            verify_done=bool(getattr(state, "verify_done", False)),
            debug_done=bool(getattr(state, "debug_done", False)),
            coverage_done=bool(getattr(state, "coverage_done", False)),
            execution_done=bool(getattr(state, "execution_done", False)),
            interrupted=bool(getattr(state, "interrupted", False)),
            eda_blocked=bool(getattr(state, "eda_blocked", False)),
            awaiting_approval=bool(getattr(state, "awaiting_approval", False)),
            terminal_reason=str(getattr(state, "terminal_reason", "") or ""),
            visits=int(getattr(state, "supervisor_visits", 0) or 0),
        )


__all__ = ["SupervisorView"]
