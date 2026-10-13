"""analysis 规则集 —— 每条规则都要有「触发」与「不误报」两面。

只测触发会让规则越写越激进（什么都报）；只测不触发会让规则形同虚设。
所以每条关键规则都配一组正反用例。
"""
from __future__ import annotations

import pytest
import yaml

from src.tools.casemodel_tools.analysis import analyze, rule_ids
from src.tools.casemodel_tools.analysis.issues import (CATEGORY_CROSS,
                                                       CATEGORY_ORTHOGONAL,
                                                       CATEGORY_REFERENCE,
                                                       CATEGORY_THEME)
from src.tools.casemodel_tools.analysis.multi import analyze_many
from src.tools.casemodel_tools.repository import (load_model_from_text,
                                                  load_models_from_text)

from .conftest import CPU, FC, FC_FLAWED, issues_of, rules_of


def build(spec: dict):
    return analyze_many(load_models_from_text(yaml.safe_dump(spec, allow_unicode=True)))


def rules_in(spec: dict, category: str = "") -> set:
    return rules_of(build(spec), category)


# 一份最小可用模型：后续用例都在它上面做局部改动
MINIMAL = {
    "object": "X",
    "object_code": "XX",
    "sub_objects": [{"id": "N1", "name": "段", "code": "SEG"}],
    "methods": ["D", "G", "SPCL"],
    "checks": ["CHECK-FUNC"],
    "environment": {"required": ["seed"], "defaults": {"seed": 1}},
    "case_defaults": {"checks": ["CHECK-FUNC"]},
    "dimensions": [{"name": "A", "fields": [
        {"name": "fa", "type": "enum", "values": [1, 2]}]}],
    "themes": [{"id": "TH", "name": "t", "priority": "P0",
                "applies_to": ["段"], "dimensions": ["A"], "method": "G"}],
}


def minimal(**over):
    return {**MINIMAL, **over}


# ════════════════════════════════════════════════════════════
# 规则集本身
# ════════════════════════════════════════════════════════════

def test_all_rules_have_identity_and_description():
    """每条规则都要自描述 —— 报告、GUI、文档三处都从注册表读。"""
    from src.tools.casemodel_tools.analysis import load_rules
    rules = load_rules()
    assert len(rules) >= 45
    for rule in rules:
        assert rule.id and rule.description
        assert rule.severity in ("error", "warning", "info")
        assert rule.category
    assert len({r.id for r in rules}) == len(rules)      # id 唯一


def test_rule_registry_has_no_duplicate_ids():
    ids = rule_ids()
    assert len(ids) == len(set(ids))


def test_rules_are_pure_reads():
    """同一份模型跑两次分析，结果必须逐条一致 —— 规则不能有副作用。"""
    a, b = build(minimal()), build(minimal())
    assert [str(i) for i in a.issues] == [str(i) for i in b.issues]


# ════════════════════════════════════════════════════════════
# 引用完整性
# ════════════════════════════════════════════════════════════

def test_clean_examples_have_no_reference_errors():
    for path in (CPU, FC):
        result = analyze_many(load_models_from_text(path.read_text(encoding="utf-8")))
        assert not [i for i in result.issues if i.category == CATEGORY_REFERENCE
                    and i.is_error]


def test_unknown_tree_node_in_theme_is_error(cpu_flawed_result):
    hits = issues_of(cpu_flawed_result, "unknown_tree_node_ref")
    assert hits and any("不存在的节点" in i.message for i in hits)


def test_unknown_theme_in_generation_is_error(cpu_flawed_result):
    assert issues_of(cpu_flawed_result, "unknown_theme_ref")


def test_unknown_dimension_in_cross_matrix_is_error():
    spec = minimal(cross_matrix={"A×不存在": "required"})
    assert "unknown_dimension_ref" in rules_in(spec, CATEGORY_REFERENCE)


