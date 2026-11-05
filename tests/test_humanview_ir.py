"""humanview 三个 IR：covg_ir / sva_ir / scb_ir。

钉住三类"写了不等于验证了"的声明：
- 功能覆盖：组有需求/矩阵/checker，路径有 SVA+SB+定向序列；
- SVA：antecedent 没触发 = vacuous，不能算验证；
- SCB：execute_count=0 = 没执行，期望来源不能是 DUT 自己。
"""
from __future__ import annotations

COVG = """
schema: covg_ir_v1
module: NPU_V2-CMDSCHED
feats: [Feat-19, Feat-20]
cells: [DEP×P_STORED_ISSUED, RSP×P_OOO_RSP]
covergroups:
  - group_id: CG-DEP
    name: 数据依赖
    requirements: [Feat-19]
    sampling_domain: scoreboard
    matrix_rows: [P_STORED_ISSUED]
    coverpoints:
      - id: CP-DEP-1
        signal: hazard_type
        bins: {none: 0, raw: 1, waw: 2, war: 3}
    evidence: {sva: [SVA-DEP], scoreboard: [SB-HAZARD]}
    status: 已签核
  - group_id: CG-RSP
    name: 返回
    requirements: [Feat-20]
    sampling_domain: sp_inst
    matrix_rows: [P_OOO_RSP]
    coverpoints:
      - id: CP-RSP-1
        signal: rsp_tag
        bins: {sync: 0, ooo: 1}
    evidence: {sva: [], scoreboard: []}
paths:
  - path_id: P_STORED_ISSUED
    stages: [cmd_hs, dep, issue, done]
    coverpoint: cp_path_stored
    bound_sva: [SVA-DEP]
    bound_scoreboard: [SB-HAZARD]
    directed_seq: [SEQ-RAW]
    feats: [Feat-19]
    status: 已签核
  - path_id: P_OOO_RSP
    stages: [issue, done, rsp]
    coverpoint: cp_path_ooo
    bound_sva: [SVA-RSP]
    bound_scoreboard: [SB-TAG]
    directed_seq: [SEQ-OOO]
    feats: [Feat-20]
    status: 已覆盖
crosses: []
"""

SVA = """
schema: sva_ir_v1
module: NPU_V2-CMDSCHED
contracts: [C2-03]
cells: [DEP×P_STORED_ISSUED]
svas:
  - sva_id: SVA-DEP
    contract: C2-03
    class: S2
    antecedent: inst_in_istb && !dep_ready
    consequent: "!start_valid"
    cover_property: inst_in_istb && !dep_ready
    property: "(inst_in_istb && !dep_ready) |-> !start_valid"
    bound_cells: [DEP×P_STORED_ISSUED]
    hit_count: 12
"""

SCB = """
schema: scb_ir_v1
module: NPU_V2-CMDSCHED
contracts: [C2-01]
cells: [RSP×P_OOO_RSP]
checks:
  - scb_id: SB-TAG
    contract: C2-01
    class: SB2
    model: transaction
    check_object: rsp.tag / rsp.data
    expected_source: tag_pending
    actual_source: rsp_item
    timing: 事务完成
    method: 按 key 匹配
    execute_count: 100
    pass_count: 100
    fail_count: 0
    bound_cells: [RSP×P_OOO_RSP]
"""


class TestCovgIR:
    def test_valid_ir_is_ok_and_matrix_has_green_and_yellow(self):
        from src.tools.humanview.covg_ir import matrix_of, validate_covg_text

        result = validate_covg_text(COVG)
        assert result["ok"], result["errors"]
        counts = matrix_of(COVG)["counts"]
        assert counts["green"] == 1        # DEP × P_STORED_ISSUED（两边都签核）
        assert counts["red"] >= 1          # RSP 组没有 checker
        assert counts["na"] >= 1           # 不适用的格子

    def test_path_without_sva_is_an_error(self):
        from src.tools.humanview.covg_ir import validate_covg_text

        broken = COVG.replace("    bound_sva: [SVA-RSP]\n", "")
        result = validate_covg_text(broken)
        assert not result["ok"]
        assert any("SVA" in e and "P_OOO_RSP" in e for e in result["errors"])

    def test_coverpoint_without_bins_is_an_error(self):
        from src.tools.humanview.covg_ir import validate_covg_text

        broken = COVG.replace("        bins: {sync: 0, ooo: 1}\n", "")
        result = validate_covg_text(broken)
        assert any("没有任何 bins" in e for e in result["errors"])

    def test_markdown_has_matrix_and_traceability(self):
        from src.tools.humanview.covg_ir import render_covg_markdown

        md = render_covg_markdown(COVG)
        assert "功能组 × 生命周期路径" in md
        assert "需求追溯" in md


