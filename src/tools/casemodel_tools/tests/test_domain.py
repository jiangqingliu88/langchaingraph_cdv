"""domain 层 —— 功能组织树（Composite）、字段类型（Strategy）、专题、聚合根。"""
from __future__ import annotations

import pytest

from src.tools.casemodel_tools.domain import (FIELD_TYPE_REGISTRY, Theme,
                                              build_org_tree, build_theme,
                                              collect_leaves, derive_code, flatten,
                                              normalize_priority, priority_gaps,
                                              priority_rank, split_cross_key,
                                              token_of, value_of, weight_of)


# ════════════════════════════════════════════════════════════
# 功能组织树（Composite）
# ════════════════════════════════════════════════════════════

def test_org_tree_branch_and_leaf_share_one_interface():
    """分支与叶子对调用方是同一种东西：leaves() 把结构差异吃掉了。"""
    tree = build_org_tree([
        {"id": "N1", "name": "指令", "code": "INST", "children": [
            {"id": "N1a", "name": "结构仲裁", "code": "ARB"},
            {"id": "N1b", "name": "发射解析", "code": "DISP"}]},
        {"id": "N2", "name": "读数据", "code": "RD"},
    ], "CPU")
    root = tree[0]
    assert root.is_branch and not root.is_leaf
    assert [n.code for n in root.leaves()] == ["ARB", "DISP"]
    assert [n.code for n in collect_leaves(tree)] == ["ARB", "DISP", "RD"]
    # 展平是前序：分支在叶子之前
    assert [n.code for n in flatten(tree)] == ["INST", "ARB", "DISP", "RD"]


def test_org_tree_parent_and_path_are_wired():
    tree = build_org_tree([
        {"id": "N1", "name": "指令", "children": [
            {"id": "N1a", "name": "结构仲裁", "children": [
                {"id": "N1a1", "name": "优先仲裁", "code": "PRI"}]}]}])
    leaf = collect_leaves(tree)[0]
    assert leaf.depth == 2
    assert leaf.path() == ["指令", "结构仲裁", "优先仲裁"]
    assert leaf.path_label() == "指令 / 结构仲裁 / 优先仲裁"
    assert leaf.parent.name == "结构仲裁"


def test_flat_list_is_a_degenerate_tree():
    """老模型只写一层 sub_objects —— 每个节点都是叶子，行为与改造前一致。"""
    tree = build_org_tree([{"id": "S1", "name": "recv", "code": "RECV"},
                           {"id": "S2", "name": "send", "code": "SEND"}])
    assert all(n.is_leaf for n in tree)
    assert len(collect_leaves(tree)) == 2


def test_code_derivation_records_its_source():
    """代号来源要能追溯 —— 规则靠它精确报「case_id 会退化」。"""
    tree = build_org_tree([
        {"id": "S1", "name": "指令", "code": "INST"},     # 显式
        {"id": "S2", "name": "ReadData"},                 # 从名字
        {"id": "STG-04", "name": "写数据"},                # 从 id
        {"name": "无名"},                                  # 序号兜底
    ], "CPU")
    assert [n.code_source for n in tree] == ["declared", "name", "id", "fallback"]
    assert [n.code for n in tree] == ["INST", "RD", "STG", "S04"]


def test_code_derivation_helper():
    assert derive_code("FlowControl") == "FC"
    assert derive_code("ReadData") == "RD"
    assert derive_code("Address") == "ADDR"
    assert derive_code("流控") == ""


def test_nodes_with_same_id_stay_distinct_but_codes_can_collide():
    """代号重复不合并节点 —— 正是这一点让 case_id 撞车，需要单独报出来。"""
    tree = build_org_tree([
        {"id": "A", "name": "仲裁", "code": "ARB"},
        {"id": "B", "name": "发射", "code": "ARB"},
    ])
    assert len(tree) == 2 and tree[0].code == tree[1].code


# ════════════════════════════════════════════════════════════
# 字段类型（Strategy）
# ════════════════════════════════════════════════════════════

def test_all_five_field_types_registered():
    assert set(FIELD_TYPE_REGISTRY) == {"enum", "range", "set", "weighted", "linkage"}


