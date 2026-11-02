"""全链路 demo：手工构造 IF01/IF02 + 真实 xlsx 整表加载 + roundtrip + M1 编译。"""
import json
from aivm_ir.ir_core import (
    Ontology, TestPointIR, Dimension, DimensionValue, LegalityRule,
    CoverageCell, Provenance, Category, DimType, Status, Component, RawColumn,
)
from aivm_ir.xlsx_writer import write_ontology_to_xlsx, write_ontology_to_json
from aivm_ir.xlsx_loader import load_xlsx_to_ontology
from aivm_ir.validate import validate_ontology
from aivm_ir.plan_compiler_m1 import compile_ontology, compile_tp


def _row(sub_feature="", sub_sub_feature="", feature="",
         test_name="func_cov监测", test_num="0") -> dict[str, str]:
    return {
        RawColumn.SEQ.value: "",
        RawColumn.FEATURE.value: feature,
        RawColumn.SUB_FEATURE.value: sub_feature,
        RawColumn.SUB_SUB_FEATURE.value: sub_sub_feature,
        RawColumn.SUB_SUB_SUB_FEATURE.value: "",
        RawColumn.TEST_NAME.value: test_name,
        RawColumn.TEST_NUM.value: test_num,
        RawColumn.DOC_SECTION.value: "L5-[NPU-HM057]-[CDD]-CMD_SCHED",
        RawColumn.CHAPTER.value: "ref 3.2 Feature List",
    }


def build_if01_if02() -> Ontology:
    lv = "仅GLSU/LLSU load/store并行执行运行允许"

    if01 = TestPointIR(
        tp_id="NPU_V2-CMDSCHED-IF01",
        feature_text="valid -ready 协议",
        feature_path=[Category.IF.value, "valid -ready 协议"],
        category=Category.IF,
        test_num=0,
        coverage_driven=True,
        directed=False,
        dimensions=[Dimension(
            dim_id="handshake_seq",
            name="valid/ready 握手顺序",
            dim_type=DimType.CATEGORICAL,
            value_domain=[
                DimensionValue("data_stable", "握手数据必稳态", 5),
                DimensionValue("valid_first", "valid先于ready", 6),
                DimensionValue("ready_first", "ready先于valid", 7),
                DimensionValue("simultaneous", "valid和ready同时置起", 8),
            ],
            semantics="区分 valid 与 ready 的先后关系",
        )],
        coverage_cells=[
            CoverageCell(cell_id="IF01#r5", raw_text="握手数据必稳态", source_row=5),
            CoverageCell(cell_id="IF01#r6", raw_text="valid先于ready", source_row=6),
            CoverageCell(cell_id="IF01#r7", raw_text="ready先于valid", source_row=7),
            CoverageCell(cell_id="IF01#r8", raw_text="valid和ready同时置起", source_row=8),
        ],
        provenance=Provenance(doc_section="L5-[NPU-HM057]-[CDD]-CMD_SCHED",
                             chapter="ref 3.2 Feature List", xlsx_rows=[5, 6, 7, 8]),
        raw_rows=[
            _row(feature="NPU_V2-CMDSCHED-IF01 valid -ready 协议", sub_feature="握手数据必稳态"),
            _row(sub_feature="valid先于ready"),
            _row(sub_feature="ready先于valid"),
            _row(sub_feature="valid和ready同时置起"),
        ],
    )

    # IF02 的维度是"分析视图"：raw_text 用源表 D 格原句里能闭包的子串，
    # 而真正的组合真理在 coverage_cells（每个格子已经是完整组合，无需笛卡尔积）。
    s_0lt1 = "start_id0 先于start_id1"
    s_1lt0 = "start_id0 后于start_id1"
    d_0lt1 = "done_id0先于done_id1"
    d_1lt0 = "done_id0后于done_id1"
    cell9  = "start_id0 先于start_id1,done_id0先于done_id1"
    cell10 = "start_id0 后于start_id1,done_id0后于done_id1"
    cell11 = f"start_id0 先于start_id1,done_id0后于done_id1  {lv}"
    cell12 = f"start_id0 后于start_id1,done_id0先于done_id1  {lv}"

    if02 = TestPointIR(
        tp_id="NPU_V2-CMDSCHED-IF02",
        feature_text="glsu: start- done inst_id0 inst_id1, start- done",
        feature_path=[Category.IF.value, "glsu: start- done ..."],
        category=Category.IF,
        dut_components=[Component.GLSU.value],
        test_num=0,
        coverage_driven=True,
        directed=False,
        dimensions=[
            Dimension(dim_id="start_order", name="start 先后", dim_type=DimType.CATEGORICAL,
                      value_domain=[DimensionValue("0<1", s_0lt1, 9),
                                    DimensionValue("1<0", s_1lt0, 10)]),
            Dimension(dim_id="done_order", name="done 先后", dim_type=DimType.CATEGORICAL,
                      value_domain=[DimensionValue("0<1", d_0lt1, 9),
                                    DimensionValue("1<0", d_1lt0, 10)]),
            Dimension(dim_id="parallel_legality", name="并行合法性", dim_type=DimType.CATEGORICAL,
                      value_domain=[DimensionValue("all", "无限制", 0),   # 推导格，不参与闭包
                                    DimensionValue("glsu_llsu_only", lv, 11)]),
        ],
        coverage_cells=[
            CoverageCell(cell_id="IF02#r9",  raw_text=cell9,  source_row=9),
            CoverageCell(cell_id="IF02#r10", raw_text=cell10, source_row=10),
            CoverageCell(cell_id="IF02#r11", raw_text=cell11, source_row=11, legality=lv),
            CoverageCell(cell_id="IF02#r12", raw_text=cell12, source_row=12, legality=lv),
        ],
        provenance=Provenance(doc_section="L5-[NPU-HM057]-[CDD]-CMD_SCHED",
                             chapter="ref 3.2 Feature List", xlsx_rows=[9, 10, 11, 12]),
        raw_rows=[
            _row(feature="NPU_V2-CMDSCHED-IF02 glsu: start- done inst_id0 inst_id1, start- done",
                 sub_sub_feature=cell9),
            _row(sub_sub_feature=cell10),
            _row(sub_sub_feature=cell11),
            _row(sub_sub_feature=cell12),
        ],
    )
    return Ontology(version="2026-11-02.m1", spec_rev="NPU-HM057-r3.2",
                    xlsx_rev="CMDSCHED-v2.7", testpoints=[if01, if02])


