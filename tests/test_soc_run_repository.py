"""SoC run 也要出现在「运行历史」里（它没有 docs/manifest.json）。"""
from __future__ import annotations

import json
from pathlib import Path

from src.layers.l2_orchestration.run_repository import RunRepository


def _soc_run(tmp_path: Path) -> Path:
    run = tmp_path / "output_soc_demo_20260101"
    (run / "soc").mkdir(parents=True)
    (run / "signoff_evidence").mkdir()
    (run / "signoff_evidence" / "manifest.json").write_text("{}", encoding="utf-8")
    (run / "soc" / "soc_run.json").write_text(json.dumps({
        "schema": "soc_run_v1",
        "project": {"name": "open_npu_soc", "rtl_hash": "abc"},
        "run": {"run_id": run.name},
        "regression": {"status": "PASS", "passed": 2, "failed": 0,
                       "unknown": 0, "total": 2},
        "waves": [{"path": "regression_run/build/test/waves/x.db"}],
    }), encoding="utf-8")
    return run


def test_soc_run_is_discovered_without_manifest(tmp_path: Path):
    run = _soc_run(tmp_path)
    repo = RunRepository(str(tmp_path / "output"))
    runs = repo.discover_runs(limit=10)
    entry = next(r for r in runs if r["run_id"] == run.name)
    assert entry["kind"] == "soc"
    assert entry["state"] == "completed"
    assert entry["verdict"] == "PASS"
    assert entry["evidence_valid"] is True
    assert entry["stages"][0]["status"] == "passed"


def test_get_soc_run_returns_soc_manifest(tmp_path: Path):
    run = _soc_run(tmp_path)
    repo = RunRepository(str(tmp_path / "output"))
    got = repo.get_run(run.name)
    assert got["kind"] == "soc"
    assert got["soc"]["regression"]["passed"] == 2
    assert got["project"] == "open_npu_soc"
