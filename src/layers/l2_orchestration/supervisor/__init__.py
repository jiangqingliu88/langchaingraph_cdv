"""Supervisor + Sub-agents orchestration.

主图只做路由：`init → supervisor → design/verify/debug/coverage_expert
→ human_review → audit_gate → finalize`。四个专家是独立编译的子图（同一份
`PipelineState`，但节点只读写自己需要的字段），debug/coverage 子图内部有循环。

兼容性：
  · `build_closed_loop_graph()` 默认返回 supervisor 主图；
  · `SIGNOFFAI_SUPERVISOR=off` 或 `build_legacy_closed_loop_graph()` 回到
    原来的 24 节点单图（测试/回滚用）。
"""
from __future__ import annotations

from .audit import n_hard_audit_gate
from .graph import build_supervisor_graph, n_supervisor, r_supervisor
from .human import n_human_review
from .state import SupervisorView
from .subgraphs import (
    build_coverage_subgraph, build_debug_subgraph, build_design_subgraph,
    build_verify_subgraph,
)

__all__ = [
    "build_supervisor_graph", "n_supervisor", "r_supervisor",
    "SupervisorView", "build_design_subgraph", "build_verify_subgraph",
    "build_debug_subgraph", "build_coverage_subgraph", "n_hard_audit_gate",
    "n_human_review",
]