def test_unknown_field_in_relation_table_is_warning():
    spec = minimal(dimensions=[{"name": "A", "relation": {"不存在": "联动"},
                                "fields": [{"name": "fa", "type": "enum",
                                            "values": [1]}]}])
    hits = issues_of(build(spec), "unknown_field_ref")
    assert hits and hits[0].severity == "warning"


def test_unknown_linkage_target_is_error():
    spec = minimal(dimensions=[{"name": "A", "fields": [
        {"name": "fa", "type": "linkage", "linked_to": "无此字段"}]}],
        themes=[{"id": "TH", "name": "t", "priority": "P0",
                 "applies_to": ["段"], "dimensions": ["A"], "method": "G"}])
    assert "unknown_linkage_ref" in rules_in(spec, CATEGORY_REFERENCE)


def test_derived_code_is_info_not_error():
    spec = minimal(sub_objects=[{"id": "STG-04", "name": "写数据"}])
    hits = issues_of(build(spec), "derived_code")
    assert hits and all(i.severity == "info" for i in hits)
    assert "code" in hits[0].message


def test_declared_codes_produce_no_derived_code_issue():
    assert not issues_of(build(minimal()), "derived_code")


# ════════════════════════════════════════════════════════════
# 功能组织树
# ════════════════════════════════════════════════════════════

def test_duplicate_leaf_code_is_error(cpu_flawed_result):
    hits = issues_of(cpu_flawed_result, "org_leaf_code_duplicate")
    assert hits and hits[0].severity == "error"
    assert "ARB" in hits[0].target


def test_unique_leaf_codes_pass(cpu_result):
    assert not issues_of(cpu_result, "org_leaf_code_duplicate")


def test_leaf_without_any_theme_is_warned(cpu_flawed_result):
    hits = {i.target for i in issues_of(cpu_flawed_result, "org_leaf_uncovered")}
    assert hits                                # 旁路校验 / 写数据 都没被专题打到


def test_dead_branch_is_warned(cpu_flawed_result):
    hits = issues_of(cpu_flawed_result, "org_branch_unreachable")
    assert hits and "旁路" in hits[0].message


def test_fully_covered_tree_is_silent(cpu_result):
    assert not issues_of(cpu_result, "org_leaf_uncovered")
    assert not issues_of(cpu_result, "org_branch_unreachable")


def test_flat_tree_is_info_only():
    """扁平组织树只是提示 —— 一层就够的模型不该被扣分。"""
    hits = issues_of(build(minimal(sub_objects=[
        {"id": "A", "name": "a", "code": "AA"},
        {"id": "B", "name": "b", "code": "BB"}])), "org_tree_flat")
    assert hits and all(i.severity == "info" for i in hits)


# ════════════════════════════════════════════════════════════
# 专题
# ════════════════════════════════════════════════════════════

def test_priority_gap_is_warned():
    spec = minimal(themes=[
        {"id": "A", "name": "a", "priority": "P0", "applies_to": ["段"],
         "dimensions": ["A"], "method": "G"},
        {"id": "B", "name": "b", "priority": "P2", "applies_to": ["段"],
         "dimensions": ["A"], "method": "SPCL"}])
    hits = issues_of(build(spec), "theme_priority_gap")
    assert hits and "P1" in hits[0].message


def test_contiguous_priorities_pass(cpu_result):
    assert not issues_of(cpu_result, "theme_priority_gap")


def test_theme_overlap_is_warned():
    """两个专题的目标 + 维度 + 方法完全相同 → 会产出字段一样的 case。"""
    spec = minimal(themes=[
        {"id": "A", "name": "a", "priority": "P0", "applies_to": ["段"],
         "dimensions": ["A"], "method": "G"},
        {"id": "B", "name": "b", "priority": "P0", "applies_to": ["段"],
         "dimensions": ["A"], "method": "G"}])
    hits = issues_of(build(spec), "theme_overlap")
    assert hits and "重复" in hits[0].message


