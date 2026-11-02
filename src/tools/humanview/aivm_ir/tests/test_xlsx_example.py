"""真实示例 xlsx 的对齐 / 往返 / M1 编译（原根目录三个脚本测试的 pytest 化）。

示例表随包走（`example/NPU_V2.CMDSCHED.testpoint.xlsx`），不再依赖
`/data/inputs/...` 这类本机绝对路径；缺文件就 skip，而不是让整个测试套件崩掉。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.humanview.aivm_ir import (
    Category, CellRole, CellType, compile_ontology, load_xlsx_to_ontology,
    write_ontology_to_xlsx,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "example" / "NPU_V2.CMDSCHED.testpoint.xlsx"
pytestmark = pytest.mark.skipif(not EXAMPLE.is_file(),
                                reason="示例 xlsx 不在仓库里")


@pytest.fixture(scope="module")
def onto():
    return load_xlsx_to_ontology(str(EXAMPLE))


def test_example_is_the_64_tp_table(onto):
    assert onto.tp_count() == 64


def test_duplicate_ids_stay_separate_rows(onto):
    """BO02-F02 / R02 在源表重复出现，不合并。"""
    assert len(onto.find_tps("NPU_V2-CMDSCHED-BO02-F02")) == 4
    # R02 的 id 带全角括号（R02（RD-RR）），按前缀数
    r02 = [tp for tp in onto.testpoints
           if (tp.orig_id or "").startswith("NPU_V2-CMDSCHED-R02")]
    assert len(r02) == 4


def test_category_comes_from_id_not_suffix(onto):
    cr = [tp for tp in onto.testpoints
          if (tp.orig_id or "").startswith("NPU_V2-CMDSCHED-CR")]
    assert cr and all(tp.category is Category.CR for tp in cr)


def test_roundtrip_conserves_tp_and_leaf_cells(onto, tmp_path):
    out = tmp_path / "rt.xlsx"
    write_ontology_to_xlsx(onto, str(out), view="leaves")
    reloaded = load_xlsx_to_ontology(str(out))
    assert [(tp.tp_id, tp.feature_text) for tp in onto.testpoints] == \
           [(tp.tp_id, tp.feature_text) for tp in reloaded.testpoints]

    def cells(model):
        return [(tp.tp_id, c.raw_text, c.cell_type.value, c.legality)
                for tp in model.testpoints for c in tp.coverage_cells
                if c.is_material()]

    assert cells(onto) == cells(reloaded)


def test_m1_compiles_if_bins(onto):
    plan = compile_ontology(onto, categories={Category.IF})
    assert plan["tp_count"] > 0
    assert plan["totals"]["cover_bins"] > 0


def test_cell_classifier_three_channels(onto):
    kinds = {c.cell_type for tp in onto.testpoints for c in tp.coverage_cells}
    assert CellType.CONSTRAINT_COMBO in kinds
    assert CellType.CONFIG_ENUM in kinds or CellType.DIRECTED_CASE in kinds
    roles = {c.role for tp in onto.testpoints for c in tp.coverage_cells}
    assert CellRole.HEADER in roles and CellRole.LEAF in roles


def test_axes_sidecar_turns_combo_cells_into_cross_bins(tmp_path):
    """真实表 + 轴声明：组合格变成真正的 cross bin（而不是场景退化）。"""
    import yaml
    from src.tools.humanview.aivm_ir.bridge import import_ontology

    axes = EXAMPLE.parent / "axes.example.yaml"
    if not axes.is_file():
        pytest.skip("轴声明示例不在仓库里")
    onto = load_xlsx_to_ontology(str(EXAMPLE))
    result = import_ontology(onto, tmp_path / "specs", module_name="npu_cmdsched",
                             source_path=EXAMPLE, axes_path=axes)
    model = yaml.safe_load(Path(result["casemodel"]).read_text(encoding="utf-8"))
    cross = model.get("cross_matrix") or {}
    assert len(cross) == 5                       # IF02..IF06 各一个 pair
    bins = [b for decl in cross.values() for b in decl["bins"]]
    assert len(bins) == 11
    # 每个 cross 的 when 必须引用**本 TP 的**维度字段，不能跨 TP 串
    for key, decl in cross.items():
        assert "×" in key
        assert all("." not in name for name in
                   [k for b in decl["bins"] for k in b["when"]])


def test_axes_drift_is_detected(tmp_path):
    from src.tools.humanview.aivm_ir.bridge import import_ontology, verify_import

    axes = EXAMPLE.parent / "axes.example.yaml"
    if not axes.is_file():
        pytest.skip("轴声明示例不在仓库里")
    onto = load_xlsx_to_ontology(str(EXAMPLE))
    result = import_ontology(onto, tmp_path / "specs", module_name="npu_cmdsched",
                             source_path=EXAMPLE, axes_path=axes)
    assert verify_import(EXAMPLE, result["casemodel"], result["source_map"],
                         axes_path=axes)["ok"] is True
    tampered = tmp_path / "axes.yaml"
    tampered.write_text(axes.read_text(encoding="utf-8") + "\n# edited\n",
                        encoding="utf-8")
    drift = verify_import(EXAMPLE, result["casemodel"], result["source_map"],
                          axes_path=tampered)
    assert drift["ok"] is False
    assert any(i["check"] == "axes_changed" for i in drift["issues"])
