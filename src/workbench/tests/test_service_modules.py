"""工程服务入口的行为测试（不重跑流水线、不碰真实 EDA）。"""
from __future__ import annotations

import json
from pathlib import Path

from ..spec import ModuleSpec
from .conftest import make_ctx, STUB_MANIFEST
from ..manifest import load_manifest_text


def _spec(module_id: str, title: str) -> ModuleSpec:
    return ModuleSpec(id=module_id, title=title, group="debug",
                      factory="src.workbench.modules.service.uvm:UVMServiceModule")


def _ctx(qt_app, settings, tmp_path):
    manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
    return make_ctx(manifest, tmp_path / "workbench.yaml", settings)


def _write_run(root: Path) -> None:
    (root / "sim" / "coverage").mkdir(parents=True)
    (root / "coverage").mkdir(parents=True)
    (root / "sim" / "coverage" / "coverage_result.json").write_text(
        json.dumps({"functional_pct": 90.0}), encoding="utf-8")
    (root / "coverage" / "tp_matrix.json").write_text(json.dumps({"rows": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1", "status": "MISS"},
        {"tp_id": "TP-B", "coverpoint": "cp", "bin": "b2", "status": "HIT"},
    ]}), encoding="utf-8")


def test_uvm_service_warns_without_inputs(qt_app, settings, tmp_path):
    from ..modules.service.uvm import UVMServiceModule

    module = UVMServiceModule(_ctx(qt_app, settings, tmp_path), _spec("service.uvm", "UVM"))
    module.create_widget()
    module._start_run()
    assert module.banner is not None and module.banner.is_showing
    assert "至少" in module.banner.text()


def test_coverage_service_writes_closure_plan(qt_app, settings, tmp_path):
    from ..modules.service.coverage import CoverageClosureModule

    run = tmp_path / "output_demo"
    _write_run(run)
    module = CoverageClosureModule(
        _ctx(qt_app, settings, tmp_path), _spec("service.coverage", "Coverage"))
    module.create_widget()
    module._runs = [{"run_id": "output_demo", "dir": str(run)}]
    module.run_combo.addItem("output_demo", "output_demo")
    module._make_plan()
    assert (run / "closure" / "plan.json").is_file()
    assert "缺口" in module.summary.text()
    assert module.table.rowCount() == 1


def test_project_overview_renders_selected_run(qt_app, settings, tmp_path):
    from ..modules.service.project import ProjectOverviewModule

    run = tmp_path / "output_demo"
    _write_run(run)
    module = ProjectOverviewModule(
        _ctx(qt_app, settings, tmp_path), _spec("project.overview", "项目总览"))
    module.create_widget()
    module._runs = [{"run_id": "output_demo", "dir": str(run),
                     "final_coverage": 90.0, "target": 95.0,
                     "verdict": "PASS_WITH_CAVEAT", "signoff_status": "CONDITIONAL"}]
    module.run_combo.addItem("output_demo", "output_demo")
    module._run_changed(0)
    text = module.summary.text()
    assert "output_demo" in text and "90.0%" in text
    assert "PASS_WITH_CAVEAT" in text


SERVICE_MANIFEST = """
version: 1
window: {restore_layout: false}
groups:
  - {id: service, title: 工程服务, section: 客户工程}
modules:
  - {id: service.uvm, title: UVM, group: service,
     factory: src.workbench.modules.service.uvm:UVMServiceModule,
     params: {subscribe: [run.selected]}}
  - {id: service.regression, title: 回归, group: service,
     factory: src.workbench.modules.service.regression:RegressionServiceModule,
     params: {subscribe: [run.selected]}}
  - {id: service.coverage, title: Coverage, group: service,
     factory: src.workbench.modules.service.coverage:CoverageClosureModule,
     params: {subscribe: [run.selected]}}
  - {id: project.overview, title: 总览, group: service,
     factory: src.workbench.modules.service.project:ProjectOverviewModule,
     params: {subscribe: [run.selected]}}
"""


def test_service_entries_subscribe_to_run_selected(qt_app, settings, tmp_path):
    from .conftest import make_window
    from ..bus import TOPIC_RUN_SELECTED

    manifest = load_manifest_text(SERVICE_MANIFEST, source="<service>")
    ctx = make_ctx(manifest, tmp_path / "workbench.yaml", settings)
    window = make_window(qt_app, ctx)
    try:
        assert ctx.bus.subscribers(TOPIC_RUN_SELECTED) == 4
        ctx.bus.publish(TOPIC_RUN_SELECTED, "output_demo")
    finally:
        window.manager.mark_all_clean()
        window.close()
