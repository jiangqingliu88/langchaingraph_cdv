"""功能覆盖率页 —— 「建模声明的覆盖点 → 实测命中了没有」。

三张表要能各自立住，而且**声明与实测必须分列**：把两者合成一个数字，就再也分不出
"该测的没测"（声明里有、压根没跑）和"测了的没打中"（跑了但 bin 没命中）——
那正是这一页存在的理由。所以这里重点钉住"没数据 ≠ 0%"。

另有一处容易错的：`run_fcov` 的测试点名单要跟**回归里跑的那份**同一分母
（`registry_bridge.case_rows`），模块名取模型的 `object` 而不是运行目录名。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

MODULE_ID = "flow.fcov"
NPU = (Path(__file__).resolve().parents[3] / "tests" / "fixtures"
       / "npu_sched")

#: 一份最小但完整的执行资产模型
CASEMODEL = """\
version: "1"
object: apb_uart
object_code: APBUART
sub_objects:
  - {id: OBJ-01, name: 寄存器读写, code: REG}
dimensions:
  - id: D_ADDR
    name: 地址
    fields:
      - name: paddr
        type: range
        min: 0
        max: 255
        boundary: ["0", "255"]
  - id: D_DIR
    name: 读写方向
    fields:
      - {name: pwrite, type: enum, values: [0, 1]}
themes:
  - {id: TH-P0, name: 功能, priority: P0, dimensions: [D_ADDR, D_DIR]}
"""

#: `vcover report -cvg -details` 的裁剪版 —— 只有 `COVERGROUP COVERAGE:` 那一段
CVG_TEXT = """\
COVERGROUP COVERAGE:
----------------------------------------------------------------------------------------------------------
 TYPE /npu_sched_env_pkg/npu_sched_env_coverage/cg_npu_sched
                                                       71.42%        100          -    Uncovered
    Coverpoint cp_queue_level                          66.66%        100          -    Uncovered