def test_theme_overlap_not_triggered_by_different_method():
    spec = minimal(themes=[
        {"id": "A", "name": "a", "priority": "P0", "applies_to": ["段"],
         "dimensions": ["A"], "method": "G"},
        {"id": "B", "name": "b", "priority": "P1", "applies_to": ["段"],
         "dimensions": ["A"], "method": "SPCL"}])
    assert not issues_of(build(spec), "theme_overlap")


def test_duplicate_theme_id_is_error():
    spec = minimal(themes=[
        {"id": "A", "name": "a", "priority": "P0", "applies_to": ["段"],
         "dimensions": ["A"], "method": "G"},
        {"id": "A", "name": "a2", "priority": "P1", "applies_to": ["段"],
         "dimensions": ["A"], "method": "SPCL"}])
    assert "theme_duplicate_id" in rules_in(spec, CATEGORY_THEME)


def test_dimension_not_selected_by_any_theme_is_warned():
    spec = minimal(dimensions=[
        {"name": "A", "fields": [{"name": "fa", "type": "enum", "values": [1]}]},
        {"name": "B", "fields": [{"name": "fb", "type": "enum", "values": [1]}]}])
    hits = issues_of(build(spec), "theme_dimension_unused")
    assert any("B" in i.target for i in hits)


def test_spcl_without_boundary_is_warned():
    spec = minimal(themes=[{"id": "TH", "name": "t", "priority": "P0",
                            "applies_to": ["段"], "dimensions": ["A"],
                            "method": "SPCL"}])
    hits = issues_of(build(spec), "theme_spcl_without_boundary")
    assert hits and "boundary" in hits[0].message


def test_spcl_with_boundary_passes():
    spec = minimal(dimensions=[{"name": "A", "fields": [
        {"name": "fa", "type": "enum", "values": [1, 2], "boundary": ["1"]}]}],
        themes=[{"id": "TH", "name": "t", "priority": "P0",
                 "applies_to": ["段"], "dimensions": ["A"], "method": "SPCL"}])
    assert not issues_of(build(spec), "theme_spcl_without_boundary")


def test_theme_forbidden_pair_is_error():
    spec = minimal(cross_matrix={"A×B": "forbidden"},
                   dimensions=[
                       {"name": "A", "fields": [{"name": "fa", "type": "enum",
                                                 "values": [1]}]},
                       {"name": "B", "fields": [{"name": "fb", "type": "enum",
                                                 "values": [1]}]}],
                   themes=[{"id": "TH", "name": "t", "priority": "P0",
                            "applies_to": ["段"], "dimensions": ["A", "B"],
                            "method": "G"}])
    hits = issues_of(build(spec), "theme_forbidden_pair")
    assert hits and hits[0].severity == "error"


def test_empty_theme_is_error(cpu_flawed_result):
    hits = issues_of(cpu_flawed_result, "theme_no_dimension")
    assert hits and "TH-BAD-DIM" in hits[0].target


def test_theme_never_generated_is_info():
    spec = minimal(generation={"themes": ["TH"], "priorities": []},
                   themes=[
                       {"id": "TH", "name": "t", "priority": "P0",
                        "applies_to": ["段"], "dimensions": ["A"], "method": "G"},
                       {"id": "OTHER", "name": "o", "priority": "P1",
                        "applies_to": ["段"], "dimensions": ["A"], "method": "SPCL"}])
    hits = issues_of(build(spec), "theme_never_generated")
    assert hits and all(i.severity == "info" for i in hits)


def test_missing_themes_is_warned():
    spec = {k: v for k, v in MINIMAL.items() if k != "themes"}
    hits = issues_of(build(spec), "themes_not_declared")
    assert hits and hits[0].severity == "warning"


def test_flat_model_reports_but_does_not_error_on_themes(fc_result):
    """老模型没有专题 → 报 warning，但不是 error。"""
    hits = issues_of(fc_result, "themes_not_declared")
    assert hits and all(i.severity == "warning" for i in hits)


