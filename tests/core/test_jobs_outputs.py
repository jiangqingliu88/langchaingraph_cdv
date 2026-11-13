from __future__ import annotations

from src.runtime_plane.core.jobs.outputs import OutputRegistry, OutputSpec
from src.runtime_plane.core.jobs.spec import JobResult
from src.runtime_plane.core.runtime.artifacts import ArtifactStore


def _result(tmp_path, job_id="j1", status="completed"):
    return JobResult(job_id=job_id, name="sim", argv=["bash", "sim.sh"],
                     cwd=str(tmp_path), purpose="sim", status=status,
                     exit_code=0)


def test_registers_existing_and_reports_missing(tmp_path):
    (tmp_path / "sim.log").write_text("ok", encoding="utf-8")
    reg = OutputRegistry()
    reg.expect("j1", "sim", [OutputSpec("log", "sim.log", kind="job_log"),
                             OutputSpec("cov", "cov.db", kind="coverage_db")])
    store = ArtifactStore(tmp_path, run_id="r1")
    out = reg.finalize(_result(tmp_path), store)
    assert out["registered"][0]["sha256"]
    assert out["missing"][0]["name"] == "cov"


def test_exit0_only_outputs_skip_failed_jobs(tmp_path):
    (tmp_path / "sim.log").write_text("partial", encoding="utf-8")
    reg = OutputRegistry()
    reg.expect("j1", "sim", [OutputSpec("log", "sim.log", when="exit0")])
    store = ArtifactStore(tmp_path, run_id="r1")
    out = reg.finalize(_result(tmp_path, status="timeout"), store)
    assert out == {"registered": [], "missing": []}