def main() -> None:
    print("=" * 64)
    onto = build_if01_if02()
    print(f"[demo] 手工 TP 数: {len(onto.testpoints)}")

    rep = validate_ontology(onto)
    for tp_id, r in rep["tps"].items():
        tp = onto.find_tp(tp_id)
        print(f"  {tp_id}: {r['status']} | mode={r['mode']} "
              f"| num_kind={r['num_kind']} | points={r['coverage_points']}")
    hard=[e for e in rep['errors'] if not e.startswith('[warn]')]; assert not hard, hard
    print("  → validate OK（无 fail）")

    write_ontology_to_json(onto, "/data/workspace/if01_if02_ontology.json")
    write_ontology_to_xlsx(onto, "/data/workspace/if01_if02_ir.xlsx", view="leaves")

    loaded = load_xlsx_to_ontology("/data/workspace/if01_if02_ir.xlsx", version="roundtrip")
    print(f"\n[roundtrip] 读回 TP 数: {len(loaded.testpoints)}")
    for tp in loaded.testpoints:
        print(f"  {tp.tp_id}: cells={len(tp.material_cells())} "
              f"rows={len(tp.raw_rows)} cat={tp.category.value} "
              f"comp={tp.dut_components} mode={tp.execution_mode.value}")

    print("\n[九组分组]")
    for cat, tps in onto.category_groups().items():
        print(f"  [{cat.value}] {len(tps)} TPs")

    # ---- M1：IF02 应当正好 4 个 cover bin，而不是 8 ----
    print("\n[M1 编译 IF01/IF02]")
    plan = compile_ontology(onto, categories={Category.IF})
    for p in plan["plans"]:
        print(f"  {p['tp_id']}: mode={p['mode']} points={p['point_count']}")
        for pt in p["points"]:
            print(f"      - {pt['kind']:10s} {pt.get('cell_id', pt.get('case_id','')):14s} "
                  f"| {pt['label'][:44]:44s} | legality={pt.get('legality')}")
    assert plan["total_cover_bins"] == 8, plan["total_cover_bins"]  # IF01 4 + IF02 4
    print(f"\n✅ 总覆盖格 = {plan['total_cover_bins']}（IF01 4 + IF02 4，未膨胀为 8×笛卡尔积）")


if __name__ == "__main__":
    main()
