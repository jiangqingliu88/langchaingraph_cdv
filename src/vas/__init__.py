"""Verification Agentic System 1.0."""

from .contracts import TaskContract, TaskResult
from .ir.models import VerificationIR
from .orchestration.orchestrator import VASResult, VerificationOrchestrator

__version__ = "1.0.0"

__all__ = [
    "TaskContract", "TaskResult", "VerificationIR", "VASResult",
    "VerificationOrchestrator", "__version__",
]
