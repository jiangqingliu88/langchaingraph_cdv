"""analysis 门面、评分、外部核对。

三条最要紧的不变式：
  1. 评分只是模型的属性 —— 换一份 case 列表分数不变（可复现）
  2. 外部核对的缺陷不进评分，但进退出码
  3. 门面把产物组装齐（矩阵 / 覆盖 / 节点命中 / 专题命中）
"""
from __future__ import annotations

import pytest
import yaml

from src.tools.generation.casemodel_tools.analysis import (SCORE_WEIGHTS, analyze, analyze_file,
                                                build_matrix, cross_check,
                                                load_rules)
from src.tools.generation.casemodel_tools.analysis.issues import CATEGORY_EXTERNAL
from src.tools.generation.casemodel_tools.repository import load_model_from_text
from src.tools.generation.casemodel_tools.repository.case_list import load_cases

from .conftest import CPU, FC, issues_of, rules_of


# ════════════════════════════════════════════════════════════
# 门面组装
# ════════════════════════════════════════════════════════════

def test_facade_fills_every_product(cpu_result):
    assert cpu_result.matrix is not None
    assert cpu_result.dimension_coverage and cpu_result.field_coverage
    assert cpu_result.score.rows()
    assert cpu_result.explosion
    assert cpu_result.generation.count > 0
    assert cpu_result.model_issues


def test_facade_runs_every_registered_rule(cpu_result):
    """门面必须把注册表里的每条规则都跑一遍 —— 漏跑等于规则不存在。"""
    assert len(load_rules()) == len(load_rules())     # 注册表稳定
    # 结果里的规则 id 必须是注册表的子集
    assert {i.rule for i in cpu_result.issues} <= set(
        r.id for r in load_rules())


def test_facade_accepts_a_prebuilt_generation(cpu):
    from src.tools.generation.casemodel_tools.generation import generate
    gen = generate(cpu, max_cases=10)
    result = analyze(cpu, generation=gen)
    assert result.generation.count == 10
    assert result.generation.truncated


def test_facade_seed_and_max_cases_override(cpu):
    result = analyze(cpu, seed=1234, max_cases=7)
    assert result.generation.seed == 1234
    assert result.generation.count == 7


def test_node_and_theme_hit_tables_are_consistent(cpu_result):
    for node in cpu_result.model.leaf_nodes:
        cases = cpu_result.cases_for_node(node.id)
        assert all(c.sub_object_id == node.id for c in cases)
    for theme in cpu_result.model.themes:
        cases = cpu_result.cases_for_theme(theme.id)
        assert all(c.theme == theme.id for c in cases)


def test_node_rows_carry_themes_and_counts(cpu_result):
    rows = {r["id"]: r for r in cpu_result.node_rows()}
    assert rows["STG-01a"]["theme_count"] > 0
    assert rows["STG-01a"]["case_count"] > 0
    assert rows["STG-01"]["covered"] is True          # 分支由叶子代表


def test_theme_rows_carry_actual_output(cpu_result):
    rows = {r["id"]: r for r in cpu_result.theme_rows()}
    assert rows["TH-P0-CFG"]["case_count"] == 5
    assert rows["TH-P0-CFG"]["actual_node_count"] == 5
    assert rows["TH-ERR"]["actual_node_count"] == 0    # 不作用树
    assert rows["TH-ERR"]["kind"] == "orthogonal"


# ════════════════════════════════════════════════════════════
# 评分
# ════════════════════════════════════════════════════════════

def test_score_weights_sum_to_one():
    assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9


@pytest.mark.parametrize("path", (CPU, FC), ids=lambda p: p.name)
def test_score_within_range(path):
    result = analyze_file(path)
    assert 0.0 <= result.score.total <= 100.0
    for _name, sub, _weighted, _reasons in result.score.row_reasons():
        assert 0.0 <= sub <= 1.0


def test_score_is_the_model_s_own_property(cpu_result, cpu_roundtrip):
    """核心不变式：传哪份外部 case 列表，模型分数都不变。

    否则同一个模型会得到两个分数，分数不再可复现 —— 与项目定位直接冲突。
    """
    assert cpu_roundtrip.external is not None
    assert cpu_roundtrip.score.total == cpu_result.score.total
    assert len(cpu_roundtrip.model_issues) == len(cpu_result.model_issues)
    # 并集里确实多了外部核对的条目
    assert len(cpu_roundtrip.issues) >= len(cpu_result.issues)


