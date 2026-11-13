"""M0 影子模式：新链路必须**复现**旧结论（停点：一致率 100%）。

造一份最小的 run 目录（case_ir + 一条 case_cov），跑 `run_shadow`：
- 账本被写入，哈希链完整；
- 推导出的组状态 / case_status 与 case_cov 里记的一致；
- 重复跑幂等（同样的包不会再写一遍）。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.ir_plane.contract import read_ledger, run_shadow, verify_chain

CASE_IR = {
    "module": "demo",
    "cases": [{
        "id": "CASE-A",
        "groups": [{
            "group": "CG-A", "name": "功能A", "cell": "CELL-A-P0",
            "required_layers": ["functional", "timing", "data"],
            "tp_ids": ["TP-1"],
        }],
        "sva": [{"id": "SVA-X", "cell": "CELL-A-P0"}],
        "scb": [{"id": "SB-X", "cell": "CELL-A-P0", "evidence": "aggregate"}],
        "not_applicable": {},
    }],
}

CASE_COV = {
    "schema": "case_cov_v1", "case_id": "CASE-A", "tst_id": "TST-A@1",
    "seed": 1, "run_id": "run_x", "task": "t1",
    "timing_ok": True,
    "scb_summary": {"total": 10, "matched": 10, "mismatched": 0},
    "tp": [{"tp_id": "TP-1", "coverpoint": "cp_a", "owned": ["b0", "b1"],
            "hits": {"b0": 3, "b1": 2}, "pct": 100.0, "status": "SIGNED_OFF"}],
    "groups": [{"group": "CG-A", "cell": "CELL-A-P0",
                "functional": {"status": "PROVEN"},
                "timing": {"status": "PROVEN"},
                "data": {"status": "PROVEN"},
                "path": {"status": "NOT_APPLICABLE"},
                "result": "PROVEN"}],
    "sva": [{"id": "SVA-X", "cell": "CELL-A-P0", "status": "PROVEN", "fail": 0}],
    "scb": [{"id": "SB-X", "cell": "CELL-A-P0", "status": "PROVEN",
             "exec": 10, "matched": 10, "mismatched": 0}],
    "case_status": "VERIFIED",
}


def _run(tmp_path: Path, cov=None) -> Path:
    root = tmp_path / "run_shadow_20260101_000000"
    (root / "coverage" / "case_cov" / "p0").mkdir(parents=True)
    (root / "coverage" / "case_ir.json").write_text(
        json.dumps(CASE_IR, ensure_ascii=False), encoding="utf-8")
    (root / "coverage" / "case_cov" / "p0" / "t1.json").write_text(
        json.dumps(cov or CASE_COV, ensure_ascii=False), encoding="utf-8")
    return root


def test_shadow_reproduces_existing_conclusions(tmp_path):
    root = _run(tmp_path)
    report = run_shadow(root)
    assert report["available"] is True
    assert report["compare"]["mismatched"] == 0, report["compare"]["diffs"]
    assert report["ok"] is True
    assert report["obligations"] == 5          # 3 层 + 1 SVA + 1 SCB
    assert report["facts"] > 0


def test_shadow_writes_a_verifiable_ledger(tmp_path):
    root = _run(tmp_path)
    run_shadow(root)
    assert (root / "evidence" / "ledger.jsonl").is_file()
    assert verify_chain(root)["ok"] is True
    assert len(read_ledger(root)) > 0


def test_shadow_is_idempotent(tmp_path):
    root = _run(tmp_path)
    run_shadow(root)
    before = len(read_ledger(root))
    run_shadow(root)
    assert len(read_ledger(root)) == before


def test_mismatch_is_reported_not_hidden(tmp_path):
    root = _run(tmp_path)
    broken = json.loads(json.dumps(CASE_COV))
    broken["groups"][0]["result"] = "MISSING"     # 旧结论说缺，事实显示全中
    (root / "coverage" / "case_cov" / "p0" / "t1.json").write_text(
        json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    report = run_shadow(root)
    assert report["ok"] is False
    assert any(d["check"] == "group" for d in report["compare"]["diffs"])


def test_batch_test_without_case_is_skipped(tmp_path):
    root = _run(tmp_path)
    batch = {"schema": "case_cov_v1", "task": "npu_basic_test_seed_1",
             "case_id": "", "tp": []}
    (root / "coverage" / "case_cov" / "p0" / "batch.json").write_text(
        json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    report = run_shadow(root)
    assert report["bundles"] == 1
    assert report["bundles_skipped_no_case"] == 1
