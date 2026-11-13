"""VPlan 项目页 —— GUI 读的是 VPlan 产物，不是 case 模型。"""
from __future__ import annotations

from pathlib import Path

from .conftest import make_ctx, shipped_manifest

# GUI 测试用冻结项目源；活项目由 front 从裸 spec bootstrap，内容不固定。
ROOT = (Path(__file__).resolve().parents[3] / "tests" / "fixtures"
        / "npu_sched")


def _build(qt_app, settings):
    from ..loader import resolve

    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == "verify.vplan")
    ctx = make_ctx(manifest, manifest_path, settings)
    module = resolve(spec.factory)(ctx, spec)
    widget = module.create_widget()
    return module, widget


def test_reads_the_shipped_vplan_project(qt_app, settings):
    module, widget = _build(qt_app, settings)
    try:
        # 活项目是可 bootstrap 的裸 spec；GUI 断言钉冻结项目源。
        module.project_edit.setText(str(ROOT))
        module._load_project()
        text = module.summary.text()
        assert "npu_sched" in text
        assert "DUT=CMDSCHED" in text
        assert module.status_table.rowCount() == 3      # 契约 / TP / case
        first = module.status_table.item(0, 0).text()
        assert first == "契约"
        assert "PLAN_ONLY" in module.notes.text()
    finally:
        widget.deleteLater()


def test_run_artifacts_come_from_the_selected_run(qt_app, settings, tmp_path):
    from src.ir.vplan import (
        load_project, run_artifacts, write_plan_only_run)

    root = tmp_path / "output_vplan_gui"
    write_plan_only_run(load_project(ROOT), root)
    module, widget = _build(qt_app, settings)
    try:
        module._fill_run(run_artifacts(root))
        rows = {module.artifact_table.item(r, 0).text():
                module.artifact_table.item(r, 2).text()
                for r in range(module.artifact_table.rowCount())}
        assert rows["测试点 IR"] == "✓"
        assert rows["契约清单"] == "✓"
    finally:
        widget.deleteLater()
