"""生成层 —— 从模型组合出 case 属性表（文档十七节）。

只有本层会「无中生有」：domain 是只读的数据，analysis 是只读的判断，
generation 是唯一会按规则造出新 case 的地方。
"""
from __future__ import annotations

from .builder import (EXPLOSION_THRESHOLD, CaseBuilder, GenerationResult,
                      apply_links, build_axes, dedupe, drop_forbidden, generate,
                      node_code, select_methods, select_themes, theme_estimates)
from .strategies import (METHOD_STRATEGIES, Axis, CartesianStrategy, Combo,
                         DirectedStrategy, MethodStrategy, RandomStrategy,
                         ReplayStrategy, TargetedStrategy, estimate,
                         method_strategy, pick_weighted, strategy_name)

__all__ = [
    "GenerationResult", "CaseBuilder", "generate",
    "build_axes", "apply_links", "drop_forbidden", "dedupe",
    "select_themes", "select_methods", "theme_estimates",
    "node_code", "EXPLOSION_THRESHOLD",
    "Axis", "Combo", "MethodStrategy", "METHOD_STRATEGIES", "method_strategy",
    "strategy_name", "estimate", "pick_weighted",
    "DirectedStrategy", "CartesianStrategy", "RandomStrategy",
    "ReplayStrategy", "TargetedStrategy",
]
