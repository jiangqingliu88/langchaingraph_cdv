"""AI VPlan 规划层 —— 把 `specs/<module>/` 的 spec-first 项目接进执行内核。

这里只做**源数据加载与投影**：读 `docs/specs/*.csv` 与
`data/contract_matrix/*.csv`，产出现有内核认识的 TestPoint IR / Case IR /
执行契约。它不跑 EDA、不产生证据，也不把 `planned`/`assume` 改成
`covered`/`active`。
"""
from __future__ import annotations

from .assets import clean_legacy_dirs, package_run_assets, scan_assets
from .build import build_case_ir, build_payload, build_testpoints
from .evidence import apply_active, evaluate, link_run, load_index
from .execution import (
    build_execution_model, build_runtime_model,
    write_execution_model, write_runtime_model,
)
from .report import project_summary, run_artifacts
from .review import (
    current_hashes, record_review, require_review, review_status,
)
from .runner import materialize_project_inputs, write_plan_only_run
from .source import VPlanError, VPlanProject, load_project

__all__ = [
    "VPlanError", "VPlanProject", "load_project",
    "build_testpoints", "build_case_ir", "build_payload",
    "build_execution_model", "write_execution_model",
    "build_runtime_model", "write_runtime_model",
    "package_run_assets", "scan_assets", "clean_legacy_dirs",
    "apply_active", "evaluate", "link_run", "load_index",
    "materialize_project_inputs", "write_plan_only_run",
    "project_summary", "run_artifacts",
    "review_status", "record_review", "require_review", "current_hashes",
]
