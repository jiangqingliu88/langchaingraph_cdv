"""运行事实面 —— 一次 run 的身份、产物索引与事件日志。

这一层刻意**只用标准库**：它不 import `src.layers`、langgraph、pydantic 或
structlog。理由不是洁癖，而是为了让它可以被任意一层安全依赖 —— 分层守卫
（`src/layers/_bootstrap.py`）只扫 `src/layers`，但架构上 core 必须比 L1 更底：
L1 也能用 RunContext / ArtifactStore，而不会把编排层拖进来。
"""
from src.core.runtime.run_context import (
    RunContext, RunPaths, active_context, bind, open_run_context, reset,
)
from src.core.runtime.artifacts import ArtifactRef, ArtifactStore
from src.core.runtime.events import EventStore, Spool, emit, flush_spool, set_active_store

__all__ = [
    "RunContext", "RunPaths", "active_context", "bind", "open_run_context", "reset",
    "ArtifactRef", "ArtifactStore",
    "EventStore", "Spool", "emit", "flush_spool", "set_active_store",
]
