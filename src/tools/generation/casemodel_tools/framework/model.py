"""框架的数据模型 —— 测试点 IR 的**稳定形状**。

这些 dataclass 是阶段之间、以及框架与下游（`uvm_tools` 文件契约）之间的
唯一交换格式。阶段只负责填充/校验，不改变形状。

    Realization   取值怎么进仿真（stimulus / sequence / observe / 自定义）
    Execution     跑哪个 test、哪一级、哪些种子
    TestPoint     一条测试点 = 身份 + 观测端 + 实现方式 + 执行计划 + 判据
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional

#: realization 的内置取值。**不是封闭枚举** —— 注册表允许扩展
#: （见 `realization.REALIZATIONS`）。
KIND_STIMULUS = "stimulus"
KIND_SEQUENCE = "sequence"
KIND_OBSERVE = "observe"
#: **后门到达**：观测型维度没有输入引脚，但内部状态可以强制写入
#: （`uvm_hdl_force` → 采覆盖 → release）。签核里单列一类，不冒充激励。
KIND_BACKDOOR = "backdoor"
BUILTIN_KINDS = (KIND_STIMULUS, KIND_SEQUENCE, KIND_OBSERVE, KIND_BACKDOOR)


@dataclass
class Realization:
    """一个测试点的**实现方式** —— 取值到底怎么进到仿真里。

    `dimension.fields[].name` 说的是"从哪儿观测"，与"往哪儿驱动"是两件事：
    `instr_type` 恰好两边同名，而 `queue_level` 根本没有输入引脚。
    """
    kind: str = KIND_OBSERVE
    agent: str = ""
    field: str = ""
    value: Optional[int] = None
    sequence: str = ""
    #: `sequence` 型维度的**逐笔事务取值**（如 `[0, 0, 3]`）。
    #: 场景名说明"是什么"，这里说明"每一笔打成什么" —— 只有后者能生成
    #: 可核对的激励差异。
    values: List[int] = _field(default_factory=list)
    #: `backdoor` 型维度的层次路径（`uvm_hdl_force` 用）。
    path: str = ""
    #: 扩展策略可以放任意附加信息（寄存器地址、hold 时长……）。
    #: 内置 kind 不使用它；写进 YAML 时只在该字段非空时输出。
    extras: Dict[str, Any] = _field(default_factory=dict)

    @property
    def drivable(self) -> bool:
        return self.kind not in (KIND_OBSERVE,)

    @property
    def is_stimulus(self) -> bool:
        return self.kind == KIND_STIMULUS

    @property
    def is_backdoor(self) -> bool:
        return self.kind == KIND_BACKDOOR

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"kind": self.kind}
        if self.kind == KIND_STIMULUS:
            out.update(agent=self.agent, field=self.field, value=self.value)
        elif self.kind == KIND_SEQUENCE:
            out.update(agent=self.agent, sequence=self.sequence)
            if self.values:
                out["values"] = list(self.values)
        elif self.kind == KIND_BACKDOOR:
            out.update(path=self.path, value=self.value)
        if self.extras:
            out["extras"] = dict(self.extras)
        return out


@dataclass
class Execution:
    """测试点的执行计划 —— 由框架派生，回归/报告都读它。"""
    test: str = ""
    stage: str = ""
    seeds: List[int] = _field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"test": self.test, "stage": self.stage, "seeds": list(self.seeds)}


@dataclass
class TestPoint:
    """一条测试点 —— 建模、激励、覆盖、回归、签核的公共主键。"""
    tp_id: str
    object: str
    dimension: str
    value: str
    field: str = ""
    dimension_name: str = ""
    tree_path: str = ""
    requirement: str = ""
    cover_id: str = ""
    coverpoint: str = ""
    bin: str = ""
    method: str = ""
    checks: List[str] = _field(default_factory=list)
    themes: List[str] = _field(default_factory=list)
    priority: str = ""
    #: 取值点是不是边界值 —— 截断时优先保留。
    boundary: bool = False
    realization: Realization = _field(default_factory=Realization)
    execution: Execution = _field(default_factory=Execution)
    status_rule: Dict[str, str] = _field(default_factory=dict)
    notes: List[str] = _field(default_factory=list)

    @property
    def observe_only(self) -> bool:
        return not self.realization.drivable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tp_id": self.tp_id,
            "object": self.object,
            "requirement": self.requirement,
            "cover_id": self.cover_id,
            "dimension": self.dimension,
            "dimension_name": self.dimension_name,
            "field": self.field,
            "value": self.value,
            "tree_path": self.tree_path,
            "coverpoint": self.coverpoint,
            "bin": self.bin,
            "method": self.method,
            "checks": list(self.checks),
            "themes": list(self.themes),
            "priority": self.priority,
            "realization": self.realization.to_dict(),
            "execution": self.execution.to_dict(),
            "status_rule": dict(self.status_rule),
            "observe_only": self.observe_only,
            "notes": list(self.notes),
        }
