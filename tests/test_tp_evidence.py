"""PATH 组 + TP Cov 四层证据视图。

钉住两件事：

1. **PATH 组是独立维度**：按指令生命周期切，一条 bin 一条 TP，不能拿功能组
   100% 冒充路径覆盖；
2. **四层证据按功能契约汇聚**：functional / timing / data / path。一个用例可以
   只提供一部分，多个用例合起来构成完整链；bin 命中单独不构成功能签核。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.layers.l3_decision.evidence.tp_evidence import (
    LAYERS, build_tp_evidence, write_tp_evidence)
from src.layers.l3_decision.casemodel.framework.paths import compile_paths
from src.layers.l3_decision.casemodel.repository.loader import load_model_from_text

MODEL = """\
version: "1"
object: demo
object_code: DEMO
sub_objects:
  - {id: OBJ-01, name: 功能, code: F}
dimensions:
  - id: D_X
    name: X
    fields:
      - {name: x, type: enum, values: [0, 1]}
themes:
  - {id: TH-P0, name: 功能, priority: P0, dimensions: [D_X]}
path_groups:
  - id: CG_PATH
    name: 端到端路径
    sample: path_seq
    coverpoint: cp_path_issue_lifecycle
    bins:
      - name: direct_full
        sequence: [cmd_hs, no_dep, direct, start, done, rls, rsp]
        checks: [SVA-START-DONE-ID, SCB-RSP-DATA]
        requirement: Feat-10
        timing: {expect_cycles: {min: 2, max: 12}, start: a, end: b}
      - name: ooo_rsp_full
        sequence: [multi_xd, out_of_order_done, rsp_by_tag, tag_match]
        checks: [SVA-RSP-HOLD]
        requirement: Feat-20
"""


class TestPathGroup:
    def _model(self):
        return load_model_from_text(MODEL)

    def test_path_group_is_parsed_and_kept_separate(self):
        model = self._model()
        assert len(model.path_groups) == 1
        group = model.path_groups[0]
        assert group.cp_name == "cp_path_issue_lifecycle"
        assert [b.name for b in group.bins] == ["direct_full", "ooo_rsp_full"]
        assert group.bins[0].checks == ["SVA-START-DONE-ID", "SCB-RSP-DATA"]

    def test_one_path_bin_compiles_to_one_tp(self):
        tps = compile_paths(self._model())
        assert [t.tp_id for t in tps] == [
            "TP-DEMO-PATH-DIRECT_FULL", "TP-DEMO-PATH-OOO_RSP_FULL"]
        first = tps[0]
        assert first.dimension == "PATH"
        assert first.coverpoint == "cp_path_issue_lifecycle"
        assert first.bin == "direct_full"
        assert first.requirement == "Feat-10"
        assert first.realization.kind == "sequence"
        assert first.timing is not None and first.timing.checkable
        assert first.execution.stage == "behavior"      # 后端待接，不冒充可执行

    def test_schema_accepts_path_groups(self):
        from src.layers.l3_decision.casemodel.api import run_validate

        result = run_validate(MODEL)
        assert not result.get("error")
        assert not result.get("errors")

    def test_the_plan_lists_the_path_group(self):
        from src.layers.l3_decision.casemodel.api import run_coverage_plan

        plan = run_coverage_plan(MODEL, "demo")["plan"]
        assert plan["summary"]["path_bin_count"] == 2
        assert plan["paths"][0]["status"] == "PENDING_BACKEND"
        # 只被 PATH 认领的需求不是孤立需求
        trace = {t["requirement"]: t for t in plan["traceability"]}
        assert trace["Feat-10"]["paths"] == ["CG_PATH.direct_full"]


CROSS_MODEL = """\
version: "1"
object: demo3
object_code: DEMO3
sub_objects:
  - {id: OBJ-01, name: 功能, code: F}
dimensions:
  - id: D_A
    fields: [{name: a, type: enum, values: [0, 1]}]
  - id: D_B
    fields: [{name: b, type: enum, values: [0, 1]}]
  - id: D_C
    fields: [{name: c, type: enum, values: [0, 1]}]
themes:
  - {id: TH-P0, name: 功能, priority: P0, dimensions: [D_A, D_B, D_C]}
cross_matrix:
  指令×单位: required
cross_groups:
  - {id: X_ISSUE_DEP_PATH, dimensions: [D_A, D_B, D_C], level: required}
