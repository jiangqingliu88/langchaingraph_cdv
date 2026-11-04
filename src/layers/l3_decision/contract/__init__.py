"""L3 契约门面 —— 新代码从这里导入，旧路径在 Phase 4 前保留。

实现仍在 `src.tools.checking.verification_os`；本模块只 re-export，行为不变。
重构计划见 `docs/design/architecture_refactor_plan.md` §5 Phase 3。
"""
from src.tools.checking.verification_os import (
    ContractAnchorMismatch, anchor_contract, append_bundle, build_bundle,
    build_worklist, canonical_hash, case_statuses, check_contract,
    compile_obligations, contract_anchor, contract_from_case_ir,
    contract_hash, derive, evaluate, load_contract, obligation_id,
    read_ledger, read_manifest, run_shadow, verify_chain, worst,
    write_contract, write_worklist,
)

__all__ = [
    "ContractAnchorMismatch", "anchor_contract", "append_bundle",
    "build_bundle", "build_worklist", "canonical_hash", "case_statuses",
    "check_contract", "compile_obligations", "contract_anchor",
    "contract_from_case_ir", "contract_hash", "derive", "evaluate",
    "load_contract", "obligation_id", "read_ledger", "read_manifest",
    "run_shadow", "verify_chain", "worst", "write_contract", "write_worklist",
]
