"""纯文本渲染 —— CLI 与界面导出报告共用的那一份。

重点固定两件事：按显示宽度对齐（中文占 2 列），
以及「渲染器不含判定逻辑」—— 同一份 AnalysisResult 渲染两次结果一致。

渲染器现在就在包根（`casemodel_tools/text.py`）：界面搬去工作台之后
（`src/workbench/modules/vms/casemodel/`），原来的 `view/` 层只剩这一个文件，
已经没有存在理由。那边的界面测试在 `src/workbench/tests/test_casemodel_*.py`。
"""
from __future__ import annotations

import pytest

from src.layers.l3_decision.casemodel import text as T

from .conftest import CPU, FC, FC_REAL


# ════════════════════════════════════════════════════════════
# 宽度计算 —— 混排中英文的表格靠它对齐
# ════════════════════════════════════════════════════════════

def test_display_width_counts_cjk_as_two():
    assert T.display_width("abc") == 3
    assert T.display_width("指令") == 4
    assert T.display_width("指令abc") == 7


def test_pad_aligns_by_display_width():
    assert T.display_width(T.pad("指令", 10)) == 10
    assert T.display_width(T.pad("abc", 10)) == 10
    assert T.pad("ab", 4, ">") == "  ab"
    assert T.display_width(T.pad("指令", 5, "^")) == 5


def test_pad_never_truncates():
    assert T.pad("很长的中文名字", 4) == "很长的中文名字"


def test_cut_respects_display_width_and_marks_ellipsis():
    cut = T.cut("指令长度和反压模式的组合", 10)
    assert T.display_width(cut) <= 10
    assert cut.endswith("…")
    assert T.cut("短的", 10) == "短的"


def test_bar_renders_proportionally():
    assert T.bar(1.0, 10) == "█" * 10
    assert T.bar(0.0, 10) == "░" * 10
    assert T.bar(0.5, 10).count("█") == 5
    assert len(T.bar(2.0, 10)) == 10          # 超界截断到 1


# ════════════════════════════════════════════════════════════
# 各段渲染
# ════════════════════════════════════════════════════════════

def test_layers_section_lists_all_eight_layers(cpu_result):
    body = T.render_layers(cpu_result)
    for layer in ("L1", "L2", "TH", "L3", "L4", "L5", "L6", "ENV"):
        assert layer in body
    assert "功能组织树" in body


def test_org_tree_section_shows_hierarchy_and_coverage(cpu_result):
    body = T.render_org_tree(cpu_result)
    assert "指令" in body and "├─" in body or "└─" in body
    assert "分支" in body                 # 分支节点标成分支，不是无覆盖
    assert "✓" in body


def test_org_tree_section_marks_uncovered_leaves(cpu_flawed_result):
    body = T.render_org_tree(cpu_flawed_result)
    assert "✗" in body


def test_themes_section_lists_priorities_and_kinds(cpu_result):
    body = T.render_themes(cpu_result)
    assert "P0" in body and "P1" in body and "P2" in body
    assert "作用于功能组织树" in body
    assert "不作用功能组织树" in body       # 错误和异常 / 性能常稳
    assert "全部维度" in body               # 随机专题


def test_themes_section_notes_fallback_for_flat_model(fc_result):
    body = T.render_themes(fc_result)
    assert "没有声明 themes" in body


def test_summary_reports_the_driver(cpu_result, fc_result):
    assert "专题（themes）" in T.render_summary(cpu_result)
    assert "交叉组（cross_groups）" in T.render_summary(fc_result)


def test_score_section_explains_each_deduction(cpu_flawed_result):
    body = T.render_score(cpu_flawed_result)
    assert "扣分原因" in body
    assert "组织树" in body


def test_matrix_section_has_legend_and_marks(cpu_result):
    body = T.render_matrix(cpu_result)
    assert "★ 必需交叉" in body and "✗ 禁止交叉" in body


def test_coverage_section_shows_missing_values(cpu_flawed_result):
    body = T.render_coverage(cpu_flawed_result)
    assert "未命中" in body


def test_external_section_only_when_cases_given(cpu_result, fc_cross):
    assert T.render_external(cpu_result) == ""
    body = T.render_external(fc_cross)
    assert "真实 case 核对" in body
    assert "评分必须只是模型的属性" in body


def test_issues_section_groups_by_category(cpu_flawed_result):
    body = T.render_issues(cpu_flawed_result)
    assert "功能组织树" in body and "专题" in body
    assert "诊断明细" in body


def test_rules_section_lists_registry():
    body = T.render_rules()
    assert "校验规则" in body
    assert "org_leaf_code_duplicate" in body
    assert "theme_forbidden_pair" in body


def test_report_concatenates_every_section(cpu_result):
    body = T.report(cpu_result)
    for fragment in ("分层结构", "功能组织树", "专题", "生成结果", "完备性评分",
                     "维度交叉矩阵", "字段取值覆盖", "诊断明细"):
        assert fragment in body


def test_report_is_deterministic(cpu_result):
    """渲染器不含判定逻辑 —— 同一份结果渲染两次必须一样。"""
    assert T.report(cpu_result) == T.report(cpu_result)


def test_report_has_no_trailing_whitespace_regressions(cpu_result):
    """按显示宽度补齐不该在行尾留下多余空格的问题（不做强断言，只查块结构）。"""
    lines = T.report(cpu_result).splitlines()
    assert any(l.startswith("─") for l in lines)
    assert not any(l.endswith("\t") for l in lines)
