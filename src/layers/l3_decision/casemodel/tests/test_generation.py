"""generation 层 —— 方法策略（Strategy）与属性表组装（Builder）。

重点固定四件事：可复现、联动字段的语义、互斥的剔除、去重与截断的诚实记录。
"""
from __future__ import annotations

import random

import yaml

from src.layers.l3_decision.casemodel.domain import NO_NODE_CODE
from src.layers.l3_decision.casemodel.generation import (CartesianStrategy, DirectedStrategy,
                                                  RandomStrategy, ReplayStrategy,
                                                  TargetedStrategy, build_axes,
                                                  dedupe, drop_forbidden, estimate,
                                                  generate, method_strategy,
                                                  select_methods, select_themes,
                                                  theme_estimates)
from src.layers.l3_decision.casemodel.repository import load_model_from_text



def model_of(text: str):
    return load_model_from_text(text)


BASE = {
    "object": "X",
    "sub_objects": [{"id": "N1", "name": "段", "code": "SEG"}],
    "methods": ["D", "RND", "G", "RPLY", "SPCL"],
    "checks": ["CHECK-FUNC"],
    "dimensions": [
        {"name": "A", "fields": [{"name": "fa", "type": "enum",
                                  "values": [1, 2, 3], "boundary": ["1", "3"]}]},
        {"name": "B", "fields": [{"name": "fb", "type": "enum",
                                  "values": ["x", "y"]}]},
    ],
}


def with_theme(**theme):
    spec = {
        "object": BASE["object"], "sub_objects": BASE["sub_objects"],
        "methods": BASE["methods"], "checks": BASE["checks"],
        "dimensions": BASE["dimensions"],
        "themes": [{"id": "TH", "name": "t", "priority": "P0",
                    "applies_to": ["段"], "dimensions": ["A", "B"], **theme}],
    }
    return model_of(yaml.safe_dump(spec, allow_unicode=True))


# ════════════════════════════════════════════════════════════
# 方法策略
# ════════════════════════════════════════════════════════════

def axes_for(model):
    return build_axes(model, model.dimensions)[0]


def test_strategy_registry_covers_all_five_methods():
    from src.layers.l3_decision.casemodel.generation import METHOD_STRATEGIES
    assert set(METHOD_STRATEGIES) == {"D", "RND", "G", "RPLY", "SPCL"}
    assert method_strategy("G") is METHOD_STRATEGIES["G"]
    # 未知方法退化为定向，不静默产出空集
    assert method_strategy("??").key == "D"


def test_directed_takes_first_value_of_each_field():
    model = with_theme(method="D")
    combos = DirectedStrategy().combine(axes_for(model), random.Random(0), 8)
    assert len(combos) == 1
    assert list(combos[0].values()) == ["1", "x"]


def test_cartesian_is_the_full_product():
    model = with_theme(method="G")
    combos = CartesianStrategy().combine(axes_for(model), random.Random(0), 8)
    assert len(combos) == 6                       # 3 × 2
    assert len({tuple(sorted(c.items())) for c in combos}) == 6


def test_random_produces_repeat_combinations():
    model = with_theme(method="RND", repeat=5)
    combos = RandomStrategy().combine(axes_for(model), random.Random(0), 5)
    assert len(combos) == 5


def test_replay_produces_one_combo():
    model = with_theme(method="RPLY")
    assert len(ReplayStrategy().combine(axes_for(model), random.Random(1), 8)) == 1


def test_targeted_pushes_only_declared_edges():
    """SPCL 只推声明了 boundary 的取值 —— 没声明的字段推不动。"""
    model = with_theme(method="SPCL")
    combos = TargetedStrategy().combine(axes_for(model), random.Random(0), 8)
    # A 有 2 个边界（1, 3）→ 2 个组合；B 没声明边界 → 0 个
    assert len(combos) == 2
    assert {c["A.fa"] for c in combos} == {"1", "3"}


def test_reproducible_random_source():
    """同 seed 两次结果一致 —— 随机源由调用方注入，不是全局 random。"""
    model = with_theme(method="RND", repeat=6)
    axes = axes_for(model)
    a = RandomStrategy().combine(axes, random.Random("s:1"), 6)
    b = RandomStrategy().combine(axes, random.Random("s:1"), 6)
    assert a == b


def test_weighted_field_respects_weights():
    spec = {**BASE, "dimensions": [
        {"name": "A", "fields": [{"name": "fa", "type": "weighted", "values": [
            {"value": "rare", "weight": 1}, {"value": "common", "weight": 99}]}]}],
        "themes": [{"id": "TH", "name": "t", "priority": "P0",
                    "applies_to": ["段"], "dimensions": ["A"], "method": "RND",
                    "repeat": 200}]}
    model = model_of(yaml.safe_dump(spec, allow_unicode=True))
    combos = RandomStrategy().combine(axes_for(model), random.Random(0), 200)
    common = sum(1 for c in combos if c["A.fa"] == "common")
    assert common > 150          # 99:1 的权重应当明显偏向 common


