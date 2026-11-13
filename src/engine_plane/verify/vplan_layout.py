"""verify 生成期的 VPlan `sv/` 布局钩子（与主流程解耦，保持 main 行数预算）。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import structlog

logger = structlog.get_logger()


def package_vplan_assets(output_dir: Path, module_name: str,
                         source_root: Path | None = None) -> None:
    """把本次生成的 UVM 资产整理进 `<run>/sv/...`（**verify 默认行为**）。

    `source_root` 是渲染的暂存目录（VPlan 布局下 verify 不再先写顶层
    `agents/env/bench`）。成功后清理暂存目录；失败保留它，便于排查。
    `SIGNOFFAI_UVM_LAYOUT=legacy` 可显式关闭 sv/ 布局；失败不拦主流程。
    """
    if os.environ.get("SIGNOFFAI_UVM_LAYOUT", "vplan").strip().lower() == "legacy":
        logger.warning(
            "SIGNOFFAI_UVM_LAYOUT=legacy 已弃用：新 run 请使用 sv/ 布局；"
            "legacy 仅用于旧 run 复现")
        return
    try:
        from src.ir_plane.vplan import (
            clean_legacy_dirs, package_run_assets)

        summary = package_run_assets(output_dir, module_name, move=True,
                                     source_root=source_root)
        try:
            cleaned = clean_legacy_dirs(output_dir, apply=True)
        except ValueError:
            cleaned = {"deleted": []}
        logger.info(
            f"UVM 资产 VPlan sv/：{summary['assets']} 个"
            f"（搬入 {summary['copied']} / 跳过 {summary['skipped']}；"
            f"删除顶层 {', '.join(cleaned.get('deleted') or []) or '无'}）")
        if source_root is not None:
            shutil.rmtree(source_root, ignore_errors=True)
    except Exception as e:                           # noqa: BLE001 旁路，别拦主流程
        logger.warning(f"UVM 资产 sv/ 布局失败: {e}")