# ════════════════════════════════════════════════════════════
# 层级正交性 —— 四类错位，各配正反用例
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", (CPU, FC), ids=lambda p: p.name)
def test_clean_examples_have_no_orthogonality_issues(path):
    result = analyze_many(load_models_from_text(path.read_text(encoding="utf-8")))
    assert not rules_of(result, CATEGORY_ORTHOGONAL)


def test_method_as_object():
    assert "method_as_object" in rules_in(minimal(object="随机反压"),
                                          CATEGORY_ORTHOGONAL)


def test_check_as_object():
    assert "check_as_object" in rules_in(minimal(object="X", object_cn="白盒检查"),
                                         CATEGORY_ORTHOGONAL)


def test_dimension_as_object():
    spec = minimal(object="A")            # 对象名与维度 A 撞车
    assert "dimension_as_object" in rules_in(spec, CATEGORY_ORTHOGONAL)


def test_method_as_dimension():
    spec = minimal(dimensions=[{"name": "随机反压", "fields": [
        {"name": "fa", "type": "enum", "values": [1]}]}],
        themes=[{"id": "TH", "name": "t", "priority": "P0", "applies_to": ["段"],
                 "dimensions": ["随机反压"], "method": "G"}])
    assert "method_as_dimension" in rules_in(spec, CATEGORY_ORTHOGONAL)


def test_check_as_dimension():
    spec = minimal(dimensions=[{"name": "白盒检查", "fields": [
        {"name": "深度", "type": "range", "min": 0, "max": 8}]}],
        themes=[{"id": "TH", "name": "t", "priority": "P0", "applies_to": ["段"],
                 "dimensions": ["白盒检查"], "method": "G"}])
    assert "check_as_dimension" in rules_in(spec, CATEGORY_ORTHOGONAL)


def test_field_as_dimension_on_prefix_match():
    """文档反例「维度：尾拍反压 / 字段：无」—— 取值被提上去当了维度名。"""
    spec = minimal(dimensions=[
        {"name": "反压模式", "fields": [{"name": "反压模式", "type": "enum",
                                        "values": ["无", "尾拍"]}]},
        {"name": "尾拍反压", "fields": [{"name": "尾拍反压", "type": "enum",
                                        "values": ["是"]}]}],
        themes=[{"id": "TH", "name": "t", "priority": "P0", "applies_to": ["段"],
                 "dimensions": ["反压模式"], "method": "G"}])
    assert "field_as_dimension" in rules_in(spec, CATEGORY_ORTHOGONAL)


def test_field_as_dimension_not_triggered_by_substring():
    """'反压持续时间' 里的 '持续' 只是构词成分，不是被提上来的取值。"""
    spec = minimal(dimensions=[
        {"name": "反压模式", "fields": [{"name": "反压模式", "type": "enum",
                                        "values": ["持续", "尾拍"]}]},
        {"name": "反压持续时间", "fields": [{"name": "反压持续时间", "type": "enum",
                                            "values": ["1拍"]}]}],
        themes=[{"id": "TH", "name": "t", "priority": "P0", "applies_to": ["段"],
                 "dimensions": ["反压持续时间"], "method": "G"}])
    assert "field_as_dimension" not in rules_in(spec, CATEGORY_ORTHOGONAL)


def test_method_token_in_values_is_warning():
    """文档十八节点名：'随机' 既是方法又是取值。"""
    spec = minimal(dimensions=[{"name": "A", "fields": [
        {"name": "fa", "type": "enum", "values": ["无", "随机"]}]}])
    hits = issues_of(build(spec), "method_token_in_field_values")
    assert hits and hits[0].severity == "warning"


def test_duplicate_field_name_across_dimensions():
    spec = minimal(dimensions=[
        {"name": "A", "fields": [{"name": "长度", "type": "enum", "values": [1]}]},
        {"name": "B", "fields": [{"name": "长度", "type": "enum", "values": [8]}]}])
    assert "duplicate_field_name" in rules_in(spec, CATEGORY_ORTHOGONAL)


