"""Evidence Store —— ledger 的类型化索引 + 解释/上下文（不是第二份事实）。"""
from .context import SCHEMA as CONTEXT_SCHEMA, build_next_context
from .index import build_evidence_index
from .interpretation import SCHEMA as INTERPRETATION_SCHEMA, build_interpretations
from .kinds import (
    EVIDENCE_KINDS, FACT_CLASSES, PRODUCER_CLASSES, PROVEN_FACT_CLASSES, SCHEMA,
)
from .query import counts, evidence_for_claims, fact_class_of, read_ledger
from .writer import annotate_fact, append_evidence

__all__ = [
    "CONTEXT_SCHEMA", "EVIDENCE_KINDS", "FACT_CLASSES",
    "INTERPRETATION_SCHEMA", "PRODUCER_CLASSES", "PROVEN_FACT_CLASSES", "SCHEMA",
    "annotate_fact", "append_evidence", "build_evidence_index",
    "build_interpretations", "build_next_context", "counts",
    "evidence_for_claims", "fact_class_of", "read_ledger",
]
