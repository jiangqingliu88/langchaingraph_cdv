"""签核证据包 `signoff_evidence_v1` —— 可对外交换的那份。

它把散在各处的证据收成**一份带 schema 的 JSON**：RTL 哈希、TP IR 哈希、
计划覆盖率、TP 矩阵、caveat、建议动作、不可达嫌疑、LLM 审计摘要。

两条纪律：
  · `seed_diversity: null` —— 没验就是没验，`None ≠ 已验证`；
  · `unreachable_justifications` 只列 `SUSPECT`（0 命中），**不冒充"已证明不可达"**。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.executors.audit.main import _build_signoff_evidence


def _run(tmp_path: Path) -> Path:
    run = tmp_path / "run_x"
    (run / "rtl").mkdir(parents=True)
    (run / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    (run / "coverage").mkdir()
    (run / "coverage" / "methodology.json").write_text(json.dumps({
        "framework": "signoff-methodology", "version": "1.0",
        "artifacts": {"testpoints_yaml": {"sha256": "a" * 64}},
    }), encoding="utf-8")
    (run / "coverage" / "tp_matrix.json").write_text(json.dumps({
        "counts": {"HIT": 3, "MISS": 1, "OBSERVED": 0, "UNOBSERVED": 2,
                   "BACKDOOR_HIT": 1, "BACKDOOR_MISS": 0, "UNMAPPED": 0},
        "total": 7, "drivable": 4, "drivable_hit": 3, "drivable_pct": 75.0,
        "backdoor": 1, "backdoor_hit": 1, "backdoor_pct": 100.0,
        "missed": [{"tp_id": "TP-MISS"}],
        "rows": [
            {"tp_id": "TP-U1", "coverpoint": "cp_queue_level", "bin": "full",
             "kind": "observe", "status": "UNOBSERVED"},
            {"tp_id": "TP-U2", "coverpoint": "cp_queue_level", "bin": "empty",
             "kind": "observe", "status": "UNOBSERVED"},
        ],
    }), encoding="utf-8")
    (run / "coverage" / "constraint_status.json").write_text(json.dumps({
        "constraint_generated": True, "constraint_policy_applied": False,
        "backed_policy_count": 5, "unbacked_policy_count": 6,
    }), encoding="utf-8")
    (run / "sim" / "coverage").mkdir(parents=True)
    (run / "sim" / "coverage" / "coverage_result.json").write_text(json.dumps({
        "plan_coverage": {"functional_pct": 94.28, "stores": 244,
                          "ucdb": str(run / "sim/coverage/plan_merged.ucdb"),
                          "single_test_pct": 68.57},
    }), encoding="utf-8")
    (run / "docs").mkdir()
    (run / "docs" / "llm_audit.jsonl").write_text('{"site":"x"}\n', encoding="utf-8")
    return run


def _evidence(run: Path, verdict="NEEDS_FIX", status="REJECTED"):
    signoff = {"verdict": verdict, "signoff_status": status, "coverage": 94.28,
               "gates": {"coverage_ok": False}}
    tp = json.loads((run / "coverage" / "tp_matrix.json").read_text(encoding="utf-8"))
    sem = {"constraint_policy_applied": None, "cg_dut_hit_gt_zero": True,
           "ucdb_nonzero_bins": True}
    return _build_signoff_evidence(run, signoff, tp, sem, ["caveat"])


def test_schema_and_hashes(tmp_path):
    ev = _evidence(_run(tmp_path))
    assert ev["schema"] == "signoff_evidence_v1"
    assert len(ev["rtl_version_hash"]) == 64
    assert ev["testpoint_ir_sha256"] == "a" * 64
    assert len(ev["llm_audit_digest"]) == 64


def test_plan_coverage_is_the_gate_source(tmp_path):
    ev = _evidence(_run(tmp_path))
    assert ev["coverage"]["plan_pct"] == 94.28
    assert ev["coverage"]["single_test_pct"] == 68.57
    assert ev["coverage"]["merged_stores"] == 244
    assert ev["coverage"]["gate_passed"] is False


def test_observe_only_zero_hits_are_suspects_not_verdicts(tmp_path):
    ev = _evidence(_run(tmp_path))
    sus = ev["unreachable_justifications"]
    assert {u["tp_id"] for u in sus} == {"TP-U1", "TP-U2"}
    assert all(u["status"] == "SUSPECT" for u in sus)
    assert all("0 hits" in u["evidence"] for u in sus)


def test_seed_diversity_is_null_until_verified(tmp_path):
    ev = _evidence(_run(tmp_path))
    assert ev["seed_diversity"] is None
    assert "尚未实现" in ev["no_test_success"]


def test_caveat_actions_include_constraint_backfill(tmp_path):
    ev = _evidence(_run(tmp_path))
    actions = {a["action"] for a in ev["caveat_actions"]}
    assert "BACKFILL_CONSTRAINTS" in actions        # 读 constraint_status.json
    assert "GENERATE_DIRECTED_TEST" in actions      # tp_matrix.missed
