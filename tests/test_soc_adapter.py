"""SoC 参考工程适配层 —— 输入校验与波形定位。"""
from __future__ import annotations

import json
from pathlib import Path

from src.interfaces.cli.soc_adapter import find_wave, load_project, load_run_manifest


ROOT = Path(__file__).resolve().parents[1] / "examples" / "open_npu_soc"


def test_open_npu_soc_project_loads_and_validates():
    project = load_project(ROOT)
    assert project.name
    assert project.validate()["ok"] is True
    assert project.rtl_files and len(project.rtl_hash) == 64
    assert "npu/soc_top.sv" in project.filelist


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
    from src.interfaces.cli.soc_adapter import SoCRun, verify_soc_evidence

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
    from src.interfaces.cli.soc_adapter import list_ips

    ips = list_ips(ROOT)
    assert len(ips) >= 4
    by_id = {ip["id"]: ip for ip in ips}
    assert "IP-NPU-GEMM" in by_id
    assert by_id["IP-NPU-GEMM"]["team"] == "NPU IP"
    assert by_id["IP-NPU-GEMM"]["rtl_present"]
    assert not by_id["IP-NPU-GEMM"]["rtl_missing"]


def test_ip_info_returns_one_ip():
    from src.interfaces.cli.soc_adapter import ip_info

    ip = ip_info(ROOT, "IP-DMA")
    assert ip["name"].startswith("Simple DMA")
    assert ip["status"] in ("released", "in_progress")
    assert ip_info(ROOT, "NOPE") == {}


# ── 两条业务线的边界：IP run 不能冒充 SoC run ──────────────────────

def _fake_run(base: Path, name: str, *, ip_id: str = "",
              status: str = "PASS", mtime: float = 1_000.0) -> Path:
    """造一个最小 run 目录（`soc/soc_run.json`，IP run 再加 `ip/ip_run.json`）。"""
    import os

    run = base / name
    (run / "soc").mkdir(parents=True)
    (run / "soc" / "soc_run.json").write_text(json.dumps({
        "schema": "soc_run_v1",
        "regression": {"status": status, "passed": 1, "failed": 0, "total": 1},
    }), encoding="utf-8")
    if ip_id:
        (run / "ip").mkdir()
        (run / "ip" / "ip_run.json").write_text(json.dumps({
            "schema": "ip_run_v1", "ip_id": ip_id, "result": {"status": status},
        }), encoding="utf-8")
    os.utime(run, (mtime, mtime))
    return run


def test_ip_run_is_labelled_as_ip_not_soc(tmp_path: Path):
    from src.interfaces.cli.soc_adapter import list_soc_runs

    _fake_run(tmp_path, "output_soc_a", mtime=1_000)
    _fake_run(tmp_path, "output_ip_x", ip_id="IP-X", mtime=2_000)
    runs = {r["run"]: r for r in list_soc_runs(tmp_path)}
    assert runs["output_ip_x"]["kind"] == "ip"
    assert runs["output_ip_x"]["ip_id"] == "IP-X"
    assert runs["output_soc_a"]["kind"] == "soc"


def test_latest_soc_run_ignores_ip_runs(tmp_path: Path):
    from src.interfaces.cli.soc_adapter import latest_soc_run

    _fake_run(tmp_path, "output_soc_a", mtime=1_000)
    _fake_run(tmp_path, "output_ip_x", ip_id="IP-X", mtime=2_000)   # 更新
    assert latest_soc_run(tmp_path).endswith("output_soc_a")


def test_ip_status_prefers_the_ips_own_run(tmp_path: Path):
    from src.interfaces.cli.soc_adapter import ip_status

    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "ip_manifest.yaml").write_text(
        "ips:\n"
        "  - {id: IP-X, name: x, team: t, owner: o, version: v0.1, status: released, rtl: []}\n",
        encoding="utf-8")
    (tmp_path / "spec" / "ip_verification_plan.yaml").write_text(
        "ips:\n  IP-X: {tests: [t1], testpoints: [TP-1]}\n", encoding="utf-8")
    _fake_run(tmp_path, "output_soc_a", mtime=1_000)
    _fake_run(tmp_path, "output_ip_x", ip_id="IP-X", mtime=2_000)

    st = ip_status(tmp_path, "IP-X")
    assert st["source_kind"] == "ip_run"
    assert Path(st["source_run"]).name == "output_ip_x"


# ── IP 发布契约：发布包 + SoC 消费绑定 ─────────────────────────────

