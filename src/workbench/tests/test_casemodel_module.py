"""case 建模模块 —— Qt 模型、自绘控件、11 个页面的构建与填充。

原在 `src/tools/casemodel_tools/tests/test_gui.py`。第二轮把界面搬进工作台时
一并迁过来：**工具包现在是纯工具，测试不需要 Qt**；界面测试归界面。

用 `QT_QPA_PLATFORM=offscreen`（conftest 里设），所以不需要显示器、也不会弹窗。
"""
from __future__ import annotations

from src.tools.casemodel_tools.analysis import CATEGORY_ORTHOGONAL
from src.workbench.modules.vms.casemodel.models import (CaseTableModel,
                                                        OrgTreeModel)
from src.workbench.modules.vms.casemodel.pages import PAGES
from src.workbench.ui.coverage_view import CoverageView
from src.workbench.ui.matrix_view import MatrixView
from src.workbench.ui.panels import IssuePanel
from src.workbench.ui.severity_model import IssueTableModel

from .conftest import CPU_FLAWED, FC, FC_FLAWED, FC_REAL


# ════════════════════════════════════════════════════════════
# 领域 Qt 模型
# ════════════════════════════════════════════════════════════

def test_issue_model_colors_by_severity(casemodel):
    from PySide6.QtCore import Qt
    model = IssueTableModel()
    model.set_issues(casemodel.result.model_issues)
    assert model.rowCount() == len(casemodel.result.model_issues)
    for row in range(model.rowCount()):
        color = model.data(model.index(row, 0), Qt.ItemDataRole.ForegroundRole)
        assert color is not None, f"第 {row} 行没有按严重度着色"
    counts = model.counts()
    assert sum(counts.values()) == model.rowCount()


def test_issue_filter_model_filters_without_touching_source(casemodel):
    from src.workbench.ui.severity_model import IssueFilterModel
    issues = casemodel.result.model_issues
    source = IssueTableModel()
    source.set_issues(issues)
    proxy = IssueFilterModel()
    proxy.setSourceModel(source)

    total = proxy.rowCount()
    proxy.set_severities({"error"})
    assert proxy.rowCount() <= total
    assert source.rowCount() == len(issues)        # 原始数据不受过滤影响

    proxy.set_severities(set())
    assert proxy.rowCount() == total               # 清掉过滤就恢复

    proxy.set_keyword("绝不存在的关键字")
    assert proxy.rowCount() == 0


def test_case_model_flattens_fields_and_keeps_case_in_userrole(casemodel):
    from PySide6.QtCore import Qt
    model = CaseTableModel()
    cases = casemodel.result.generation.cases
    model.set_cases(cases)
    assert model.rowCount() == len(cases)
    first = model.case_at(0)
    text = model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole)
    for name in first.fields:
        assert name in text
    # 整条 case 留在 UserRole 里 —— 详情面板据此直接取，不用回查
    assert model.data(model.index(0, 0), Qt.ItemDataRole.UserRole) is first


def test_tree_model_exposes_hierarchy(casemodel):
    from PySide6.QtCore import QModelIndex, Qt
    model = OrgTreeModel()
    model.set_result(casemodel.result)

    roots = model.rowCount(QModelIndex())
    assert roots == len(casemodel.result.model.org_root)
    branch = model.index(0, 0, QModelIndex())
    assert model.data(branch, Qt.ItemDataRole.DisplayRole) == "指令"
    assert model.rowCount(branch) == 2                 # 指令下有两个叶子
    leaf = model.index(0, 0, branch)
    assert model.parent(leaf) == branch                # 父索引正确
    assert model.data(leaf, Qt.ItemDataRole.DisplayRole) == "控制请求数据/结构仲裁"
    # 分支自身的「覆盖」列标 —；它在根层，不在自己孩子那层。
    # 叶子用「有/缺」而不是 ✓/✗ —— 那两个字符不是每个字体都有，会渲染成豆腐块。
    assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "—"


def test_tree_model_marks_uncovered_leaves_red(casemodel):
    from PySide6.QtCore import QModelIndex, Qt
    from src.workbench.modules.vms.casemodel import models as cm_models
    model = OrgTreeModel()
    model.set_result(casemodel.result)
    branch = model.index(0, 0, QModelIndex())
    leaf = model.index(0, 0, branch)
    assert model.data(leaf, Qt.ItemDataRole.ForegroundRole) == cm_models.COVERED