def test_value_points_delegate_to_the_type_strategy():
    from src.tools.casemodel_tools.domain import build_field
    enum = build_field({"name": "f", "type": "enum", "values": ["a", "b"]}, "D")
    rng = build_field({"name": "g", "type": "range", "min": 0, "max": 100,
                       "boundary": ["0", "50", "100"]}, "D")
    weighted = build_field({"name": "h", "type": "weighted",
                            "values": [{"value": 1, "weight": 5},
                                       {"value": 8, "weight": 1}]}, "D")
    assert [p.token for p in enum.value_points()] == ["a", "b"]
    assert [p.token for p in rng.value_points()] == ["0", "50", "100"]
    assert [p.weight for p in weighted.value_points()] == [5.0, 1.0]
    # range 的覆盖点全部是边界；SPCL 靠 is_edge 选推哪些
    assert all(p.is_edge for p in rng.value_points())


def test_range_without_boundary_falls_back_to_endpoints():
    from src.tools.casemodel_tools.domain import build_field
    fld = build_field({"name": "g", "type": "range", "min": 1, "max": 64}, "D")
    assert [p.token for p in fld.value_points()] == ["1", "64"]


def test_boundary_marks_which_values_are_edges():
    from src.tools.casemodel_tools.domain import build_field
    fld = build_field({"name": "f", "type": "enum", "values": ["无", "首拍", "非法"],
                       "boundary": ["非法"]}, "D")
    edges = [p.token for p in fld.value_points() if p.is_edge]
    assert edges == ["非法"]


def test_cover_bins_align_by_index_when_lengths_match():
    from src.tools.casemodel_tools.domain import build_field
    fld = build_field({"name": "f", "type": "enum", "values": ["a", "b"],
                       "cover_bins": ["cp_a", "cp_b"]}, "D")
    assert fld.bins_for("a") == ["cp_a"]
    assert fld.bins_for("b") == ["cp_b"]
    # 长度不齐就整体挂上 —— 宁可多报几个仓，也不静默丢掉映射
    ragged = build_field({"name": "g", "type": "enum", "values": ["a", "b"],
                          "cover_bins": ["cp_x"]}, "D")
    assert ragged.bins_for("a") == ["cp_x"]


def test_linked_field_gives_its_values_to_linkage():
    from src.tools.casemodel_tools.domain import build_field
    target = build_field({"name": "长度", "type": "set", "values": [1, 8]}, "D")
    link = build_field({"name": "元素数", "type": "linkage",
                        "linked_to": "长度"}, "D")
    link.values = list(target.cover_tokens())
    assert link.cover_tokens() == ["1", "8"]


# ════════════════════════════════════════════════════════════
# 词表归一
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    ("P0", "P0"), ("p1", "P1"), (2, "P2"), ("2", "P2"), ("P9", "P9"),
])
def test_priority_normalisation(raw, expected):
    assert normalize_priority(raw) == expected


def test_priority_rank_and_gaps():
    assert priority_rank("P0") == 0 and priority_rank("P2") == 2
    themes = [Theme(id="a", name="a", priority="P0"),
              Theme(id="b", name="b", priority="P2")]
    assert priority_gaps(themes) == ["P1"]
    assert priority_gaps([Theme(id="a", name="a", priority="P0")]) == []


@pytest.mark.parametrize("key", ["指令长度×反压模式", "长度*模式", "长度x模式",
                                 "长度,模式", "长度/模式"])
def test_cross_key_separators(key):
    assert split_cross_key(key) is not None


def test_cross_key_without_separator_is_rejected():
    assert split_cross_key("只是长度") is None


def test_value_helpers():
    assert value_of({"value": 8, "weight": 2}) == 8
    assert weight_of({"value": 8, "weight": 2}) == 2.0
    assert weight_of("首拍") is None
    assert token_of(8.0) == "8" and token_of(True) == "true"


# ════════════════════════════════════════════════════════════
# 专题：三类的区别全由两个字段派生
# ════════════════════════════════════════════════════════════

