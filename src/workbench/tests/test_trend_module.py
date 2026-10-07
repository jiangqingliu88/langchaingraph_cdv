"""进度趋势模块。

用**真清单 + 真示例数据**（`config/trend/trend.yaml`）建模块，不打桩 —— 固定
「绑定 flow.trend 通、清单 input 解析对、run_trend 返回形状是界面吃得下的」。
两图一表分别断言：构建图拿 build 序列、收敛图拿 0–100% 序列、汇总表按阶段出行。

不建整窗口：本模块不依赖别的模块，也不需要平台布局。
"""
from __future__ import annotations

from pathlib import Path

import pytest

MODULE_ID = "flow.trend"


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


@pytest.fixture
def module(qt_app, settings):
    from .conftest import make_ctx
    from ..modules.flow.trend import TrendModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = TrendModule(ctx, spec)
    widget = mod.create_widget()
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


class TestManifestData:
    def test_loads_shipped_example(self, module):
        module.refresh()
        assert module.build_chart._series            # 构建面板有序列
        assert module.test_chart._series             # 收敛面板有序列
        assert module.summary_model.rowCount() == 8  # 八个阶段一行一条

    def test_build_panel_has_the_count_metrics(self, module):
        """横坐标是**回归阶段与动作**，所以一条线 = 一个量，不是一条线 = 一个阶段。"""
        module.refresh()
        ids = [s["id"] for s in module.build_chart._series]
        assert ids == ["builds", "cases", "loop"]

    def test_convergence_panel_covers_the_tiers(self, module):
        """百分比面板 = 各档通过率（loop 是迭代数，归到次数面板去）。"""
        module.refresh()
        ids = [s["id"] for s in module.test_chart._series]
        assert ids == ["base", "p0", "p1", "p2", "p3"]

    def test_convergence_panel_pins_y_axis_to_100(self, module):
        """百分比同轴 —— y 轴必须钉在 100，否则两条线的高低会被自动缩放骗了。"""
        module.refresh()
        assert module.test_chart._y_max == 100

    def test_build_panel_y_axis_is_auto(self, module):
        module.refresh()
        assert module.build_chart._y_max is None     # 自适应，不钉死

    def test_counts_label_reports_rounds_and_builds(self, module):
        module.refresh()
        text = module.count_label.text()
        assert "apb_uart" in text
        assert "4 轮" in text
        assert "13 次 build" in text

    def test_clean_data_has_no_warning(self, module):
        module.refresh()
        assert not module.banner.is_showing


class TestHoverDetail:
    def test_hover_updates_the_label(self, module):
        module.refresh()
        module._on_point("p0", 2, 83.3)
        assert "p0" in module.count_label.text()
        assert "第 2 轮" in module.count_label.text()


class TestMissingInput:
    def test_missing_file_is_loud_and_clears(self, qt_app, settings):
        from .conftest import make_ctx
        from ..modules.flow.trend import TrendModule

        spec, manifest, manifest_path = _shipped_spec()
        spec = spec.model_copy(update={"input": "trend/does_not_exist.yaml"})
        ctx = make_ctx(manifest, manifest_path, settings)
        mod = TrendModule(ctx, spec)
        widget = mod.create_widget()
        try:
            mod.refresh()
            assert not mod.build_chart._series
            assert not mod.test_chart._series
            assert mod.summary_model.rowCount() == 0
            assert mod.banner.is_showing          # 横幅起来了，不静默
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestChartWidget:
    """自绘组件的纯逻辑 —— 不依赖窗口。"""

    def test_set_series_drops_empty_series(self, qt_app):
        from ..ui.views.trend import TrendChart

        chart = TrendChart()
        try:
            chart.set_series([{"id": "empty", "title": "空", "points": []},
                              {"id": "ok", "title": "有", "points": [[1, 5]]}])
            assert [s["id"] for s in chart._series] == ["ok"]
            assert chart._rounds == [1]
        finally:
            chart.deleteLater()

    def test_series_are_colored_distinctly(self, qt_app):
        from ..ui.views.trend import SERIES_COLORS, TrendChart

        chart = TrendChart()
        try:
            chart.set_series([{"id": str(i), "title": str(i), "points": [[1, i]]}
                              for i in range(len(SERIES_COLORS))])
            colors = {s["color"].name() for s in chart._series}
            assert len(colors) == len(SERIES_COLORS)
        finally:
            chart.deleteLater()


class TestBinding:
    def test_binding_is_registered_and_pure(self):
        from ..bridge.catalog import by_name

        binding = by_name("flow.trend")
        assert binding is not None
        assert binding.kind == "json"
        assert binding.pure is True

    def test_input_resolves_under_config(self):
        spec, _manifest, manifest_path = _shipped_spec()
        resolved = (Path(manifest_path).parent / spec.input).resolve()
        assert resolved.exists(), resolved
        assert resolved.name == "trend.yaml"
