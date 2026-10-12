"""功能覆盖率页 —— 「建模声明的覆盖点 → 实测命中了没有」。

三张表要能各自立住，而且**声明与实测必须分列**：把两者合成一个数字，就再也分不出
"该测的没测"（声明里有、压根没跑）和"测了的没打中"（跑了但 bin 没命中）——
那正是这一页存在的理由。所以这里重点钉住"没数据 ≠ 0%"。

另有一处容易错的：`run_fcov` 的测试点名单要跟**回归里跑的那份**同一分母
（`registry_bridge.case_rows`），模块名取模型的 `object` 而不是运行目录名。
"""
from __future__ import annotations

import json

import pytest

MODULE_ID = "flow.fcov"

#: 一份最小但完整的 case 模型（跟 `front._draft_casemodel` 的草稿同形）
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
 TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_apb
                                                       71.42%        100          -    Uncovered
    Coverpoint cp_paddr                                66.66%        100          -    Uncovered
"""


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    return next(s for s in manifest.modules if s.id == MODULE_ID), manifest, manifest_path


@pytest.fixture
def run_dir(tmp_path):
    """一次运行的目录骨架 —— 造的是"前缀式"那一支（与产物审查台同一套反解）。"""
    root = tmp_path / "output_test_20260101_000000"
    (root / "inputs").mkdir(parents=True)
    (root / "inputs" / "casemodel.yaml").write_text(CASEMODEL, encoding="utf-8")
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


#: 覆盖点表里「实测 %」那一列的下标（与 `COVERPOINT_COLUMNS` 的顺序同源）
ACTUAL_COL = 7


def _fg(model, row: int, col: int):
    """某格的前景色 —— 弱化就是往这里塞了 muted 色（与跟踪表测试同一套读法）。"""
    from PySide6.QtCore import Qt

    return model.data(model.index(row, col), Qt.ItemDataRole.ForegroundRole)


class TestCoverpointTable:
    def test_one_row_per_declared_coverpoint(self, module):
        assert module.cp_model.rowCount() == 2          # paddr + pwrite

    def test_bin_count_comes_from_the_model_declaration(self, module):
        rows = {r["signal"]: r for r in module._coverpoints}
        assert rows["paddr"]["bin_count"] == 2          # 边界 0 / 255
        assert rows["pwrite"]["bin_count"] == 2         # 枚举 0 / 1

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
            # 实测里 coverpoint 叫 `cp_paddr`，声明里叫 `paddr` —— 要能对上
            assert rows["paddr"]["measured"] is True
            assert rows["paddr"]["actual"] == 66.66
            assert rows["pwrite"]["measured"] is False      # 实测里没有它
        finally:
            widget.deleteLater()


class TestTestpointTable:
    def test_testpoints_come_from_the_same_denominator_as_the_regression(self, module):
        """`registry_bridge.case_rows` 摊出来的名字 —— 与回归里跑的那份同一分母。"""
        names = [r["name"] for r in module.tp_model.rows]
        assert names == ["apb_uart_D_ADDR_0", "apb_uart_D_ADDR_255",
                         "apb_uart_D_DIR_0", "apb_uart_D_DIR_1"]

    def test_the_module_name_is_the_models_object_not_the_run_dir(self, module):
        """用运行目录名会得到 `output_test_20260101_000000_D_ADDR_0` —— 噪音。"""
        assert all(not r["name"].startswith("output_test") for r in module.tp_model.rows)

    def test_each_row_carries_its_coverage_bin(self, module):
        rows = {r["name"]: r for r in module.tp_model.rows}
        assert rows["apb_uart_D_ADDR_0"]["coverage_bin"] == "D_ADDR.paddr[0]"


class TestAssetTable:
    def test_the_chain_files_are_listed(self, module):
        paths = {a["path"] for a in module.asset_model.rows}
        assert {"inputs/casemodel.yaml", "coverage/coverage_points.json",
                "inputs/yaml/uvm/env_cov_bins.yaml",
                "sim/coverage/reports/coverage_cvg.txt"} <= paths

    def test_a_missing_file_is_still_a_row(self, module):
        """"还没生成"是有用的信息 —— 照列，标 `exists: false`。"""
        rows = {a["path"]: a for a in module.asset_model.rows}
        assert rows["coverage/coverage_points.json"]["exists"] is False
        assert rows["inputs/casemodel.yaml"]["exists"] is True


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
            assert "case 模型" in mod.notes_label.text()
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

    def test_a_model_without_ids_leaves_the_cells_empty(self, module):
        """没有编号就是空 —— **不编一个出来**（编了就看不出"这份模型没写编号"）。"""
        assert all(r["cover_id"] == "" for r in module._coverpoints)


class TestTheNpuModelEndToEnd:
    """把 NPU 那份模型喂进这一页 —— 12 个覆盖点 / 7 条交叉都要在表上。"""

    @pytest.fixture
    def npu_run(self, tmp_path):
        import shutil
        from pathlib import Path

        root = tmp_path / "output_npu_20260101_000000"
        (root / "inputs").mkdir(parents=True)
        shutil.copy(Path(__file__).resolve().parents[3]
                    / "specs" / "npu_sched" / "casemodel.yaml",
                    root / "inputs" / "casemodel.yaml")
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
