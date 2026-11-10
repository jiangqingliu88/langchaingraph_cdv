"""工具板块（board）—— **按职责分组，而不是按目录出现顺序**。

七个板块：

    generation  生成产物（case 模型 / UVM / ISA / C 模型 / 文档）
    checking    检查与判定（断言、debug、覆盖率分析、spec 校验）
    execution   执行 EDA / 回归
    flow        签核 / 血缘 / 趋势等跨阶段流程
    integration 对外集成（IDE 桥）
    humanview   人读视图（PM 手写测试点表 → 测试点本体）
    common      共享底层（lib）

**一个包只属于一个板块**；新增工具必须在这里登记（有测试钉住）。
这不是物理搬迁的替代品 —— 目录仍可逐步迁移，但"谁负责什么"从今天起
有一个显式、可测试的单一答案。
"""
from __future__ import annotations

from typing import Dict, Tuple

BOARDS: Dict[str, Tuple[str, ...]] = {
    "generation": (
        # case 模型引擎已删除；执行资产在 `src.layers.l3_decision.vplan`
        "uvm_tools", "isa_ir_tools",
        "cmodel_tools", "scmodel_tools", "doc_tools",
    ),
    "checking": (
        # verification_os 已迁到 `src.layers.l3_decision.contract`
        "assertion_tools", "debug_tools", "coverage_tools", "spec_tools",
    ),
    "execution": (
        "regression_tools",
    ),
    "flow": (
        "flow_tools", "trend_tools",
    ),
    "integration": (
        "ide_tools",
    ),
    "humanview": (
        "aivm_ir",
        # 身份层（CCAT/CASE/TST）与人类可读视图（含 Case Gate）
        "case_ir", "case_associate_view", "covg_ir", "sva_ir", "scb_ir",
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
