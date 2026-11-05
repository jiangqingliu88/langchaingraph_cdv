"""EDA Job Runtime —— 进程生命周期、超时、进程树回收、命令白名单。"""
from src.core.jobs.spec import JobResult, JobSpec
from src.core.jobs.supervisor import JobSupervisor
from src.core.jobs.allowlist import CommandPolicy, check_command, scan_tool_args
from src.core.jobs.outputs import OutputRegistry, OutputSpec

__all__ = [
    "JobResult", "JobSpec", "JobSupervisor",
    "CommandPolicy", "check_command", "scan_tool_args",
    "OutputRegistry", "OutputSpec",
]
