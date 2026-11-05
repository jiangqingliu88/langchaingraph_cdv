"""L3 维度，以及维度之间的组合关系（交叉对 / 交叉组）。

维度只归类、不承载取值 —— 取值全在 fields 里（文档六节）。维度之间的关系
表达成两张东西：
  · `relation`   维度内部（或跨维度）的字段两两关系：并列 / 联动 / 互斥
  · `CrossPair`  两个维度之间要不要一起组合：★ 必需 / ✓ 可选 / ✗ 禁止
  · `CrossGroup` 一组必须一起组合的维度（矩阵里每个 ★ 对应一个组）

注意三者都不是「专题」。专题是横切在功能组织树上的验证关注点，
层级在维度之上（见 domain/themes.py）；交叉矩阵只描述维度之间怎么配。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional

from .fields import Field, build_field
from .vocab import (CROSS_LEVEL_MARKS, CROSS_LEVEL_NAMES, METHOD_ALIASES,
                    RELATION_ALIASES, as_list, canon)


@dataclass
class Dimension:
    """L3 维度 —— 一组语义相关字段的集合。"""
    key: str
    id: str = ""
    name: str = ""
    description: str = ""
    #: **覆盖目标**（0–100）：这一维度的闭合目标。0 = 用全局目标。
    goal: int = 0
    sub_objects: List[str] = _field(default_factory=list)   # 限定的组织树节点
    relation: Dict[str, str] = _field(default_factory=dict)  # 另一字段名 → 关系
    fields: List[Field] = _field(default_factory=list)
    #: **激励绑定** —— 本维度的取值由哪个事务字段承载（`stimulus: {field: instr_type}`）。
    #:
    #: 为什么必须有这一格：`fields[].name` 说的是**观测点**（`queue_level` 是 DUT
    #: 内部寄存器、`issue_unit` 是输出端口），它只决定覆盖率从哪儿采样。而"属性
    #: test 要往 DUT 里灌什么"是**另一件事**，两者的名字经常不相等、甚至根本没有
    #: 对应物（队列水位没有输入引脚，只能靠打一串指令把 DUT 推到那个状态）。
    #:
    #: 不写就是**观测型维度**：它照样生成属性 test 与覆盖仓，但该 test 不建立
    #: 激励差异（数值只落在 config_db 通道上）。写空串与不写同义。
    #:
    #: 值必须是一个**事务字段名**（`<agent>_master_seq_item` 上的 rand 成员），
    #: 由 `run_uvm_tests` 原样传给 UVM 生成器；对不上时生成的约束不生效 ——
    #: 所以 `associate` / 生成期校验会拿它对比 agent 的事务字段（见测试）。
    stimulus_field: str = ""
    #: **实现方式的显式声明**（`realization: {kind: stimulus|sequence|observe}`）。
    #:
    #: `stimulus.field` 是它的一个特例（单字段绑定）。显式写 `realization`
    #: 可以表达另外两类：
    #:   · `sequence` —— 取值是多条事务的组合/时序，靠场景序列到达（`sequence:` 给名字）
    #:   · `observe`  —— 明确声明只能观测（DUT 内部/输出/派生量）
    #:
    #: 空串 = 由 `stimulus_field` 推导（有就当 stimulus，没有就当 observe）。
    realization_kind: str = ""
    realization_agent: str = ""
    realization_sequence: str = ""
    #: `backdoor` 型维度的**层次路径**（如
    #: `npu_sched_bench_tb_top.u_npu_sched.queue_level`）。
    #:
    #: 观测型维度没有输入引脚，但内部状态可以**强制写入**（`uvm_hdl_force` →
    #: 采覆盖 → release）。路径是领域知识（DUT 实例名/信号名），模型里显式写，
    #: 不猜。
    realization_path: str = ""
    #: `sequence` 型维度的**事务取值序列**（如 `[0, 0, 3]`）。
    #:
    #: `realization.sequence` 给的是"场景名/语义"，而仿真要的是**逐笔的字段值**。
    #: 两者分开：名字给人看，`values` 给生成的 sequence 逐笔约束。缺省空 =
    #: 这个 sequence 测试点只能生成类骨架，不能建立确定的事务差异。
    realization_values: List[int] = _field(default_factory=list)
    #: **按取值点**给的逐笔序列（`{MAC_MAC: [0, 0], LOAD_MAC: [6, 0]}`）。
    #:
    #: 一个维度里的不同取值点对应不同场景（相邻 opcode 组合），所以序列不能
    #: 只有一份。没有这一格时退回 `realization_values`（整个维度共用一条）。
    realization_sequences: Dict[str, List[int]] = _field(default_factory=dict)
    #: **时序窗口**（`realization.timing`）—— 归一成 `{token: spec}`；
    #: `"*"` 表示整维度共用一份（`timing: {expect_cycles: {...}}`）。
    #: 取值点单独写时按 token 覆盖：`timing: {MAC_MAC: {...}, LOAD_MAC: {...}}`。
    #: 空 dict = 不判时序（**不是**"默认通过"，见 `framework.model.Timing`）。
    realization_timing: Dict[str, Any] = _field(default_factory=dict)

    @property
    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]

    @property
    def label(self) -> str:
        return self.name or self.id or self.key

    @property
    def value_point_count(self) -> int:
        return sum(len(f.cover_tokens()) for f in self.fields)

    def matches(self, ref: str) -> bool:
        r = (ref or "").strip()
        if r in (self.id, self.name, self.key):
            return True
        low = r.lower()
        return low in (self.id.lower(), self.name.lower(), self.key.lower())

    def contains(self, ref: str) -> bool:
        """松匹配：文档的矩阵表头常用简称（长度 ↔ 指令长度）。"""
        r = (ref or "").strip()
        if not r:
            return False
        return any(c and (r in c or c in r) for c in (self.id, self.name, self.key))


@dataclass
class CrossPair:
    """两个维度的交叉关系（矩阵的一个格子）。"""
    a: str
    b: str
    level: str = "optional"
    reason: str = ""
    source: str = "declared"        # declared | group
    #: **显式交叉仓**（可选）：`[{name, when: {维度: 仓名}}]`。
    #:
    #: 不给就是**全交叉**（`cross cp_a, cp_b;`，两边的仓两两相乘）；给了就只出
    #: 列出来的那几个（`bins x = binsof(cp_a.ba) && binsof(cp_b.bb);`）。
    #:
    #: 为什么需要它：全交叉的仓数按乘积涨 —— 4×4 就是 16 个，而关心的往往只有
    #: 四五个。更糟的是**非法组合**：`mac` 指令发到 `dma` 单元这种，全交叉会
    #: 给它一个正常的仓，等于在说"这是个合法状态"。见 `illegal`。
    bins: List[Any] = _field(default_factory=list)
    #: **非法交叉仓** —— 命中即报错。形状同 `bins`。
    illegal: List[Any] = _field(default_factory=list)
    #: **交叉编号 / 需求编号** —— 追溯矩阵的另一头（与 `Field.cover_id` 对称）。
    #: 生成器派生的名字是 `cx_<a>_<b>`（给 SV），文档里引用的是
    #: `X_NPU_TYPE_UNIT_001`。两者都要有，不能拿一个当另一个。
    cover_id: str = ""
    requirement: str = ""
    dim_a: Optional[Dimension] = _field(default=None, repr=False, compare=False)
    dim_b: Optional[Dimension] = _field(default=None, repr=False, compare=False)

    @property
    def resolved(self) -> bool:
        return self.dim_a is not None and self.dim_b is not None

    @property
    def level_name(self) -> str:
        return CROSS_LEVEL_NAMES.get(self.level, self.level)

    @property
    def mark(self) -> str:
        return CROSS_LEVEL_MARKS.get(self.level, "?")


@dataclass
class CrossGroup:
    """交叉组 —— 一组必须一起组合的维度。"""
    id: str
    name: str = ""
    dimensions: List[str] = _field(default_factory=list)    # 原始引用
    level: str = "required"
    method: str = ""
    sub_objects: List[str] = _field(default_factory=list)
    checks: List[str] = _field(default_factory=list)
    expected_result: str = ""
    description: str = ""
    dims: List[Dimension] = _field(default_factory=list)    # resolve 后
    unresolved: List[str] = _field(default_factory=list)
    source: str = "declared"        # declared | derived

    @property
    def key(self) -> str:
        return self.id or self.name

    @property
    def label(self) -> str:
        return self.name or self.id or "×".join(self.dimensions)

    def dimension_keys(self) -> List[str]:
        return [d.key for d in self.dims] or list(self.dimensions)


# ════════════════════════════════════════════════════════════
# 构建
# ════════════════════════════════════════════════════════════

def _goal_of(item: Dict[str, Any]) -> int:
    """`goal` → 0–100；非法/缺省 = 0（用全局目标）。"""
    try:
        return max(0, min(100, int(item.get("goal") or 0)))
    except (TypeError, ValueError):
        return 0


def build_dimension(item: Any) -> Optional[Dimension]:
    if not isinstance(item, dict):
        return None
    dim_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    key = dim_id or name
    if not key:
        return None
    goal = _goal_of(item)

    relation: Dict[str, str] = {}
    for ref, kind in (item.get("relation") or {}).items():
        level = canon(str(kind), RELATION_ALIASES)
        if level:
            relation[str(ref)] = level

    stimulus = item.get("stimulus")
    stimulus_field = ""
    if isinstance(stimulus, dict):
        stimulus_field = str(stimulus.get("field") or "").strip()

    realization = item.get("realization")
    realization_kind = realization_agent = realization_sequence = ""
    realization_path = ""
    realization_values: List[int] = []
    realization_sequences: Dict[str, List[int]] = {}
    realization_timing: Dict[str, Any] = {}
    if isinstance(realization, dict):
        realization_kind = str(realization.get("kind") or "").strip().lower()
        realization_agent = str(realization.get("agent") or "").strip()
        realization_sequence = str(realization.get("sequence") or "").strip()
        realization_path = str(realization.get("path") or "").strip()
        for v in as_list(realization.get("values")):
            try:
                realization_values.append(int(v))
            except (TypeError, ValueError):
                continue
        for token, seq in (realization.get("sequences") or {}).items():
            vals = []
            for v in as_list(seq):
                try:
                    vals.append(int(v))
                except (TypeError, ValueError):
                    continue
            if vals:
                realization_sequences[str(token)] = vals
        realization_timing = _normalize_timing(realization.get("timing"))

    return Dimension(
        key=key, id=dim_id, name=name,
        description=str(item.get("description") or ""), goal=goal,
        sub_objects=[str(s) for s in as_list(item.get("sub_objects"))],
        relation=relation,
        fields=[build_field(f, key) for f in as_list(item.get("fields"))],
        stimulus_field=stimulus_field,
        realization_kind=realization_kind,
        realization_agent=realization_agent,
        realization_sequence=realization_sequence,
        realization_path=realization_path,
        realization_values=realization_values,
        realization_sequences=realization_sequences,
        realization_timing=realization_timing,
    )


#: 一份 timing 规格会出现的键。出现任一就是"整维度共用"，否则按 token 分。
_TIMING_KEYS = {"expect_cycles", "min", "max", "min_cycles", "max_cycles",
                "start", "end", "sample", "tolerance", "clock", "reset"}


def _normalize_timing(raw: Any) -> Dict[str, Any]:
    """`realization.timing` → `{token|"*": spec}`（两种写法都认）。

        timing: {expect_cycles: {min: 2, max: 12}, start: a, end: b}   # 共用
        timing: {MAC_MAC: {...}, default: {...}, LOAD_MAC: {...}}      # 按取值
    """
    if not isinstance(raw, dict) or not raw:
        return {}
    if _TIMING_KEYS & set(raw):
        return {"*": dict(raw)}
    return {str(token): dict(spec) for token, spec in raw.items()
            if isinstance(spec, dict)}


def build_cross_pair(key: str, level_raw: Any) -> Optional[CrossPair]:
    """`cross_matrix` 的一个格子 → `CrossPair`。

    值有两种写法：

      · **字符串** —— 只声明级别：`指令长度×反压模式: required`
      · **对象** —— 连仓一起声明：
        ```yaml
        指令类型×执行单元:
          level: required
          bins:
            - {name: mac_to_mac, when: {指令类型: mac, 执行单元: mac}}
          illegal:
            - {name: mac_to_dma, when: {指令类型: mac, 执行单元: dma}}
        ```
    对象形式是"只交叉有意义的那几对 + 把非法的那几对钉成 illegal"的写法 ——
    全交叉在 4×4 上就是 16 个仓，而真正关心的往往四五个，**非法组合更是会被
    当成正常状态统计**（见 `CrossPair.bins` 的注释）。
    """
    from .vocab import CROSS_LEVEL_ALIASES, split_cross_key
    split = split_cross_key(str(key))
    if not split:
        return None

    if isinstance(level_raw, dict):
        level = canon(str(level_raw.get("level") or ""), CROSS_LEVEL_ALIASES) or "optional"
        return CrossPair(a=split[0], b=split[1], level=level, source="declared",
                         bins=_as_dicts(level_raw.get("bins")),
                         illegal=_as_dicts(level_raw.get("illegal")),
                         cover_id=str(level_raw.get("cover_id") or "").strip(),
                         requirement=str(level_raw.get("requirement") or "").strip())

    level = canon(str(level_raw), CROSS_LEVEL_ALIASES) or "optional"
    return CrossPair(a=split[0], b=split[1], level=level, source="declared")


def _as_dicts(raw: Any) -> list:
    """过滤出 mapping 条目 —— 列表里混进字符串/数字不该让整个交叉解不出来。"""
    return [x for x in (raw if isinstance(raw, list) else ([] if raw is None else [raw]))
            if isinstance(x, dict)]


def build_cross_group(item: Any, index: int) -> Optional[CrossGroup]:
    from .vocab import CHECK_ALIASES, CROSS_LEVEL_ALIASES
    if not isinstance(item, dict):
        return None
    return CrossGroup(
        id=str(item.get("id") or f"XG-{index:02d}"),
        name=str(item.get("name") or ""),
        dimensions=[str(d) for d in as_list(item.get("dimensions"))],
        level=canon(str(item.get("level")), CROSS_LEVEL_ALIASES) or "required",
        method=canon(str(item.get("method") or ""), METHOD_ALIASES) or "",
        sub_objects=[str(s) for s in as_list(item.get("sub_objects"))],
        checks=[c for c in (canon(str(x), CHECK_ALIASES)
                            for x in as_list(item.get("checks"))) if c],
        expected_result=str(item.get("expected_result") or ""),
        description=str(item.get("description") or ""),
    )
