from __future__ import annotations

from pathlib import Path

from src.core.jobs.spec import JobResult
from src.core.runtime.artifacts import ArtifactStore
from src.layers.l2_orchestration.runtime import _register_artifacts
from src.tools.execution.regression_tools.regression_framework.execution.strategy import (
    LocalStrategy, get_job_supervisor, set_job_supervisor,
)


class _FakeSupervisor:
    def __init__(self, status="completed"):
        self.status = status
        self.specs = []

    def run(self, spec):
        self.specs.append(spec)
        return JobResult(job_id="j1", name=spec.name, argv=spec.argv,
                         cwd=str(spec.cwd), purpose=spec.purpose,
                         status=self.status, exit_code=0 if self.status == "completed" else 1)


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "sim.sh"
    path.write_text("echo ok\n", encoding="utf-8")
    return path


def test_local_strategy_uses_bound_supervisor(tmp_path):
    fake = _FakeSupervisor()
    set_job_supervisor(fake)
    try:
        assert LocalStrategy().run_script(str(_script(tmp_path)), str(tmp_path),
                                          job_name="sim") is True
        spec = fake.specs[0]
        assert spec.purpose == "regression"
        assert "sim.sh" in " ".join(spec.argv)
        assert spec.cwd == tmp_path
    finally:
        set_job_supervisor(None)
    assert get_job_supervisor() is None


def test_local_strategy_maps_failure(tmp_path):
    set_job_supervisor(_FakeSupervisor(status="failed"))
    try:
        assert LocalStrategy().run_script(str(_script(tmp_path)), str(tmp_path)) is False
    finally:
        set_job_supervisor(None)


def test_switch_off_keeps_original_path(tmp_path, monkeypatch):
    fake = _FakeSupervisor()
    set_job_supervisor(fake)
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        return None

    monkeypatch.setenv("SIGNOFFAI_JOB_RUNTIME", "off")
    monkeypatch.setattr("subprocess.run", _fake_run)
    try:
        assert LocalStrategy().run_script(str(_script(tmp_path)), str(tmp_path)) is True
    finally:
        set_job_supervisor(None)
    assert calls and not fake.specs


def test_executor_outputs_enter_artifact_store(tmp_path):
    store = ArtifactStore(tmp_path, run_id="r1")
    f = tmp_path / "rtl" / "dut.sv"
    f.parent.mkdir()
    f.write_text("module dut; endmodule\n", encoding="utf-8")

    class _RT:
        artifacts = store

    class _State:
        round_num = 2

    _register_artifacts(_RT(), "design",
                        {"design_arch": {"files": [str(f)]}}, _State())
    refs = store.all("executor_output")
    assert refs and refs[0].producer == "design"
    assert refs[0].round == 2
