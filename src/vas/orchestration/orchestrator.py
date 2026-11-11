"""Verification Orchestrator 1.0 — 确定性闭环，Agent 只执行角色任务。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agents.handlers import HANDLERS
from ..contracts import TaskContract
from ..engine.protocols import NullEngine, VerificationEngine
from ..evidence.policy import GatePolicy
from ..evidence.store import ArtifactStore, Provenance, sha256_bytes
from ..ir.models import VerificationIR
from ..runtime.context import AgentContext
from ..runtime.llm import LLMAdapter, NullLLM
from ..runtime.runtime import AgentRuntime
from .state import Phase, StateMachine


@dataclass
class OrchestratorConfig:
    target: float = 95.0
    max_rounds: int = 2
    max_tokens: int = 200_000
    require_human: bool = True
    authorized: bool = False
    workspace: str = ""


@dataclass
class VASResult:
    status: str
    phase: str
    gate: Dict[str, Any]
    ir: VerificationIR
    evidence_dir: str
    blockers: List[str] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "phase": self.phase,
            "gate": self.gate,
            "evidence_dir": self.evidence_dir,
            "blockers": self.blockers,
            "trace": self.trace,
            "ir": self.ir.model_dump(),
        }


class VerificationOrchestrator:
    def __init__(self, *, engine: Optional[VerificationEngine] = None,
                 llm: Optional[LLMAdapter] = None,
                 config: Optional[OrchestratorConfig] = None):
        self.engine = engine or NullEngine()
        self.llm = llm or NullLLM()
        self.config = config or OrchestratorConfig()

    def run(self, *, spec_text: str = "", design: Optional[Dict[str, Any]] = None,
            workspace: str = "") -> VASResult:
        root = Path(workspace or self.config.workspace or "output_vas")
        evidence_dir = root / "evidence"
        ir = VerificationIR()
        store = ArtifactStore(evidence_dir / "artifacts")
        provenance = Provenance(evidence_dir / "provenance.jsonl")
        ctx = AgentContext(
            ir=ir, engine=self.engine, artifacts=store, provenance=provenance,
            llm=self.llm, workspace=str(root), target=self.config.target,
            max_tokens=self.config.max_tokens,
            metadata={"spec_text": spec_text, "design": design or {}},
        )
        runtime = AgentRuntime(HANDLERS)
        machine = StateMachine()
        trace: List[Dict[str, Any]] = []

        def task(task_id: str, task_type: str, agent: str,
                 inputs: Optional[Dict[str, str]] = None) -> Any:
            contract = TaskContract(
                id=task_id, type=task_type, agent=agent,
                inputs=inputs or {},
                outputs=["result"],
                acceptance=["outputs present"],
                evidence_required=True,
            )
            result = runtime.run(contract, ctx)
            trace.append({"task": task_id, "agent": agent,
                          "type": task_type, "status": result.status,
                          "error": result.error})
            return result

        def blocked(reason: str) -> VASResult:
            machine.phase = Phase.BLOCKED if machine.phase != Phase.BLOCKED else machine.phase
            return VASResult("blocked", machine.phase.value,
                             {"ok": False, "blockers": [reason], "checks": {}},
                             ir, str(evidence_dir), [reason], trace)

        req = task("T-requirement", "requirement_extraction", "requirement",
                   {"spec_text": spec_text})
        if req.status != "ok":
            return blocked(req.error or "requirement extraction failed")
        machine.move(Phase.REQUIREMENT)

        arch = task("T-architecture", "architecture_analysis", "architecture")
        if arch.status != "ok":
            return blocked(arch.error or "architecture analysis failed")
        machine.move(Phase.ARCHITECTURE)

        plan = task("T-planning", "planning", "planning")
        if plan.status != "ok":
            return blocked(plan.error or "planning failed")
        machine.move(Phase.PLANNING)

        for round_index in range(1, self.config.max_rounds + 1):
            uvm = task(f"T-uvm-{round_index}", "uvm_generation", "uvm")
            formal = task(f"T-formal-{round_index}", "formal_generation", "formal")
            if uvm.status != "ok" or formal.status != "ok":
                return blocked(uvm.error or formal.error or "generation failed")
            machine.move(Phase.GENERATE)

            reg = task(f"T-regression-{round_index}", "regression", "regression")
            machine.move(Phase.EXECUTE)
            if reg.status == "blocked":
                return blocked(reg.error or "EDA_MISSING")
            if reg.status != "ok":
                debug = task(f"T-debug-{round_index}", "debug", "debug")
                if debug.status != "ok":
                    return blocked(debug.error or "debug failed")

            cov = task(f"T-coverage-{round_index}", "coverage_analysis", "coverage")
            machine.move(Phase.ANALYZE)
            if cov.status != "ok":
                return blocked(cov.error or "coverage failed")
            gaps = cov.outputs.get("gaps", [])
            if not gaps:
                break
            if round_index >= self.config.max_rounds:
                break
            repair = task(f"T-repair-{round_index}", "repair", "repair")
            machine.move(Phase.REPAIR)
            if repair.status != "ok":
                return blocked(repair.error or "repair failed")

        if self.config.authorized:
            ir.evidence.decisions.append({
                "decision": "auto_approved",
                "by": "orchestrator",
                "reason": "authorized deterministic run",
            })
        else:
            ir.evidence.decisions.append({
                "decision": "pending",
                "by": "system",
                "reason": "human approval required",
            })

        task("T-signoff", "signoff", "signoff")
        machine.move(Phase.SIGNOFF)
        artifacts = [store.put_text(
            ir.model_dump_json(indent=2), kind="verification_ir")]
        gate = GatePolicy().evaluate(ir, artifacts, store)
        status = "passed" if gate.ok else "blocked"
        if gate.ok:
            machine.move(Phase.DONE)
        else:
            machine.phase = Phase.BLOCKED
        return VASResult(status, machine.phase.value, gate.to_dict(), ir,
                         str(evidence_dir), list(gate.blockers), trace)
