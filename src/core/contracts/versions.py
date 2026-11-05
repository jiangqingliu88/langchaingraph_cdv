"""所有 schema 版本常量的**唯一来源**。

新增/升级 schema 时先改这里，再改产生者；文档与测试引用同一个常量，
避免「代码写 v1、文档写 v2、校验器写 v3」这种漂移。
"""
from __future__ import annotations

# ── run-local facts ──
EVENTS = "events_v1"
ARTIFACT_INDEX = "artifact_index_v1"
PROVENANCE = "provenance_dag_v1"
QUALITY = "verification_quality_v1"
DECISION = "decision_eval_v1"
ATTRIBUTION = "coverage_attribution_v1"
INCREMENTAL_PLAN = "incremental_plan_v1"
RUN_DIFF = "run_diff_v1"
ROUND_MANIFEST = "round_manifest_v1"
TEST_DEPENDENCIES = "test_dependencies_v1"
ENGINEERING_METRICS = "engineering_metrics_v1"

# ── case view（身份脊梁：CASE → TST → EVD → CELL）──
CASE_IR = "case_ir_v1"
REGRESSION_TASK = "regression_task_v2"
CASE_COV = "case_cov_v1"          # 只加键、不升版（向后兼容）
EVD = "evd_v1"
CELL_MATRIX = "cell_matrix_v1"
CASE_GATES = "case_gates_v1"
EVIDENCE_MANIFEST = "evidence_manifest_v1"
CASE_VIEW = "case_associate_view_v2"

# ── Verification OS v3（契约驱动内核）：见 docs/design/contract_driven_architecture_v3.md ──
CONTRACT = "contract_v2"
OBLIGATION = "obligation_v1"
FACT = "fact_v1"
OS_SHADOW = "os_shadow_v1"

# ── evidence ──
EVIDENCE_ENVELOPE = "evidence_envelope_v1"
EVIDENCE_UVM_PROFILE = "uvm_signoff_v2"
EVIDENCE_SOC_PROFILE = "soc_evidence_v1"
EVIDENCE_IP_PROFILE = "ip_release_v1"

#: 所有已知 schema → 所属契约族。`schema_registry()` 供文档/校验器用。
SCHEMAS = {
    EVENTS: "run_facts",
    ARTIFACT_INDEX: "run_facts",
    PROVENANCE: "run_facts",
    QUALITY: "run_facts",
    DECISION: "run_facts",
    ATTRIBUTION: "run_facts",
    INCREMENTAL_PLAN: "run_facts",
    RUN_DIFF: "run_facts",
    ROUND_MANIFEST: "run_facts",
    TEST_DEPENDENCIES: "run_facts",
    ENGINEERING_METRICS: "run_facts",
    CASE_IR: "case_view",
    REGRESSION_TASK: "case_view",
    CASE_COV: "case_view",
    EVD: "case_view",
    CELL_MATRIX: "case_view",
    CASE_GATES: "case_view",
    EVIDENCE_MANIFEST: "case_view",
    CASE_VIEW: "case_view",
    CONTRACT: "verification_os",
    OBLIGATION: "verification_os",
    FACT: "verification_os",
    OS_SHADOW: "verification_os",
    EVIDENCE_ENVELOPE: "evidence",
    EVIDENCE_UVM_PROFILE: "evidence",
    EVIDENCE_SOC_PROFILE: "evidence",
    EVIDENCE_IP_PROFILE: "evidence",
}


def known(name: str) -> bool:
    return name in SCHEMAS


def schema_registry() -> dict:
    """返回副本（调用方改不到表本身）。"""
    return dict(SCHEMAS)
