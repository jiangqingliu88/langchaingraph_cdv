"""VAS 1.0: IR traceability, runtime permissions, deterministic closure."""
from __future__ import annotations

from src.vas.contracts import TaskContract
from src.vas.engine.protocols import EngineResult
from src.vas.evidence.store import Provenance
from src.vas.orchestration.orchestrator import (
    OrchestratorConfig, VerificationOrchestrator,
)
from src.vas.runtime.runtime import AgentRuntime


class _FakeEngine:
    name = "fake"

    def compile(self, execution):
        return EngineResult("passed")

    def run(self, execution):
        return [EngineResult("passed", evidence=["sim.log"])
                for _ in execution.tests]

    def coverage(self):
        return {"O001": 98.0, "O002": 97.0, "O003": 99.0}


def _spec():
    return "- DMA overlapping address must be detected\n" \
           "- Unaligned access must be rejected\n" \
           "- Reset clears pending descriptors\n"


def test_orchestrator_closes_with_fake_eda_evidence(tmp_path):
    result = VerificationOrchestrator(
        engine=_FakeEngine(),
        config=OrchestratorConfig(target=95, max_rounds=2,
                                  authorized=True,
                                  workspace=str(tmp_path)),
    ).run(spec_text=_spec(), design={"top": "dut"})
    assert result.status == "passed"
    assert result.gate["ok"] is True
    assert result.ir.trace_errors() == []
    assert result.ir.evidence.runs
    assert result.evidence_dir.endswith("evidence")


def test_null_engine_blocks_instead_of_faking(tmp_path):
    result = VerificationOrchestrator(
        config=OrchestratorConfig(authorized=True, workspace=str(tmp_path)),
    ).run(spec_text=_spec(), design={"top": "dut"})
    assert result.status == "blocked"
    assert any("EDA_MISSING" in b for b in result.blockers)


def test_runtime_rejects_unauthorized_task():
    runtime = AgentRuntime({})
    contract = TaskContract(
        id="T1", type="regression", agent="requirement",
        outputs=["x"], acceptance=["x"])
    assert contract.validate_contract() == []
    result = runtime.run(contract, ctx=None)  # permission checked before handler
    assert result.status == "failed"
    assert "cannot run task" in result.error


def test_provenance_hash_chain_detects_tamper(tmp_path):
    prov = Provenance(tmp_path / "p.jsonl")
    prov.append({"event": "a"})
    prov.append({"event": "b"})
    assert prov.verify() == []
    path = tmp_path / "p.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"a"', '"x"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert any("hash mismatch" in e for e in prov.verify())
