"""AIVM → casemodel 导入桥（方案 B）。

用合成的 IF02 形状做金样：4 个二维组合格 → 4 个 cross bin；配置枚举与定向
用例各走自己的通道；绑不上/三维的格子必须进 dropped，不能静默消失。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.tools.generation.casemodel_tools.api import run_validate
from src.tools.humanview.aivm_ir.bridge import (
    AivmImportError, bind_cells, import_ontology, to_casemodel, verify_import,
)
from src.tools.humanview.aivm_ir.ir_core import (
    Category, CoverageCell, Dimension, DimensionValue, Ontology, Provenance,
    TestPointIR,
)


def _tp(tp_id, feature, dims, cells, *, category=Category.IF, test_name=None,
        test_num=0, directed=False, coverage_driven=True):
    return TestPointIR(
        tp_id=tp_id, orig_id=tp_id, feature_text=feature, category=category,
        dimensions=dims, coverage_cells=cells, test_name=test_name,
        test_num=test_num, directed=directed, coverage_driven=coverage_driven,
        provenance=Provenance(doc_section="L5-[NPU]-[CDD]", chapter="ref 3.2"),
    )


def _ontology():
    s_dim = Dimension("start_order", "start 顺序", None, [
        DimensionValue("s0_first", "start_id0 先于start_id1", 9),
        DimensionValue("s1_first", "start_id0 后于start_id1", 9),
    ])
    d_dim = Dimension("done_order", "done 顺序", None, [
        DimensionValue("d0_first", "done_id0先于done_id1", 9),
        DimensionValue("d1_first", "done_id0后于done_id1", 9),
    ])
    cells = [
        CoverageCell("IF02#r9", "start_id0 先于start_id1,done_id0先于done_id1", 9),
        CoverageCell("IF02#r10", "start_id0 后于start_id1,done_id0后于done_id1", 10),
        CoverageCell("IF02#r11", "start_id0 先于start_id1,done_id0后于done_id1", 11),
        CoverageCell("IF02#r12", "start_id0 后于start_id1,done_id0先于done_id1", 12),
    ]
    from src.tools.humanview.aivm_ir.ir_core import CellType
    for cell in cells:
        cell.cell_type = CellType.CONSTRAINT_COMBO

    cfg = TestPointIR(
        tp_id="C02", orig_id="C02", feature_text="tile 模式", category=Category.C,
        coverage_cells=[
            CoverageCell("C02#r3", "13'b0_0000_0000_0001", 3),
            CoverageCell("C02#r4", "13'b0_0000_0000_0010", 4),
        ],
        test_num=0, coverage_driven=True, directed=False,
    )
    from src.tools.humanview.aivm_ir.ir_core import CellType
    for cell in cfg.coverage_cells:
        cell.cell_type = CellType.CONFIG_ENUM

    direct = TestPointIR(
        tp_id="F21", orig_id="F21", feature_text="glsu 定向", category=Category.F,
        coverage_cells=[CoverageCell("F21#r7", "glsu_cfg_drv_base", 7)],
        test_name="glsu_cfg_drv_base", test_num=1, directed=True,
        coverage_driven=False,
    )
    for cell in direct.coverage_cells:
        cell.cell_type = CellType.DIRECTED_CASE

    return Ontology(version="t", testpoints=[
        _tp("IF02", "start/done 顺序", [s_dim, d_dim], cells), cfg, direct])


class TestBind:
    def test_binds_each_cell_to_its_two_dimensions(self):
        stats = bind_cells(_ontology())
        assert stats["cells"] == 4 and stats["bound"] == 4
        assert stats["unbound"] == 0

    def test_unbound_cell_is_reported_not_dropped_silently(self):
        onto = _ontology()
        onto.testpoints[0].coverage_cells.append(
            CoverageCell("IF02#r99", "完全无关的文字", 99))
        onto.testpoints[0].coverage_cells[-1].cell_type = \
            onto.testpoints[0].coverage_cells[0].cell_type
        stats = bind_cells(onto)
        assert stats["unbound"] == 1


class TestToCasemodel:
    def _build(self):
        onto = _ontology()
        bind_cells(onto)
        return to_casemodel(onto, module_name="npu_cmdsched")

    def test_four_combo_cells_become_four_cross_bins(self):
        model, source_map = self._build()
        cross = model["cross_matrix"]
        assert len(cross) == 1
        decl = next(iter(cross.values()))
        assert [b["name"] for b in decl["bins"]] == ["r9", "r10", "r11", "r12"]
        cross_bins = [v for v in source_map["bins"].values() if v["kind"] == "cross"]
        assert len(cross_bins) == 4

    def test_generated_model_passes_schema(self):
        model, _ = self._build()
        text = yaml.safe_dump(model, allow_unicode=True, sort_keys=False)
        errors = [i for i in (run_validate(text).get("issues") or [])
                  if i.get("severity") == "error"]
        assert errors == [], errors

    def test_config_enum_and_directed_get_their_own_dimensions(self):
        model, source_map = self._build()
        ids = {d["id"] for d in model["dimensions"]}
        assert any(i.endswith("_cfg") for i in ids)
        assert any(i.endswith("_case") for i in ids)
        kinds = {v["kind"] for v in source_map["bins"].values()}
        assert {"cross", "config_enum", "directed_case"} <= kinds

    def test_three_way_cell_is_dropped_with_reason(self):
        onto = _ontology()
        third = Dimension("mode", "模式", None,
                          [DimensionValue("fast", "fast_mode", 13)])
        onto.testpoints[0].dimensions.append(third)
        cell = onto.testpoints[0].coverage_cells[0]
        cell.raw_text += ",fast_mode"
        bind_cells(onto)
        _, source_map = to_casemodel(onto, module_name="m")
        assert any(d["reason"] == "n_way_unsupported" for d in source_map["dropped"])


class TestImportFiles:
    def test_writes_files_and_detects_drift(self, tmp_path):
        xlsx = tmp_path / "t.xlsx"
        xlsx.write_bytes(b"fake-xlsx")
        result = import_ontology(_ontology(), tmp_path / "out",
                                 module_name="npu_cmdsched", source_path=xlsx)
        assert Path(result["casemodel"]).is_file()
        assert Path(result["source_map"]).is_file()
        assert result["bins"] == 7          # 4 cross + 2 cfg + 1 directed

        ok = verify_import(xlsx, result["casemodel"], result["source_map"])
        assert ok["ok"] is True

        xlsx.write_bytes(b"changed")
        drift = verify_import(xlsx, result["casemodel"], result["source_map"])
        assert drift["ok"] is False
        assert any(i["check"] == "xlsx_changed" for i in drift["issues"])

    def test_invalid_generated_model_is_refused(self, tmp_path):
        onto = _ontology()
        onto.testpoints[0].feature_text = ""      # theme.name 会变空 → schema error
        onto.testpoints[0].orig_id = ""
        with __import__("pytest").raises(AivmImportError):
            import_ontology(onto, tmp_path / "out", module_name="m")


def test_dimensionless_tp_falls_back_to_scenario_bins():
    """真实 xlsx loader 不建维度 —— 退化成场景维度，但绝不冒充交叉覆盖。"""
    from src.tools.humanview.aivm_ir.ir_core import CellType

    cells = [CoverageCell("IF#r1", "valid先于ready", 1),
             CoverageCell("IF#r2", "ready先于valid", 2)]
    for cell in cells:
        cell.cell_type = CellType.CONSTRAINT_COMBO
    onto = Ontology(version="t", testpoints=[
        _tp("IF01", "valid/ready", [], cells)])
    stats = bind_cells(onto)
    assert stats["unbound"] == 2
    model, source_map = to_casemodel(onto, module_name="m")
    assert any(d["id"].endswith("_scenario") for d in model["dimensions"])
    kinds = [v["kind"] for v in source_map["bins"].values()]
    assert kinds == ["scenario", "scenario"]
    assert "cross_matrix" not in model


def test_cli_import_and_verify_on_example(tmp_path):
    """端到端：CLI 导入真实示例表 → schema 通过 → 双哈希校验。"""
    from click.testing import CliRunner

    from src.cli.commands import cli

    example = Path(__file__).resolve().parents[1] / "example" / "NPU_V2.CMDSCHED.testpoint.xlsx"
    if not example.is_file():
        import pytest
        pytest.skip("示例 xlsx 不在仓库里")
    axes = example.parent / "axes.example.yaml"
    out = tmp_path / "specs"
    runner = CliRunner()
    argv = ["case-model", "import-xlsx", str(example),
            "--module", "npu_cmdsched", "--out", str(out)]
    if axes.is_file():
        argv += ["--axes", str(axes)]
    result = runner.invoke(cli, argv)
    assert result.exit_code == 0, result.output
    casemodel = out / "casemodel.yaml"
    source_map = out / "source_map.json"
    assert casemodel.is_file() and source_map.is_file()
    if axes.is_file():
        model = yaml.safe_load(casemodel.read_text(encoding="utf-8"))
        assert model.get("cross_matrix"), "轴声明没生效：cross_matrix 为空"
        argv = ["case-model", "verify-import", str(example),
                str(casemodel), str(source_map), "--axes", str(axes)]
    else:
        argv = ["case-model", "verify-import", str(example),
                str(casemodel), str(source_map)]
    check = runner.invoke(cli, argv)
    assert check.exit_code == 0, check.output
