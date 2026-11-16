"""Formal IR —— 形式化验证计划（`formal_plan_v1`）。

这一层只描述**准备怎么证**：性质、假设、证明义务与引擎需求。
是否真的跑过形式引擎由 `engine.ran` 如实记录；没有引擎就写 `ran=false`，
绝不把"生成了属性"说成"已经证明"。
"""

from .model import (
    FormalPlan,
    FormalProperty,
    FormalSourceAnchor,
    ProofObligation,
)

__all__ = ["FormalPlan", "FormalProperty", "FormalSourceAnchor", "ProofObligation"]