def test_field_without_values():
    spec = minimal(dimensions=[{"name": "A", "fields": [
        {"name": "fa", "type": "linkage", "linked_to": "不存在"}]}])
    assert "field_without_values" in rules_in(spec, CATEGORY_ORTHOGONAL)


# ════════════════════════════════════════════════════════════
# 维度交叉
# ════════════════════════════════════════════════════════════

def test_cross_level_mismatch_between_matrix_and_group():
    spec = minimal(cross_matrix={"A×B": "required"},
                   dimensions=[
                       {"name": "A", "fields": [{"name": "fa", "type": "enum",
                                                 "values": [1]}]},
                       {"name": "B", "fields": [{"name": "fb", "type": "enum",
                                                 "values": [1]}]}],
                   cross_groups=[{"id": "XG", "dimensions": ["A", "B"],
                                  "level": "optional"}])
    hits = issues_of(build(spec), "cross_level_mismatch")
    assert hits and hits[0].severity == "warning"


def test_forbidden_pair_inside_required_group_is_error():
    spec = minimal(cross_matrix={"A×B": "forbidden"},
                   dimensions=[
                       {"name": "A", "fields": [{"name": "fa", "type": "enum",
                                                 "values": [1]}]},
                       {"name": "B", "fields": [{"name": "fb", "type": "enum",
                                                 "values": [1]}]}],
                   cross_groups=[{"id": "XG", "dimensions": ["A", "B"]}])
    assert "cross_conflict" in rules_in(spec, CATEGORY_CROSS)


def test_group_with_one_resolved_dimension_is_error():
    """fc_flawed 的 XG-02 = [随机反压, 不存在的维度] —— 解析后只剩一个维度。"""
    result = analyze_many(load_models_from_text(
        FC_FLAWED.read_text(encoding="utf-8")))
    assert issues_of(result, "cross_group_too_small")

def test_group_with_two_dimensions_passes():
    assert not issues_of(build(minimal()), "cross_group_too_small")


def test_dimension_not_crossed_is_warned():
    spec = minimal(dimensions=[
        {"name": "A", "fields": [{"name": "fa", "type": "enum", "values": [1]}]},
        {"name": "B", "fields": [{"name": "fb", "type": "enum", "values": [1]}]}])
    hits = issues_of(build(spec), "dimension_not_crossed")
    assert any("B" in i.target for i in hits)


def test_cross_explosion_is_warned():
    big = [str(i) for i in range(78)]
    spec = minimal(
        dimensions=[
            {"name": "A", "fields": [{"name": "fa", "type": "range", "min": 0,
                                      "max": 77, "boundary": big}]},
            {"name": "B", "fields": [{"name": "fb", "type": "range", "min": 0,
                                      "max": 77, "boundary": big}]}],
        cross_groups=[{"id": "XG", "dimensions": ["A", "B"], "method": "G"}])
    assert "cross_group_explosion" in rules_in(spec, CATEGORY_CROSS)


# ════════════════════════════════════════════════════════════
# 覆盖 / 环境
# ════════════════════════════════════════════════════════════

def test_uncovered_values_are_reported(cpu_flawed_result):
    hits = issues_of(cpu_flawed_result, "field_value_uncovered")
    assert hits and all(i.severity == "warning" for i in hits)


def test_full_coverage_is_silent(cpu_result):
    assert not issues_of(cpu_result, "field_value_uncovered")


def test_no_cases_generated_is_error():
    spec = minimal(generation={"themes": [], "priorities": ["P9"]})
    assert "no_cases_generated" in rules_of(build(spec))


def test_missing_environment_declaration_is_warned():
    spec = {k: v for k, v in MINIMAL.items() if k != "environment"}
    assert "environment_not_declared" in rules_of(build(spec))


def test_unknown_environment_key_is_reported():
    spec = minimal(environment={"defaults": {"rtl_version": "v1", "bogus": "x"}})
    hits = issues_of(build(spec), "environment_unknown_key")
    assert hits and "bogus" in hits[0].message


