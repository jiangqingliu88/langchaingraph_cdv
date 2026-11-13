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
class Timing:
    """测试点的**时序窗口**（P2）—— "这件事该在几拍内发生"的机器判据。

    写在 case 模型的维度 `realization.timing` 里（见 `domain/dimensions.py`）：

        realization:
          kind: sequence
          timing:
            expect_cycles: {min: 2, max: 12}
            start: load_submit          # SV 信号名（DUT 侧）
            end: issue_valid            # 不给就退回 sample
            sample: issue_valid
            tolerance: 0

    **没有 timing 的 TP 不判时序**：不编一个假期望，也不把"没声明"当"通过"。
    `start`/`end` 都必须是 DUT 信号名（env 检查组通过覆盖率接口读），任一缺失
    就 `checkable=False` —— 生成期在 `notes` 里说清，而不是生成一个永远不报的
    空检查。
    """
    min_cycles: int = 0
    max_cycles: int = 0
    start: str = ""
    end: str = ""
    sample: str = ""
    tolerance: int = 0
    clock: str = ""
    reset: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["Timing"]:
        if not isinstance(raw, dict) or not raw:
            return None
        spec = raw.get("expect_cycles")
        if not isinstance(spec, dict):
            spec = raw
        try:
            lo = int(spec.get("min", spec.get("min_cycles", 0)) or 0)
            hi = int(spec.get("max", spec.get("max_cycles", 0)) or 0)
        except (TypeError, ValueError):
            return None
        if hi < lo:
            lo, hi = hi, lo
        return cls(
            min_cycles=lo, max_cycles=hi,
            start=str(raw.get("start") or "").strip(),
            end=str(raw.get("end") or raw.get("sample") or "").strip(),
            sample=str(raw.get("sample") or "").strip(),
            tolerance=int(raw.get("tolerance") or 0),
            clock=str(raw.get("clock") or "").strip(),
            reset=str(raw.get("reset") or "").strip(),
        )

    @property
    def checkable(self) -> bool:
        """有起点、有终点、窗口合法才可判 —— 缺一项就是"判不了"。"""
        return bool(self.start and self.end) and self.max_cycles >= self.min_cycles

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"expect_cycles": {"min": self.min_cycles,
                                                 "max": self.max_cycles}}
        for key in ("start", "end", "sample", "clock", "reset"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if self.tolerance:
            out["tolerance"] = self.tolerance
        return out


@dataclass
class TestPoint:
    """一条测试点 —— 建模、激励、覆盖、回归、签核的公共主键。"""
    tp_id: str
    object: str
    dimension: str
    value: str
    field: str = ""
    dimension_name: str = ""
    #: 覆盖描述（模型里维度的 `description`）：这一组测的**功能点**是什么。
    #: 签核视图据此回答"这条用例证明的是哪块逻辑"，而不是只给 CG 编号。
    dimension_description: str = ""
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
    #: 时序窗口（可选）。没有就是**不判时序**，不是"默认通过"。
    timing: Optional[Timing] = None
    status_rule: Dict[str, str] = _field(default_factory=dict)
    notes: List[str] = _field(default_factory=list)
    #: **逻辑用例身份**（Case IR）的**主身份**（`case_ids` 首项）。
    #: 空串 = 模型没声明 cases 且合成也没绑上 —— 序列化时不写这个键，
    #: 让"没有身份"和"身份为空串"在 IR 里可区分。
    case_id: str = ""
    #: **全部逻辑用例身份**（去重保序）。一条 TP（维度 × 取值）可以被多条
    #: 业务 CASE 共享（CASE A 只绑 D_type，CASE B 绑 D_type + D_dep），
    #: 单值 `case_id` 会让第二条 CASE 永远没有证据；这里保留全量。
    case_ids: List[str] = _field(default_factory=list)
    #: 可执行实例**模板**身份（`TST-<test>`）；带种子的实例身份在 task_meta 里。
    tst_id: str = ""
    #: **四集合契约引用**（见 `docs/design/architecture_transformation_plan.md`
    #: 与 `arch.md`）：这条 TP 属于哪些功能组、受哪些断言/检查/约束保护。
    #: 由 `plan` 在生成期从 dimension 与 assertion bindings 聚合，不手写。
    groups: List[str] = _field(default_factory=list)
    sva: List[str] = _field(default_factory=list)
    scb: List[str] = _field(default_factory=list)
    #: **约束 id**（`p_*` 策略名）—— 这条 TP 的激励受哪些约束塑造。
    constraints: List[str] = _field(default_factory=list)

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
            **({"dimension_description": self.dimension_description}
               if self.dimension_description else {}),
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
            # 没有时序就不写这个键 —— 序列化是 manifest 哈希的一部分，
            # 空 dict 会让"没声明"和"声明了空窗口"看起来一样。
            **({"timing": self.timing.to_dict()} if self.timing else {}),
            # 身份同理：没有就不写，别让空串混进哈希。
            # `case_id` 是主身份，`case_ids` 是全量（单值时不重复写）。
            **({"case_id": self.case_id} if self.case_id else {}),
            **({"case_ids": list(self.case_ids)}
               if len(self.case_ids) > 1 else {}),
            **({"tst_id": self.tst_id} if self.tst_id else {}),
            # 四集合引用：空就不写（"没声明"与"声明了空集合"要能分开）
            **({"groups": list(self.groups)} if self.groups else {}),
            **({"sva": list(self.sva)} if self.sva else {}),
            **({"scb": list(self.scb)} if self.scb else {}),
            **({"constraints": list(self.constraints)} if self.constraints else {}),
            "status_rule": dict(self.status_rule),
            "observe_only": self.observe_only,
            "notes": list(self.notes),
        }
