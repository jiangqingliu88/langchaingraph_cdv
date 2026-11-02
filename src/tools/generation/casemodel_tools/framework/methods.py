"""生成方法（Method）策略表 —— P5：把"方法"从枚举变成可执行语义。

方法决定三件事，**必须在一处定义**：

  1. 约束策略名后缀（`directed` / `combo` / `special` / `random` / `replay`）；
  2. 组合器模式（`APPLY_FIRST_MATCH` / `APPLY_ALL` / `APPLY_SEQUENTIAL` /
     `APPLY_WEIGHTED`）；
  3. 逐字段赋值方式（`cycle` 轮转 vs `random` 随机）。

以前这三件事分散在 `associate.METHOD_TO_POLICY`、`METHOD_TO_CONSTRAINT`
（文字描述）和 `constraints.py` 里的 `if method == "RND"` —— 改一个方法要记三处，
漏一处不会报错，只会"策略名对、模式不对、赋值方式退化"。现在统一到这里。

**输出保持逐字节一致**：所有值都是现有产物的原值，本模块只做集中。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class MethodStrategy:
    id: str
    suffix: str              # 策略名后缀
    combinator: str          # 组合器模式（写进 constraint.yaml 的 combinator）
    assignment_mode: str     # 逐字段赋值：cycle | random
    note: str                # 人读的一句话（进 case 模型 → 约束的映射说明）


METHODS: Dict[str, MethodStrategy] = {
    "D": MethodStrategy("D", "directed", "APPLY_FIRST_MATCH", "cycle",
                        "定向策略（一条策略压住具体取值）+ APPLY_FIRST_MATCH"),
    "G": MethodStrategy("G", "combo", "APPLY_ALL", "cycle",
                        "组合策略 + APPLY_ALL（维度之间两两组合）"),
    "SPCL": MethodStrategy("SPCL", "special", "APPLY_SEQUENTIAL", "cycle",
                           "专项策略（推边界）+ APPLY_SEQUENTIAL"),
    "RND": MethodStrategy("RND", "random", "APPLY_WEIGHTED", "random",
                          "加权随机策略 + APPLY_WEIGHTED"),
    "RPLY": MethodStrategy("RPLY", "replay", "APPLY_SEQUENTIAL", "cycle",
                           "回放策略（复用历史激励）"),
}


def registered_ids() -> List[str]:
    return sorted(METHODS)


def strategy(method_id: str) -> Optional[MethodStrategy]:
    return METHODS.get(str(method_id or "").strip().upper())


def assignment_mode(method_id: str) -> str:
    """逐字段赋值方式；认不出的方法（含空串）与 v1 一致，落 `cycle`。"""
    found = strategy(method_id)
    return found.assignment_mode if found else "cycle"


def policy_map() -> Dict[str, tuple]:
    """`method → (策略名后缀, 组合器模式)` —— `associate` 的生成表来源。"""
    return {key: (item.suffix, item.combinator) for key, item in METHODS.items()}


def constraint_form_map() -> Dict[str, str]:
    """`method → 一句话约束形态` —— 人读映射说明的来源。"""
    return {key: item.note for key, item in METHODS.items()}
