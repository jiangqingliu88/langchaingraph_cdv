"""证据闭环的类型词表 —— 唯一来源，避免各模块各起名字。"""
from __future__ import annotations

SCHEMA = "evidence_index_v1"

#: 事实类别。只有前三类参与 `derive()`。
FACT_CLASSES = ("OBSERVED", "DERIVED", "HUMAN_DECISION",
                "HYPOTHESIS", "TOOL_RECEIPT")
PROVEN_FACT_CLASSES = frozenset({"OBSERVED", "DERIVED", "HUMAN_DECISION"})

#: 产生者类别。
PRODUCER_CLASSES = ("engine", "human", "agent")

#: 工具证据种类（对齐芯华章的 EDA Evidence Sources）。
EVIDENCE_KINDS = (
    "compile_result", "sim_result", "formal_proof", "proof_core_coverage",
    "waveform", "coverage_report", "sva_hit", "scb_executed",
    "lint_report", "cdc_report", "rdc_report", "emulation_run",
    "regression_round", "tool_receipt", "human_approval", "action_decision",
)


__all__ = ["EVIDENCE_KINDS", "FACT_CLASSES", "PRODUCER_CLASSES",
           "PROVEN_FACT_CLASSES", "SCHEMA"]
