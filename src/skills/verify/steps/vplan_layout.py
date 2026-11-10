"""verify 生成期的 VPlan `sv/` 布局钩子（与主流程解耦，保持 main 行数预算）。"""
from __future__ import annotations

import os
from pathlib import Path

import structlog

logger = structlog.get_logger()


def package_vplan_assets(output_dir: Path, module_name: str) -> None:
    """把本次生成的 UVM 资产同时落 `<run>/sv/...`（**verify 默认行为**）。

    生成完就**搬进 sv/** 并删掉顶层 agents/env/bench/build：run 里只留一份
    UVM 资产。`SIGNOFFAI_UVM_LAYOUT=legacy` 可显式关闭；失败不拦主流程。
    """
    if os.environ.get("SIGNOFFAI_UVM_LAYOUT", "vplan").strip().lower() == "legacy":
        logger.warning(
            "SIGNOFFAI_UVM_LAYOUT=legacy 已弃用：新 run 请使用 sv/ 布局；"
            "legacy 仅用于旧 run 复现")
        return
    try:
        from src.layers.l3_decision.vplan import (
            clean_legacy_dirs, package_run_assets)

        summary = package_run_assets(output_dir, module_name, move=True)
        try:
            cleaned = clean_legacy_dirs(output_dir, apply=True)
        except ValueError:
            cleaned = {"deleted": []}
        logger.info(
            f"UVM 资产 VPlan sv/：{summary['assets']} 个"
            f"（搬入 {summary['copied']} / 跳过 {summary['skipped']}；"
            f"删除顶层 {', '.join(cleaned.get('deleted') or []) or '无'}）")
    except Exception as e:                           # noqa: BLE001 旁路，别拦主流程
        logger.warning(f"UVM 资产 sv/ 布局失败: {e}")
