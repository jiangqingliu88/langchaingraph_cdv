"""Proposal → Gate → approve → promote 的受控通道。"""
from __future__ import annotations

import sys
from pathlib import Path

from src.workspace import WorkspaceZones, new_proposal
from src.workspace.gate import approve_gate, load_gate, promote, run_gate
from src.workspace.proposal.schema import Proposal


def _zones(tmp_path: Path) -> WorkspaceZones:
    src = tmp_path / "baseline"
    (src / "rtl").mkdir(parents=True)
    (src / "rtl" / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    return WorkspaceZones.init(tmp_path / "ws", src)


def _log(zones: WorkspaceZones, text: str = "ok") -> str:
    rel = ".evidence/001.log"
    zones.write_staging(rel, text)
    return f"staging/{rel}"


def _proposal(zones: WorkspaceZones, *, questions=(), modify=True):
    if modify:
        zones.write_staging("rtl/a.sv", "module a; // fix\nendmodule\n")
    else:
        zones.write_staging("rtl/new.sv", "module new; endmodule\n")
    log = _log(zones)
    return new_proposal(
        "补齐边界用例", zones,
        evidence={"before": "coverage 82%", "after": "coverage 94%",
                  "commands": [{"cmd": "python -c pass", "exit_code": 0,
                                "log": log}],
                  "logs": [log], "reasoning_trace": "先读覆盖率报告，再补边界"},
        open_questions=list(questions))


def test_gate_passes_and_marks_human_question(tmp_path):
    zones = _zones(tmp_path)
    proposal = _proposal(zones, questions=["line 47 复位行为未验证"])
    report = run_gate(proposal, zones)
    assert report["ok"] is True
    assert report["human_required"] is True
    assert load_gate(zones, proposal.proposal_id)["ok"] is True
    assert (zones.gate_path(proposal.proposal_id)).is_file()


def test_gate_rejects_tampered_staging(tmp_path):
    zones = _zones(tmp_path)
    proposal = _proposal(zones)
    zones.write_staging("rtl/a.sv", "module a; // changed after proposal\nendmodule\n")
    report = run_gate(proposal, zones)
    assert report["ok"] is False
    assert any(row["name"] == "changed_files" and row["status"] == "fail"
               for row in report["checks"])


def test_gate_rejects_moved_main_baseline(tmp_path):
    zones = _zones(tmp_path)
    proposal = _proposal(zones)
    # 模拟另一条通道先改了 main（用 promote 之外的直接写只发生在测试里）
    (zones.main / "rtl" / "a.sv").write_text("module a; // moved\nendmodule\n",
                                             encoding="utf-8")
    report = run_gate(proposal, zones)
    assert report["ok"] is False
    assert any(row["name"] == "main_baseline" and row["status"] == "fail"
               for row in report["checks"])


def test_human_question_blocks_promote_until_approved(tmp_path):
    zones = _zones(tmp_path)
    proposal = _proposal(zones, questions=["line 47 复位行为未验证"])
    run_gate(proposal, zones)
    loaded = Proposal.load(zones, proposal.proposal_id)

    denied = promote(loaded, zones, by="jiang")
    assert "error" in denied
    assert "fix" not in (zones.main / "rtl" / "a.sv").read_text(encoding="utf-8")

    assert "error" in approve_gate(loaded, zones, by="")
    approved = approve_gate(loaded, zones, by="jiang", comment="确认 line 47")
    assert approved["approved"] is True

    result = promote(Proposal.load(zones, proposal.proposal_id), zones, by="jiang")
    assert result["ok"] is True
    assert "fix" in (zones.main / "rtl" / "a.sv").read_text(encoding="utf-8")
    assert zones.ledger_path().is_file()
    assert "补齐边界用例" in zones.ledger_path().read_text(encoding="utf-8")
    assert result["backup"] and Path(result["backup"]).is_dir()


def test_manual_proposal_runs_commands_and_gates(tmp_path):
    """手工通道：staging 改动 + --run 真命令 → 同一份 proposal/gate 契约。"""
    from src.app.services.workspace_service import create_proposal

    zones = _zones(tmp_path)
    zones.write_staging("rtl/a.sv", "module a; // manual\nendmodule\n")
    result = create_proposal(
        zones.root, "手工修边界", before="coverage 82%", after="coverage 94%",
        reasoning_trace="手工改了 a.sv 并跑了一条命令",
        commands=[[sys.executable, "-c", "print('ok')"]],
        open_questions=["line 47 复位未验证"])
    assert result["ok"] is True
    proposal = Proposal.load(zones, result["proposal_id"])
    assert proposal.changed_files[0]["path"] == "staging/rtl/a.sv"
    assert proposal.evidence["commands"][0]["exit_code"] == 0
    report = run_gate(proposal, zones)
    assert report["ok"] is True
    assert report["human_required"] is True


def test_promote_adds_new_file_and_updates_fingerprint(tmp_path):
    zones = _zones(tmp_path)
    proposal = _proposal(zones, modify=False)
    report = run_gate(proposal, zones)
    assert report["ok"] is True
    before = zones.fingerprint("main")
    result = promote(Proposal.load(zones, proposal.proposal_id), zones)
    assert result["ok"] is True
    assert (zones.main / "rtl" / "new.sv").is_file()
    assert zones.fingerprint("main") != before
    assert Proposal.load(zones, proposal.proposal_id).status == "promoted"