def test_tree_model_reset_clears(casemodel):
    from PySide6.QtCore import QModelIndex
    model = OrgTreeModel()
    model.set_result(casemodel.result)
    assert model.rowCount(QModelIndex()) > 0
    model.set_result(None)
    assert model.rowCount(QModelIndex()) == 0


# ════════════════════════════════════════════════════════════
# 自绘控件 —— grab() 会真的跑一遍 paintEvent
# ════════════════════════════════════════════════════════════

def test_matrix_view_paints_and_hits(qt_app, casemodel):
    view = MatrixView()
    view.set_matrix(casemodel.result.matrix)
    view.resize(700, 520)
    image = view.grab()                            # 触发 paintEvent
    assert not image.isNull()
    assert view.sizeHint().width() > 0

    picked = []
    view.cellPicked.connect(lambda a, b, c: picked.append((a, b, c)))
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from src.workbench.ui.matrix_view import HEADER_H, HEADER_W
    view._recompute_cell()
    cell = view._cell
    pos = QPointF(HEADER_W + 2, HEADER_H + cell + 2)     # 第 (1,0) 个格子
    view.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    assert picked and picked[0][2] is not None


def test_matrix_view_handles_empty_matrix(qt_app):
    view = MatrixView()
    view.set_matrix(None)
    view.resize(400, 300)
    assert not view.grab().isNull()                # 空数据也要能画


def test_coverage_view_paints(qt_app, casemodel):
    view = CoverageView()
    view.set_coverage(casemodel.result.dimension_coverage)
    assert view.sizeHint().height() > 0
    assert not view.grab().isNull()
    view.set_coverage([])
    assert not view.grab().isNull()


def test_issue_panel_shows_summary(qt_app):
    from src.tools.casemodel_tools.analysis import analyze_file
    panel = IssuePanel("提示", empty_hint="（空）")
    panel.set_issues([])
    assert "（空）" in panel.summary.text()

    issues = analyze_file(str(CPU_FLAWED)).model_issues
    panel.set_issues(issues)
    assert "共" in panel.summary.text() and "错误" in panel.summary.text()


# ════════════════════════════════════════════════════════════
# 模块与页面
# ════════════════════════════════════════════════════════════

def test_module_has_one_page_per_registered_page(casemodel):
    assert casemodel.tabs.count() == len(PAGES) == 11
    for i, page_cls in enumerate(PAGES):
        assert casemodel.tabs.tabText(i) == page_cls.TITLE
        assert page_cls.TITLE in casemodel.pages


def test_editor_is_first_page(casemodel):
    assert casemodel.tabs.tabText(0) == "编辑 YAML"


def test_module_titles_its_tab_with_the_open_file(casemodel, casemodel_window):
    """标签页标题挂上文件名 —— 同时开着几个模块时要看得出这是哪一份模型。"""
    for index in range(casemodel_window.center_tabs.count()):
        widget = casemodel_window.center_tabs.widget(index)
        if widget.property("module_id") == "vms.casemodel":
            assert "cpu_pipeline.yaml" in casemodel_window.center_tabs.tabText(index)
            return
    raise AssertionError("中央标签页里没有 Case 建模")


def test_opening_a_model_populates_every_page(casemodel):
    """每页都要有东西 —— 空白的页面说明 refresh 没接上。"""
    result = casemodel.result
    assert result is not None
    pages = casemodel.pages

    assert pages["概览"].layer_model.rowCount() == 8     # L1..ENV + 专题
    assert pages["概览"].score_model.rowCount() == 8     # 八项子分
    assert pages["组织树 / 专题"].tree_model.rowCount() == 4
    assert pages["组织树 / 专题"].theme_model.rowCount() == len(result.model.themes)
    assert pages["层级正交性"].panel.model.rowCount() == \
        len(result.by_category().get(CATEGORY_ORTHOGONAL, []))
    assert pages["Case 属性表"].model.rowCount() == result.generation.count
    assert pages["规则清单"].model.rowCount() == len(
        __import__("src.tools.casemodel_tools.analysis",
                   fromlist=["rule_docs"]).rule_docs())
    assert pages["取值覆盖"].model.rowCount() == len(result.field_coverage)
    assert pages["环境与检查"].env_model.rowCount() > 0
    assert pages["维度交叉矩阵"].matrix_view.matrix is not None


def test_overview_score_matches_analysis(casemodel):
    assert casemodel.pages["概览"].score_label.text() == \
        f"{casemodel.result.score.total:.0f}"


