# src/regression_framework/execution/strategy.py
import os
import re
import subprocess
from abc import ABC, abstractmethod
from ..core.logging_config import get_logger
from ..core.exceptions import LSFError

logger = get_logger(__name__)

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
    def run_script(self, script_path, cwd, job_name=None, timeout=None, retry=0):
        if not os.path.exists(script_path):
            logger.warning(f"Script not found: {script_path}")
            return True
        logger.info(f"[LOCAL] Executing {script_path} in {cwd}")

        # Windows: .sh 脚本需要通过 bash 执行（优先 Git Bash，避免 WSL）
        if os.name == 'nt' and script_path.endswith('.sh'):
            bash_exe = None
            for candidate in [
                r'D:\Gitt\usr\bin\bash.exe',
                r'C:\Program Files\Git\bin\bash.exe',
                r'C:\Program Files (x86)\Git\bin\bash.exe',
            ]:
                if os.path.exists(candidate):
                    bash_exe = candidate
                    break
            if not bash_exe:
                bash_exe = 'bash'
            # 用绝对路径 + 正斜杠给 bash
            abs_script = os.path.abspath(script_path).replace('\\', '/')
            abs_cwd = os.path.abspath(cwd).replace('\\', '/')
            cmd = [bash_exe, '-c', f'cd "{abs_cwd}" && bash "{abs_script}"']
        else:
            cmd = [script_path]

        try:
            subprocess.run(cmd, cwd=cwd, check=True, shell=False, timeout=timeout)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Script failed with exit code {e.returncode}")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"Script timed out after {timeout}s")
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