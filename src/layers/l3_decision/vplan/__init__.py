"""AI VPlan 规划层 —— 把 `specs/<module>/` 的 spec-first 项目接进执行内核。

这里只做**源数据加载与投影**：读 `docs/specs/*.csv` 与
`data/contract_matrix/*.csv`，产出现有内核认识的 TestPoint IR / Case IR /
执行契约。它不跑 EDA、不产生证据，也不把 `planned`/`assume` 改成
`covered`/`active`。
"""
from __future__ import annotations

from .build import build_case_ir, build_payload, build_testpoints
from .runner import write_plan_only_run
from .source import VPlanError, VPlanProject, load_project

__all__ = [
    "VPlanError", "VPlanProject", "load_project",
    "build_testpoints", "build_case_ir", "build_payload",
    "write_plan_only_run",
]
