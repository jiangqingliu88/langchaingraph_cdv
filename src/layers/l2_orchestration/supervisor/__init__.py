"""Supervisor + Sub-agents orchestration.

主图只做路由：`init → supervisor → design_expert/execution_expert → audit_gate
→ finalize`。专家是**独立编译的子图**（同一份 `PipelineState`，但节点只读写
自己需要的字段），执行专家内部保留原来的轮次/调试/覆盖率循环。

兼容性：
  · `build_closed_loop_graph()` 默认返回 supervisor 主图；
  · `SIGNOFFAI_SUPERVISOR=off` 或 `build_legacy_closed_loop_graph()` 回到
    原来的 24 节点单图（测试/回滚用）。
"""
from __future__ import annotations

from .audit import n_hard_audit_gate
from .graph import build_supervisor_graph, n_supervisor, r_supervisor
from .state import SupervisorView
from .subgraphs import build_design_subgraph, build_execution_subgraph

__all__ = [
    "build_supervisor_graph", "n_supervisor", "r_supervisor",
    "SupervisorView", "build_design_subgraph", "build_execution_subgraph",
    "n_hard_audit_gate",
]