class TestSVAIR:
    def test_valid_ir_is_non_vacuous(self):
        from src.tools.humanview.sva_ir import validate_sva_text

        result = validate_sva_text(SVA)
        assert result["ok"], result["errors"]
        non_vacuous = next(m for m in result["metrics"] if m["name"] == "非 vacuous")
        assert non_vacuous["covered"] == 1

    def test_antecedent_never_triggered_is_vacuous_error(self):
        from src.tools.humanview.sva_ir import validate_sva_text

        result = validate_sva_text(SVA.replace("hit_count: 12", "hit_count: 0"))
        assert not result["ok"]
        assert any("vacuous" in e for e in result["errors"])

    def test_duplicate_property_is_an_error(self):
        from src.tools.humanview.sva_ir import validate_sva_text

        text = SVA + """
  - sva_id: SVA-DEP-2
    contract: C2-03
    class: S2
    antecedent: inst_in_istb && !dep_ready
    consequent: "!start_valid"
    cover_property: inst_in_istb && !dep_ready
    property: "(inst_in_istb && !dep_ready) |-> !start_valid"
    bound_cells: [DEP×P_STORED_ISSUED]
    hit_count: 3
"""
        result = validate_sva_text(text)
        assert any("语义重复" in e for e in result["errors"])

    def test_class_alias_is_normalized(self):
        from src.tools.humanview.sva_ir import norm_class

        assert norm_class("S2 时序关系") == "S2"
        assert norm_class("S7") == "S7"


EXAMPLE_XLSX = ("src/tools/humanview/aivm_ir/example/"
                "NPU_V2.CMDSCHED.testpoint.xlsx")


class TestXlsxCaseProjection:
    def _doc(self, bindings=None):
        from pathlib import Path

        from src.layers.l3_decision.case_ir import project_from_xlsx

        if not Path(EXAMPLE_XLSX).is_file():
            import pytest

            pytest.skip("示例 xlsx 不在仓库里")
        return project_from_xlsx(EXAMPLE_XLSX, module="NPU_V2-CMDSCHED",
                                 bindings=bindings)

    def test_one_anchor_tp_is_one_case_and_duplicate_ids_stay_separate(self):
        doc = self._doc()
        assert len(doc.cases) == 64
        ids = [c.id for c in doc.cases]
        assert len(ids) == len(set(ids))
        # 源表 BO02-F02 重复出现 —— CASE 身份不能撞
        assert len([i for i in ids if "BO02" in i]) >= 2

    def test_business_fields_are_preserved(self):
        doc = self._doc()
        case = next(c for c in doc.cases if "IF02" in c.id)
        assert case.test_intent == "func_cov监测"
        assert case.doc_section.startswith("L5-")
        assert case.chapter
        assert case.provenance.get("xlsx_rows")
        assert case.source == "xlsx"

    def test_bindings_fill_dimensions_and_reduce_binding_errors(self):
        from src.layers.l3_decision.case_ir import validate_case_doc

        without = validate_case_doc(self._doc())
        with_bind = validate_case_doc(self._doc({
            "schema": "case_bindings_v1",
            "bindings": {
                "CASE-NPU_V2-CMDSCHED-IF01": {"dimensions": ["D_type"]},
                "CASE-NPU_V2-CMDSCHED-IF02": {"dimensions": ["D_seq"]},
            },
        }))
        assert len(with_bind["errors"]) < len(without["errors"])

    def test_bindings_skeleton_has_every_case(self):
        from src.layers.l3_decision.case_ir import bindings_skeleton

        doc = self._doc()
        skeleton = bindings_skeleton(doc)
        assert len(skeleton["bindings"]) == len(doc.cases)

    def test_case_source_xlsx_is_used_instead_of_dimension_synthesis(self):
        from src.layers.l3_decision.case_ir import project_from_casemodel

        model = {"object": "npu_sched", "source": EXAMPLE_XLSX,
                 "dimensions": [{"id": "D_type", "fields": []}],
                 "case_source": {"xlsx": EXAMPLE_XLSX}}
        doc = project_from_casemodel(model, module="npu_sched")
        assert len(doc.cases) == 64
        assert doc.to_dict()["counts"]["xlsx"] == 64


class TestSCBIR:
    def test_valid_ir_is_executed(self):
        from src.tools.humanview.scb_ir import validate_scb_text

        result = validate_scb_text(SCB)
        assert result["ok"], result["errors"]
        executed = next(m for m in result["metrics"] if m["name"] == "执行率")
        assert executed["covered"] == 1

    def test_execute_count_zero_is_an_error(self):
        from src.tools.humanview.scb_ir import validate_scb_text

        result = validate_scb_text(SCB.replace("execute_count: 100",
                                               "execute_count: 0"))
        assert any("从未执行" in e for e in result["errors"])

    def test_expected_source_equal_to_actual_is_warned(self):
        from src.tools.humanview.scb_ir import validate_scb_text

        result = validate_scb_text(SCB.replace("actual_source: rsp_item",
                                               "actual_source: tag_pending"))
        assert any("不是独立比对" in w for w in result["warnings"])

    def test_ledger_outstanding_is_an_error(self):
        from src.tools.humanview.scb_ir import validate_scb_text

        text = SCB.replace("    bound_cells: [RSP×P_OOO_RSP]",
                           "    outstanding: 2\n    bound_cells: [RSP×P_OOO_RSP]")
        result = validate_scb_text(text)
        assert any("账本未平" in e for e in result["errors"])
