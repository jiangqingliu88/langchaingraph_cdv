"""Agent Context 1.0 — 一次运行所需的只读/可写句柄。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..engine.protocols import VerificationEngine
from ..evidence.store import ArtifactStore, Provenance
from ..ir.models import VerificationIR
from .llm import LLMAdapter, NullLLM


@dataclass
class AgentContext:
    ir: VerificationIR
    engine: VerificationEngine
    artifacts: ArtifactStore
    provenance: Provenance
    llm: LLMAdapter = field(default_factory=NullLLM)
    workspace: str = ""
    target: float = 95.0
    max_tokens: int = 200_000
    metadata: Dict[str, Any] = field(default_factory=dict)

    def record(self, event: Dict[str, Any]) -> None:
        self.provenance.append(event)

    def put_text(self, text: str, kind: str) -> Dict[str, str]:
        return self.artifacts.put_text(text, kind=kind)


@dataclass
class RuntimeResult:
    status: str
    outputs: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    error: str = ""
    attempts: int = 0
