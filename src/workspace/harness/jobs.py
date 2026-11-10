"""后台任务 —— `job_start / job_output / job_kill`（对齐 dsh-jobs-local 的最小版）。

进程只在当前 harness 进程内登记；重启后 `status` 变 `unknown`，但日志仍在
`staging/.jobs/<id>.log`（可继续读）。
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..zones import WorkspaceZones

_SECRET = re.compile(r"(SECRET|TOKEN|PASSWORD|API[_-]?KEY|PRIVATE[_-]?KEY)",
                     re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, zones: WorkspaceZones, *, timeout: int = 3600):
        self.zones = zones
        self.timeout = timeout
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def start(self, command, name: str = "") -> Dict[str, Any]:
        job_id = f"J-{uuid.uuid4().hex[:8]}"
        log_rel = f".jobs/{job_id}.log"
        log_path = self.zones.staging_path(log_rel)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not _SECRET.search(k)}
        env["SIGNOFFAI_WORKSPACE"] = str(self.zones.root)
        shell = isinstance(command, str)
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command, cwd=str(self.zones.staging), shell=shell, env=env,
                stdout=log, stderr=subprocess.STDOUT)
        self._jobs[job_id] = {
            "job_id": job_id, "name": name or job_id,
            "command": command if shell else list(map(str, command)),
            "process": process, "log": f"staging/{log_rel}",
            "started_at": _now(), "exit_code": None,
        }
        return {"job_id": job_id, "pid": process.pid,
                "log": f"staging/{log_rel}", "status": "running"}

    def _job(self, job_id: str) -> Dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            return {"job_id": job_id, "status": "unknown",
                    "error": "job 不在当前进程（重启后无法控制，日志仍可读）"}
        return job

    def status(self, job_id: str) -> Dict[str, Any]:
        job = self._job(job_id)
        if "error" in job:
            return job
        code = job["process"].poll()
        job["exit_code"] = code
        return {"job_id": job_id, "status": "running" if code is None else "exited",
                "exit_code": code, "log": job["log"], "name": job["name"]}

    def output(self, job_id: str, tail: int = 4000) -> Dict[str, Any]:
        job = self._job(job_id)
        log = job.get("log") or f"staging/.jobs/{job_id}.log"
        try:
            path = self.zones.zone_path(log, "staging", must_exist=True)
        except Exception:                       # noqa: BLE001 日志缺失按空处理
            return {"job_id": job_id, "log": log, "output": "", "missing": True}
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"job_id": job_id, "log": log, "output": text[-tail:],
                "bytes": len(text), "status": self.status(job_id).get("status")}

    def kill(self, job_id: str) -> Dict[str, Any]:
        job = self._job(job_id)
        if "error" in job:
            return job
        if job["process"].poll() is None:
            job["process"].terminate()
        return {"job_id": job_id, "status": "killed"}

    def list(self) -> List[Dict[str, Any]]:
        return [{"job_id": key, "name": job["name"],
                 "status": "running" if job["process"].poll() is None else "exited",
                 "exit_code": job["process"].poll(), "log": job["log"]}
                for key, job in self._jobs.items()]
