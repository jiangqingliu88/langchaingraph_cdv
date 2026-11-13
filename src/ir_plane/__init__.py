"""IR & Evidence facade (Architecture 4.0).

Spec/Design/Verification/Execution IR + contracts + evidence currently live in
`src/ir_plane/decision/` and `src/ir_plane/proposal/`.
"""
from src.ir_plane.contract.build import (
    build_vplan_contract_map, ensure_vplan_map,
)
from src.ir_plane.vplan import (
    build_case_ir, build_execution_model, build_payload, build_testpoints,
    load_index, load_project, write_runtime_model,
)
from src.ir_plane.vplan.evidence import evaluate
from src.ir_plane.proposal.schema import Proposal, new_proposal

__all__ = [
    "load_project", "build_testpoints", "build_case_ir", "build_payload",
    "build_execution_model", "write_runtime_model", "load_index", "evaluate",
    "build_vplan_contract_map", "ensure_vplan_map", "Proposal", "new_proposal",
]
