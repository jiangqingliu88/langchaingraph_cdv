"""测试点表（xlsx）页 —— 真示例表 + 真绑定，建一次 widget。

方案 B 的"该测什么"侧是只读视图：页面不写盘，也不复制导入逻辑。
"""
from __future__ import annotations

MODULE_ID = "ide.aivm"


def _build(qt_app, settings):
    from .conftest import make_ctx, shipped_manifest

    from ..loader import resolve

    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    ctx = make_ctx(manifest, manifest_path, settings)
    module = resolve(spec.factory)(ctx, spec)
    widget = module.create_widget()
    return module, widget, qt_app


def test_builds_with_the_shipped_example_table(qt_app, settings):
    module, widget, app = _build(qt_app, settings)
    try:
        assert module.path_edit.text().endswith(".xlsx")
        assert module.table.rowCount() == 64
        assert "64 个 TP" in module.summary.text()
    finally:
        widget.deleteLater()
        app.processEvents()


def test_headers_follow_the_xlsx_headtitle(qt_app, settings):
    """GUI 的列名 = 源 xlsx 的表头（第 2 行 + 第 3 行释义），不是 GUI 自己一套。"""
    module, widget, app = _build(qt_app, settings)
    try:
        headers = [module.table.horizontalHeaderItem(i).text()
                   for i in range(module.table.columnCount())]
        assert [h.split("·")[0] for h in headers] == [
            "序号", "Feature 提取", "Sub_Feature（可选）",
            "Sub_Sub_Feature（可选）", "Sub_Sub_Feature（可选）",
            "TestName", "TestNum", "Doc Section", "章节",
        ]
        # D/E 在源表同名，靠第 3 行的三级/四级区分
        assert headers[3].endswith("三级分类")
        assert headers[4].endswith("四级分类")
        # 第一行的 A/B 列是源表原文（TP id + feature 提取）
        assert module.table.item(0, 0).text().startswith("NPU_V2-CMDSCHED-")
        assert module.table.item(0, 1).text().strip()
    finally:
        widget.deleteLater()
        app.processEvents()


def test_missing_input_is_reported_not_crashed(qt_app, settings):
    module, widget, app = _build(qt_app, settings)
    try:
        module.path_edit.setText("")
        module.refresh()
        assert "先选择" in module.summary.text()
        assert module.table.rowCount() == 0
    finally:
        widget.deleteLater()
        app.processEvents()