def test_environment_key_without_default_is_info():
    spec = minimal(environment={"required": ["rtl_version"]})
    hits = issues_of(build(spec), "environment_key_without_default")
    assert hits and all(i.severity == "info" for i in hits)


def test_case_missing_required_environment_key_is_error():
    """必需键没有缺省值时，生成的 case 就带不上它 —— 失败即不可复现。"""
    spec = minimal(environment={"required": ["rtl_version"]})
    hits = issues_of(build(spec), "case_missing_environment_key")
    assert hits and hits[0].severity == "error"


def test_required_key_with_default_lands_on_every_case():
    spec = minimal(environment={"required": ["rtl_version"],
                                "defaults": {"rtl_version": "v1"}})
    assert not issues_of(build(spec), "case_missing_environment_key")


def test_case_without_check_is_error():
    spec = minimal(checks=[], case_defaults={"checks": []},
                   themes=[{"id": "TH", "name": "t", "priority": "P0",
                            "applies_to": ["段"], "dimensions": ["A"],
                            "method": "G"}])
    assert "case_without_check" in rules_of(build(spec))


def test_unused_check_is_info():
    spec = minimal(checks=["CHECK-FUNC", "CHECK-PERF"],
                   case_defaults={"checks": ["CHECK-FUNC"]})
    hits = issues_of(build(spec), "check_never_used")
    assert hits and all(i.severity == "info" for i in hits)


def test_check_suggested_from_tree_and_field_keywords():
    """模型里有队列/仲裁类节点，却没声明 CHECK-WBOX。"""
    spec = minimal(
        sub_objects=[{"id": "N", "name": "结构仲裁", "code": "ARB"}],
        themes=[{"id": "TH", "name": "t", "priority": "P0",
                 "applies_to": ["结构仲裁"], "dimensions": ["A"], "method": "G"}],
        checks=["CHECK-FUNC"], case_defaults={"checks": ["CHECK-FUNC"]})
    hits = issues_of(build(spec), "check_suggested")
    assert any("CHECK-WBOX" in i.target for i in hits)


def test_check_suggestion_silent_when_already_declared():
    spec = minimal(checks=["CHECK-FUNC", "CHECK-WBOX"],
                   case_defaults={"checks": ["CHECK-FUNC"]},
                   sub_objects=[{"id": "N", "name": "结构仲裁", "code": "ARB"}],
                   themes=[{"id": "TH", "name": "t", "priority": "P0",
                            "applies_to": ["结构仲裁"], "dimensions": ["A"],
                            "method": "G"}])
    hits = issues_of(build(spec), "check_suggested")
    assert not any("CHECK-WBOX" in i.target for i in hits)


# ════════════════════════════════════════════════════════════
# 示例模型：干净的要干净，有坑的每条都要抓到
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", (CPU, FC), ids=lambda p: p.name)
def test_clean_examples_have_no_errors(path):
    result = analyze_many(load_models_from_text(path.read_text(encoding="utf-8")))
    assert not [i for i in result.model_issues if i.is_error], \
        [str(i) for i in result.model_issues if i.is_error]


def test_flawed_examples_trigger_the_expected_tree_and_theme_rules(cpu_flawed_result):
    expected = {
        "org_leaf_code_duplicate", "org_leaf_uncovered", "org_branch_unreachable",
        "theme_priority_gap", "theme_overlap", "theme_spcl_without_boundary",
        "theme_forbidden_pair", "theme_dimension_unused", "theme_no_dimension",
        "unknown_tree_node_ref", "unknown_theme_ref",
    }
    assert expected <= rules_of(cpu_flawed_result)


def test_flawed_examples_trigger_the_expected_dimension_rules():
    result = analyze_many(load_models_from_text(FC_FLAWED.read_text(encoding="utf-8")))
    expected = {"field_as_dimension", "method_as_dimension", "check_as_dimension",
                "method_as_object", "check_as_object", "dimension_as_object",
                "method_token_in_field_values", "unknown_dimension_ref",
                "unknown_linkage_ref", "cross_group_too_small"}
    assert expected <= rules_of(result)


