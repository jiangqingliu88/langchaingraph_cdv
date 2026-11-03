"""verify 产出的 IR 文件清单 + 契约构建（从 `main.py` 抽出，控制单文件规模）。

这里只放"落盘之后的记账"：哪些文件算这一步的产物、契约怎么编译。
判定与生成逻辑不在这里 —— `main.py` 仍是唯一入口。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()

#: 这一步可能产出的附属文件（相对运行目录）。没生成的不列。
_EXTRA_FILES = (
    ("coverage", ("case_ir.json", "case_group_map.json",
                  "case_checker_map.json", "stimulus_plan.json")),
    ("contract", ("contract.yaml", "obligations.json",
                  "contract_manifest.json")),
)


def testpoint_files(output_dir: Path) -> List[str]:
    """TP IR 这一步产出的全部文件（含 Case IR / 契约 / StimulusPlan）。"""
    files = [str(output_dir / "coverage" / "testpoints.yaml"),
             str(output_dir / "coverage" / "testpoints.json"),
             str(output_dir / "coverage" / "methodology.json")]
    for sub, names in _EXTRA_FILES:
        for name in names:
            if (output_dir / sub / name).is_file():
                files.append(str(output_dir / sub / name))
    return files


def write_contract_build(output_dir: Path, case_ir: Dict[str, Any]) -> None:
    """M1：把 case_ir 编译成**构建物**（contract/contract.yaml + 义务 + 清单）。

    失败只告警：契约缺失会在 ops 的前置门禁上响亮失败 —— 不在这里把 verify
    整轮拖死（"生成失败"和"没契约"是两件事，各自都要看得见）。
    """
    if not case_ir or not case_ir.get("cases"):
        return
    try:
        from src.tools.checking.verification_os import write_contract

        manifest = write_contract(output_dir, case_ir)
        logger.info(f"契约：{manifest['contract_id']} · "
                    f"{manifest['obligations']} 条义务 · "
                    f"hash {manifest['contract_hash'][:12]}… → contract/")
    except Exception as e:                       # noqa: BLE001 旁路
        logger.warning(f"契约编译失败（ops 会被门禁拦下）: {e}")
