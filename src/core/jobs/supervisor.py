"""JobSupervisor —— EDA 进程的生命周期管理。

它只做四件事：**白名单检查 → 起进程 → 超时收进程树 → 收日志/登记产物**。
它不解析 EDA 日志、不改回归结果；那些是执行层的职责。

Windows 上「杀进程」必须杀**整棵树**：`subprocess.kill()` 只杀 `bash`，
它拉起的 `vlog/vsim` 会变成孤儿继续占 license。这里优先用 Job Object
（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`），失败再退回 `taskkill /F /T`。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.jobs.adapters import adapt
from src.core.jobs.allowlist import CommandPolicy
from src.core.jobs.spec import JobResult, JobSpec
from src.core.runtime.artifacts import ArtifactStore
from src.core.runtime.events import EventStore, emit

_GRACE_S = 5.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# ═══════════════════════════════════════════════════════════════
# Windows Job Object
# ═══════════════════════════════════════════════════════════════

class _WindowsJob:
    """最小 Job Object 封装；任何一步失败都抛异常，由调用方退回 taskkill。"""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", ctypes.c_uint32),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMIT),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self._ext = EXTENDED_LIMIT()
        self._ext.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObjectW failed")
        if not k32.SetInformationJobObject(
                self.handle, 9, ctypes.byref(self._ext),
                ctypes.sizeof(self._ext)):
            self.close()
            raise OSError("SetInformationJobObject failed")

    def assign(self, proc: subprocess.Popen) -> None:
        import ctypes
        from ctypes import wintypes

        handle = wintypes.HANDLE(int(getattr(proc, "_handle", 0) or 0))
        if not handle or not self._k32.AssignProcessToJobObject(self.handle, handle):
            raise OSError("AssignProcessToJobObject failed")

    def terminate(self) -> None:
        self._k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if getattr(self, "handle", None):
            self._k32.CloseHandle(self.handle)
            self.handle = None


def _kill_tree(proc: subprocess.Popen, job: Optional[_WindowsJob] = None,
               grace_s: float = _GRACE_S) -> bool:
    """杀整棵进程树。返回是否用了强杀（调用方据此记录 killed_tree）。"""
    killed = False
    if job is not None:
        try:
            job.terminate()
            killed = True
        except Exception:                       # noqa: BLE001
            pass
    if os.name == "nt":
        if not killed:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=30)
                killed = True
            except Exception:                   # noqa: BLE001
                try:
                    subprocess.run(
                        ["wmic", "process", "where",
                         f"ParentProcessId={proc.pid}", "call", "terminate"],
                        capture_output=True, timeout=30)
                except Exception:
                    pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            killed = True
        except Exception:                       # noqa: BLE001
            try:
                proc.terminate()
                killed = True
            except Exception:
                pass
    try:
        proc.wait(timeout=grace_s)
    except Exception:                           # noqa: BLE001
        try:
            proc.kill()
            killed = True
        except Exception:
            pass
    return killed


# ═══════════════════════════════════════════════════════════════
# Supervisor
# ═══════════════════════════════════════════════════════════════

class JobSupervisor:
    def __init__(self, *, run_dir: str | Path | None = None,
                 run_id: str = "", event_store: Optional[EventStore] = None,
                 artifact_store: Optional[ArtifactStore] = None,
                 policy: Optional[CommandPolicy] = None):
        self.run_dir = Path(run_dir) if run_dir else None
        self.run_id = run_id or (self.run_dir.name if self.run_dir else "")
        self.event_store = event_store
        self.artifact_store = artifact_store
        self.policy = policy or CommandPolicy.from_env()

    def _emit(self, event_type: str, **kwargs) -> None:
        if self.event_store is not None:
            self.event_store.append(event_type, **kwargs)
        else:
            emit(event_type, **kwargs)

    @staticmethod
    def _status_of(error: str, timed_out: bool, exit_code) -> str:
        if error:
            return "failed"
        if timed_out:
            return "timeout"
        return "completed" if exit_code == 0 else "failed"

    def _spawn_and_wait(self, spec: JobSpec, argv: List[str], capture: Path,
                        env: Dict[str, str], job_id: str):
        """起进程 → 等 → 超时杀树。返回 (proc, timed_out, killed, error, out, err)。"""
        out_path = capture / f"{job_id}.out"
        err_path = capture / f"{job_id}.err"
        job = None
        proc = None
        timed_out = False
        killed = False
        error = ""
        try:
            with out_path.open("wb") as out_fh, err_path.open("wb") as err_fh:
                proc = subprocess.Popen(
                    argv, cwd=str(spec.cwd), env=env, stdout=out_fh,
                    stderr=err_fh, start_new_session=(os.name != "nt"))
                if os.name == "nt":
                    try:
                        job = _WindowsJob()
                        job.assign(proc)
                    except Exception:               # noqa: BLE001 退回 taskkill
                        job = None
                try:
                    proc.wait(timeout=spec.timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    killed = _kill_tree(proc, job)
        except FileNotFoundError:
            error = f"命令不存在: {argv[0]}"
        except OSError as exc:
            error = str(exc)[:300]
        finally:
            if job is not None:
                job.close()
        return proc, timed_out, killed, error, out_path, err_path

    def _emit_finished(self, result: JobResult) -> None:
        self._emit("job.finished", job_id=result.job_id, stage=result.purpose,
                   status=result.status, source="supervisor",
                   payload={"name": result.name, "exit_code": result.exit_code,
                            "timed_out": result.timed_out,
                            "killed_tree": result.killed_tree,
                            "duration_s": result.duration_s,
                            "stdout_sha256": result.stdout_sha256,
                            "stderr_sha256": result.stderr_sha256})

    def run(self, spec: JobSpec) -> JobResult:
        job_id = uuid.uuid4().hex[:12]
        started = _now()
        t0 = time.monotonic()
        cwd = spec.cwd

        ok, reason = self.policy.check(spec.argv, cwd=cwd,
                                       run_dir=spec.run_dir or self.run_dir)
        if not ok:
            self._emit("job.denied", job_id=job_id, stage=spec.purpose,
                       status="denied", source="supervisor",
                       payload={"name": spec.name, "argv": spec.argv,
                                "reason": reason})
            return JobResult(job_id=job_id, name=spec.name, argv=list(spec.argv),
                             cwd=str(cwd), purpose=spec.purpose,
                             status="denied", error=reason, started_at=started,
                             ended_at=_now(), duration_s=0.0)
        if reason:
            self._emit("job.denied", job_id=job_id, stage=spec.purpose,
                       status="monitor", source="supervisor",
                       payload={"name": spec.name, "reason": reason})

        argv = adapt(list(spec.argv), str(cwd))
        capture = Path(spec.capture_dir) if spec.capture_dir else (
            (spec.run_dir or self.run_dir or cwd) / ".signoffai" / "jobs")
        capture.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (spec.env or {}).items()})
        self._emit("job.started", job_id=job_id, stage=spec.purpose,
                   status="running", source="supervisor",
                   payload={"name": spec.name, "argv": argv, "cwd": str(cwd),
                            "timeout_s": spec.timeout_s})

        proc, timed_out, killed, error, out_path, err_path = self._spawn_and_wait(
            spec, argv, capture, env, job_id)
        duration = round(time.monotonic() - t0, 3)
        exit_code = proc.returncode if proc is not None else None
        result = JobResult(
            job_id=job_id, name=spec.name, argv=argv, cwd=str(cwd),
            purpose=spec.purpose,
            status=self._status_of(error, timed_out, exit_code),
            exit_code=exit_code, timed_out=timed_out, killed_tree=killed,
            duration_s=duration, pid=proc.pid if proc is not None else 0,
            started_at=started, ended_at=_now(), error=error,
            stdout_path=str(out_path) if out_path.exists() else "",
            stderr_path=str(err_path) if err_path.exists() else "",
            stdout_sha256=_sha(out_path), stderr_sha256=_sha(err_path))

        if self.artifact_store is not None:
            for kind, path in (("job_log", out_path), ("job_stderr", err_path)):
                if path.exists():
                    self.artifact_store.put(kind, path, producer="job",
                                            round=0, content_address=True)
        self._emit_finished(result)
        return result

    async def run_async(self, spec: JobSpec) -> JobResult:
        return await asyncio.to_thread(self.run, spec)
