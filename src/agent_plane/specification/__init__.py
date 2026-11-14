"""Specification Intelligence 复用现有 Agent Plane 的推理能力。"""

from .analysis import SpecificationAnalyst
from .temporal_extractor import TemporalCandidateExtractor

__all__ = ["SpecificationAnalyst", "TemporalCandidateExtractor"]
