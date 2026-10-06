"""测试点 / 验证资产 跟踪表模块。

用**真清单 + 真示例数据**（`config/tracking/tracking.yaml`）建模块，不打桩 ——
这条路径同时固定了三件事：绑定 `flow.tracking` 通、清单的 `input` 解析对、
`run_tracking` 的返回形状是界面真正吃得下的那种。

不建整窗口：本模块不依赖别的模块，也不需要平台布局（`run_tool` 经 ctx 走，
横幅在 `create_widget` 里就有了）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

MODULE_ID = "flow.tracking"
#: 示例数据里第一条测试点引用的资产 —— 联动断言用
FIRST_TP_ID = "apb_uart_TP_001"
FIRST_TP_ASSET = "apb_uart_rtl"


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


def _row_color(model, row: int):
    """某一行第一列的前景色 —— 高亮就是往这里塞了 accent 色。"""
    return model.data(model.index(row, 0), Qt.ItemDataRole.ForegroundRole)


def _row_index_of(model, row_key: str, value: str) -> int:
    for i, row in enumerate(model.rows):
        if str(row.get(row_key, "")) == value:
            return i
    raise AssertionError(f"没找到 {row_key}={value}")


@pytest.fixture
def module(qt_app, settings):
    from .conftest import make_ctx
    from ..modules.flow.tracking import TrackingModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = TrackingModule(ctx, spec)
    widget = mod.create_widget()
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


class TestManifestData:
    def test_loads_shipped_example(self, module):
        module.refresh()
        assert module.tp_model.rowCount() > 0
        assert module.asset_model.rowCount() > 0

    def test_counts_are_reported(self, module):
        module.refresh()
        text = module.count_label.text()
        assert "apb_uart" in text
        assert f"{module.tp_model.rowCount()} 个测试点" in text

    def test_clean_data_has_no_dangling_warning(self, module):
        """示例数据资产引用都对得上 —— 不该冒出悬空提示。"""
        module.refresh()
        assert "对不上" not in module.count_label.text()


class TestMissingInput:
    def test_missing_file_is_loud_and_clears_tables(self, qt_app, settings):
        from .conftest import make_ctx
        from ..modules.flow.tracking import TrackingModule

        spec, manifest, manifest_path = _shipped_spec()
        spec = spec.model_copy(update={"input": "tracking/does_not_exist.yaml"})
        ctx = make_ctx(manifest, manifest_path, settings)
        mod = TrackingModule(ctx, spec)
        widget = mod.create_widget()
        try:
            mod.refresh()
            assert mod.tp_model.rowCount() == 0
            assert mod.asset_model.rowCount() == 0
            assert mod.banner.is_showing          # 横幅起来了，不静默
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestCrossTableHighlight:
    def _select(self, table, row: int) -> None:
        table.setCurrentIndex(table.model().index(row, 0))

    def test_selecting_testpoint_highlights_its_assets(self, module):
        module.refresh()
        tp_row = _row_index_of(module.tp_model, "id", FIRST_TP_ID)
        refs = set(module.tp_model.rows[tp_row]["asset_refs"])
        self._select(module.tp_table, tp_row)

        # 高亮的恰好是这条测试点引用的那几行，不多不少
        highlighted = {str(row["id"]) for i, row in enumerate(module.asset_model.rows)
                       if _row_color(module.asset_model, i) is not None}
        assert highlighted == refs

    def test_selecting_asset_highlights_referencing_testpoints(self, module):
        module.refresh()
        asset_row = _row_index_of(module.asset_model, "id", FIRST_TP_ASSET)
        linked = set(module.asset_model.rows[asset_row]["testpoint_refs"])
        self._select(module.asset_table, asset_row)

        highlighted = {str(row["id"]) for i, row in enumerate(module.tp_model.rows)
                       if _row_color(module.tp_model, i) is not None}
        assert highlighted == linked

    def test_refresh_clears_highlight(self, module):
        module.refresh()
        self._select(module.tp_table, 0)
        module.refresh()
        assert all(_row_color(module.asset_model, i) is None
                   for i in range(module.asset_model.rowCount()))


class TestBinding:
    def test_binding_is_registered_and_pure(self):
        """flow.tracking 是纯读绑定 —— 切标签页不该弹确认。"""
        from ..bridge.catalog import by_name

        binding = by_name("flow.tracking")
        assert binding is not None
        assert binding.kind == "json"
        assert binding.pure is True

    def test_input_resolves_under_config(self):
        """`input: tracking/tracking.yaml` 相对**清单目录**解析，不是 CWD。"""
        spec, _manifest, manifest_path = _shipped_spec()
        resolved = (Path(manifest_path).parent / spec.input).resolve()
        assert resolved.exists(), resolved
        assert resolved.name == "tracking.yaml"