"""


class TestCrossGroups:
    def test_a_group_builds_an_n_way_cross(self):
        from src.layers.l3_decision.casemodel.api import run_covergroups

        payload = run_covergroups(CROSS_MODEL, "demo3")
        grp = next(c for c in payload["crosses"] if c["name"].startswith("cx_grp_"))
        assert grp["dimensions"] == ["D_A", "D_B", "D_C"]
        assert "cross cp_a, cp_b, cp_c;" in payload["covergroup_code"]

    def test_a_pair_already_covered_by_cross_matrix_is_not_duplicated(self):
        from src.layers.l3_decision.casemodel.api import run_covergroups

        # 去掉三元组，只留 `cross_matrix` 的两两组合 → 不应再派生 `cx_grp_`
        text = CROSS_MODEL.replace(
            "cross_groups:\n  - {id: X_ISSUE_DEP_PATH, dimensions: [D_A, D_B, D_C], level: required}\n", "")
        payload = run_covergroups(text, "demo3")
        assert not any(c["name"].startswith("cx_grp_") for c in payload["crosses"])


# ────────────────────────────────────────────────────────────────
# 证据视图
# ────────────────────────────────────────────────────────────────

def _make_run(tmp_path: Path, *, two_cases: bool = False) -> Path:
    run = tmp_path / "run"
    (run / "coverage" / "case_cov" / "p1").mkdir(parents=True)
    (run / "coverage" / "coverage_plan.yaml").write_text(yaml.safe_dump({
        "paths": [{"id": "CG_PATH", "name": "端到端", "sample": "path_seq",
                   "coverpoint": "cp_path_issue_lifecycle",
                   "bins": [{"name": "direct_full",
                             "sequence": ["cmd_hs", "rsp"],
                             "checks": ["SVA-A", "SCB-B"],
                             "requirement": "Feat-10"}]}],
        "crosses": [{"name": "X_ISSUE_DEP", "dimensions": ["D1", "D2"],
                     "bins": ["a", "b"], "requirement": "Feat-1"}],
    }, allow_unicode=True), encoding="utf-8")
    (run / "coverage" / "testpoints.yaml").write_text(yaml.safe_dump({
        "testpoints": [
            {"tp_id": "TP-A", "object": "o", "dimension": "D", "value": "v",
             "bin": "b0", "coverpoint": "cp_x",
             "realization": {"kind": "stimulus"},
             "execution": {"test": "t", "stage": "p1"}},
            {"tp_id": "TP-PATH", "object": "o", "dimension": "PATH",
             "value": "direct_full", "bin": "direct_full",
             "coverpoint": "cp_path_issue_lifecycle",
             "realization": {"kind": "sequence", "sequence": "cmd_hs > rsp"},
             "execution": {"stage": "behavior"}},
        ]}, allow_unicode=True), encoding="utf-8")
    (run / "coverage" / "methodology.json").write_text(json.dumps(
        {"artifacts": {"testpoints_yaml": {"sha256": "abc"}}}), encoding="utf-8")
    (run / "coverage" / "tp_matrix.json").write_text(json.dumps({"rows": [
        {"tp_id": "TP-A", "coverpoint": "cp_x", "bins": ["b0"],
         "bin_hits": {"b0": 5}, "hits": 5, "status": "HIT", "kind": "stimulus",
         "stage": "p1", "signed_off": True,
         "signed_off_by": "tp_a_seed_1@1", "owner_case": "tp_a_seed_1"},
        {"tp_id": "TP-PATH", "coverpoint": "cp_path_issue_lifecycle",
         "bins": ["direct_full"], "bin_hits": {}, "hits": 0,
         "status": "PENDING_BACKEND", "kind": "sequence", "stage": "behavior",
         "signed_off": False},
    ]}), encoding="utf-8")
    cases = [{"task": "tp_a_seed_1", "seed": 1}] if not two_cases else [
        {"task": "tp_a_seed_1", "seed": 1}, {"task": "tp_a_seed_2", "seed": 2}]
    (run / "coverage" / "case_tp.json").write_text(json.dumps({"by_tp": {
        "TP-A": {"signed_off": True, "signed_off_by": "tp_a_seed_1@1",
                 "owner_case": "tp_a_seed_1", "wave": "w", "cases": cases},
        "TP-PATH": {"signed_off": False, "cases": []},
    }}), encoding="utf-8")
    _case(run, "tp_a_seed_1", 1, scb=True, rules=2)
    if two_cases:
        _case(run, "tp_a_seed_2", 2, scb=True, rules=2)
    (run / "sim" / "coverage").mkdir(parents=True)
    (run / "sim" / "coverage" / "coverage_result.json").write_text(json.dumps({
        "coverage": {"functional_detail": {"covergroups": [{
            "name": "cg_dut", "actual": 80.0,
            "coverpoints": [{"name": "cp_x", "actual": 100.0}],
            "crosses": [{"name": "X_ISSUE_DEP", "actual": 50.0}],
        }]}}}), encoding="utf-8")
    return run


def _case(run: Path, task: str, seed: int, *, scb: bool, rules: int) -> None:
    (run / "coverage" / "case_cov" / "p1" / f"{task}.json").write_text(json.dumps({
        "schema": "case_cov_v1", "task": task, "test": "t", "seed": seed,
        "stage": "p1",
        "scb": ({"total": 4, "matched": 4, "mismatched": 0} if scb else {}),
        "assertions": {"rules": rules, "fired": 0},
        "timing_ok": None, "wave": "w",
        "tp": [{"tp_id": "TP-A", "hits": {"b0": 5}, "pct": 100.0,
                "status": "SIGNED_OFF", "reasons": [], "timing_ok": None}],
    }), encoding="utf-8")


class TestEvidenceView:
    def test_four_layers_and_contract_status(self, tmp_path):
        ev = build_tp_evidence(_make_run(tmp_path))
        tp = next(t for t in ev["tps"] if t["tp_id"] == "TP-A")
        layers = tp["evidence_layers"]
        assert layers["functional"]["status"] == "PROVEN"
        assert layers["timing"]["status"] == "PROVEN"
        assert layers["data"]["status"] == "PROVEN"
        assert layers["path"]["status"] == "NOT_APPLICABLE"
        assert tp["contract_status"] == "VERIFIED"
        assert ev["counts"]["VERIFIED"] == 1

    def test_bin_hit_alone_is_not_verified(self, tmp_path):
        """只有功能覆盖、没有 SCB / 断言时只能 PARTIAL —— 命中 ≠ 验证。"""
        run = _make_run(tmp_path)
        (run / "coverage" / "case_cov" / "p1" / "tp_a_seed_1.json").write_text(
            json.dumps({"schema": "case_cov_v1", "task": "tp_a_seed_1",
                        "test": "t", "seed": 1, "stage": "p1",
                        "scb": {}, "assertions": {"rules": 0, "fired": 0},
                        "timing_ok": None, "wave": "w",
                        "tp": [{"tp_id": "TP-A", "hits": {"b0": 5}, "pct": 100.0,
                                "status": "SIGNED_OFF", "reasons": [],
                                "timing_ok": None}]}), encoding="utf-8")
        tp = next(t for t in build_tp_evidence(run)["tps"] if t["tp_id"] == "TP-A")
        assert tp["contract_status"] == "PARTIAL"
        assert tp["evidence_layers"]["data"]["status"] == "NOT_APPLICABLE"

    def test_path_tp_is_pending_backend_and_not_counted_as_proven(self, tmp_path):
        ev = build_tp_evidence(_make_run(tmp_path))
        tp = next(t for t in ev["tps"] if t["tp_id"] == "TP-PATH")
        assert tp["contract_status"] == "PENDING_BACKEND"
        assert tp["evidence_layers"]["path"]["status"] == "PENDING_BACKEND"
        assert ev["review"]["path_backend"] == "pending"
        proof = ev["review"]["path_proof"][0]
        assert proof["checks"] == ["SVA-A", "SCB-B"]
        assert proof["tp_id"] == "TP-PATH"

    def test_multiple_cases_jointly_supply_the_chain(self, tmp_path):
        ev = build_tp_evidence(_make_run(tmp_path, two_cases=True))
        tp = next(t for t in ev["tps"] if t["tp_id"] == "TP-A")
        assert len(tp["cases"]) == 2
        assert tp["evidence_layers"]["data"]["source"]["scb_cases"] == [
            "tp_a_seed_1", "tp_a_seed_2"]
        assert tp["contract_status"] == "VERIFIED"

    def test_groups_cover_functional_path_and_cross(self, tmp_path):
        ev = build_tp_evidence(_make_run(tmp_path))
        assert ev["groups"]["functional"][0]["name"] == "cg_dut"
        assert ev["groups"]["path"][0]["bins"][0]["name"] == "direct_full"
        assert ev["groups"]["cross"][0]["name"] == "X_ISSUE_DEP"
        assert ev["groups"]["cross"][0]["actual"] == 50.0

    def test_review_answers_the_path_question_with_four_layers(self, tmp_path):
        review = build_tp_evidence(_make_run(tmp_path))["review"]
        assert len(review["four_layers"]) == len(LAYERS) == 4
        assert "路径" in review["question"] or "path" in review["question"].lower()
        assert "cross" in review["cross_architecture"]["source"]
        assert "does_not_prove" in review["cross_architecture"]

    def test_write_and_load(self, tmp_path):
        from src.layers.l3_decision.evidence.tp_evidence import load_tp_evidence

        run = _make_run(tmp_path)
        write_tp_evidence(run)
        assert (run / "coverage" / "tp_cov_evidence.json").is_file()
        assert load_tp_evidence(run)["schema"] == "tp_cov_evidence_v1"
