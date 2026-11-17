"""配置域 —— DUT / 特性配置空间（方法学 v2 P3）。

配置改变的是**功能空间本身**（队列深度 8 还是 32、GEMM 开不开），不是运行环境
（工具版本、seed）。它应该参与验证空间：同一功能点在不同配置下是两个执行实例。

第一版（P3a）只做建模、校验与**组合可行性计算**；把配置实例乘进 TP（每个
组合一套 tp_id）是 P3b —— 那会改变 TP 数量，单独一批做、单独验收。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ConfigDimension:
    name: str
    values: List[Any] = field(default_factory=list)


@dataclass
class ConfigSpace:
    dimensions: List[ConfigDimension] = field(default_factory=list)
    #: 配置维度的交叉组（哪些维度必须一起组合覆盖）。
    cross_groups: List[Dict[str, Any]] = field(default_factory=list)
    #: 可行性规则：when 命中时，该组合明确排除（exclude=true）或只禁用某些 TP。
    feasibility: List[Dict[str, Any]] = field(default_factory=list)
    #: 组合数上限 —— 超过就截断并**记账**（默认 64）。
    max_combinations: int = 64

    def dimension(self, name: str):
        return next((d for d in self.dimensions
                     if d.name == str(name or "")), None)
