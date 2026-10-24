"""生成方法策略 —— L5 的五个方法各是一个可替换算法。

设计模式：**Strategy**。五种方法（定向/随机/组合/重放/专项）对「怎么从取值点里
挑一组取值」给出完全不同的算法，但调用方只认识一个接口：

    combine(axes, rng, repeat) -> List[Combo]

Combo = {字段限定名: 取值 token}。字段限定名形如 `D_mode.反压模式`，
保证跨维度同名不冲突，同时让属性表的字段顺序稳定、可 diff。
新增方法 = 新增一个子类 + 在 METHOD_STRATEGIES 登记。

文档八节：方法不是 case 类型，而是 case 的生成属性 —— 所以这里只有算法，
不持有任何 case 状态。
"""
from __future__ import annotations

import itertools
import random
from abc import ABC, abstractmethod
from typing import Dict, List, Sequence, Tuple

from ..domain import Dimension, Field, ValuePoint

# 一根轴：某个维度下的某个字段及其全部取值点
Axis = Tuple[Dimension, Field, List[ValuePoint]]
Combo = Dict[str, str]          # 字段限定名 → 取值 token


def _combo_of(picks: Dict[str, ValuePoint]) -> Combo:
    return {name: point.token for name, point in picks.items()}


def pick_weighted(points: Sequence[ValuePoint], rng: random.Random) -> ValuePoint:
    """按权重挑一个取值点；没有权重就是等概率。

    加权型字段的 weight 只影响「挑哪个」的概率，不影响覆盖分母 ——
    加权型同样要求每个取值都被覆盖到，那是 coverage 的事。
    """
    if any(p.weight is not None for p in points):
        weights = [(p.weight if p.weight is not None else 1.0) for p in points]
        return rng.choices(list(points), weights=weights, k=1)[0]
    return rng.choice(list(points))


class MethodStrategy(ABC):
    """生成方法策略。"""

    key: str = ""
    name: str = ""
    #: 该方法产出的组合数是否随取值点数增长（组合爆炸预警要用）
    combinatorial: bool = False

    @abstractmethod
    def combine(self, axes: Sequence[Axis], rng: random.Random,
                repeat: int) -> List[Combo]:
        ...

    def _directed(self, axes: Sequence[Axis], chooser) -> Combo:
        picks: Dict[str, ValuePoint] = {}
        for _dim, fld, points in axes:
            if points:
                picks[fld.qualified] = chooser(points)
        return _combo_of(picks)


class DirectedStrategy(MethodStrategy):
    """D 定向 —— 每个字段取第一个取值点（固定取值）。

    文档八节：`指令长度 = 1 → D`。定向是「把某个点钉死」，
    所以取声明里的第一个取值点，顺序由模型作者掌握。
    """
    key = "D"
    name = "定向"

    def combine(self, axes, rng, repeat) -> List[Combo]:
        return [self._directed(axes, lambda points: points[0])]


class CartesianStrategy(MethodStrategy):
    """G 组合 —— 全笛卡尔积。

    文档八节：`指令长度 × 反压模式 16 组 → G`。
    这是唯一会让组合数爆炸的方法，所以 combinatorial=True，
    规模估算与预警都看这个标记。
    """
    key = "G"
    name = "组合"
    combinatorial = True

    def combine(self, axes, rng, repeat) -> List[Combo]:
        if not axes:
            return []
        names = [fld.qualified for _dim, fld, _points in axes]
        pools = [points for _dim, _fld, points in axes]
        return [{name: point.token for name, point in zip(names, product)}
                for product in itertools.product(*pools)]


class RandomStrategy(MethodStrategy):
    """RND 随机 —— 约束随机采样 repeat 轮。

    文档八节：`指令长度 随机 1~MAX → RND`。
    随机源由调用方注入（不是全局 random），所以同 seed 完全可复现。
    """
    key = "RND"
    name = "随机"

    def combine(self, axes, rng, repeat) -> List[Combo]:
        return [self._directed(axes, lambda points: pick_weighted(points, rng))
                for _ in range(max(1, repeat))]


class ReplayStrategy(MethodStrategy):
    """RPLY 重放 —— 复现失败 seed。

    文档八节：`RPLY 重放 失败 seed`。用注入的 seed 固定采一组取值，
    跑出来的组合与当初失败那条一致，所以只产出 1 个组合。
    """
    key = "RPLY"
    name = "重放"

    def combine(self, axes, rng, repeat) -> List[Combo]:
        return [self._directed(axes, lambda points: pick_weighted(points, rng))]


class TargetedStrategy(MethodStrategy):
    """SPCL 专项 —— 针对性变异：逐个字段推到边界，其余保持定向点。

    文档十三节说「类型决定如何做边界分析」；这里用的就是字段类型策略声明的
    boundary（范围型的端点、枚举型显式标注的边界取值）。
    没有任何字段声明边界时退化为定向，避免产出空集。
    """
    key = "SPCL"
    name = "专项"

    def combine(self, axes, rng, repeat) -> List[Combo]:
        base: Dict[str, ValuePoint] = {}
        for _dim, fld, points in axes:
            if points:
                base[fld.qualified] = points[0]
        out: List[Combo] = []
        for _dim, fld, points in axes:
            for edge in (p for p in points if p.is_edge):
                picks = dict(base)
                picks[fld.qualified] = edge
                out.append(_combo_of(picks))
        return out or [_combo_of(base)]


METHOD_STRATEGIES: Dict[str, MethodStrategy] = {
    s.key: s for s in (DirectedStrategy(), CartesianStrategy(), RandomStrategy(),
                       ReplayStrategy(), TargetedStrategy())
}


def method_strategy(key: str) -> MethodStrategy:
    """查不到就按定向处理 —— 与 schema 层的「未知方法代号直接报错」互补：
    schema 挡住非法输入，这里保证即便被绕过也不会静默产出空集。
    """
    return METHOD_STRATEGIES.get(key) or METHOD_STRATEGIES["D"]


def strategy_name(key: str) -> str:
    return method_strategy(key).name


def estimate(axes: Sequence[Axis], method: str, repeat: int) -> int:
    """按轴与方法的语义估算组合规模 —— 组合爆炸预警用。"""
    if not axes:
        return 0
    strat = method_strategy(method)
    if strat.key == "G":
        size = 1
        for _dim, _fld, points in axes:
            size *= len(points) if points else 1
        return size
    if strat.key == "RND":
        return max(1, repeat)
    if strat.key == "SPCL":
        return sum(sum(1 for p in points if p.is_edge)
                   for _dim, _fld, points in axes) or 1
    return 1                     # D / RPLY