# ════════════════════════════════════════════════════════════
# 估算
# ════════════════════════════════════════════════════════════

def test_estimate_matches_method_semantics():
    model = with_theme()
    axes = axes_for(model)
    assert estimate(axes, "G", 8) == 6
    assert estimate(axes, "RND", 8) == 8
    assert estimate(axes, "D", 8) == 1
    assert estimate(axes, "SPCL", 8) == 2


def test_theme_estimates_multiply_by_target_count(cpu):
    rows = {r["theme"]: r for r in theme_estimates(cpu)}
    # TH-P0-CFG：D 方法 → 每个叶子 1 个 × 5 个叶子 = 5
    assert rows["TH-P0-CFG"]["size"] == 5
    assert rows["TH-P0-CFG"]["targets"] == 5
    # 非结构类专题只有 1 个目标
    assert rows["TH-ERR"]["targets"] == 1


# ════════════════════════════════════════════════════════════
# 约束：互斥剔除
# ════════════════════════════════════════════════════════════

def test_forbidden_pair_drops_the_later_dimension():
    spec = {**BASE,
            "cross_matrix": {"A×B": "forbidden"},
            "themes": [{"id": "TH", "name": "t", "priority": "P0",
                        "applies_to": ["段"], "dimensions": ["A", "B"],
                        "method": "G"}]}
    model = model_of(yaml.safe_dump(spec, allow_unicode=True))
    kept, dropped = drop_forbidden(model, model.dimensions)
    assert [d.key for d in kept] == ["A"]
    assert dropped == [("A", "B")]


def test_forbidden_pair_is_announced_not_silent():
    spec = {**BASE,
            "cross_matrix": {"A×B": "forbidden"},
            "themes": [{"id": "TH", "name": "t", "priority": "P0",
                        "applies_to": ["段"], "dimensions": ["A", "B"],
                        "method": "G"}]}
    gen = generate(model_of(yaml.safe_dump(spec, allow_unicode=True)))
    assert any("禁止交叉" in n for n in gen.notes)
    # B 被剔除 → 只按 A 的 3 个取值生成
    assert gen.count == 3


def test_flawed_example_generates_only_the_themes_it_selected(cpu_flawed):
    """flawed 模型的 generation.themes 只选了 TH-P0-CFG 与 TH-DUP ——
    带禁止交叉的 TH-P2-BND 不在其中，所以这一次生成并不会发生剔除。
    剔除本身由 test_forbidden_pair_is_announced_not_silent 固定。"""
    gen = generate(cpu_flawed)
    assert set(gen.themes_used) == {"TH-P0-CFG", "TH-DUP"}
    assert not any("禁止交叉" in n for n in gen.notes)


# ════════════════════════════════════════════════════════════
# 联动字段
# ════════════════════════════════════════════════════════════

def test_linkage_field_follows_target_and_does_not_multiply():
    spec = {"object": "X", "sub_objects": [{"id": "N", "name": "段", "code": "SEG"}],
            "methods": ["G"], "checks": ["CHECK-FUNC"],
            "dimensions": [{"name": "D", "fields": [
                {"name": "长度", "type": "set", "values": [1, 8, "MAX"]},
                {"name": "元素数", "type": "linkage", "linked_to": "长度"}]}],
            "themes": [{"id": "TH", "name": "t", "priority": "P0",
                        "applies_to": ["段"], "dimensions": ["D"], "method": "G"}]}
    model = model_of(yaml.safe_dump(spec, allow_unicode=True))
    axes, derived = build_axes(model, model.dimensions)
    assert len(axes) == 1                      # 联动字段不是独立的轴
    assert len(derived) == 1
    gen = generate(model)
    assert gen.count == 3                      # 不是 3 × 3
    for case in gen.cases:
        assert case.fields["元素数"] == case.fields["长度"]


# ════════════════════════════════════════════════════════════
# 去重与截断
# ════════════════════════════════════════════════════════════

def test_dedupe_helper():
    combos = [{"a": "1", "b": "2"}, {"a": "1", "b": "2"}, {"a": "1", "b": "3"}]
    kept, dropped = dedupe(combos)
    assert len(kept) == 2 and dropped == 1


def test_random_theme_never_emits_duplicate_field_combinations(cpu):
    """文档十二节：字段取值相同即为重复 —— 与其产出来再报，不如源头不产出。"""
    gen = generate(cpu)
    seen = set()
    for case in gen.cases:
        key = (case.sub_object_id, case.theme, tuple(sorted(case.fields.items())))
        assert key not in seen, f"字段取值重复: {case.case_id}"
        seen.add(key)