def _ip_project(root: Path, *, test: str = "t1", tp: str = "TP-1") -> None:
    (root / "spec").mkdir(exist_ok=True)
    (root / "rtl").mkdir(exist_ok=True)
    (root / "rtl" / "x.sv").write_text("module x; endmodule\n", encoding="utf-8")
    (root / "spec" / "ip_manifest.yaml").write_text(
        "ips:\n"
        "  - {id: IP-X, name: x, team: t, owner: o, version: v0.1,"
        "     status: released, rtl: [rtl/x.sv]}\n", encoding="utf-8")
    (root / "spec" / "ip_verification_plan.yaml").write_text(
        "ips:\n"
        f"  IP-X:\n"
        f"    methodology: ip_cdv\n"
        f"    tests: [{test}]\n"
        f"    testpoints: [{tp}]\n"
        f"    coverage: {{strategy: feature_coverpoint, target: 95}}\n",
        encoding="utf-8")


def _stage_envidence(run: Path, rel: str = "inputs/a.txt") -> None:
    """造一个自洽的 signoff_evidence（package_hash 与文件哈希对得上）。"""
    import hashlib

    pkg = run / "signoff_evidence"
    f = pkg / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
    h = hashlib.sha256(b"x").hexdigest()
    canon = json.dumps({"files": [(rel, h)]}, ensure_ascii=False,
                       sort_keys=True, default=str)
    (pkg / "manifest.json").write_text(json.dumps({
        "files": [{"path": rel, "sha256": h}],
        "package_hash": hashlib.sha256(canon.encode("utf-8")).hexdigest(),
    }), encoding="utf-8")


def _stage_ip_run(root: Path, ip_id: str, *, test: str = "t1",
                  tp: str = "TP-1", evidence: bool = True) -> Path:
    run = _fake_run(root, f"output_ip_{ip_id}", ip_id=ip_id, mtime=2_000)
    (run / "regression_run").mkdir()
    (run / "regression_run" / "report.json").write_text(json.dumps({
        "tasks": [{"name": test, "status": "pass"}]}), encoding="utf-8")
    (run / "coverage").mkdir()
    (run / "coverage" / "tp_matrix.json").write_text(json.dumps({
        "rows": [{"tp_id": tp, "status": "HIT", "test": test}]}), encoding="utf-8")
    if evidence:
        _stage_envidence(run)
    return run


def test_build_and_verify_ip_release(tmp_path: Path):
    from src.interfaces.cli.soc_adapter import (
        build_ip_release, ip_release_package, verify_ip_release,
    )

    _ip_project(tmp_path)
    _stage_ip_run(tmp_path, "IP-X")

    result = build_ip_release(tmp_path, "IP-X")
    assert result["ok"] is True
    assert result["released"] is True, result["blocking"]
    pkg = ip_release_package(tmp_path, "IP-X")
    assert pkg["schema"] == "ip_release_v1"
    assert pkg["methodology"] == "ip_cdv"
    assert pkg["source_kind"] == "ip_run"
    # 覆盖**没有测量**就是 None，不拿 SoC 数字冒充
    assert pkg["coverage"]["measured"] is False
    assert pkg["coverage"]["functional_pct"] is None
    assert verify_ip_release(tmp_path, "IP-X")["ok"] is True


def test_release_marks_blocking_criteria_instead_of_passing(tmp_path: Path):
    from src.interfaces.cli.soc_adapter import build_ip_release, verify_ip_release

    _ip_project(tmp_path)
    _stage_ip_run(tmp_path, "IP-X", evidence=False)   # 缺证据包

    result = build_ip_release(tmp_path, "IP-X")
    assert result["released"] is False
    assert "evidence_ok" in result["blocking"]
    check = verify_ip_release(tmp_path, "IP-X")
    assert check["ok"] is False
    assert any(i["check"] == "not_released" for i in check["issues"])


def test_release_goes_stale_when_rtl_changes(tmp_path: Path):
    from src.interfaces.cli.soc_adapter import (
        build_ip_release, soc_ip_binding, verify_ip_release,
    )

    _ip_project(tmp_path)
    _stage_ip_run(tmp_path, "IP-X")
    assert build_ip_release(tmp_path, "IP-X")["released"] is True

    (tmp_path / "rtl" / "x.sv").write_text("module x; wire y; endmodule\n",
                                           encoding="utf-8")
    check = verify_ip_release(tmp_path, "IP-X")
    assert check["ok"] is False
    assert any(i["check"] == "rtl_hash_mismatch" for i in check["issues"])
    assert soc_ip_binding(tmp_path)[0]["state"] == "STALE"


def test_soc_run_records_consumed_ip_binding(tmp_path: Path):
    from src.interfaces.cli.soc_adapter import SoCRun, load_project

    run = SoCRun(load_project(ROOT), tmp_path / "run")
    run.finish({"status": "PASS", "passed": 1, "failed": 0,
                "unknown": 0, "total": 1})
    doc = json.loads((tmp_path / "run" / "soc" / "soc_run.json").read_text(
        encoding="utf-8"))
    rows = doc["consumed_ips"]
    assert rows and all("state" in r for r in rows)
    # 示例工程还没生成发布包：released 的 IP 应为 MISSING（不是静默通过）
    states = {r["ip_id"]: r["state"] for r in rows}
    assert states["IP-DMA"] == "MISSING"