"""


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    return next(s for s in manifest.modules if s.id == MODULE_ID), manifest, manifest_path


@pytest.fixture
def run_dir(tmp_path):
    """一次 VPlan 运行的目录骨架（执行资产挂在 `inputs/vplan/`）。"""
    from src.ir_plane.vplan import (
        load_project, materialize_project_inputs)

    root = tmp_path / "output_test_20260101_000000"
    materialize_project_inputs(load_project(NPU), root)
    return root


def _module(qt_app, settings, run_id: str = ""):
    from .conftest import make_ctx
    from ..modules.flow.fcov import FunctionalCoverageModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = FunctionalCoverageModule(ctx, spec)
    widget = mod.create_widget()
    mod.run_id = run_id
    return mod, widget


@pytest.fixture
def module(qt_app, settings, run_dir):
    mod, widget = _module(qt_app, settings, run_id=run_dir.name)
    mod.load(run_id=run_dir.name)
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


def test_the_case_evidence_tab_exists(module):
    titles = [module.tabs.tabText(i) for i in range(module.tabs.count())]
    assert "Case 证据" in titles
    from PySide6.QtWidgets import QTabWidget

    page = module.tabs.widget(titles.index("Case 证据"))
    inner = page.findChild(QTabWidget)
    assert inner is not None
    sub = [inner.tabText(i) for i in range(inner.count())]
    assert "用例 × 证据层" in sub and "功能契约 × 证据层" in sub
    assert "功能组 × 路径" in sub and "缺口与豁免" in sub


def test_the_three_set_tabs_exist(module):
    """arch.md 的 Groups / SVA / SCB 三节 + Case×CELL + 执行证据。"""
    from PySide6.QtWidgets import QTabWidget

    titles = [module.tabs.tabText(i) for i in range(module.tabs.count())]
    page = module.tabs.widget(titles.index("Case 证据"))
    inner = page.findChild(QTabWidget)
    sub = [inner.tabText(i) for i in range(inner.count())]
    for title in ("Groups", "SVA", "SCB", "Case × CELL", "执行证据"):
        assert title in sub, title


def test_three_set_rows_flatten_from_case_view(module):
    """`case_view.cases[]` 的三集合 → 三张平表（行数与状态都要对）。"""
    cases = [{
        "case_id": "CASE-D_DEP",
        "groups_evidence": [{
            "group": "CG-D_DEP", "cell": "CELL-D_DEP-P1",
            "functional": {"status": "PROVEN"}, "timing": {"status": "NOT_APPLICABLE"},
            "data": {"status": "PROVEN"}, "path": {"status": "NOT_APPLICABLE"},
            "result": "PROVEN"}],
        "sva_items": [{"id": "SVA-X", "cell": "CELL-D_DEP-P1", "fail": 0,
                       "cover_property_hit": 3, "status": "PROVEN"}],
        "scb_items": [{"id": "SB-Y", "cell": "CELL-D_DEP-P1", "exec": 40,
                       "matched": 40, "mismatched": 0,
                       "evidence_level": "aggregate", "status": "PROVEN"}],
    }]
    module._fill_three_sets(cases)
    assert module.ce_groups_model.rowCount() == 1
    assert module.ce_sva_model.rowCount() == 1
    assert module.ce_scb_model.rowCount() == 1
    g = module.ce_groups_model.rows[0]
    assert (g["group"], g["functional"], g["result"]) == ("CG-D_DEP", "PROVEN", "PROVEN")
    assert module.ce_scb_model.rows[0]["evidence_level"] == "aggregate"


def test_cell_and_evd_tables_flatten(module):
    module._fill_cell_and_evd({
        "case_cell": {"rows": [{
            "cell_id": "CELL-D_DEP-P1", "cg": "CG-D_DEP", "p": "p1",
            "color": "green", "tp_count": 2,
            "declared_cases": ["CASE-D_DEP"], "observed_cases": ["CASE-D_DEP"]}]},
        "case_runs": [{
            "evd_id": "EVD-r-TST-X@1", "case_id": "CASE-D_DEP", "tst_id": "TST-X@1",
            "test": "x", "seed": 1, "stage": "p1",
            "cells": ["CELL-D_DEP-P1"], "legacy": False}],
    })
    assert module.ce_cell_model.rowCount() == 1
    assert module.ce_evd_model.rowCount() == 1
    assert module.ce_evd_model.rows[0]["legacy"] == "否"
    row = module.ce_cell_model.rows[0]
    assert row["cell_id"] == "CELL-D_DEP-P1"
    assert row["declared_cases"] == "CASE-D_DEP"


def test_tp_evidence_rows_flatten_the_four_layers(module):
    module._tp_evidence = {"tps": [{
        "tp_id": "TP-1", "domain": "attribute", "contract_status": "VERIFIED",
        "signed_off_by": "tp_a_seed_1@1",
        "evidence_layers": {k: {"status": "PROVEN"}
                            for k in ("functional", "timing", "data", "path")},
    }]}
    rows = module._tp_evidence_rows()
    assert rows[0]["functional"] == "PROVEN"
    assert rows[0]["timing"] == "PROVEN"
    assert rows[0]["data"] == "PROVEN"
    assert rows[0]["path"] == "PROVEN"
    assert rows[0]["contract_status"] == "VERIFIED"


#: 覆盖点表里「实测 %」那一列的下标（与 `COVERPOINT_COLUMNS` 的顺序同源）
ACTUAL_COL = 7


def _fg(model, row: int, col: int):
    """某格的前景色 —— 弱化就是往这里塞了 muted 色（与跟踪表测试同一套读法）。"""
    from PySide6.QtCore import Qt

    return model.data(model.index(row, col), Qt.ItemDataRole.ForegroundRole)


class TestCoverpointTable:
    def test_one_row_per_declared_coverpoint(self, module):
        assert module.cp_model.rowCount() == 19         # 12 覆盖点 + 7 交叉

    def test_bin_count_comes_from_the_model_declaration(self, module):
        rows = {r["signal"]: r for r in module._coverpoints}
        assert rows["queue_level"]["bin_count"] == 6
        assert rows["instr_type"]["bin_count"] == 4

    def test_no_measurement_yet_leaves_the_cell_blank_not_zero(self, module):
        """**没测到 ≠ 0%**。写 0 会让人去查一个不存在的覆盖率问题。"""
        assert all(r["measured"] is False for r in module._coverpoints)
        assert all(r["actual"] == "" for r in module._coverpoints)

    def test_unmeasured_cells_are_muted(self, module):
        """标灰 —— "还没有数据"和"这一格没内容"要看得出区别。"""
        muted = [_fg(module.cp_model, r, ACTUAL_COL)
                 for r in range(module.cp_model.rowCount())]
        assert all(c is not None for c in muted), "未测量的那一列应当弱化"


class TestMeasurementJoinsTheDeclaration:
    def test_measured_percentage_lands_on_the_matching_coverpoint(self, run_dir, qt_app,
                                                                 settings):
        reps = run_dir / "sim" / "coverage" / "reports"
        reps.mkdir(parents=True)
        (reps / "coverage_cvg.txt").write_text(CVG_TEXT, encoding="utf-8")
        mod, widget = _module(qt_app, settings, run_id=run_dir.name)
        try:
            mod.load(run_id=run_dir.name)
            rows = {r["signal"]: r for r in mod._coverpoints}
            # 实测里 coverpoint 叫 `cp_queue_level`，声明里叫 `queue_level`
            assert rows["queue_level"]["measured"] is True
            assert rows["queue_level"]["actual"] == 66.66
            assert rows["instr_type"]["measured"] is False  # 实测里没有它
        finally:
            widget.deleteLater()


class TestTestpointTable:
    def test_testpoints_come_from_the_same_denominator_as_the_regression(self, module):
        """`registry_bridge.case_rows` 摊出来的名字 —— 与回归里跑的那份同一分母。"""
        names = [r["name"] for r in module.tp_model.rows]
        assert len(names) == 70
        assert names[0] == "npu_sched_env_d_queue_p0_test"
        assert "npu_sched_env_d_type_pVECTOR_test" in names

    def test_the_module_name_is_the_models_object_not_the_run_dir(self, module):
        """用运行目录名会得到 `output_test_20260101_000000_D_ADDR_0` —— 噪音。"""
        assert all(not r["name"].startswith("output_test") for r in module.tp_model.rows)

    def test_each_row_carries_its_coverage_bin(self, module):
        rows = {r["name"]: r for r in module.tp_model.rows}
        assert rows["npu_sched_env_d_queue_p0_test"]["coverage_bin"] == "empty"


class TestAssetTable:
    def test_the_chain_files_are_listed(self, module):
        paths = {a["path"] for a in module.asset_model.rows}
        assert {"inputs/vplan/data/execution_meta.csv",
                "coverage/coverage_points.json",
                "inputs/yaml/uvm/env_cov_bins.yaml",
                "sim/coverage/reports/coverage_cvg.txt"} <= paths

    def test_a_missing_file_is_still_a_row(self, module):
        """"还没生成"是有用的信息 —— 照列，标 `exists: false`。"""
        rows = {a["path"]: a for a in module.asset_model.rows}
        assert rows["coverage/coverage_points.json"]["exists"] is False
        assert rows["inputs/vplan/data/execution_meta.csv"]["exists"] is True


class TestDegradesHonestly:
    def test_no_run_selected_says_so(self, qt_app, settings):
        mod, widget = _module(qt_app, settings)
        try:
            mod.load("")
            assert mod.cp_model.rowCount() == 0
        finally:
            widget.deleteLater()

    def test_no_case_model_is_stated_not_silently_empty(self, tmp_path, qt_app, settings):
        """没有模型就说没有 —— 一张空表看不出是"没选运行"还是"没建模型"。"""
        root = tmp_path / "output_nomod_20260101_000000"
        root.mkdir(parents=True)
        mod, widget = _module(qt_app, settings, run_id=root.name)
        try:
            mod.load(root.name)
            assert mod.cp_model.rowCount() == 0
            assert "VPlan" in mod.notes_label.text()
        finally:
            widget.deleteLater()

    def test_old_format_coverage_text_is_labelled_old_not_missing(self, run_dir,
                                                                  qt_app, settings):
        """实测文本在、但里面没有逐 covergroup 的段 —— 说"旧格式"，别说"文件不在"。

        不然人会对着一个明明存在的文件去找"为什么说它不在"。
        """
        reps = run_dir / "sim" / "coverage" / "reports"
        reps.mkdir(parents=True)
        (reps / "coverage_cvg.txt").write_text(
            "Covergroups  3 na na 34.24%\n", encoding="utf-8")
        mod, widget = _module(qt_app, settings, run_id=run_dir.name)
        try:
            mod.load(run_dir.name)
            note = mod.notes_label.text()
            assert "旧格式" in note and "还没有实测" not in note
        finally:
            widget.deleteLater()


class TestTraceability:
    """编号那一对 —— 「哪条需求被谁验了」要能一眼串起来。

    生成器派生的 `cp_<信号>` 是给编译器的；文档里引用的是 `CP_NPU_xxx`。
    拿后者跟人对账才是日常动作，所以两列都得在表上。
    """

    def test_ids_are_on_the_coverpoint_table(self, module):
        from ..modules.flow.fcov.module import COVERPOINT_COLUMNS

        names = [c[0] for c in COVERPOINT_COLUMNS]
        assert "cover_id" in names and "requirement" in names

    def test_coverpoints_carry_document_ids(self, module):
        """VPlan 的覆盖点带文档编号（`CP_NPU_*`），不是只有派生信号名。"""
        ids = [r["cover_id"] for r in module._coverpoints if r["cover_id"]]
        assert "CP_NPU_QUEUE_001" in ids


class TestTheNpuModelEndToEnd:
    """把 NPU 那份模型喂进这一页 —— 12 个覆盖点 / 7 条交叉都要在表上。"""

    @pytest.fixture
    def npu_run(self, tmp_path):
        from pathlib import Path

        from src.ir_plane.vplan import (
            load_project, materialize_project_inputs)

        root = tmp_path / "output_npu_20260101_000000"
        project = (Path(__file__).resolve().parents[3] / "tests" / "fixtures"
              / "npu_sched")
        materialize_project_inputs(load_project(project), root)
        return root

    def test_twelve_coverpoints_and_seven_crosses_land(self, npu_run, qt_app, settings):
        mod, widget = _module(qt_app, settings, run_id=npu_run.name)
        try:
            mod.load(npu_run.name)
            assert mod.cp_model.rowCount() == 19        # 12 个覆盖点 + 7 条交叉
            ids = [r["cover_id"] for r in mod.cp_model.rows if r["cover_id"]]
            assert len(ids) == 12
            assert "CP_NPU_QUEUE_001" in ids
            reqs = {r["requirement"] for r in mod.cp_model.rows if r["requirement"]}
            assert "REQ-NPU-008" in reqs
        finally:
            widget.deleteLater()


class TestBatchesAndTraceability:
    """批次 / 种子与需求追溯两张表 —— 「打算怎么测够」与「哪条需求被谁验了」。

    它们和覆盖点表**同源**（都从 case 模型派生、落在一份计划里），分开摆是因为
    读者不同：覆盖点表给"生成 covergroup 的人"，这两张给"回归"和"签核的人"。
    """

    NPU = (Path(__file__).resolve().parents[3]
           / "tests" / "fixtures" / "npu_sched")

    @pytest.fixture
    def npu_run(self, tmp_path):
        from src.ir_plane.vplan import engine

        root = tmp_path / "output_npu_20260101_000000"
        (root / "inputs").mkdir(parents=True)
        (root / "coverage").mkdir(parents=True)
        plan = engine.run_coverage_plan(
            engine.load_project_from(self.NPU), "npu_sched")
        (root / "coverage" / "coverage_plan.yaml").write_text(
            plan["plan_yaml"], encoding="utf-8")
        return root

    def _load(self, npu_run, qt_app, settings):
        mod, widget = _module(qt_app, settings, run_id=npu_run.name)
        mod.load(npu_run.name)
        return mod, widget

    def test_the_batch_table_carries_the_seed_management(self, npu_run, qt_app, settings):
        mod, widget = self._load(npu_run, qt_app, settings)
        try:
            rows = {r["theme"]: r for r in mod.batch_model.rows}
            assert len(rows) == 12
            b = rows["TH-TC_CMDSCHED_BASIC_001"]
            assert b["test"] == "cmdsched_basic_test"
            assert (b["base"], b["count"], b["explore"]) == (1100, 1, 0)
            assert b["total_runs"] == 1
        finally:
            widget.deleteLater()

    def test_the_trace_table_links_requirement_to_coverpoint_and_cross(
            self, npu_run, qt_app, settings):
        mod, widget = self._load(npu_run, qt_app, settings)
        try:
            rows = {r["requirement"]: r for r in mod.trace_model.rows}
            assert len(rows) == 12
            r = rows["REQ-NPU-001"]
            assert r["coverpoints"] == "CP_NPU_QUEUE_001"
            assert r["crosses"] == "X_NPU_LEVEL_DEC_004"
            assert r["covered"] is True
        finally:
            widget.deleteLater()

    def test_an_orphan_requirement_is_not_marked_covered(self, npu_run, qt_app, settings):
        """§9.1 的「无孤立需求」看的就是这个标记 —— 不能一律 True。"""
        # 把覆盖点与交叉上的 requirement 都摘掉，只留一条没人认领的
        import yaml

        plan_path = npu_run / "coverage" / "coverage_plan.yaml"
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        plan["traceability"].append({"requirement": "REQ-GHOST", "coverpoints": [],
                                     "crosses": [], "batches": []})
        plan_path.write_text(yaml.safe_dump(plan, allow_unicode=True), encoding="utf-8")

        mod, widget = self._load(npu_run, qt_app, settings)
        try:
            ghost = next(r for r in mod.trace_model.rows
                         if r["requirement"] == "REQ-GHOST")
            assert ghost["covered"] is False
            row = [i for i, r in enumerate(mod.trace_model.rows)
                   if r["requirement"] == "REQ-GHOST"][0]
            from PySide6.QtCore import Qt
            assert mod.trace_model.data(mod.trace_model.index(row, 0),
                                        Qt.ItemDataRole.ForegroundRole) is not None
        finally:
            widget.deleteLater()
