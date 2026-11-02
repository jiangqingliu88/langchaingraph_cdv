"""IP 团队三个页面 —— 用真清单 + 真示例工程**建一次 widget**。

回归点：`ip.workspace` 曾在 `_show_status` 里引用了一个不在作用域的 `ip_id`，
页面在 `build_content()` 阶段就 `NameError`，界面上报"模块加载失败"。
工具函数单测覆盖不到这条路 —— 页面构建本身要有测试。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "examples" / "open_npu_soc"


@pytest.fixture
def ip_root(monkeypatch):
    """把"工程根"钉到仓库里的示例工程（autouse 的 cwd 隔离会把它藏起来）。"""
    from src.workbench.modules.ip import common as ip_common

    monkeypatch.setattr(ip_common, "find_project_root", lambda: ROOT)
    return ROOT


def _build(module_id: str, qt_app, settings):
    from .conftest import make_ctx, shipped_manifest

    from ..loader import resolve

    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == module_id)
    ctx = make_ctx(manifest, manifest_path, settings)
    module_cls = resolve(spec.factory)
    module = module_cls(ctx, spec)
    widget = module.create_widget()
    return module, widget, qt_app


class TestIpWorkspace:
    def test_builds_with_the_real_project(self, qt_app, settings, ip_root):
        module, widget, app = _build("ip.workspace", qt_app, settings)
        try:
            assert module.combo.count() == 5           # 示例工程 5 个 IP
            assert module.table.rowCount() >= 1         # 选中 IP 的 RTL 清单
            assert "发布包" in module.release.text()     # 没有包时如实说"未生成"
        finally:
            widget.deleteLater()
            app.processEvents()


class TestIpSignoff:
    def test_builds_and_reports_release_state(self, qt_app, settings, ip_root):
        module, widget, app = _build("ip.signoff", qt_app, settings)
        try:
            assert module.combo.count() == 5
            assert "发布包" in module.release.text()
        finally:
            widget.deleteLater()
            app.processEvents()


class TestIpCatalog:
    def test_builds_with_one_row_per_ip(self, qt_app, settings, ip_root):
        module, widget, app = _build("ip.catalog", qt_app, settings)
        try:
            assert module.table.rowCount() == 5
        finally:
            widget.deleteLater()
            app.processEvents()
