"""Deterministic Engine facade (Architecture 4.0).

Existing implementations: `src/engine/{front,design,verify,ops,coverage,audit,
diagnostics,orchestration}`, `src/layers/l{1,2,3}_*`, and
`src/interfaces/api/{verify,soc}_service.py`.
"""
from src.interfaces.api.soc_service import run_soc_project
from src.interfaces.api.verify_service import run_verify, run_verify_async
from src.ir.vplan import (
    apply_active, evaluate, link_run, load_project,
)
from src.modes.verify_mode import run_goal

__all__ = [
    "run_goal", "run_verify", "run_verify_async", "run_soc_project",
    "load_project", "evaluate", "link_run", "apply_active",
]
