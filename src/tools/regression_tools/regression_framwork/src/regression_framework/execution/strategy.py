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
        try:
            subprocess.run([script_path], cwd=cwd, check=True, shell=False)
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