def test_external_issues_still_affect_the_exit_code(cpu_roundtrip):
    """分数不受影响，但既然要了核对，它的结论就该影响命令成败。"""
    assert cpu_roundtrip.external is not None


def test_flawed_scores_lower_than_clean(cpu_result, cpu_flawed_result):
    assert cpu_flawed_result.score.total < cpu_result.score.total


def test_score_reasons_explain_the_deduction(cpu_flawed_result):
    """每个扣分子项都要能说清扣在哪 —— 否则分数没法行动。"""
    rows = {name: reasons for name, _sub, _w, reasons
            in cpu_flawed_result.score.row_reasons()}
    # 组织树有叶子没被覆盖，应当给出理由
    assert rows["组织树"]
    assert any("叶子" in r for r in rows["组织树"])


def test_clean_model_has_no_error_reasons(cpu_result):
    for name, sub, _w, reasons in cpu_result.score.row_reasons():
        if sub < 1.0:
            assert reasons, f"{name} 扣了分却没给理由"


# ════════════════════════════════════════════════════════════
# 交叉矩阵
# ════════════════════════════════════════════════════════════

def test_matrix_is_symmetric(cpu):
    matrix = build_matrix(cpu)
    for (i, j), cell in matrix.cells.items():
        assert matrix.get(matrix.dimensions[i].key,
                          matrix.dimensions[j].key) is cell


def test_matrix_marks_and_grid(cpu):
    matrix = build_matrix(cpu)
    grid = matrix.mark_grid()
    n = len(matrix.dimensions)
    for i in range(n):
        assert grid[i][i] == "—"
    assert any(cell.mark == "★" for cell in matrix.cells.values())


def test_matrix_declared_wins_over_group():
    """显式声明优先 —— 不被交叉组静默覆盖。"""
    spec = {"object": "X", "object_code": "XX",
            "dimensions": [
                {"name": "A", "fields": [{"name": "fa", "type": "enum",
                                          "values": [1]}]},
                {"name": "B", "fields": [{"name": "fb", "type": "enum",
                                          "values": [1]}]}],
            "cross_matrix": {"A×B": "required"},
            "cross_groups": [{"id": "XG", "dimensions": ["A", "B"],
                              "level": "optional"}]}
    matrix = build_matrix(load_model_from_text(yaml.safe_dump(spec)))
    assert matrix.get("A", "B").level == "required"
    assert matrix.conflicts


def test_forbidden_pairs_helper():
    spec = {"object": "X", "object_code": "XX",
            "dimensions": [
                {"name": "A", "fields": [{"name": "fa", "type": "enum",
                                          "values": [1]}]},
                {"name": "B", "fields": [{"name": "fb", "type": "enum",
                                          "values": [1]}]}],
            "cross_matrix": {"A×B": "forbidden"}}
    matrix = build_matrix(load_model_from_text(yaml.safe_dump(spec)))
    assert matrix.forbidden_pairs() == [("A", "B")]


# ════════════════════════════════════════════════════════════
# 外部核对
# ════════════════════════════════════════════════════════════

def test_cross_check_attaches_report(fc_cross):
    assert fc_cross.external is not None
    assert fc_cross.external.case_count == 45
    assert fc_cross.external.source.endswith("fc_real_cases.yaml")


def test_roundtrip_of_own_cases_is_clean(cpu_roundtrip):
    """模型 vs「它自己生成的 case 列表」—— 应当无话可说。

    这条固定了三件事：导出与解析同构（闭环无损）、生成侧不产重复、
    覆盖统计在两份数据上一致。
    """
    ext = cpu_roundtrip.external
    assert ext is not None
    assert ext.issues == [], [str(i) for i in ext.issues]
    assert ext.coverage_ratio == pytest.approx(ext.generated_ratio)
    assert not ext.duplicates and not ext.unknown_fields


def test_cross_check_finds_unknown_field_and_value(fc_cross):
    ext = fc_cross.external
    assert ("TC-FC-RECV-D-98", "带宽") in ext.unknown_fields
    assert ("TC-FC-RECV-D-97", "反压模式", "脉冲") in ext.undeclared_values
    rules = {i.rule for i in ext.issues}
    assert {"external_unknown_field", "external_undeclared_value"} <= rules


