"""Proposal —— staging → gate 的唯一通道（窄接口）。"""
from .schema import Proposal, ProposalError, PROPOSAL_JSON_SCHEMA, new_proposal

__all__ = ["Proposal", "ProposalError", "PROPOSAL_JSON_SCHEMA", "new_proposal"]
