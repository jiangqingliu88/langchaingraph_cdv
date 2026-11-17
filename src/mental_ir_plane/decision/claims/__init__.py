"""Claim —— 需要被证据证明的结论（默认 CANDIDATE）。"""
from .audit import audit_claims
from .compiler import EVIDENCE_BY_KIND, claims_from_intents
from .schema import SCHEMA, STATUSES, Claim, canonical_hash, from_dict
from .store import load_claims, save_claims, write_claims

__all__ = [
    "EVIDENCE_BY_KIND", "SCHEMA", "STATUSES", "Claim", "audit_claims",
    "canonical_hash", "claims_from_intents", "from_dict", "load_claims",
    "save_claims", "write_claims",
]
