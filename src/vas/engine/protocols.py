"""Deterministic Verification Engine 1.0 — 只执行，不解释。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

from ..ir.models import ExecutionIR


@dataclass
class EngineResult:
    status: str                 # passed | failed | blocked | error
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    evidence: List[str] = field(default_factory=list)


class VerificationEngine(Protocol):
    name: str

    def compile(self, execution: ExecutionIR) -> EngineResult: ...
    def run(self, execution: ExecutionIR) -> List[EngineResult]: ...
    def coverage(self) -> Dict[str, float]: ...


class NullEngine:
    """没有 EDA / 没有执行后端时的显式阻断；绝不伪造 passed。"""
    name = "null"

    def _blocked(self) -> EngineResult:
        return EngineResult(
            status="blocked",
            error="EDA_MISSING: no deterministic verification engine configured",
        )

    def compile(self, execution: ExecutionIR) -> EngineResult:
        return self._blocked()

    def run(self, execution: ExecutionIR) -> List[EngineResult]:
        return [self._blocked() for _ in execution.tests]

    def coverage(self) -> Dict[str, float]:
        return {}


class CallableEngine:
    """把外部执行函数适配成 Engine；用于接入现有 skill/EDA 后端。"""
    name = "callable"

    def __init__(self, *, compiler=None, runner=None, coverage_reader=None):
        self.compiler = compiler
        self.runner = runner
        self.coverage_reader = coverage_reader

    def compile(self, execution: ExecutionIR) -> EngineResult:
        if self.compiler is None:
            return EngineResult("blocked", error="compile backend not configured")
        return self.compiler(execution)

    def run(self, execution: ExecutionIR) -> List[EngineResult]:
        if self.runner is None:
            return [EngineResult("blocked", error="run backend not configured")]
        return list(self.runner(execution))

    def coverage(self) -> Dict[str, float]:
        return dict(self.coverage_reader() if self.coverage_reader else {})
