"""VPlan 项目 → SignOffAI 规划/契约 IR 的接入测试。

钉住三件事：

1. 源数据计数与状态**原样**进入 IR（42 assume / 66 planned / 12 planned）；
2. 不读旧建模模型，项目里也没有它；
3. 只规划 run 明确写 `PLAN_ONLY`，不产生 `signoff_evidence/`。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from src.layers.l3_decision.vplan import (
    build_execution_model, build_payload, load_project, project_summary,
    run_artifacts, write_execution_model, write_plan_only_run,
)

# 冻结的项目源（首个完整 CMDSCHED VPlan 项目）。活项目 `specs/npu_sched`
# 现在只剩裸 spec，由 front bootstrap 生成表，内容随 LLM 抽取变化 —— 集成测试
# 必须钉一个确定的项目源，否则计数断言天天漂。
ROOT = Path(__file__).resolve().parent / "fixtures" / "npu_sched"
REPO = Path(__file__).resolve().parents[1]


def test_vplan_build_does_not_import_legacy_model():
    """VPlan 的规划/IR 层必须自包含 —— 引擎删掉后 build 仍能跑。"""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import src.layers.l3_decision.vplan.build\n"
        "bad = sorted(m for m in sys.modules if 'casemodel' in m)\n"
        "print(bad)\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=str(REPO),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_load_project_reads_current_source():
    proj = load_project(ROOT)
    assert proj.module == "npu_sched"
    assert proj.dut == "CMDSCHED"
    assert len(proj.requirements) == 20
    assert len(proj.features) == 39
    assert len(proj.topics) == 10
    assert len(proj.contracts) == 42
    assert sum(proj.status_counts.values()) == 42
    assert len(proj.testpoints) == 66
    assert proj.tp_status_counts == {"planned": 66}
    assert len(proj.cases) == 12
    assert proj.case_status_counts == {"planned": 12}
    assert not (ROOT / "runtime_model.yaml").exists()


def test_vplan_testpoint_can_bind_explicit_stimulus_field(tmp_path):
    """VPlan 行显式声明 realization 时，不再把刺激强制降级成 observe-only。"""
    from src.layers.l3_decision.vplan.build import build_testpoints
    from src.layers.l3_decision.vplan.source import VPlanProject

    project = VPlanProject(
        root=tmp_path, module="m", dut="m",
        spec_dir=tmp_path, spec_path=tmp_path / "m.md", spec_hash="",
        spec_meta={}, features=[], cases=[],
        testpoints=[{
            "tp_id": "TP-1", "feature_id": "F-1", "topic": "接口",
            "test_point": "value", "contract_id": "C-1",
            "realization_kind": "stimulus", "stimulus_field": "instr_type",
            "realization_agent": "cmd_agent", "priority": "P0",
        }],
    )
    tp = build_testpoints(project)[0]
    assert tp["realization"]["kind"] == "stimulus"
    assert tp["realization"]["field"] == "instr_type"
    assert tp["realization"]["agent"] == "cmd_agent"


def test_matrix_schema_rejects_unknown_status_and_missing_columns(tmp_path):
    """手改 CSV 不能造出“看起来合法”的状态；列不齐也不能静默读。"""
    from src.layers.l3_decision.vplan.source import VPlanError, _load_matrix

    matrix = tmp_path / "data" / "contract_matrix"
    matrix.mkdir(parents=True)
    (matrix / "func.csv").write_text(
        "contract_id,class,object,description,source_ref,owner,p_level,"
        "check_method,check_artifact,gate,status,assumption,remark\n"
        "C-1,func,x,x,1,dv,P0,scb,x,g,active,a,\n",
        encoding="utf-8")
    assert _load_matrix(tmp_path)["C-1"]["status"] == "active"

    (matrix / "func.csv").write_text(
        "contract_id,class,object,description,source_ref,owner,p_level,"
        "check_method,check_artifact,gate,status,assumption,remark\n"
        "C-1,func,x,x,1,dv,P0,scb,x,g,done,a,\n",
        encoding="utf-8")
    with pytest.raises(VPlanError, match="status"):
        _load_matrix(tmp_path)

    (matrix / "func.csv").write_text("contract_id,status\nC-1,assume\n",
                                     encoding="utf-8")
    with pytest.raises(VPlanError, match="列不齐"):
        _load_matrix(tmp_path)


def test_payload_keeps_ids_and_statuses():
    proj = load_project(ROOT)
    payload = build_payload(proj)

    assert payload["count"] == 66
    assert {tp["tp_id"] for tp in payload["testpoints"]} == {
        row["tp_id"] for row in proj.testpoints
    }
    # 没有事务字段绑定，就不能冒充可驱动：全部是 observe-only。
    assert all(tp["observe_only"] for tp in payload["testpoints"])
    assert all("vplan_status=planned" in (tp.get("notes") or [])
               for tp in payload["testpoints"])
    assert payload["case_ir"]["schema"] == "case_ir_v1"
    assert len(payload["case_ir"]["cases"]) == 12

    # C-* 仍在 TP 的 requirement/cover_id 与 case 的 feats 上。
    tp_contracts = {tp["cover_id"] for tp in payload["testpoints"]
                    if tp.get("cover_id")}
    assert tp_contracts <= set(proj.contracts)
    case_contracts = {cid for case in payload["case_ir"]["cases"]
                      for cid in case["feats"]}
    assert case_contracts <= set(proj.contracts)

    link = payload["contract_link"]
    assert link["schema"] == "vplan_contract_link_v1"
    assert len(link["contracts"]) == 42
    assert sum(link["status_counts"].values()) == 42
    assert all(row["status"] in {"assume", "active"} for row in link["contracts"])


def test_plan_only_run_writes_ir_but_no_evidence(tmp_path):
    proj = load_project(ROOT)
    out = tmp_path / "output_vplan_npu_sched"
    summary = write_plan_only_run(proj, out)

    assert summary["execution"]["status"] == "PLAN_ONLY"
    assert summary["execution"]["signable"] is False
    assert (out / "coverage" / "testpoints.yaml").is_file()
    assert (out / "coverage" / "testpoints.json").is_file()
    assert (out / "coverage" / "case_ir.json").is_file()
    assert (out / "contract" / "contract_manifest.json").is_file()
    assert (out / "contract" / "plan_link.yaml").is_file()
    assert (out / "docs" / "manifest.json").is_file()
    assert not (out / "signoff_evidence").exists()
    assert not (out / "report.json").exists()

    manifest = json.loads(
        (out / "docs" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["origin"] == "vplan"
    assert manifest["status"] == "PLANNED"
    assert manifest["execution"]["signable"] is False

    link = yaml.safe_load(
        (out / "contract" / "plan_link.yaml").read_text(encoding="utf-8"))
    assert sum(link["status_counts"].values()) == 42
    assert len(link["contracts"]) == 42
    assert len(link["cases"]) == 12

    tp_doc = json.loads(
        (out / "coverage" / "testpoints.json").read_text(encoding="utf-8"))
    assert tp_doc["count"] == 66
    assert tp_doc["methodology"]["counts"]["contracts_by_status"] == \
        proj.status_counts


def test_execution_model_projects_vplan_cases(tmp_path):
    proj = load_project(ROOT)
    model = build_execution_model(proj)

    assert len(model["dimensions"]) == 12
    assert len(model["themes"]) == 12
    assert len(model["cases"]["cases"]) == 12
    assert {t["test"] for t in model["themes"]} == {
        c["test_name"] for c in proj.cases
    }
    assert all(t["dimensions"] for t in model["themes"])
    dim_ids = {d["id"] for d in model["dimensions"]}
    assert all(set(t["dimensions"]) <= dim_ids for t in model["themes"])
    assert len({tuple(t["dimensions"]) for t in model["themes"]}) > 1
    assert all(c["requirements"] for c in model["cases"]["cases"])
    assert (ROOT / "rtl" / "npu_sched.sv").is_file()

    path = write_execution_model(proj, tmp_path)
    from src.layers.l3_decision.vplan.runtime.repository import load_models_from_text

    models = load_models_from_text(path.read_text(encoding="utf-8"))
    resolved = models[0].resolve()
    assert len(resolved.themes) == 12
    assert len(resolved.cases_doc.get("cases") or []) == 12


def test_package_run_assets_maps_generated_layout(tmp_path):
    from src.layers.l3_decision.vplan import package_run_assets, scan_assets

    files = {
        "agents/foo/1_interface/foo_if.sv": "interface foo_if; endinterface\n",
        "agents/foo/4_driver_monitor/foo_driver.sv": "class foo_driver; endclass\n",
        "env/foo_env.sv": "class foo_env; endclass\n",
        "env/coverage/foo_cov.sv": "class foo_cov; endclass\n",
        "coverage/foo_cov_if.sv": "interface foo_cov_if; endinterface\n",
        "env/tests/foo_test.sv": "class foo_test; endclass\n",
        "env/rtl_sc/foo_scb.sv": "class foo_scb; endclass\n",
        "env/cons/foo_policy.sv": "class foo_policy; endclass\n",
        "bench/foo_tb_top.sv": "module foo_tb_top; endmodule\n",
        "agents/foo/loopback/foo_loopback_scb.sv": "class foo_loopback_scb; endclass\n",
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / "inputs" / "filelists").mkdir(parents=True)
    (tmp_path / "inputs" / "filelists" / "filelist.f").write_text(
        "agents/foo/1_interface/foo_if.sv\nenv/foo_env.sv\n"
        "bench/foo_tb_top.sv\n", encoding="utf-8")
    (tmp_path / "coverage" / "case_ir.json").write_text(
        '{"schema": "case_ir_v1", "cases": [{"id": "TC_FOO", '
        '"tests": ["foo_test"], "feats": ["C-FUNC-UNIT-001"], '
        '"sva": [], "scb": [{"id": "foo_scb"}]}]}',
        encoding="utf-8")

    summary = package_run_assets(tmp_path, "foo")
    assert summary["copied"] == 10
    assert (tmp_path / "sv" / "interface" / "foo_if.sv").is_file()
    assert (tmp_path / "sv" / "agents" / "foo" / "foo_driver.sv").is_file()
    assert (tmp_path / "sv" / "env" / "foo_env.sv").is_file()
    assert (tmp_path / "sv" / "covgs" / "foo_cov.sv").is_file()
    assert (tmp_path / "sv" / "interface" / "foo_cov_if.sv").is_file()
    assert (tmp_path / "sv" / "test" / "foo_test.sv").is_file()
    assert (tmp_path / "sv" / "scbs" / "foo_scb.sv").is_file()
    assert (tmp_path / "sv" / "cons" / "foo_policy.sv").is_file()
    assert (tmp_path / "sv" / "tb" / "hdl_top.sv").is_file()
    assert (tmp_path / "sv" / "scbs" / "foo_loopback_scb.sv").is_file()
    text = (tmp_path / "sv" / "interface" / "foo_if.sv").read_text(
        encoding="utf-8")
    assert "// ARTIFACT: foo_if" in text
    scb = (tmp_path / "sv" / "scbs" / "foo_scb.sv").read_text(encoding="utf-8")
    assert "// CONTRACT_REFS: C-FUNC-UNIT-001" in scb
    test = (tmp_path / "sv" / "test" / "foo_test.sv").read_text(encoding="utf-8")
    assert "// CASE_ID: TC_FOO" in test
    hdl = (tmp_path / "sv" / "vc" / "hdl_files.f").read_text(encoding="utf-8")
    hvl = (tmp_path / "sv" / "vc" / "hvl_files.f").read_text(encoding="utf-8")
    assert "sv/interface/foo_if.sv" in hdl
    assert "sv/tb/hdl_top.sv" in hdl
    assert "sv/env/foo_env.sv" in hvl
    assert len(scan_assets(tmp_path)) == 10


def test_gate_uses_latest_linked_run_and_reports_active_drift():
    """gate 选 run 不能靠 append 顺序；active 但证据不满足要单独标出。

    这是纯函数级测试：不建 EDA 产物，只构造两个 linked run 条目，
    验证 `_latest` 的排序键与 `active_drift` 字段。
    """
    from src.layers.l3_decision.vplan.evidence import (
        _evaluate_contract, _latest)

    old = {
        "run_id": "run_old", "linked_at": "2026-11-09T10:00:00+00:00",
        "contracts": [{"contract_id": "C-FUNC-UNIT-001",
                       "tp_ids": ["TP-1"], "case_ids": []}],
        "tp_status": {"TP-1": "HIT"}, "regression_status": "PASS",
        "sv_contracts": ["C-FUNC-UNIT-001"],
    }
    new = {
        "run_id": "run_new", "linked_at": "2026-11-10T10:00:00+00:00",
        "contracts": [{"contract_id": "C-FUNC-UNIT-001",
                       "tp_ids": ["TP-1"], "case_ids": []}],
        "tp_status": {"TP-1": "MISS"}, "regression_status": "PASS",
        "sv_contracts": ["C-FUNC-UNIT-001"],
    }
    assert _latest([old, new])["run_id"] == "run_new"
    result = _evaluate_contract("C-FUNC-UNIT-001", "active", [old, new])
    assert result["run_id"] == "run_new"
    assert result["eligible_active"] is False
    assert result["active_drift"] is True
    assert any("TP not hit" in reason for reason in result["reasons"])


def test_evidence_gate_requires_tp_regression_and_asset(tmp_path):
    from src.layers.l3_decision.vplan import apply_active, evaluate, link_run

    proj = tmp_path / "proj"
    matrix = proj / "data" / "contract_matrix"
    matrix.mkdir(parents=True)
    fields = ["contract_id", "class", "object", "description", "source_ref",
              "owner", "p_level", "check_method", "check_artifact", "gate",
              "status", "assumption", "remark"]
    rows = []
    for cid in ("C-FUNC-UNIT-001", "C-FUNC-DEP-002"):
        rows.append({"contract_id": cid, "class": "func", "object": "x",
                     "description": "x", "source_ref": "1", "owner": "dv",
                     "p_level": "P0", "check_method": "scb",
                     "check_artifact": "x", "gate": "g", "status": "assume",
                     "assumption": "planned", "remark": ""})
    with (matrix / "func.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    run = tmp_path / "run"
    (run / "contract").mkdir(parents=True)
    (run / "coverage").mkdir()
    (run / "sv").mkdir()
    (run / "contract" / "plan_link.yaml").write_text(yaml.safe_dump({
        "schema": "vplan_contract_link_v1",
        "module": "p", "spec_hash": "x",
        "contracts": [
            {"contract_id": "C-FUNC-UNIT-001", "tp_ids": ["TP-1"],
             "case_ids": ["TC-1"]},
            {"contract_id": "C-FUNC-DEP-002", "tp_ids": ["TP-2"],
             "case_ids": ["TC-2"]},
        ],
    }), encoding="utf-8")
    (run / "coverage" / "tp_matrix.json").write_text(json.dumps({
        "rows": [{"tp_id": "TP-1", "status": "HIT"},
                 {"tp_id": "TP-2", "status": "MISS"}],
    }), encoding="utf-8")
    (run / "regression_stages.json").write_text(json.dumps({"status": "PASS"}),
                                                encoding="utf-8")
    (run / "sv" / "asset_registry.csv").write_text(
        "artifact,kind,path,owner,status,contract_ids,case_ids,source\n"
        "unit_scb,scb,sv/scb/unit_scb.sv,dv,candidate,C-FUNC-UNIT-001,,x\n",
        encoding="utf-8")

    link_run(proj, run)
    result = {row["contract_id"]: row for row in evaluate(proj)}
    assert result["C-FUNC-UNIT-001"]["eligible_active"] is True
    assert result["C-FUNC-DEP-002"]["eligible_active"] is False
    assert any("TP not hit" in reason
               for reason in result["C-FUNC-DEP-002"]["reasons"])

    assert apply_active(proj, result.values()) == 1
    after = {row["contract_id"]: row for row in evaluate(proj)}
    assert after["C-FUNC-UNIT-001"]["status"] == "active"
    assert after["C-FUNC-DEP-002"]["status"] == "assume"


def test_gate_prefers_mapped_environment_obligations(tmp_path):
    """有 `vplan_map.json` 时，gate 按环境契约义务判，不再看 TP 名字。"""
    from src.layers.l3_decision.vplan import evaluate, link_run

    proj = tmp_path / "proj"
    matrix = proj / "data" / "contract_matrix"
    matrix.mkdir(parents=True)
    fields = ["contract_id", "class", "object", "description", "source_ref",
              "owner", "p_level", "check_method", "check_artifact", "gate",
              "status", "assumption", "remark"]
    ids = ("C-FUNC-UNIT-001", "C-FUNC-DEP-002")
    with (matrix / "func.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for cid in ids:
            writer.writerow({"contract_id": cid, "class": "func", "object": "x",
                             "description": "x", "source_ref": "1",
                             "owner": "dv", "p_level": "P0",
                             "check_method": "scb", "check_artifact": "x",
                             "gate": "g", "status": "assume",
                             "assumption": "planned", "remark": ""})

    run = tmp_path / "run"
    (run / "contract").mkdir(parents=True)
    (run / "evidence").mkdir()
    (run / "sv").mkdir()
    # plan_link 里的 TP 都不可用 —— 映射存在时不应再回落到 TP 口径。
    (run / "contract" / "plan_link.yaml").write_text(yaml.safe_dump({
        "schema": "vplan_contract_link_v1", "module": "p", "spec_hash": "x",
        "contracts": [{"contract_id": cid, "tp_ids": ["TP-VPLAN"],
                       "case_ids": []} for cid in ids],
    }), encoding="utf-8")
    (run / "contract" / "vplan_map.json").write_text(json.dumps({
        "schema": "vplan_contract_map_v1", "module": "p",
        "contracts": {
            "C-FUNC-UNIT-001": {"cases": ["TC-1"],
                                "obligations": ["OBL-OK"],
                                "artifacts": ["foo_scb"]},
            "C-FUNC-DEP-002": {"cases": ["TC-2"],
                               "obligations": ["OBL-MISS"],
                               "artifacts": ["bar_scb"]},
        },
    }), encoding="utf-8")
    (run / "contract" / "obligations.json").write_text(json.dumps([
        {"schema": "obligation_v1", "obligation_id": "OBL-OK",
         "contract_id": "CT-x", "kind": "scb", "case": "TC-1",
         "subject": {"scb": "foo_scb"},
         "predicate": {"fact_type": "scb_result", "op": "executed",
                       "where": {"case": "TC-1", "id": "foo_scb"}},
         "required": True},
        {"schema": "obligation_v1", "obligation_id": "OBL-MISS",
         "contract_id": "CT-x", "kind": "scb", "case": "TC-2",
         "subject": {"scb": "bar_scb"},
         "predicate": {"fact_type": "scb_result", "op": "executed",
                       "where": {"case": "TC-2", "id": "bar_scb"}},
         "required": True},
    ]), encoding="utf-8")
    (run / "evidence" / "ledger.jsonl").write_text(json.dumps({
        "type": "scb_result", "fact_class": "OBSERVED",
        "subject": {"case": "TC-1", "id": "foo_scb"},
        "value": {"exec": 4, "matched": 4, "mismatched": 0},
    }) + "\n", encoding="utf-8")
    (run / "regression_stages.json").write_text(json.dumps({"status": "PASS"}),
                                                encoding="utf-8")
    (run / "sv" / "asset_registry.csv").write_text(
        "artifact,kind,path,owner,status,contract_ids,case_ids,source\n"
        "foo_scb,scb,sv/scbs/foo_scb.sv,dv,candidate,"
        "C-FUNC-UNIT-001,,x\n"
        "bar_scb,scb,sv/scbs/bar_scb.sv,dv,candidate,"
        "C-FUNC-DEP-002,,x\n", encoding="utf-8")
    (run / "coverage").mkdir()
    (run / "coverage" / "case_ir.json").write_text(json.dumps({
        "cases": [{"id": "TC-1", "feats": ["C-FUNC-UNIT-001"],
                   "scb": [{"id": "foo_scb"}]},
                  {"id": "TC-2", "feats": ["C-FUNC-DEP-002"],
                   "scb": [{"id": "bar_scb"}]}],
    }), encoding="utf-8")

    link_run(proj, run)
    result = {row["contract_id"]: row for row in evaluate(proj)}
    ok, miss = result["C-FUNC-UNIT-001"], result["C-FUNC-DEP-002"]
    assert ok["via"] == "vplan_obligations" and ok["eligible_active"] is True
    assert miss["via"] == "vplan_obligations"
    assert miss["eligible_active"] is False
    assert any("OBL-MISS=NOT_EXECUTED" in reason
               for reason in miss["reasons"]), miss["reasons"]


def test_verify_vplan_layout_default_and_legacy(tmp_path, monkeypatch):
    from src.executors.verify.steps.vplan_layout import package_vplan_assets

    calls = []
    monkeypatch.setattr(
        "src.layers.l3_decision.vplan.package_run_assets",
        lambda *a, **k: calls.append(a) or {
            "assets": 0, "copied": 0, "skipped": 0})
    monkeypatch.delenv("SIGNOFFAI_UVM_LAYOUT", raising=False)
    package_vplan_assets(tmp_path, "m")
    assert calls, "verify 默认应生成 sv/ 布局"

    calls.clear()
    monkeypatch.setenv("SIGNOFFAI_UVM_LAYOUT", "legacy")
    package_vplan_assets(tmp_path, "m")
    assert not calls, "legacy 模式应跳过 sv/ 布局"


def test_clean_legacy_dirs_requires_sv(tmp_path):
    from src.layers.l3_decision.vplan import clean_legacy_dirs

    run = tmp_path / "run"
    (run / "agents").mkdir(parents=True)
    (run / "sv").mkdir()
    with pytest.raises(ValueError):
        clean_legacy_dirs(run)

    (run / "sv" / "asset_registry.csv").write_text("artifact\nx\n",
                                                   encoding="utf-8")
    (run / "sv" / "x.sv").write_text("module x; endmodule\n", encoding="utf-8")
    dry = clean_legacy_dirs(run)
    assert dry["present"] == ["agents"]
    assert (run / "agents").is_dir()

    applied = clean_legacy_dirs(run, apply=True)
    assert applied["deleted"] == ["agents"]
    assert not (run / "agents").exists()


def test_mount_vplan_copies_the_project_into_the_run(tmp_path, monkeypatch):
    from src.layers.l2_orchestration.verify_request import mount_vplan

    # 人工审阅门：测试用显式跳过（真实流程必须先 `vplan review`）。
    monkeypatch.setenv("SIGNOFFAI_ALLOW_UNREVIEWED", "1")
    run = tmp_path / "run"
    dest = mount_vplan(str(ROOT), run)
    base = run / "inputs" / "vplan"
    assert dest == base
    assert (base / "docs" / "specs" / "cmdsched.md").is_file()
    assert (base / "data" / "contract_matrix" / "func.csv").is_file()
    assert (base / "data" / "dimensions.csv").is_file()
    assert (base / "cases").is_dir()
    assert (base / "schemas").is_dir()
    assert not (run / "inputs" / "casemodel.yaml").exists()


def test_mount_vplan_rejects_a_case_model_file(tmp_path):
    """旧 case 模型 YAML 不再支持 —— 给错输入要响，而不是静默什么都不做。"""
    import pytest

    from src.layers.l2_orchestration.verify_request import mount_vplan

    cfg = tmp_path / "model.yaml"
    cfg.write_text("version: '1'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="VPlan"):
        mount_vplan(str(cfg), tmp_path / "run")


def test_project_summary_and_run_artifacts(tmp_path):
    """GUI/CLI 共用的只读投影：项目计数 + 运行产物登记。"""
    summary = project_summary(ROOT)
    assert summary["module"] == "npu_sched"
    assert summary["testpoints"] == 66 and summary["cases"] == 12
    assert summary["status"] == "PLAN_ONLY" and summary["signable"] is False

    out = tmp_path / "run_vplan"
    write_plan_only_run(load_project(ROOT), out)
    art = run_artifacts(out)
    assert art["testpoints"] == 66
    assert art["contract_hash"]
    paths = {a["path"]: a["exists"] for a in art["artifacts"]}
    assert paths["coverage/testpoints.json"] is True
    assert paths["inputs/vplan/data/execution_meta.csv"] is True


def test_dplan_map_aligns_with_vplan_contracts():
    """dplan feature/behavior → VPlan feature/requirement/contract 的对齐。"""
    from src.layers.l3_decision.dplan import build_dplan_map

    proj = load_project(ROOT)
    contract = {
        "design_name": "npu_sched",
        "interfaces": [{"name": "cmd"}],
        "features": [
            {"name": "cmd_hs", "description": "cmd valid ready"},
            {"name": "some_unknown_thing", "description": "zzz"},
        ],
        "model_contract": {"ports": [], "behaviors": [{"name": "cmd_hs"}]},
    }
    doc = build_dplan_map(contract, proj)
    assert doc["schema"] == "dplan_map_v1"
    assert doc["features"][0]["vplan_feature_id"] == "F-CMD-HS"
    assert doc["features"][0]["mapped"] is True
    assert doc["features"][1]["mapped"] is False
    assert "F-CMD-HS" in doc["coverage"]["vplan_feature_mapped"]
    assert doc["coverage"]["contract_count"] == 42


def test_uvm_arch_is_built_from_vplan_contracts(tmp_path):
    """UVM 环境架构来自 VPlan 契约/TP/case，而不是 RTL 端口猜测。"""
    from src.layers.l3_decision.vplan.uvm_arch import write_uvm_arch

    proj = load_project(ROOT)
    run = tmp_path / "run_arch"
    write_plan_only_run(proj, run)
    doc = write_uvm_arch(run, proj)
    assert doc["schema"] == "vplan_uvm_arch_v1"
    agents = {a["name"]: a for a in doc["agents"]}
    assert "cmd_if_agent" in agents
    assert "C-IF-HS-001" in agents["cmd_if_agent"]["contracts"]
    assert doc["checkers"] and doc["coverage"] and doc["tests"]
    assert len(doc["tests"]) == 12
    for name in ("uvm_arch.yaml", "uvm_arch.csv", "uvm_arch.md"):
        assert (run / "sv" / name).is_file(), name
