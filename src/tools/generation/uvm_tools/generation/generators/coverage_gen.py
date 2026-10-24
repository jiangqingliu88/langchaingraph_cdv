"""覆盖率计划生成器 —— `coverage/coverage_plan.yaml` 的独立入口。

从 `VerifyExecutor._write_coverage_plan` 拆出：只负责
"case 模型文本 → 覆盖率计划 YAML → 落盘"，不读 spec、不生成 env。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


def write_coverage_plan(output_dir: Path, case_model: Optional[Path],
                        logger: Any, module_name: str = "dut") -> Optional[dict]:
    """生成并落盘 `coverage/coverage_plan.yaml`；没有 case 模型返回 None。

    调用方负责"找 case 模型"（那是 spec/布局层的职责）；本函数只做生成与落盘。
    """
    if case_model is None:
        return None
    try:
        from src.tools.generation.casemodel_tools.api import run_coverage_plan

        payload = run_coverage_plan(case_model.read_text(encoding="utf-8"), module_name)
    except Exception as e:                       # noqa: BLE001 旁路
        logger.warning(f"生成功能覆盖率计划失败: {e}")
        return None
    if payload.get("error"):
        logger.warning(f"功能覆盖率计划生成不了：{payload['error']}")
        return None

    cov_dir = output_dir / "coverage"
    cov_dir.mkdir(parents=True, exist_ok=True)
    path = cov_dir / "coverage_plan.yaml"
    path.write_text(payload["plan_yaml"], encoding="utf-8")
    logger.info(
        f"功能覆盖率计划：{payload['coverpoint_count']} 覆盖点 / "
        f"{payload['bin_count']} bin / {payload['cross_count']} cross / "
        f"{payload['batch_count']} 批次 / 共 {payload['total_runs']} 次运行 → "
        f"{path.name}")
    for note in payload["plan"].get("notes") or []:
        logger.warning(f"覆盖率计划: {note}")
    return payload
