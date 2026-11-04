"""case 属性表的组装。

设计模式：**Builder**。文档十七节的六步流水线是固定的，只是每一步的选择来自
不同的配置源，所以把「选什么」与「怎么拼」分开：

    1. 选对象 + 子对象    ← 专题的 applies_to（展开到叶子）
    2. 选维度集合         ← 专题的 dimensions（留空 = 全部维度）
    3. 取各字段取值       ← domains.fields 的类型策略给取值点
    4. 选生成方法         ← 专题的 method，缺省继承 generation.methods
    5. 计算组合           ← generation.strategies 的方法策略
    6. 输出 case 属性表   ← 本模块

产物是文档十六节的「case 属性表最小字段集」——那张表才是 case 的真正主体，
case_id 只是人读的坐标。

专题缺省时退化为按交叉组生成（老模型不用改），所以两条路都保留。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain import (NO_NODE_CODE, CaseAttribute, CaseModel, CrossGroup,
                      Dimension, Field, OrgNode, Theme, sort_themes)
from .strategies import Axis, Combo, estimate, method_strategy


@dataclass
class GenerationResult:
    cases: List[CaseAttribute] = _field(default_factory=list)
    themes_used: List[str] = _field(default_factory=list)
    priorities_used: List[str] = _field(default_factory=list)
    groups_used: List[str] = _field(default_factory=list)
    methods_used: List[str] = _field(default_factory=list)
    total_before_cap: int = 0
    truncated: bool = False
    dropped: int = 0
    notes: List[str] = _field(default_factory=list)
    seed: int = 0
    driver: str = ""            # themes | groups

    @property
    def count(self) -> int:
        return len(self.cases)

    def ids(self) -> List[str]:
        return [c.case_id for c in self.cases]

    def by_theme(self) -> Dict[str, List[CaseAttribute]]:
        out: Dict[str, List[CaseAttribute]] = {}
        for c in self.cases:
            out.setdefault(c.theme, []).append(c)
        return out

    def by_node(self) -> Dict[str, List[CaseAttribute]]:
        out: Dict[str, List[CaseAttribute]] = {}
        for c in self.cases:
            out.setdefault(c.node_key, []).append(c)
        return out

    def to_rows(self) -> List[List[str]]:
        return [[c.case_id, c.sub_object_id, c.method, c.theme, c.priority,
                 "、".join(c.dimensions),
                 "；".join(f"{k}={v}" for k, v in c.fields.items()),
                 "、".join(c.checks)] for c in self.cases]


# ════════════════════════════════════════════════════════════
# 轴与约束
# ════════════════════════════════════════════════════════════

def build_axes(model: CaseModel, dims: Sequence[Dimension]
               ) -> Tuple[List[Axis], List[Tuple[Field, Field]]]:
    """专题选定的维度 → (独立轴, 联动派生)。

    联动型字段若其 linked_to 目标也在同一组里，它就不是一根独立的轴 ——
    取值必须等于目标（总元素数 = 指令长度），不能参与笛卡尔积，
    否则会生成「指令长度=MAX 而总元素数=8」这种自相矛盾的 case。
    """
    axes: List[Axis] = []
    derived: List[Tuple[Field, Field]] = []
    axis_names = {fld.qualified for dim in dims for fld in dim.fields}
    for dim in dims:
        for fld in dim.fields:
            target = (model.field(fld.linked_to)
                      if (fld.is_linkage and fld.linked_to) else None)
            if target is not None and target.qualified in axis_names:
                derived.append((fld, target))
            else:
                axes.append((dim, fld, fld.value_points()))
    return axes, derived


def apply_links(combo: Combo, derived: Sequence[Tuple[Field, Field]]) -> Combo:
    if not derived:
        return combo
    out = dict(combo)
    for fld, target in derived:
        token = out.get(target.qualified, "")
        if token:
            out[fld.qualified] = token
    return out


def drop_forbidden(model: CaseModel, dims: Sequence[Dimension]
                   ) -> Tuple[List[Dimension], List[Tuple[str, str]]]:
    """把与其它维度构成「禁止交叉」的维度剔出去。

    「禁止交叉」是维度之间的硬约束（如 比例×持续时间 不能同时变），
    它优先于专题的 dimensions 列表 —— 专题列了两个互斥的维度，是模型自相矛盾，
    由 analysis 报出来，生成侧则保留先声明的那个、丢掉后一个，并记进 notes。
    """
    forbidden = {frozenset((p.dim_a.key, p.dim_b.key))
                 for p in model.cross_pairs
                 if p.level == "forbidden" and p.resolved}
    if not forbidden:
        return list(dims), []
    kept: List[Dimension] = []
    dropped: List[Tuple[str, str]] = []
    for dim in dims:
        conflict = next((d for d in kept if frozenset((d.key, dim.key)) in forbidden),
                        None)
        if conflict is not None:
            dropped.append((conflict.key, dim.key))
        else:
            kept.append(dim)
    return kept, dropped


# ════════════════════════════════════════════════════════════
# 选专题 / 选方法
# ════════════════════════════════════════════════════════════

def select_themes(model: CaseModel) -> List[Theme]:
    """按 generation 的选择器挑专题，再按优先级排序。"""
    gen = model.generation
    themes = list(model.themes)
    if gen.priorities:
        themes = [t for t in themes if t.priority in gen.priorities]
    if gen.themes:
        picked: List[Theme] = []
        for ref in gen.themes:
            theme = model.theme(ref)
            if theme is not None and theme not in picked:
                picked.append(theme)
        themes = picked
    return sort_themes(themes)


def select_methods(model: CaseModel, theme: Theme) -> List[str]:
    """专题声明了 method 就用它，否则继承 generation.methods。"""
    if theme.method:
        return [theme.method]
    return list(model.generation.methods) or list(model.methods) or ["G"]


def _select_groups(model: CaseModel) -> List[CrossGroup]:
    """没有专题时的退路：按交叉组生成。"""
    gen = model.generation
    if gen.groups:
        picked = [g for g in (model.cross_group(r) for r in gen.groups) if g is not None]
        if picked:
            return picked
    return list(model.cross_groups)


def dedupe(combos: Sequence[Combo]) -> Tuple[List[Combo], int]:
    """去掉字段取值完全相同的组合，返回 (保留的组合, 丢弃数)。

    为什么在生成侧就去重：文档十二节说「对象+子对象+字段取值相同就是重复」，
    而 RND 在小取值空间里必然会撞（3 个取值抽 16 轮），SPCL 也会 ——
    某个字段的第一个取值恰好是边界时，「把它推到边界」与基准组合完全一致。
    与其生成一堆字段一样的 case 再靠核对去报重复，不如源头就不产出。

    G 天然无重复，D/RPLY 只产一个，所以这个去重实际只对 RND/SPCL 起作用；
    对四者都无害，就统一放在这里。
    """
    seen: set = set()
    out: List[Combo] = []
    for combo in combos:
        key = tuple(sorted(combo.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(combo)
    return out, len(combos) - len(out)


# ════════════════════════════════════════════════════════════
# Builder
# ════════════════════════════════════════════════════════════

class CaseBuilder:
    """把模型拼成 case 属性表。"""

    def __init__(self, model: CaseModel, *, seed: Optional[int] = None,
                 max_cases: Optional[int] = None) -> None:
        self.model = model
        self.seed = model.generation.seed if seed is None else seed
        self.cap = model.generation.max_cases if max_cases is None else max_cases
        self.counters: Dict[Tuple[str, str], int] = {}
        self._noted: set = set()
        self.result = GenerationResult(seed=self.seed)

    # ── 对外 ──

    def build(self) -> GenerationResult:
        model = self.model
        themes = select_themes(model)
        if themes:
            self.result.driver = "themes"
            for theme in themes:
                self._emit_theme(theme)
        else:
            groups = _select_groups(model)
            if not groups:
                self.result.notes.append("模型没有可用专题或交叉组，未生成任何 case")
                return self.result
            self.result.driver = "groups"
            for group in groups:
                self._emit_group(group)

        self._finish()
        return self.result

    # ── 专题路径 ──

    def _emit_theme(self, theme: Theme) -> None:
        model = self.model
        dims, dropped = drop_forbidden(model, theme.dims)
        for a_key, b_key in dropped:
            self.result.notes.append(
                f"专题 {theme.key} 同时选了互斥的两个维度 "
                f"{a_key}×{b_key}，已保留 {a_key}、剔除 {b_key}（cross_matrix 标为禁止交叉）")
        if not dims:
            self.result.notes.append(f"专题 {theme.key} 没有任何可用维度，已跳过")
            return

        axes, derived = build_axes(model, dims)
        dim_names = [d.name for d in dims]
        repeat = theme.repeat or model.generation.repeat
        env = self._environment()
        checks = list(theme.checks or model.case_defaults.checks or model.checks)
        expected = theme.expected_result or model.case_defaults.expected_result

        for node in theme.targets():
            for method in select_methods(model, theme):
                # 每个 (专题, 节点, 方法) 一个独立随机源：
                # 增删其它专题/节点不会改变本组的取值序列，可复现
                rng = random.Random(f"{self.seed}:{theme.key}:{node_code(node)}:{method}")
                combos = method_strategy(method).combine(axes, rng, repeat)
                combos, dupes = dedupe(combos)
                self._note_dedupe(theme.key, method, dupes, repeat)
                for combo in combos:
                    combo = apply_links(combo, derived)
                    self._append(theme, node, method, combo, dim_names,
                                 checks, env, expected)

        self.result.themes_used.append(theme.key)
        if theme.priority not in self.result.priorities_used:
            self.result.priorities_used.append(theme.priority)

    # ── 交叉组路径（退路） ──

    def _emit_group(self, group: CrossGroup) -> None:
        model = self.model
        dims = list(group.dims)
        if not dims:
            self.result.notes.append(f"交叉组 {group.key} 没有有效维度，已跳过")
            return

        nodes = [model.node(r) for r in group.sub_objects]
        leaves: List[OrgNode] = []
        for n in nodes:
            if n is not None:
                leaves.extend(x for x in n.leaves() if x not in leaves)
        if not leaves:
            leaves = [None]                       # type: ignore[list-item]

        axes, derived = build_axes(model, dims)
        dim_names = [d.name for d in dims]
        env = self._environment()
        checks = list(group.checks or model.case_defaults.checks or model.checks)
        expected = group.expected_result or model.case_defaults.expected_result
        methods = [group.method] if group.method else (
            list(model.generation.methods) or list(model.methods) or ["G"])

        for node in leaves:
            for method in methods:
                rng = random.Random(f"{self.seed}:{group.key}:{node_code(node)}:{method}")
                combos = method_strategy(method).combine(
                    axes, rng, model.generation.repeat)
                combos, dupes = dedupe(combos)
                self._note_dedupe(group.key, method, dupes,
                                  model.generation.repeat)
                for combo in combos:
                    combo = apply_links(combo, derived)
                    self._append(None, node, method, combo, dim_names,
                                 checks, env, expected, group=group)

        self.result.groups_used.append(group.key)

    # ── 收尾 ──

    def _append(self, theme: Optional[Theme], node: Optional[OrgNode],
                method: str, combo: Combo, dim_names: List[str],
                checks: List[str], env: Dict[str, Any], expected: str,
                group: Optional[CrossGroup] = None) -> None:
        model = self.model
        code = node.code if node is not None else NO_NODE_CODE
        key = (code, method)
        self.counters[key] = self.counters.get(key, 0) + 1
        prefix = model.case_defaults.id_prefix or "TC"
        case_id = f"{prefix}-{model.object_code}-{code}-{method}-{self.counters[key]:02d}"

        fields: Dict[str, str] = {}
        bins: List[str] = []
        for fld in _ordered_fields(model, theme, group, dim_names):
            token = combo.get(fld.qualified, "")
            if not token:
                continue
            fields[fld.name] = token
            bins.extend(fld.bins_for(token))

        self.result.cases.append(CaseAttribute(
            case_id=case_id,
            object=model.object,
            sub_object=node.name if node is not None else "（不作用功能组织树）",
            sub_object_id=node.id if node is not None else "",
            theme=theme.id if theme is not None else "",
            priority=theme.priority if theme is not None else "",
            tree_path=node.path_label() if node is not None else "",
            dimensions=list(dim_names),
            fields=fields,
            method=method,
            cross_group=group.key if group is not None else "",
            checks=checks,
            cover_bins=bins,
            environment=env,
            expected_result=expected,
            seed=self.seed,
        ))

    def _note_dedupe(self, owner: str, method: str, dupes: int,
                     repeat: int) -> None:
        """采样撞车导致的去重记一条 —— 不静默少产 case，也不逐节点刷屏。"""
        if not dupes:
            return
        reason = (f"取值空间不足 {repeat} 种" if method == "RND"
                  else "某些字段的第一个取值本身就是边界")
        key = f"dedupe:{owner}:{method}"
        if key in self._noted:
            return
        self._noted.add(key)
        self.result.notes.append(
            f"{owner} 的 {method} 方法丢弃了 {dupes} 个字段取值重复的组合"
            f"（{reason}）—— 文档十二节：字段取值相同即为重复，不再产出")

    def _environment(self) -> Dict[str, Any]:
        env = dict(self.model.case_defaults.environment)
        if "seed" in self.model.env_required and "seed" not in env:
            env["seed"] = self.seed
        return env

    def _finish(self) -> None:
        used: List[str] = []
        for c in self.result.cases:
            if c.method not in used:
                used.append(c.method)
        self.result.methods_used = used

        self.result.total_before_cap = len(self.result.cases)
        if self.cap is not None and len(self.result.cases) > self.cap:
            self.result.dropped = len(self.result.cases) - self.cap
            self.result.cases = self.result.cases[:self.cap]
            self.result.truncated = True
            self.result.notes.append(
                f"组合规模 {self.result.total_before_cap} 超过 max_cases="
                f"{self.cap}，已截断并丢弃 {self.result.dropped} 个组合（未静默丢弃）")


def _ordered_fields(model: CaseModel, theme: Optional[Theme],
                    group: Optional[CrossGroup], dim_names: List[str]) -> List[Field]:
    """属性表的字段顺序：按维度声明顺序，稳定可 diff。"""
    out: List[Field] = []
    for dim in model.dimensions:
        if dim.name in dim_names:
            out.extend(dim.fields)
    if out:
        return out
    return model.all_fields


def node_code(node: Optional[OrgNode]) -> str:
    """节点的 case_id 代号 —— 只用于编号与随机源标识，不用于索引。"""
    return node.code if node is not None else NO_NODE_CODE


# ════════════════════════════════════════════════════════════
# 规模估算
# ════════════════════════════════════════════════════════════

EXPLOSION_THRESHOLD = 5000


def theme_estimates(model: CaseModel) -> List[Dict[str, Any]]:
    """逐个专题估算规模 —— 给「这轮会跑出多少个 case」一个数字。

    非结构类专题只产一轮（不乘节点数），结构类要乘目标叶子数。
    """
    rows: List[Dict[str, Any]] = []
    for theme in sort_themes(model.themes):
        dims, dropped = drop_forbidden(model, theme.dims)
        axes, _derived = build_axes(model, dims)
        repeat = theme.repeat or model.generation.repeat
        methods = select_methods(model, theme)
        per_target = sum(estimate(axes, m, repeat) for m in methods)
        targets = len(theme.targets())
        size = per_target * targets
        rows.append({
            "theme": theme.key,
            "name": theme.label,
            "priority": theme.priority,
            "kind_name": theme.kind_name,
            "dimensions": [d.name for d in dims],
            "dimensions_dropped": [f"{a}×{b}" for a, b in dropped],
            "method": "、".join(methods),
            "targets": targets,
            "size": size,
            "explosive": size > EXPLOSION_THRESHOLD,
        })
    return rows


def generate(model: CaseModel, *, seed: Optional[int] = None,
             max_cases: Optional[int] = None) -> GenerationResult:
    """按模型与生成参数产出 case 属性表。"""
    return CaseBuilder(model, seed=seed, max_cases=max_cases).build()
