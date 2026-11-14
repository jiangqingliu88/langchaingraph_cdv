# src/regression_framework/execution/strategy.py
import os
import re
import subprocess
from abc import ABC, abstractmethod
from ..core.logging_config import get_logger
from ..core.exceptions import LSFError

logger = get_logger(__name__)

#: 由 `Runtime` 在 run 入口注入的 JobSupervisor（`src/runtime_plane/core/jobs/`）。
#: 个人级 CLI 单进程串行，module-global 足够；多 run 并发时应改成 contextvar。
_JOB_SUPERVISOR = None


def set_job_supervisor(supervisor) -> None:
    """绑定/解绑 EDA Job 运行时。`None` = 退回原始 subprocess 路径。"""
    global _JOB_SUPERVISOR
    _JOB_SUPERVISOR = supervisor


def get_job_supervisor():
    return _JOB_SUPERVISOR


class ExecutionStrategy(ABC):
    @abstractmethod
    def run_script(self, script_path: str, cwd: str, job_name: str = None, timeout: int = None, retry: int = 0):
        """返回：LSF返回作业ID，local/mock返回布尔值"""
        pass

class MockStrategy(ExecutionStrategy):
    def run_script(self, script_path, cwd, job_name=None, timeout=None, retry=0):
        logger.info(f"[MOCK] Would execute {script_path} in {cwd}")
        return True

class LocalStrategy(ExecutionStrategy):
    @staticmethod
    def _shell_argv(script_path: str, cwd: str):
        """`.sh` 必须交给 shell 执行，且路径要是 bash 认得的。

        Windows 上 `subprocess.run([x.sh], shell=False)` 会直接
        `OSError: [WinError 193] %1 不是有效的 Win32 应用程序` —— `.sh` 不是可执行
        映像，CreateProcess 起不来。统一改成 `bash <script>`（本工程在 MSYS /
        Git-Bash 下跑），POSIX 上等价。

        路径这一步有两个坑，都要绕：
          · `\` 会被 bash 当转义符 → "No such file or directory"（exit 127）
          · `script_path` 是**相对进程 cwd** 的，而 subprocess 的 `cwd=` 是脚本
            自己所在的目录 —— 原样交给 bash 会拼出两层路径。按 `cwd` + 文件名重算。
        """
        if os.name == "nt":
            # **只给文件名**：subprocess 的 `cwd=` 已经把进程放在脚本自己那层目录里，
            # 再带任何前缀都会被拼成两层路径（`<cwd>/<前缀>/<脚本>` → 找不到）。
            return ["bash", os.path.basename(script_path)]
        return [script_path]

    def run_script(self, script_path, cwd, job_name=None, timeout=None, retry=0):
        if not os.path.exists(script_path):
            logger.warning(f"Script not found: {script_path}")
            return True
        logger.info(f"[LOCAL] Executing {script_path} in {cwd}")

        # Architecture 2.0：有 JobSupervisor 就走统一进程生命周期（超时/杀树/事件）。
        # 没绑定（或显式关闭）时**保持原路径逐字节不变** —— 回归是热路径，
        # 任何行为变化都必须能被关掉。
        supervisor = get_job_supervisor()
        if supervisor is not None and os.environ.get(
                "SIGNOFFAI_JOB_RUNTIME", "on").strip().lower() != "off":
            try:
                from src.runtime_plane.core.jobs.spec import JobSpec

                result = supervisor.run(JobSpec(
                    name=job_name or os.path.basename(script_path),
                    argv=self._shell_argv(script_path, cwd),
                    cwd=cwd,
                    purpose="regression",
                    timeout_s=timeout,
                ))
                if result.status == "completed":
                    return True
                logger.error(f"Script failed: status={result.status} "
                             f"exit={result.exit_code} timed_out={result.timed_out}")
                return False
            except Exception as e:                      # noqa: BLE001 退回原路径
                logger.warning(f"JobSupervisor 执行失败，退回 subprocess: {e}")

        try:
            subprocess.run(self._shell_argv(script_path, cwd), cwd=cwd, check=True, shell=False)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Script failed with exit code {e.returncode}")
            return False

class LsfStrategy(ExecutionStrategy):
    def __init__(self, queue='normal', project=None, resource='rusage[mem=4096]'):
        self.queue = queue
        self.project = project
        self.resource = resource

    def run_script(self, script_path, cwd, job_name=None, timeout=None, retry=0):
        if not os.path.exists(script_path):
            logger.warning(f"Script not found: {script_path}")
            return None
        if job_name is None:
            job_name = os.path.basename(os.path.dirname(script_path)) + '_' + os.path.basename(script_path).replace('.sh', '')
        cmd = f"bsub -J \"{job_name}\" -q {self.queue}"
        if self.project:
            cmd += f" -P {self.project}"
        if self.resource:
            cmd += f" -R \"{self.resource}\""
        if timeout:
            cmd += f" -W {timeout}"
        log_file = os.path.join(cwd, 'job.log')
        cmd += f" -o {log_file} -e {log_file}"
        cmd += f" 'cd {cwd} && ./{os.path.basename(script_path)}'"
        logger.info(f"[LSF] Submitting: {cmd}")
        try:
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
            m = re.search(r'Job <(\d+)>', output)
            if m:
                job_id = int(m.group(1))
                logger.info(f"[LSF] Submitted job {job_id}")
                return job_id
            else:
                logger.warning(f"Could not parse job ID from: {output}")
                return None
        except subprocess.CalledProcessError as e:
            logger.error(f"LSF submission failed: {e.output}")
            return None