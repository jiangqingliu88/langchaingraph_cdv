"""工具板块（board）—— **按职责分组，而不是按目录出现顺序**。

七个板块：

    generation  生成产物（UVM / ISA IR / C 模型）
    checking    检查与判定（断言）
    execution   EDA / 回归（当前实现位于 `src/layers/l2_orchestration/regression_tools/`）
    flow        签核 / 血缘 / 趋势等跨阶段流程
    integration 对外集成（IDE 桥）
    humanview   人读视图（PM 手写测试点表 → 测试点本体）
    common      共享底层（lib）

**一个包只属于一个板块**；新增工具必须在这里登记（有测试钉住）。

2026-11-10 收口：
  · `scmodel_tools` / `doc_tools` / `debug_tools` / `coverage_tools` /
    `spec_tools` 已迁到 layers 或删除，不再登记；
  · `case_associate_view` 已并入 `humanview.case_view`；
  · `regression_tools` 已迁到 `src/layers/l2_orchestration/regression_tools/`，
    因此 `execution` 板块当前没有工具包子目录（保留板块名，避免文档/CLI 口径断裂）。
"""
from __future__ import annotations

from typing import Dict, Tuple

BOARDS: Dict[str, Tuple[str, ...]] = {
    "generation": (
        "uvm_tools", "isa_ir_tools", "cmodel_tools",
    ),
    "checking": (
        "assertion_tools",
    ),
    "execution": (),
    "flow": (
        "trend_tools",
    ),
    "integration": (
        "ide_tools",
    ),
    "humanview": (
        "aivm_ir",
        # 身份层（CCAT/CASE/TST）与人类可读视图（含 Case Gate）
        "case_ir", "covg_ir", "sva_ir", "scb_ir",
    ),
    "common": (
        "lib",
    ),
}

BOARD_OF: Dict[str, str] = {
    pkg: board for board, pkgs in BOARDS.items() for pkg in pkgs
}


def board_of(package: str) -> str:
    """包名 → 板块；未登记返回空串（调用方应报错，不猜）。"""
    return BOARD_OF.get(str(package or ""), "")


def packages(board: str = "") -> Tuple[str, ...]:
    if board:
        return BOARDS.get(board, ())
    return tuple(sorted(BOARD_OF))