def test_structural_theme_derives_kind_from_applies_to():
    t = build_theme({"id": "T", "name": "t", "priority": "P0",
                     "applies_to": ["指令"], "dimensions": ["指令长度"]}, 1)
    assert t.is_structural and t.kind == "structural"
    assert t.kind_name == "作用于功能组织树"
    assert not t.covers_all_dimensions and t.dim_scope == "restricted"


def test_orthogonal_theme_is_the_one_without_applies_to():
    """错误和异常 / 性能常稳 —— 不作用功能组织树，靠 applies_to 留空表达。"""
    t = build_theme({"id": "T", "name": "错误和异常", "priority": "P1",
                     "dimensions": ["异常类型"]}, 1)
    assert not t.is_structural and t.kind == "orthogonal"
    assert t.target_label == "不作用功能组织树"
    # 不作用树的专题照样生成 case —— 目标是 [None]，不是空列表
    assert t.targets() == [None]


def test_random_theme_is_the_one_without_dimensions():
    """随机专题 = 各维度随机组合 —— 靠 dimensions 留空表达。"""
    t = build_theme({"id": "T", "name": "随机专题", "priority": "P2",
                     "applies_to": ["*"]}, 1)
    assert t.covers_all_dimensions and t.dim_scope == "all"
    assert t.dimension_label == "全部维度"
    assert t.applies_to_all and t.target_label == "全树"


def test_theme_priority_defaults_and_repeat():
    t = build_theme({"id": "T", "name": "t"}, 1)
    assert t.priority == "P0"
    assert build_theme({"id": "T", "name": "t", "repeat": 12}, 1).repeat == 12


def test_themes_sort_by_priority_keeping_declaration_order():
    from src.tools.casemodel_tools.domain import sort_themes
    themes = [Theme(id="c", name="c", priority="P2"),
              Theme(id="a", name="a", priority="P0"),
              Theme(id="b", name="b", priority="P0")]
    assert [t.id for t in sort_themes(themes)] == ["a", "b", "c"]


# ════════════════════════════════════════════════════════════
# 聚合根
# ════════════════════════════════════════════════════════════

def test_model_leaf_nodes_are_the_generation_targets(cpu):
    leaves = cpu.leaf_nodes
    assert [n.code for n in leaves] == ["ARB", "DISP", "RD", "ALU", "WR"]
    codes = cpu.node_codes()
    assert "INST" in codes and len(codes) == 6      # 分支也在树里


def test_resolve_expands_branch_reference_to_leaves(cpu):
    """applies_to 写分支名 → 展开到它的叶子。这是「专题作用于树」的核心语义。"""
    theme = cpu.theme("TH-P0-CFG")
    assert [n.code for n in theme.nodes] == ["ARB", "DISP", "RD", "ALU", "WR"]


def test_resolve_wildcard_means_whole_tree(cpu):
    assert [n.code for n in cpu.theme("TH-RND").nodes] == \
        ["ARB", "DISP", "RD", "ALU", "WR"]


def test_resolve_empty_applies_to_means_no_nodes(cpu):
    theme = cpu.theme("TH-ERR")
    assert theme.nodes == [] and theme.targets() == [None]


def test_resolve_clears_theme_unresolved_on_success(cpu):
    assert not cpu.resolve_report.any
    for theme in cpu.themes:
        assert not theme.unresolved_nodes and not theme.unresolved_dims


def test_flawed_model_records_dangling_theme_refs(cpu_flawed):
    rep = cpu_flawed.resolve_report
    assert rep.theme_nodes == [("TH-BAD-NODE", "不存在的节点")]
    assert rep.theme_dims == [("TH-BAD-DIM", "不存在的维度")]
    assert rep.gen_themes == ["不存在的专题"]


def test_flat_sub_objects_model_still_resolves(fc):
    """只写一层 sub_objects 的老模型照常工作（没有 children）。"""
    assert len(fc.leaf_nodes) == 4
    assert not fc.org_root[0].children


def test_dimension_loose_reference_resolution(fc):
    """文档十四节的矩阵表头用简称（长度 ↔ 指令长度）。"""
    assert fc.dimension("长度") is fc.dimension("指令长度")
