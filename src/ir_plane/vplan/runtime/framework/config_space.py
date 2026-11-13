"""配置域编译 —— `config_space:` → 组合清单与可行性（方法学 v2 P3a）。

第一版只做**组合枚举 + 可行性过滤**，把结果放进 TP IR payload 的
`config_space` 段；把配置乘进 TP（每个组合一套 tp_id）是 P3b。

两条纪律：

  · 组合数有上限，**截断要记账**（`truncated` / `total`），不静默少跑；
  · 可行性规则命中的组合是"不该跑"，不是"没覆盖" —— 单列 `excluded` 并带规则 id。
"""
from __future__ import annotations

from fnmatch import fnmatch
from itertools import islice, product
from typing import Any, Dict, List


def _product_size(space: Any) -> int:
    total = 1
    for dimension in space.dimensions:
        total *= max(1, len(dimension.values))
    return total


def _combinations(space: Any) -> List[Dict[str, Any]]:
    names = [d.name for d in space.dimensions]
    pools = [list(d.values) or [None] for d in space.dimensions]
    limit = max(1, int(space.max_combinations))
    return [dict(zip(names, combo))
            for combo in islice(product(*pools), limit)]


def _matches(condition: Dict[str, Any], combo: Dict[str, Any]) -> bool:
    return all(combo.get(str(key)) == value for key, value in condition.items())


def _exclude_rule(space: Any, combo: Dict[str, Any]) -> str:
    for rule in space.feasibility:
        condition = rule.get("when")
        then = rule.get("then") or {}
        if not isinstance(condition, dict) or not isinstance(then, dict):
            continue
        if then.get("exclude") and _matches(condition, combo):
            return str(rule.get("id") or "rule")
    return ""


def feasible_combinations(space: Any) -> List[Dict[str, Any]]:
    """可执行组合：全枚举（受上限约束）后去掉 `exclude` 规则命中的。"""
    return [combo for combo in _combinations(space)
            if not _exclude_rule(space, combo)]


def _disabled_for(space: Any, combo: Dict[str, Any], tp_id: str) -> bool:
    """这个组合下，该 TP 是否被 `disable_tps` 规则禁用（支持 `*` 通配）。"""
    for rule in space.feasibility:
        condition = rule.get("when")
        then = rule.get("then") or {}
        if not isinstance(condition, dict) or not isinstance(then, dict):
            continue
        if not _matches(condition, combo):
            continue
        patterns = then.get("disable_tps") or []
        if any(fnmatch(str(tp_id), str(p)) for p in patterns):
            return True
    return False


def attach_instances(model: Any, testpoints: List[Dict[str, Any]]) -> int:
    """给每条 TP 挂 `config_instances`（组合不分叉 tp_id）。返回实例总数。

    `disable_tps` 规则只在**命中的组合**下禁用匹配的 TP —— 同一 TP 在别的
    配置下仍然要跑，这正是"配置改变功能空间"的意思。
    """
    space = getattr(model, "config_space", None)
    if space is None:
        return 0
    combos = feasible_combinations(space)
    total = 0
    for tp in testpoints:
        tp_id = str(tp.get("tp_id") or "")
        instances = [combo for combo in combos
                     if not _disabled_for(space, combo, tp_id)]
        if instances:
            tp["config_instances"] = instances
        total += len(instances)
    return total


def combination_summary(model: Any) -> Dict[str, Any]:
    """模型 → 配置组合摘要；没有配置域返回空 dict（payload 形状与 v1 一致）。"""
    space = getattr(model, "config_space", None)
    if space is None:
        return {}
    combos = _combinations(space)
    kept = feasible_combinations(space)
    excluded = [{"config": combo, "rule": _exclude_rule(space, combo)}
                for combo in combos if _exclude_rule(space, combo)]
    total = _product_size(space)
    return {
        "dimensions": [{"name": d.name, "values": list(d.values)}
                       for d in space.dimensions],
        "total": total,
        "enumerated": len(combos),
        "feasible": len(kept),
        "truncated": total > len(combos),
        "max_combinations": space.max_combinations,
        "combinations": kept[:20],
        "excluded": excluded[:20],
    }
