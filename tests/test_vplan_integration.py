"""VPlan 项目 → SignOffAI 规划/契约 IR 的接入测试。

钉住三件事：

1. 源数据计数与状态**原样**进入 IR（42 assume / 66 planned / 12 planned）；
2. 不读 `casemodel.yaml`，项目里也没有它；
3. 只规划 run 明确写 `PLAN_ONLY`，不产生 `signoff_evidence/`。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.layers.l3_decision.vplan import (
    build_execution_model, build_payload, load_project,
    write_execution_model, write_plan_only_run,
)

ROOT = Path(__file__).resolve().parents[1] / "specs" / "npu_sched"


def test_load_project_reads_current_source():
    proj = load_project(ROOT)
    assert proj.module == "npu_sched"
    assert proj.dut == "CMDSCHED"
    assert len(proj.requirements) == 20
    assert len(proj.features) == 39
    assert len(proj.topics) == 10
    assert len(proj.contracts) == 42
    assert proj.status_counts == {"assume": 42}
    assert len(proj.testpoints) == 66
    assert proj.tp_status_counts == {"planned": 66}
    assert len(proj.cases) == 12
    assert proj.case_status_counts == {"planned": 12}
    assert not (ROOT / "casemodel.yaml").exists()


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
    assert link["status_counts"] == {"assume": 42}
    assert all(row["status"] == "assume" for row in link["contracts"])


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
    assert link["status_counts"] == {"assume": 42}
    assert len(link["contracts"]) == 42
    assert len(link["cases"]) == 12

    tp_doc = json.loads(
        (out / "coverage" / "testpoints.json").read_text(encoding="utf-8"))
    assert tp_doc["count"] == 66
    assert tp_doc["methodology"]["counts"]["contracts_by_status"] == {
        "assume": 42}


def test_execution_model_projects_vplan_cases(tmp_path):
    proj = load_project(ROOT)
    model = build_execution_model(proj)

    assert len(model["dimensions"]) == 12
    assert len(model["themes"]) == 12
    assert len(model["cases"]["cases"]) == 12
    assert {t["test"] for t in model["themes"]} == {
        c["test_name"] for c in proj.cases
    }
    assert all(t["dimensions"] == ["*"] for t in model["themes"])
    assert all(c["requirements"] for c in model["cases"]["cases"])
    assert (ROOT / "rtl" / "npu_sched.sv").is_file()

    path = write_execution_model(proj, tmp_path)
    from src.layers.l3_decision.casemodel.repository import load_models_from_text

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
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    summary = package_run_assets(tmp_path, "foo")
    assert summary["copied"] == 6
    assert (tmp_path / "sv" / "interface" / "foo_if.sv").is_file()
    assert (tmp_path / "sv" / "agents" / "foo" / "foo_driver.sv").is_file()
    assert (tmp_path / "sv" / "env" / "foo_env.sv").is_file()
    assert (tmp_path / "sv" / "coverage" / "foo_cov.sv").is_file()
    assert (tmp_path / "sv" / "interface" / "foo_cov_if.sv").is_file()
    assert (tmp_path / "sv" / "test" / "foo_test.sv").is_file()
    text = (tmp_path / "sv" / "interface" / "foo_if.sv").read_text(
        encoding="utf-8")
    assert "// ARTIFACT: foo_if" in text
    assert len(scan_assets(tmp_path)) == 6


def test_explicit_casemodel_marker(tmp_path):
    from src.layers.l2_orchestration.verify_request import copy_casemodel

    src = tmp_path / "model.yaml"
    src.write_text("version: '1'\n", encoding="utf-8")
    dest = copy_casemodel(str(src), tmp_path / "run")
    assert dest.is_file()
    assert (dest.parent / ".casemodel_explicit").is_file()
