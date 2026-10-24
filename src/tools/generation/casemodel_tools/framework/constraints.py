"""约束编译器 —— **专题 → `apply()` 里真实赋值**的可扩展实现。

## 为什么不是写死在 `associate` 里

约束的"来源"会越来越多：

    stimulus-assign   可驱动维度 → 字段赋值（本轮实现）
    sequence          场景型维度 → 序列约束（待实现）
    relation          互斥/联动关系 → 排除组合（待实现）
    cross-illegal     非法交叉 → 组合排除（待实现）

每加一种就改一次 `build_constraint` 的 if/elif，很快会变成不可维护的分支树。
这里把它们收成注册表：新增编译器只注册一个类，`associate` 只是调用方。

## 输出契约

    [{trans: <agent>, field: <事务字段>, values: [<int>...], mode: cycle|random}]

`mode=cycle` 表示按迭代轮转（保证每个合法取值都打到）；`random` 用于 RND。
模板 `env_cons_policies.sv.j2` 只认这个形状。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .contracts import Registry
from .naming import int_value_of


@dataclass
class ConstraintRequest:
    """一次约束编译的输入 —— 扩展编译器只依赖这个结构。"""
    theme_key: str
    method: str
    dims: List[Any]
    ports: List[Dict[str, str]]
    agent_fields: Optional[Dict[str, List[str]]] = None
    notes: List[str] = field(default_factory=list)


class ConstraintCompiler(ABC):
    """一种约束来源。"""
    name: str = ""

    @abstractmethod
    def compile(self, req: ConstraintRequest) -> List[Dict[str, Any]]:
        ...


CONSTRAINT_COMPILERS: Registry = Registry("constraint compiler")


@CONSTRAINT_COMPILERS.register("stimulus-assign")
class StimulusAssignmentCompiler(ConstraintCompiler):
    """声明了 `stimulus.field` 的维度 → 事务字段赋值。

    只有**可驱动**维度才产生赋值 —— `queue_level` 是 DUT 内部寄存器、
    `issue_unit` 是输出端口，硬给它们编约束就是造假。
    """
    name = "stimulus-assign"

    def compile(self, req: ConstraintRequest) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for dim in req.dims:
            field_name = str(getattr(dim, "stimulus_field", "") or "").strip()
            if not field_name:
                continue

            owner = self._owner(field_name, req)
            if not owner:
                req.notes.append(
                    f"专题 {req.theme_key}: 维度 {dim.key} 的字段 "
                    f"{field_name} 找不到所属 agent —— 这条维度不会产生约束"
                    f"（字段名要与 agent 的事务字段一致）")
                continue

            values = self._values(dim)
            if not values:
                req.notes.append(
                    f"专题 {req.theme_key}: 维度 {dim.key} 没有取值点 —— 无从约束")
                continue

            out.append({
                "trans": owner,
                "field": field_name,
                "values": values,
                # D/G/SPCL/RPLY 用轮转（保证每个合法取值都被打到）；RND 用随机。
                "mode": "random" if req.method == "RND" else "cycle",
            })
        return out

    @staticmethod
    def _owner(field_name: str, req: ConstraintRequest) -> str:
        """字段属于哪个 agent。**不猜**：多端口又给不出归属就返回空。"""
        if req.agent_fields:
            owners = [p["name"] for p in req.ports
                      if field_name in (req.agent_fields.get(p["name"]) or [])]
            if owners:
                if len(owners) > 1:
                    req.notes.append(
                        f"专题 {req.theme_key}: 字段 {field_name} 同时属于 "
                        f"{'、'.join(owners)} —— 取第一个 ({owners[0]})；"
                        f"要分别约束请拆专题/显式声明 agent")
                return owners[0]
            return ""
        # 只有一个端口时无需归属判断；多端口没有 agent_fields 时不敢落。
        return req.ports[0]["name"] if len(req.ports) == 1 else ""

    @staticmethod
    def _values(dim: Any) -> List[int]:
        values: List[int] = []
        for fld in dim.fields:
            for i, point in enumerate(fld.value_points()):
                iv = int_value_of(point.token, i)
                if iv not in values:
                    values.append(iv)
        return values


def compile_assignments(req: ConstraintRequest,
                        compiler: str = "stimulus-assign") -> List[Dict[str, Any]]:
    """跑注册表里的编译器；未知名字直接报错（不静默退回空）。"""
    cls = CONSTRAINT_COMPILERS.require(compiler)
    instance = cls() if isinstance(cls, type) else cls
    return instance.compile(req)
