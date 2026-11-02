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