def test_dedupe_is_announced_not_silent(cpu):
    gen = generate(cpu)
    assert any("重复的组合" in n for n in gen.notes)


def test_max_cases_truncates_and_reports():
    gen = generate(with_theme(method="G"), max_cases=2)
    assert gen.count == 2 and gen.truncated and gen.dropped == 4
    assert gen.total_before_cap == 6
    assert any("已截断" in n for n in gen.notes)


# ════════════════════════════════════════════════════════════
# 专题驱动的生成
# ════════════════════════════════════════════════════════════

def test_theme_drives_when_declared(cpu, cpu_gen):
    assert cpu_gen.driver == "themes"
    assert cpu_gen.themes_used == ["TH-P0-CFG", "TH-ERR", "TH-P1-FC",
                                   "TH-PERF", "TH-P2-BND", "TH-RND"]
    assert cpu_gen.priorities_used == ["P0", "P1", "P2"]


def test_themes_are_generated_in_priority_order(cpu_gen):
    ranks = [c.priority for c in cpu_gen.cases]
    assert ranks == sorted(ranks, key=lambda p: int(p[1]))


def test_generation_is_reproducible(cpu):
    a, b = generate(cpu), generate(cpu)
    assert a.ids() == b.ids()
    assert [c.fields for c in a.cases] == [c.fields for c in b.cases]


def test_case_ids_are_unique_and_follow_the_convention(cpu_gen):
    ids = cpu_gen.ids()
    assert len(set(ids)) == len(ids)
    for case in cpu_gen.cases:
        assert case.case_id.startswith("TC-CPU-")
        parts = case.case_id.split("-")
        assert len(parts) == 5 and parts[-1].isdigit()


def test_structural_theme_cases_carry_the_tree_path(cpu_gen):
    for case in cpu_gen.cases:
        if case.theme in ("TH-P0-CFG", "TH-P1-FC"):
            assert case.tree_path and case.sub_object_id


def test_orthogonal_theme_cases_are_not_tied_to_a_node(cpu_gen):
    """错误和异常 / 性能常稳不作用树 —— 它们的 case 不该挂任何节点。"""
    orthogonal = [c for c in cpu_gen.cases if c.theme in ("TH-ERR", "TH-PERF")]
    assert orthogonal
    for case in orthogonal:
        assert case.sub_object_id == "" and case.tree_path == ""
        assert case.node_key == NO_NODE_CODE


def test_orthogonal_themes_differ_in_checks_and_method(cpu_gen):
    err = [c for c in cpu_gen.cases if c.theme == "TH-ERR"]
    perf = [c for c in cpu_gen.cases if c.theme == "TH-PERF"]
    assert {c.method for c in err} == {"SPCL"}
    assert {c.method for c in perf} == {"RND"}
    assert all("CHECK-PERF" in c.checks for c in perf)


def test_branch_reference_expands_to_its_leaves(cpu_gen):
    """TH-P0-CFG 写的是分支「指令」→ 产出落在 ARB 与 DISP 两个叶子上。"""
    nodes = {c.sub_object_id for c in cpu_gen.cases if c.theme == "TH-P0-CFG"}
    assert nodes == {"STG-01a", "STG-01b", "STG-02", "STG-03", "STG-04"}


def test_select_themes_respects_priority_filter():
    model = with_theme()
    model.generation.priorities = ["P1"]
    assert select_themes(model) == []
    model.generation.priorities = ["P0"]
    assert [t.id for t in select_themes(model)] == ["TH"]


def test_method_falls_back_to_generation_when_theme_is_silent():
    model = with_theme()          # 专题没声明 method
    assert select_methods(model, model.themes[0]) == model.generation.methods
    model2 = with_theme(method="G")
    assert select_methods(model2, model2.themes[0]) == ["G"]


# ════════════════════════════════════════════════════════════
# 退路：没有专题时按交叉组生成（老模型不迁移也能用）
# ════════════════════════════════════════════════════════════

def test_flat_model_without_themes_falls_back_to_cross_groups(fc):
    gen = generate(fc)
    assert gen.driver == "groups"
    assert gen.groups_used
    assert not gen.themes_used
    assert gen.count > 0


def test_group_path_also_dedupes(fc):
    gen = generate(fc)
    seen = set()
    for case in gen.cases:
        key = (case.sub_object_id, case.cross_group,
               tuple(sorted(case.fields.items())))
        assert key not in seen
        seen.add(key)


def test_no_themes_but_cross_groups_are_kept_in_layer_rows(fc):
    rows = {r["layer"]: r for r in fc.layer_rows()}
    assert rows["TH"]["count"] == 0
