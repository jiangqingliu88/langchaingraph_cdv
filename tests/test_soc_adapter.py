"""SoC 参考工程适配层 —— 输入校验与波形定位。"""
from __future__ import annotations

import json
from pathlib import Path

from src.cli.soc_adapter import find_wave, load_project, load_run_manifest


ROOT = Path(__file__).resolve().parents[1] / "examples" / "open_npu_soc"


def test_open_npu_soc_project_loads_and_validates():
    project = load_project(ROOT)
    assert project.name
    assert project.validate()["ok"] is True
    assert project.rtl_files and len(project.rtl_hash) == 64
    assert "rtl/soc_top.sv" in project.filelist


def test_find_wave_prefers_manifest_entry(tmp_path: Path):
    db = tmp_path / "regression_run" / "build" / "test" / "waves" / "x.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"db")
    (tmp_path / "soc").mkdir()
    (tmp_path / "soc" / "soc_run.json").write_text(json.dumps({
        "schema": "soc_run_v1",
        "waves": [{"path": "regression_run/build/test/waves/x.db"}],
    }), encoding="utf-8")
    assert load_run_manifest(tmp_path)["schema"] == "soc_run_v1"
    assert find_wave(tmp_path) == db


def test_find_wave_falls_back_to_glob(tmp_path: Path):
    db = tmp_path / "regression_run" / "build" / "test" / "waves" / "y.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"db")
    assert find_wave(tmp_path) == db


def test_soc_run_records_context_artifacts_events_and_evidence(tmp_path: Path):
    from src.cli.soc_adapter import SoCRun, verify_soc_evidence

    project = load_project(ROOT)
    run = SoCRun(project, tmp_path / "run")
    (tmp_path / "run" / "regression_run").mkdir(parents=True)
    (tmp_path / "run" / "regression_run" / "report.json").write_text(
        json.dumps({"stats": {"pass": 2, "fail": 0}}), encoding="utf-8")
    summary = run.finish({"status": "PASS", "passed": 2, "failed": 0,
                          "unknown": 0, "total": 2})

    root = tmp_path / "run"
    assert (root / "docs" / "run_context.json").is_file()
    assert (root / "docs" / "events.jsonl").is_file()
    assert (root / "artifacts" / "artifacts.json").is_file()
    assert (root / "soc" / "soc_run.json").is_file()
    assert summary["evidence"]["path"].endswith("manifest.json")
    check = verify_soc_evidence(root)
    assert check["ok"] is True
    # 输入（spec/RTL/TB）真的进包了，不是只有执行产物
    manifest = json.loads((root / "signoff_evidence" / "manifest.json")
                          .read_text(encoding="utf-8"))
    sections = {f["section"] for f in manifest["files"]}
    assert sections == {"inputs", "execution"}


def test_ip_manifest_lists_teams_and_rtl_presence():
    from src.cli.soc_adapter import list_ips

    ips = list_ips(ROOT)
    assert len(ips) >= 4
    by_id = {ip["id"]: ip for ip in ips}
    assert "IP-NPU-GEMM" in by_id
    assert by_id["IP-NPU-GEMM"]["team"] == "NPU IP"
    assert by_id["IP-NPU-GEMM"]["rtl_present"]
    assert not by_id["IP-NPU-GEMM"]["rtl_missing"]


def test_ip_info_returns_one_ip():
    from src.cli.soc_adapter import ip_info

    ip = ip_info(ROOT, "IP-DMA")
    assert ip["name"].startswith("Simple DMA")
    assert ip["status"] in ("released", "in_progress")
    assert ip_info(ROOT, "NOPE") == {}
