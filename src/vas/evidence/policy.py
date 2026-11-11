"""Deterministic Gate 1.0 — Agent 只能提交，不能裁决。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from ..ir.models import VerificationIR
from .store import ArtifactStore, sha256_file


@dataclass
class GateReport:
    ok: bool
    blockers: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "blockers": self.blockers, "checks": self.checks}


class GatePolicy:
    def __init__(self, target_override: float | None = None):
        self.target_override = target_override

    def evaluate(self, ir: VerificationIR, artifacts: List[Dict[str, str]],
                 store: ArtifactStore | None = None) -> GateReport:
        blockers: List[str] = []
        checks: Dict[str, bool] = {}

        trace_errors = ir.trace_errors()
        checks["trace"] = not trace_errors
        blockers.extend(trace_errors)

        runs = {run.test_id: run for run in ir.evidence.runs}
        missing = [t.id for t in ir.execution.tests if t.id not in runs]
        failed = [r.test_id for r in ir.evidence.runs
                  if r.status not in ("passed", "waived")]
        checks["tests_executed"] = not missing
        checks["tests_passed"] = not failed
        if missing:
            blockers.append(f"tests without run evidence: {missing}")
        if failed:
            blockers.append(f"tests not passed: {failed}")

        coverage_ok = True
        for cov in ir.evidence.coverage:
            target = self.target_override if self.target_override is not None else cov.target
            if cov.value < target:
                coverage_ok = False
                blockers.append(
                    f"coverage {cov.objective_id}={cov.value:.1f} < {target:.1f}")
        checks["coverage"] = coverage_ok

        artifact_ok = True
        for artifact in artifacts:
            if store is not None and not store.verify(artifact):
                artifact_ok = False
                blockers.append(f"artifact hash mismatch: {artifact.get('id')}")
        checks["artifacts"] = artifact_ok

        decisions = [d.get("decision") for d in ir.evidence.decisions]
        checks["human_gate"] = "approved" in decisions or "auto_approved" in decisions
        if not checks["human_gate"]:
            blockers.append("no human/authorized gate decision")

        return GateReport(ok=not blockers, blockers=blockers, checks=checks)
