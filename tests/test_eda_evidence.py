"""EDA 证据：collect / compare / decompose / export / gate eda_evidence / 自动拆子目标。"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

from src.workspace import WorkspaceZones, new_proposal
from src.workspace.gate import run_gate
from src.workspace.gate.domain_checks import eda_evidence
from src.workspace.harness import Harness, HarnessConfig
from src.workspace.harness.domain import (collect_evidence, compare_evidence,
                                          decompose_coverage, export_evidence)


def _fake_run(tmp_path: Path, *, functional=63.0, failed=0,
              status="PASS") -> Path:
    root = tmp_path / "run"
    (root / "sim" / "coverage").mkdir(parents=True)
    (root / "coverage").mkdir(parents=True)
    (root / "status").mkdir(parents=True)
    (root / "contract").mkdir(parents=True)
    (root / "regression_stages.json").write_text(json.dumps({
        "status": status,
        "blocked_at": "" if status == "PASS" else "p0",
        "stages": [{"name": "p0", "status": status, "passed": 57,
                    "failed": failed, "total": 57}],
    }), encoding="utf-8")
    (root / "sim" / "coverage" / "coverage_result.json").write_text(json.dumps({
        "plan_coverage": {"functional_pct": functional, "merged": 89, "stores": 89},
        "code_coverage_plan": {"branch_pct": 70.0, "toggle_pct": 60.45,
                               "statement_pct": 76.92},
        "tp_matrix": {"counts": {"OBSERVED": 140, "UNOBSERVED": 60}},
    }), encoding="utf-8")
    (root / "coverage" / "coverage_holes.json").write_text(json.dumps({
        "counts": {"holes": 200, "signoff_gap": 140, "stimulus_gap": 60},
        "holes": [{"dimension": "D_CMD_DISP_RDY",
                   "coverpoint": "cp_cmd_disp_rdy"}],
    }), encoding="utf-8")
    (root / "status" / "closure_plan.json").write_text(json.dumps({
        "continue": True, "closure_rate": 0.33, "total": 7826, "done": 2626,
        "actions": [{"action": "ADD_MONITOR", "target": "OBL-A"},
                    {"action": "ADD_MONITOR", "target": "OBL-B"}],
    }), encoding="utf-8")
    (root / "contract" / "contract_manifest.json").write_text(json.dumps({
        "contract_id": "C-TEST", "obligations": 46, "cases": 20,
    }), encoding="utf-8")
    return root


def _zones(tmp_path: Path) -> WorkspaceZones:
    src = tmp_path / "baseline"
    (src / "rtl").mkdir(parents=True)
    (src / "rtl" / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    return WorkspaceZones.init(tmp_path / "ws", src)


def _proposal(zones: WorkspaceZones, evidence: dict, target: float):
    zones.write_staging("rtl/a.sv", "module a; // fixed\nendmodule\n")
    zones.write_staging(".evidence/001.log", "ok\n")
    return new_proposal(
        "补覆盖率", zones,
        evidence={"before": "63%", "after": f"{evidence['coverage']['functional_pct']}%",
                  "commands": [{"cmd": "vplan execute", "exit_code": 0,
                                "log": "staging/.evidence/001.log"}],
                  "logs": ["staging/.evidence/001.log"],
                  "reasoning_trace": "按缺口补 monitor",
                  "eda": {"after": evidence, "target": target,
                          "run_dir": evidence["run_dir"]}},
        open_questions=[])


def test_collect_and_compare(tmp_path):
    run = _fake_run(tmp_path)
    evidence = collect_evidence(run, target=95)
    assert evidence["exists"] is True
    assert evidence["coverage"]["functional_pct"] == 63.0
    assert evidence["regression"]["failed"] == 0
    assert evidence["holes"]["counts"]["holes"] == 200
    assert len(evidence["hashes"]) == 5

    after = _fake_run(tmp_path / "after", functional=80.0)
    comparison = compare_evidence(evidence, collect_evidence(after, target=95))
    assert comparison["delta"]["functional_pct"] == 17.0
    assert comparison["improved"] is True


def test_decompose_coverage_uses_closure_actions(tmp_path):
    evidence = collect_evidence(_fake_run(tmp_path), target=95)
    subgoals = decompose_coverage(evidence, 95, max_subgoals=6)
    assert len(subgoals) == 3
    assert subgoals[0]["title"].startswith("ADD_MONITOR: OBL-A")
    assert "重跑验证" in subgoals[-1]["title"]
    assert decompose_coverage(evidence, 60) == []


def test_eda_gate_blocks_below_target(tmp_path):
    zones = _zones(tmp_path)
    evidence = collect_evidence(_fake_run(tmp_path / "run"), target=95)
    proposal = _proposal(zones, evidence, 95)
    report = run_gate(proposal, zones, extra_checks=[eda_evidence])
    assert report["ok"] is False
    assert any(row["name"] == "eda_coverage" and row["status"] == "fail"
               for row in report["checks"])

    evidence_ok = collect_evidence(_fake_run(tmp_path / "run2", functional=96.0),
                                   target=95)
    proposal_ok = _proposal(zones, evidence_ok, 95)
    report_ok = run_gate(proposal_ok, zones, extra_checks=[eda_evidence])
    assert report_ok["ok"] is True


def test_export_evidence_prefers_signoff_package(tmp_path):
    run = _fake_run(tmp_path)
    partial = export_evidence(run)
    assert partial["ok"] is True and partial["complete"] is False
    assert partial["source"] == "run" and partial["files"] >= 5
    with zipfile.ZipFile(partial["zip_path"]) as archive:
        names = set(archive.namelist())
        assert "export_manifest.json" in names
        assert "regression_stages.json" in names

    package = run / "signoff_evidence"
    (package / "verdict").mkdir(parents=True)
    (package / "manifest.json").write_text('{"run": "run"}', encoding="utf-8")
    (package / "verdict" / "signoff_evidence.json").write_text("{}", encoding="utf-8")
    full = export_evidence(run, tmp_path / "out" / "evidence.zip")
    assert full["complete"] is True and full["source"] == "signoff_evidence"
    with zipfile.ZipFile(full["zip_path"]) as archive:
        assert "verdict/signoff_evidence.json" in archive.namelist()
    with pytest.raises(ValueError):
        export_evidence(tmp_path / "missing")


def test_harness_export_tool_writes_staging(tmp_path):
    zones = _zones(tmp_path)
    zones.write_staging(".evidence/runs/run-1/regression_stages.json",
                        '{"status": "PASS", "stages": []}\n')
    zones.write_staging(".evidence/runs/run-1/workspace_verify.log", "ok\n")
    decisions = [
        {"tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"tool": "export_evidence",
         "args": {"run_dir": ".evidence/runs/run-1"}},
        {"tool": "propose",
         "args": {"before": "无导出", "after": "证据 zip 已生成",
                  "reasoning_trace": "run_verify 后自动导出",
                  "open_questions": []}},
    ]
    queue = list(decisions)
    harness = Harness(zones, config=HarnessConfig(),
                      planner=lambda payload: queue.pop(0))
    result = harness.run("导出证据")
    assert result["status"] == "proposal"
    exports = harness.session.working["exports"]
    assert exports and exports[0]["ok"] is True
    assert result["proposal"]["evidence"]["exports"][0]["zip_path"]
    zip_path = Path(exports[0]["zip_path"])
    assert zip_path.is_file()
    zip_path.relative_to(zones.staging)
    with zipfile.ZipFile(zip_path) as archive:
        assert "regression_stages.json" in archive.namelist()


def test_harness_auto_decomposes_from_evidence(tmp_path):
    zones = _zones(tmp_path)
    evidence_dir = _fake_run(tmp_path / "evidence")
    decisions = [
        {"tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"tool": "complete_subgoal", "args": {"summary": "OBL-A 对应 monitor 已补"}},
        {"tool": "complete_subgoal", "args": {"summary": "OBL-B 对应 monitor 已补"}},
        {"tool": "complete_subgoal", "args": {"summary": "重跑证据已收集"}},
        {"tool": "propose",
         "args": {"before": "coverage 63%", "after": "coverage 63%",
                  "reasoning_trace": "按 closure actions 补 monitor",
                  "open_questions": ["覆盖率仍未达 95%"]}},
    ]
    queue = list(decisions)
    config = HarnessConfig(goal="coverage", coverage_target=95,
                           evidence=str(evidence_dir), max_subgoals=6)
    harness = Harness(zones, config=config, planner=lambda payload: queue.pop(0))
    result = harness.run("把覆盖率补到 95%")

    assert result["status"] == "proposal"
    assert len(harness.session.subgoals) == 3
    assert harness.session.subgoals[0]["title"].startswith("ADD_MONITOR:")
    eda = result["proposal"]["evidence"]["eda"]
    assert eda["target"] == 95.0
    assert eda["after"]["coverage"]["functional_pct"] == 63.0
    report = run_gate(
        __import__("src.workspace.proposal.schema", fromlist=["Proposal"]).Proposal.load(
            zones, result["proposal_id"]),
        zones, extra_checks=[eda_evidence])
    assert report["ok"] is False
