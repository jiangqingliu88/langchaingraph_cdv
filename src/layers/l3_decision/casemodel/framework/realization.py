"""Realization 策略 —— **"取值怎么进仿真"的可扩展实现**。

## 三分法

    stimulus  取值落到 seq_item 的 rand 字段 → 属性 test + 事务约束
    sequence  取值是多条事务的组合/时序      → 场景序列
    observe   DUT 内部/输出/派生量，没有输入引脚 → 只能靠"到达该状态"，
              否则显式标 observe_only（**诚实状态，不是缺陷**）

`D_queue.queue_level` 是内部寄存器、`D_unit.issue_unit` 是输出端口 —— 硬凑
一个"激励"就是造假。`D_seq` 是多条 opcode 的组合，单字段约束表达不了。

## 怎么扩

新增一种实现方式（`backdoor` / `preload` / `formal` …）只需要：

    from .realization import REALIZATIONS
    from .model import Realization

    @REALIZATIONS.register("backdoor")
    class BackdoorRealization:
        kind = "backdoor"
        def resolve(self, req) -> Realization:
            return Realization(kind="backdoor", extras={
                "path": req.dim.backdoor_path, "value": req.value})
        def validate(self, tp, ctx):
            return [] if tp.realization.extras.get("path") else ["缺少后门路径"]

**核心阶段一行都不用改** —— 这就是把它做成框架而不是 if/elif 的意义。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .contracts import Registry
from .model import (BUILTIN_KINDS, KIND_BACKDOOR, KIND_OBSERVE, KIND_SEQUENCE,
                    KIND_STIMULUS, Realization)


@dataclass
class RealizationRequest:
    """一次 realization 解析的输入。扩展策略只依赖这个结构。"""
    dim: Any
    field: Any
    value: int
    #: 取值点的文本 token（`MAC_MAC`）—— 按取值点给序列时靠它查表。
    token: str = ""
    agents: Optional[Dict[str, List[str]]] = None
    notes: List[str] = field(default_factory=list)


class RealizationStrategy(ABC):
    """一种实现方式的解析器。"""
    kind: str = ""

    @abstractmethod
    def resolve(self, req: RealizationRequest) -> Realization:
        ...

    def validate(self, tp, ctx) -> List[str]:      # noqa: ARG002
        """可选的校验（缺字段/缺参数）。返回问题列表，空 = 通过。"""
        return []


REALIZATIONS: Registry = Registry("realization kind")


@REALIZATIONS.register(KIND_OBSERVE)
class ObserveRealization(RealizationStrategy):
    """没有激励通道 —— 只能靠"到达该状态"，报告里按 OBSERVE_ONLY 统计。"""
    kind = KIND_OBSERVE

    def resolve(self, req: RealizationRequest) -> Realization:
        return Realization(kind=KIND_OBSERVE)


@REALIZATIONS.register(KIND_STIMULUS)
class StimulusRealization(RealizationStrategy):
    """取值落到事务字段 —— 属性 test + 事务约束。"""
    kind = KIND_STIMULUS

    def resolve(self, req: RealizationRequest) -> Realization:
        dim = req.dim
        field = str(getattr(dim, "stimulus_field", "") or "").strip()
        if not field:
            req.notes.append(
                f"维度 {dim.key} 声明 realization.kind=stimulus，但没有 "
                f"`stimulus.field` —— 没有事务字段可钉，激励落不下去")
            return Realization(kind=KIND_OBSERVE)

        # 字段属于哪个 agent：有 agent_fields 就查；给不出归属 → 不猜。
        agent = ""
        if req.agents:
            owners = [a for a, fields in req.agents.items() if field in fields]
            if owners:
                agent = owners[0]
                if len(owners) > 1:
                    req.notes.append(
                        f"维度 {dim.key} 的事务字段 {field} 同时出现在 "
                        f"{'、'.join(owners)} —— 取第一个 ({agent})；"
                        f"要在多个 agent 上同时钉住，请显式写 realization.agent")
            else:
                req.notes.append(
                    f"维度 {dim.key} 声明 stimulus.field={field}，但它不在任何 "
                    f"master agent 的事务字段里 —— 这个测试点的激励不会生效")
        return Realization(kind=KIND_STIMULUS, agent=agent, field=field,
                           value=req.value)

    def validate(self, tp, ctx) -> List[str]:
        if not tp.realization.field:
            return [f"{tp.tp_id}: stimulus 型但没有字段"]
        return []


@REALIZATIONS.register(KIND_SEQUENCE)
class SequenceRealization(RealizationStrategy):
    """取值是多条事务的组合/时序 —— 靠场景序列到达。"""
    kind = KIND_SEQUENCE

    def resolve(self, req: RealizationRequest) -> Realization:
        dim = req.dim
        seq = str(getattr(dim, "realization_sequence", "") or "").strip()
        if not seq:
            req.notes.append(
                f"维度 {dim.key} 声明 realization.kind=sequence，但没有给 "
                f"`realization.sequence` —— 场景序列名无从生成（先按观测型处理）")
            return Realization(kind=KIND_OBSERVE)
        by_token = getattr(dim, "realization_sequences", {}) or {}
        values = list(by_token.get(str(req.token), []) or [])
        if not values:
            values = list(getattr(dim, "realization_values", []) or [])
        if not values:
            req.notes.append(
                f"维度 {dim.key} 的 sequence={seq!r} 没有逐笔取值 "
                f"（`realization.values` / `sequences.<取值>`）—— "
                f"生成的测试只会是随机序列，建立不了确定差异")
        return Realization(
            kind=KIND_SEQUENCE,
            agent=str(getattr(dim, "realization_agent", "") or ""),
            sequence=seq, values=values)

    def validate(self, tp, ctx) -> List[str]:
        if not tp.realization.sequence:
            return [f"{tp.tp_id}: sequence 型但没有场景序列名"]
        return []


@REALIZATIONS.register(KIND_BACKDOOR)
class BackdoorRealization(RealizationStrategy):
    """观测型维度的**状态注入**：`uvm_hdl_force(path, value)` → 采覆盖 → release。

    为什么需要它：`queue_level` 没有输入引脚，靠激励"撞"到 full/empty 是低效
    且不保证的。强制写入内部状态能让覆盖仓确定命中；但签核里必须**单列**为
    `backdoor-reached`，不能冒充"激励覆盖"。
    """
    kind = KIND_BACKDOOR

    def resolve(self, req: RealizationRequest) -> Realization:
        dim = req.dim
        path = str(getattr(dim, "realization_path", "") or "").strip()
        if not path:
            req.notes.append(
                f"维度 {dim.key} 声明 realization.kind=backdoor，但没有给 "
                f"`realization.path` —— 不知道 force 哪根信号，先按观测型处理")
            return Realization(kind=KIND_OBSERVE)
        return Realization(kind=KIND_BACKDOOR, path=path, value=req.value)

    def validate(self, tp, ctx) -> List[str]:
        if not tp.realization.path:
            return [f"{tp.tp_id}: backdoor 型但缺少层次路径"]
        return []


def resolve_realization(dim: Any, field: Any, value: int,
                        agents: Optional[Dict[str, List[str]]],
                        notes: List[str], token: str = "") -> Realization:
    """按维度声明选策略；未知/缺失一律回退 observe 并记账。

    选择顺序：
      1. 显式 `realization.kind`；
      2. 声明了 `stimulus.field` → stimulus；
      3. 其余 → observe。
    """
    explicit = str(getattr(dim, "realization_kind", "") or "").strip().lower()
    if explicit:
        kind = explicit
    elif getattr(dim, "stimulus_field", ""):
        kind = KIND_STIMULUS
    else:
        kind = KIND_OBSERVE

    if kind not in REALIZATIONS:
        notes.append(
            f"维度 {dim.key} 的 realization.kind={kind!r} 没有注册策略 —— "
            f"按观测型处理（已注册：{'、'.join(REALIZATIONS.keys())}）")
        kind = KIND_OBSERVE

    strategy = REALIZATIONS.require(kind)
    instance = strategy() if isinstance(strategy, type) else strategy
    return instance.resolve(RealizationRequest(dim=dim, field=field, value=value,
                                               token=token, agents=agents,
                                               notes=notes))


def validate_bundled_kinds() -> List[str]:
    """框架自检：内置 kind 必须都有策略（启动/测试用）。"""
    return [k for k in BUILTIN_KINDS if k not in REALIZATIONS]
