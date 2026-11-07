"""verify 生成期的 VPlan `sv/` 布局钩子（与主流程解耦，保持 main 行数预算）。"""
from __future__ import annotations

import os
from pathlib import Path

import structlog

logger = structlog.get_logger()


def package_vplan_assets(output_dir: Path, module_name: str) -> None:
    """把本次生成的 UVM 资产同时落 `<run>/sv/...`。

    顶层 agents/env/bench 仍是内核工作路径；sv/ 是同一批文件的 VPlan 视图。
    只在 `SIGNOFFAI_UVM_LAYOUT=vplan` 时启用；失败不拦主流程。
    """
    if os.environ.get("SIGNOFFAI_UVM_LAYOUT", "").strip().lower() != "vplan":
        return
    try:
        from src.layers.l3_decision.vplan import package_run_assets

        summary = package_run_assets(output_dir, module_name)
        logger.info(
            f"UVM 资产 VPlan sv/：{summary['assets']} 个"
            f"（复制 {summary['copied']} / 跳过 {summary['skipped']}）")
    except Exception as e:                           # noqa: BLE001 旁路，别拦主流程
        logger.warning(f"UVM 资产 sv/ 布局失败: {e}")