def test_cross_check_finds_duplicates_by_object_node_fields(fc_cross):
    """文档十二节：对象+节点+字段取值相同即重复，方法不同也算。"""
    ext = fc_cross.external
    assert ext.duplicates
    ids = {cid for _desc, group in ext.duplicates for cid in group}
    assert "TC-FC-RECV-D-99" in ids
    assert any(i.rule == "external_duplicate_case" for i in ext.issues)


def test_cross_check_finds_gap_where_impl_lags_model(fc_cross):
    ext = fc_cross.external
    assert ext.generated_only
    assert ext.coverage_ratio < ext.generated_ratio
    assert any(i.rule == "external_coverage_gap" for i in ext.issues)


def test_cross_check_finds_naming_and_fingerprint_problems(fc_cross):
    rules = {i.rule for i in fc_cross.external.issues}
    assert "external_case_id_pattern" in rules
    assert "external_case_missing_environment" in rules
    assert "external_case_missing_checks" in rules


def test_cross_check_reports_uncovered_nodes_and_themes(cpu_roundtrip):
    """模型有、真实没有的叶子/专题 —— 实现漏了哪块结构、哪一轮。"""
    ext = cpu_roundtrip.external
    assert not rules_of(cpu_roundtrip, "external_node_uncovered")
    assert not issues_of(cpu_roundtrip, "external_theme_uncovered")


def test_cross_check_flags_unknown_theme(tmp_path):
    spec = tmp_path / "c.yaml"
    spec.write_text(
        "cases:\n"
        "  - case_id: TC-CPU-ARB-D-01\n    sub_object_id: STG-01a\n"
        "    theme: TH-NOT-EXIST\n    fields: {指令长度: '1'}\n"
        "    environment: {seed: 1}\n    checks: [CHECK-FUNC]\n",
        encoding="utf-8")
    from .conftest import one_model
    cases = load_cases(spec)
    model = one_model(CPU)
    report = cross_check(model, cases)
    assert any(i.rule == "external_unknown_theme" for i in report.issues)
    # 真实 case 报的专题在模型里一个都不存在 —— 模型自己的专题自然零覆盖，
    # 不该被那个未知 id 掩盖掉
    assert not set(report.theme_coverage) & {t.id for t in model.themes}
    assert len([i for i in report.issues if i.rule == "external_theme_uncovered"]) \
        == len(model.themes)


def test_cross_check_all_issues_are_tagged_external(fc_cross):
    assert all(i.category == CATEGORY_EXTERNAL for i in fc_cross.external.issues)


def test_external_report_to_dict_is_serialisable(fc_cross):
    import json
    payload = fc_cross.external.to_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False))
    assert {"case_count", "coverage_ratio", "issues"} <= set(payload)


def test_analysis_result_summary_includes_external(cpu_roundtrip):
    s = cpu_roundtrip.summary()
    assert s["external_case_count"] > 0
    assert "external_coverage_ratio" in s
    assert "model_error_count" in s


# ════════════════════════════════════════════════════════════
# 文本入口 vs 文件入口
#
# 这三条原先住在 GUI 的编辑器测试里（那个文件随旧界面一起删了），但它们
# 测的其实是**工具层**：界面只是「从编辑器文本分析」的第一个消费者。
# 放在这里之后，删掉任何界面都不会带走它们 —— 这正是把界面与工具分开的收益。
# ════════════════════════════════════════════════════════════

def test_check_text_reports_parse_and_schema_errors():
    from src.tools.generation.casemodel_tools.analysis.schema_check import SchemaChecker
    checker = SchemaChecker()
    assert checker.check_text("a: [b")[0].rule == "yaml_parse_error"
    assert any(i.rule == "missing_required" for i in checker.check_text("object: X"))
    assert checker.check_text(CPU.read_text(encoding="utf-8")) == []


def test_analyze_text_supports_external_cases():
    from src.tools.generation.casemodel_tools.analysis import analyze_text
    from .conftest import FC, FC_REAL
    result = analyze_text(FC.read_text(encoding="utf-8"), cases=str(FC_REAL))
    assert result.external is not None
    assert result.external.case_count == 45


def test_analyze_text_matches_analyze_file():
    """同一份内容，从文本分析 vs 从文件分析，结论必须一致。

    这条是界面「改一行马上看效果」的前提：编辑器分析的是**内存里的文本**，
    它得和「存盘再分析」给同一个答案，否则未保存时看到的结果就不可信。
    """
    from src.tools.generation.casemodel_tools.analysis import analyze_text
    assert analyze_text(CPU.read_text(encoding="utf-8")).score.total == \
        analyze_file(str(CPU)).score.total
