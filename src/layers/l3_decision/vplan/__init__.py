"""AI VPlan 规划层 —— 把 `specs/<module>/` 的 spec-first 项目接进执行内核。

这里只做**源数据加载与投影**：读 `docs/specs/*.csv` 与
`data/contract_matrix/*.csv`，产出现有内核认识的 TestPoint IR / Case IR /
执行契约。它不跑 EDA、不产生证据，也不把 `planned`/`assume` 改成
`covered`/`active`。
"""
from __future__ import annotations

from .assets import package_run_assets, scan_assets
from .build import build_case_ir, build_payload, build_testpoints
from .execution import build_execution_model, write_execution_model
from .runner import write_plan_only_run
from .source import VPlanError, VPlanProject, load_project

__all__ = [
    "VPlanError", "VPlanProject", "load_project",
    "build_testpoints", "build_case_ir", "build_payload",
    "build_execution_model", "write_execution_model",
    "package_run_assets", "scan_assets",
    "write_plan_only_run",
]