def test_flawed_model_shows_errors_on_the_right_pages(casemodel):
    """有坑的模型各页都要有内容，且坑要落在对应的诊断页上。

    cpu_pipeline_flawed 的坑在组织树 / 专题层（叶子代号重复、专题重叠…），
    fc_flawed 的坑才是层级正交性 —— 两页分开断言，免得把页面接错也测不出来。
    """
    casemodel.load(str(CPU_FLAWED))
    assert casemodel.result is not None
    assert casemodel.pages["组织树 / 专题"].theme_model.rowCount() > 0
    assert casemodel.pages["环境与检查"].panel.model.rowCount() > 0   # 含引用类诊断

    casemodel.load(str(FC_FLAWED))
    assert casemodel.pages["层级正交性"].panel.model.rowCount() > 0


def test_case_detail_follows_selection(casemodel):
    """视图套了排序代理，选中要按**视图的**（代理）索引来 —— 拿源索引会选不中。"""
    page = casemodel.pages["Case 属性表"]
    page.view.setCurrentIndex(page.view.model().index(0, 0))
    text = page.detail.toPlainText()
    assert "case_id" in text and "树路径" in text and "环境指纹" in text


def test_matrix_cell_click_updates_detail(casemodel):
    page = casemodel.pages["维度交叉矩阵"]
    matrix = casemodel.result.matrix
    i, j = 0, 1
    cell = matrix.cells.get((min(i, j), max(i, j)))
    page._on_cell(matrix.dimensions[i].label, matrix.dimensions[j].label, cell)
    assert "级别" in page.detail.text() and "来源" in page.detail.text()


def test_external_page_populates_after_loading_cases(casemodel):
    page = casemodel.pages["真实 case 核对"]
    assert casemodel.result.external is None
    assert page.summary_model.rowCount() == 0

    casemodel.cases_path = FC_REAL
    casemodel.load(str(FC))
    assert casemodel.result.external is not None
    assert page.summary_model.rowCount() == 7
    assert page.detail_model.rowCount() > 10

    casemodel.on_clear_cases()
    assert casemodel.result.external is None
    assert page.summary_model.rowCount() == 0


def test_report_matches_cli_sections(casemodel):
    """导出的报告复用 CLI 渲染器 —— 两处不该各说各话。"""
    from src.tools.casemodel_tools import text as T
    report = casemodel.render_report()
    assert "组织树" in report and "完备性评分" in report
    assert T.report(casemodel.result) in report


def test_broken_model_shows_banner_and_keeps_text(casemodel_empty, tmp_path):
    """坏模型不弹模态框，而是挂提示条 + 保留编辑器里的文本。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text("object: [1, 2]\ndimensions: []\n", encoding="utf-8")
    casemodel_empty.load(str(bad))
    assert "构不出模型" in casemodel_empty.banner.text()
    # 窗口没 show 时子控件 isVisible() 恒为 False，所以看 isHidden()（显式隐藏标志）
    assert not casemodel_empty.banner.isHidden()
    assert casemodel_empty.editor.get_text() == bad.read_text(encoding="utf-8")
    assert not casemodel_empty.editor.dirty


def test_missing_file_reports_error(casemodel_empty, tmp_path, monkeypatch):
    from src.workbench.modules.vms.casemodel import module as module_module
    calls = []
    monkeypatch.setattr(module_module.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: calls.append(a)))
    casemodel_empty.load(str(tmp_path / "nope.yaml"))
    assert calls
    assert "打开失败" in casemodel_empty.ctx.window.status_label.text()


def test_clearing_pages_when_text_is_empty(casemodel):
    assert casemodel.pages["Case 属性表"].model.rowCount() > 0
    casemodel.editor.editor.setPlainText("")
    casemodel.reanalyze()
    assert casemodel.result is None
    assert casemodel.pages["Case 属性表"].model.rowCount() == 0
    assert "空的" in casemodel.banner.text()


def test_actions_carry_the_usual_shortcuts(casemodel):
    """模块把 Ctrl+O / Ctrl+S / Ctrl+R 拿走 —— 清单那条链改用了别的键。

    两边都绑同一个键的话 Qt 会判定歧义，两个都不触发（表现为「按了没反应」），
    所以这条断言是防回归的。
    """
    shortcuts = {a.text(): a.shortcut().toString() for a in casemodel.create_actions()}
    assert shortcuts["打开模型…"] == "Ctrl+O"
    assert shortcuts["保存模型"] == "Ctrl+S"
    assert shortcuts["重新分析"] == "Ctrl+R"
