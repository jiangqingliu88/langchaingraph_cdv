from __future__ import annotations

import asyncio
import sys

from src.core.jobs.spec import JobSpec
from src.core.jobs.allowlist import CommandPolicy
from src.core.jobs.supervisor import JobSupervisor
from src.core.runtime.artifacts import ArtifactStore
from src.core.runtime.events import EventStore


def _spec(tmp_path, argv, timeout=10):
    return JobSpec(name="probe", argv=list(argv), cwd=tmp_path,
                   timeout_s=timeout, run_dir=tmp_path)


def test_success_captures_output_and_registers_log(tmp_path):
    events = EventStore(tmp_path, run_id="r1")
    store = ArtifactStore(tmp_path, run_id="r1", event_store=events)
    sup = JobSupervisor(run_dir=tmp_path, run_id="r1",
                        event_store=events, artifact_store=store,
                        policy=CommandPolicy(mode="off"))
    result = sup.run(_spec(tmp_path, [sys.executable, "-c", "print('hello')"]))
    assert result.status == "completed"
    assert result.exit_code == 0
    assert "hello" in open(result.stdout_path, encoding="utf-8").read()
    assert result.stdout_sha256
    assert events.read("job.started")
    assert events.read("job.finished")[0]["status"] == "completed"
    assert store.latest("job_log") is not None


def test_nonzero_exit_is_failure(tmp_path):
    sup = JobSupervisor(run_dir=tmp_path, policy=CommandPolicy(mode="off"))
    result = sup.run(_spec(tmp_path, [sys.executable, "-c", "import sys; sys.exit(3)"]))
    assert result.status == "failed"
    assert result.exit_code == 3


def test_timeout_kills_process(tmp_path):
    sup = JobSupervisor(run_dir=tmp_path, policy=CommandPolicy(mode="off"))
    result = sup.run(_spec(tmp_path,
                           [sys.executable, "-c", "import time; time.sleep(30)"],
                           timeout=0.3))
    assert result.timed_out is True
    assert result.status == "timeout"
    assert result.killed_tree is True


def test_enforce_denies_unknown_tool_without_spawning(tmp_path):
    events = EventStore(tmp_path, run_id="r1")
    sup = JobSupervisor(run_dir=tmp_path, event_store=events,
                        policy=CommandPolicy(mode="enforce"))
    result = sup.run(_spec(tmp_path, ["definitely-not-a-real-tool-xyz"]))
    assert result.status == "denied"
    assert result.pid == 0
    denied = events.read("job.denied")
    assert denied and denied[0]["status"] == "denied"


def test_monitor_records_but_runs(tmp_path):
    events = EventStore(tmp_path, run_id="r1")
    sup = JobSupervisor(run_dir=tmp_path, event_store=events,
                        policy=CommandPolicy(mode="monitor"))
    result = sup.run(_spec(tmp_path, ["definitely-not-a-real-tool-xyz"]))
    assert result.status == "failed"          # 进程起不来，但没被白名单拦
    assert events.read("job.denied")[0]["status"] == "monitor"


def test_run_async_parity(tmp_path):
    sup = JobSupervisor(run_dir=tmp_path, policy=CommandPolicy(mode="off"))
    result = asyncio.run(sup.run_async(
        _spec(tmp_path, [sys.executable, "-c", "print('async')"])))
    assert result.status == "completed"
