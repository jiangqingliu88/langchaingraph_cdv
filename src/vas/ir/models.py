"""Verification IR 1.0 — 五类语义模型 + 可追踪图。

IR 不是文件引用；每条边都是可校验的语义关系：
Requirement → Objective → Test → Run → Evidence → Decision。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _IR(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirement(_IR):
    id: str
    text: str
    priority: int = 3
    source: str = ""


class Objective(_IR):
    id: str
    requirement_id: str
    metric: str = "functional_coverage"
    target: float = 95.0
    description: str = ""


class Scenario(_IR):
    id: str
    objective_id: str
    stimulus: str = ""
    checker: str = ""
    tags: List[str] = Field(default_factory=list)


class IntentIR(_IR):
    requirements: List[Requirement] = Field(default_factory=list)
    objectives: List[Objective] = Field(default_factory=list)
    scenarios: List[Scenario] = Field(default_factory=list)


class Port(_IR):
    name: str
    direction: str = "input"
    width: int = 1


class Module(_IR):
    name: str
    ports: List[Port] = Field(default_factory=list)
    path: str = ""


class DesignIR(_IR):
    top: str = ""
    modules: List[Module] = Field(default_factory=list)
    interfaces: List[str] = Field(default_factory=list)


class Resource(_IR):
    id: str
    kind: str = "generic"
    owner: str = ""
    address_range: str = ""
    notes: str = ""


class ResourceConflict(_IR):
    id: str
    resource_ids: List[str] = Field(default_factory=list)
    description: str = ""


class ResourceIR(_IR):
    resources: List[Resource] = Field(default_factory=list)
    conflicts: List[ResourceConflict] = Field(default_factory=list)


class TestCase(_IR):
    id: str
    objective_ids: List[str] = Field(default_factory=list)
    sequence: str = ""
    sva: str = ""
    scoreboard: str = ""
    constraints: str = ""


class Job(_IR):
    id: str
    test_id: str
    seed: int = 0
    status: str = "planned"
    log: str = ""


class ExecutionIR(_IR):
    tests: List[TestCase] = Field(default_factory=list)
    jobs: List[Job] = Field(default_factory=list)


class EvidenceArtifact(_IR):
    id: str
    kind: str
    path: str
    sha256: str


class RunEvidence(_IR):
    id: str
    test_id: str
    status: str = "unknown"
    seed: int = 0
    log: str = ""
    error: str = ""


class CoverageEvidence(_IR):
    objective_id: str
    value: float = 0.0
    target: float = 95.0


class EvidenceIR(_IR):
    artifacts: List[EvidenceArtifact] = Field(default_factory=list)
    runs: List[RunEvidence] = Field(default_factory=list)
    coverage: List[CoverageEvidence] = Field(default_factory=list)
    decisions: List[Dict[str, str]] = Field(default_factory=list)


class VerificationIR(_IR):
    intent: IntentIR = Field(default_factory=IntentIR)
    design: DesignIR = Field(default_factory=DesignIR)
    resources: ResourceIR = Field(default_factory=ResourceIR)
    execution: ExecutionIR = Field(default_factory=ExecutionIR)
    evidence: EvidenceIR = Field(default_factory=EvidenceIR)

    def trace_errors(self) -> List[str]:
        errors: List[str] = []
        req_ids = {r.id for r in self.intent.requirements}
        obj_ids = {o.id for o in self.intent.objectives}
        test_ids = {t.id for t in self.execution.tests}
        run_test_ids = {r.test_id for r in self.evidence.runs}

        for objective in self.intent.objectives:
            if objective.requirement_id not in req_ids:
                errors.append(f"objective {objective.id} references unknown requirement")
        for scenario in self.intent.scenarios:
            if scenario.objective_id not in obj_ids:
                errors.append(f"scenario {scenario.id} references unknown objective")
        for test in self.execution.tests:
            if not test.objective_ids:
                errors.append(f"test {test.id} has no objective")
            for oid in test.objective_ids:
                if oid not in obj_ids:
                    errors.append(f"test {test.id} references unknown objective {oid}")
        for run in self.evidence.runs:
            if run.test_id not in test_ids:
                errors.append(f"run {run.id} references unknown test {run.test_id}")
        for cov in self.evidence.coverage:
            if cov.objective_id not in obj_ids:
                errors.append(f"coverage references unknown objective {cov.objective_id}")
        for test in self.execution.tests:
            if test.id not in run_test_ids:
                errors.append(f"test {test.id} has no run evidence")
        return errors
