"""Verification OS v3 —— 契约驱动内核（M0 影子模式已可用）。

    L1 Contract    ← case_ir / xlsx 编译而来，带规范哈希
    L2 Obligation  ← compile_obligations(contract)：一条义务一个证明
    L3 Ledger      ← append-only 事实（哈希链），按 FactBundle 批次写入
    L4 Derive      ← derive(obligations, facts)：唯一判定实现（纯函数）
    L5 Adjudicate  ← 见 gates / audit（M0 阶段仍走旧链路，影子对账）

用法：

    from src.layers.l3_decision.contract import run_shadow
    report = run_shadow(run_dir)          # 把事实写进账本并和旧结论对账
    assert report["ok"]                   # M0 停点：100% 一致

设计见 `docs/design/contract_driven_architecture_v3.md`。
"""
from __future__ import annotations

from .build import (
    check_contract, contract_hash, load_contract, read_manifest, write_contract,
)
from .compiler import LAYER_PREDICATES, compile_obligations, obligation_id
from .contract_model import (
    FACT_TYPES, LAYERS, CaseStatus, CaseSpec, Contract, Fact, FactBundle,
    FactType, GroupSpec, Obligation, Predicate, ScbSpec, SvaSpec, canonical_hash,
    contract_from_case_ir, worst,
)
from .derive import case_statuses, derive, evaluate, tp_contract_status
from .explain import explain, obligations_view, status_summary
from .ledger import (
    ContractAnchorMismatch, anchor_contract, append_bundle, contract_anchor,
    read_ledger, verify_chain,
)
from .seeds import build_seed_index, write_seed_index
from .shadow import build_bundle, run_shadow
from .worklist import build_worklist, regression_test_name, write_worklist

__all__ = [
    "FACT_TYPES", "LAYERS", "LAYER_PREDICATES",
    "CaseStatus", "CaseSpec", "Contract", "Fact", "FactBundle", "FactType",
    "GroupSpec", "Obligation", "Predicate", "ScbSpec", "SvaSpec",
    "ContractAnchorMismatch", "anchor_contract", "append_bundle", "build_bundle",
    "canonical_hash", "case_statuses", "contract_anchor",
    "check_contract", "compile_obligations", "contract_from_case_ir",
    "contract_hash", "derive", "evaluate", "load_contract", "obligation_id",
    "read_ledger", "read_manifest", "run_shadow", "verify_chain", "worst",
    "write_contract", "explain", "status_summary", "tp_contract_status",
    "build_worklist", "regression_test_name", "write_worklist",
    "build_seed_index", "write_seed_index",
]
