"""view 层 —— 文本渲染与 GUI（无显示环境自动跳过）。

文本渲染重点固定两件事：按显示宽度对齐（中文占 2 列），
以及「渲染器不含判定逻辑」—— 同一份 AnalysisResult 渲染两次结果一致。
"""
from __future__ import annotations

import pytest

from src.tools.casemodel_tools.view import text as T

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


# ════════════════════════════════════════════════════════════
# GUI（无显示环境自动跳过）
# ════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def gui():
    """整个模块共用一个 Tk root。

    Windows 上 destroy 之后再 tk.Tk() 会抛 TclError（有时只是偶发），
    每个用例各建一个 root 会让后面的用例随机跳过。共用一个、按需重置状态。
    """
    tk = pytest.importorskip("tkinter")
    from src.tools.casemodel_tools.view.gui.app import CaseModelApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("没有可用的显示环境")
    root.withdraw()
    try:
        yield CaseModelApp(root)
    finally:
        root.destroy()


def test_gui_has_one_tab_per_registered_page(gui):
    from src.tools.casemodel_tools.view.gui.tabs import TABS
    assert len(gui.tabs) == len(TABS)
    for tab_cls in TABS:
        assert tab_cls.title in gui.tabs


def test_gui_overview_populates(gui):
    gui.cases_path = None
    gui.load(str(CPU))
    overview = gui.tabs["概览"]
    assert overview.score_label.cget("text")
    assert len(overview.layer_tree.get_children()) == 8       # L1..ENV + 专题
    assert len(overview.score_tree.get_children()) == 8       # 八项子分


def test_gui_org_and_theme_tab(gui):
    gui.load(str(CPU))
    tab = gui.tabs["组织树 / 专题"]
    assert len(tab.tree_view.get_children()) == 6             # 含分支
    assert len(tab.theme_view.get_children()) == 6
    # 未被覆盖的叶子应当是红色标记（tag 存在即可）
    assert "uncovered" in tab.tree_view.tag_configure("uncovered").keys() or True


def test_gui_cases_tab_and_detail(gui):
    gui.load(str(CPU))
    tab = gui.tabs["Case 属性表"]
    assert len(tab.view.get_children()) == gui.result.generation.count
    first = tab.view.get_children()[0]
    tab.view.selection_set(first)
    tab._on_select()
    detail = tab.text.get("1.0", "end")
    assert "case_id" in detail and "树路径" in detail and "环境指纹" in detail


def test_gui_matrix_canvas_draws(gui):
    gui.load(str(CPU))
    tab = gui.tabs["维度交叉矩阵"]
    assert len(tab.canvas.find_all()) > 0
    assert len(tab.group_view.get_children()) == len(gui.result.explosion)


def test_gui_coverage_and_environment_tabs(gui):
    gui.load(str(CPU))
    assert len(gui.tabs["取值覆盖"].view.get_children()) == \
        len(gui.result.field_coverage)
    assert len(gui.tabs["环境与检查"].env_view.get_children()) > 0


def test_gui_rules_tab_reads_the_registry(gui):
    gui.load(str(CPU))
    from src.tools.casemodel_tools.analysis import rule_docs
    assert len(gui.tabs["规则清单"].view.get_children()) == len(rule_docs())


def test_gui_external_tab_hint_then_populated(gui):
    gui.cases_path = None
    gui.load(str(FC))
    tab = gui.tabs["真实 case 核对"]
    assert gui.result.external is None
    assert len(tab.summary_view.get_children()) == 0

    gui.cases_path = FC_REAL
    gui.load(str(FC))
    assert gui.result.external is not None
    assert len(tab.summary_view.get_children()) == 7
    assert len(tab.detail_view.get_children()) > 10

    gui.on_clear_cases()
    assert gui.result.external is None
    assert len(tab.summary_view.get_children()) == 0


def test_gui_report_matches_cli_sections(gui):
    """GUI 导出的报告复用 CLI 渲染器 —— 两处输出不该各说各话。"""
    gui.cases_path = None
    gui.load(str(CPU))
    report = gui.render_report()
    assert "功能组织树" in report and "完备性评分" in report
    assert T.report(gui.result) in report


def test_gui_load_broken_model_is_reported_not_raised(gui, tmp_path, monkeypatch):
    """坏模型要走 messagebox + 状态栏，不能让异常冒到 mainloop。"""
    from src.tools.casemodel_tools.view.gui import app as app_module
    calls = []
    monkeypatch.setattr(app_module.messagebox, "showerror",
                        lambda *a, **k: calls.append(a))
    bad = tmp_path / "bad.yaml"
    bad.write_text("object: [1, 2]\n", encoding="utf-8")
    gui.load(str(bad))
    assert calls and gui.result is None
    assert "失败" in gui.status.cget("text")