def test_flawed_scores_below_clean(cpu_result, cpu_flawed_result):
    assert cpu_flawed_result.score.total < cpu_result.score.total


class TestCoverBinUnreachable:
    """显式覆盖仓 vs 取值点：**某个仓一个取值点都打不到**要拦住。

    这是"激励侧与度量侧同一份分母"的准确说法 —— 不是"一比一"（给了显式仓时
    天然多对一），而是"**每个仓至少有一个取值点能打到**"。

    多对一无害，空洞致命：某个仓空着 → 声明的覆盖率**永远封顶**，而 covergroup
    编译通过、回归跑得过、日志一切正常（实测踩过 `cluster_id`）。
    """

    def _model(self, field: dict) -> dict:
        return {
            "version": "1", "object": "dut", "object_code": "DUT",
            "sub_objects": [{"id": "OBJ-01", "name": "F", "code": "F1"}],
            "dimensions": [{"id": "D_x", "name": "X", "fields": [field]}],
            "themes": [{"id": "TH-P0", "name": "f", "priority": "P0",
                        "dimensions": ["D_x"]}],
        }

    def test_a_bin_no_value_point_can_reach_is_an_error(self):
        """**这条就是实测那个 bug**：4 个显式仓却不给 boundary。"""
        bad = {"name": "c", "type": "range", "min": 0, "max": 3,
               "cover_bins": [{"name": "c0", "at": 0}, {"name": "c1", "at": 1},
                              {"name": "c2", "at": 2}, {"name": "c3", "at": 3}]}
        hits = issues_of(build(self._model(bad)), "cover_bin_unreachable")
        assert len(hits) == 1
        assert hits[0].severity == "error"
        assert "c1" in hits[0].message and "c2" in hits[0].message

    def test_giving_boundary_fixes_it(self):
        good = {"name": "c", "type": "range", "min": 0, "max": 3,
                "boundary": ["0", "1", "2", "3"],
                "cover_bins": [{"name": "c0", "at": 0}, {"name": "c1", "at": 1},
                               {"name": "c2", "at": 2}, {"name": "c3", "at": 3}]}
        assert "cover_bin_unreachable" not in rules_in(self._model(good))

    def test_many_to_one_is_not_reported(self):
        """**多对一无害**：`queue_level` 那种 10 取值点落进 6 个区间仓。

        只按"取值点数 ≠ bin 数"报的话，这一条会被误报 —— 而它恰恰是正常的。
        """
        many = {"name": "q", "type": "range", "min": 0, "max": 32,
                "boundary": ["0", "1", "7", "8", "15", "16", "24", "25", "31", "32"],
                "cover_bins": [{"name": "empty", "at": 0},
                               {"name": "low", "range": [1, 7]},
                               {"name": "mid", "range": [8, 15]},
                               {"name": "high", "range": [16, 24]},
                               {"name": "near_full", "range": [25, 31]},
                               {"name": "full", "at": 32}]}
        assert "cover_bin_unreachable" not in rules_in(self._model(many))

    def test_a_model_without_explicit_bins_is_never_reported(self):
        """没写显式仓 → 取值点与 bin 天然一比一，这条规则不该出现。"""
        plain = {"name": "e", "type": "enum", "values": [0, 1, 2]}
        assert "cover_bin_unreachable" not in rules_in(self._model(plain))

    def test_the_shipped_npu_model_is_clean(self):
        """仓库里那份真模型 —— 修完 `cluster_id` 之后不该再有这一条。"""
        import pathlib

        npu = (pathlib.Path(__file__).resolve().parents[4]
               / "specs" / "npu_sched" / "casemodel.yaml")
        ids = rules_of(build(yaml.safe_load(npu.read_text(encoding="utf-8"))))
        assert "cover_bin_unreachable" not in ids
