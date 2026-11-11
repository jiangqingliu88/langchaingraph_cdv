"""TaskContract 1.0 — Agent 之间只用结构化任务契约通信。"""
from __future__ import annotations

from typing import Any, Dict, List

from dataclasses import dataclass, field
from pydantic import BaseModel, ConfigDict, Field


class TaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    agent: str
    inputs: Dict[str, str] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    outputs: List[str] = Field(default_factory=list)
    acceptance: List[str] = Field(default_factory=list)
    evidence_required: bool = True

    def validate_contract(self) -> List[str]:
        errors: List[str] = []
        for field in ("id", "type", "agent"):
            if not str(getattr(self, field) or "").strip():
                errors.append(f"{field} is required")
        if not self.outputs:
            errors.append("outputs is required")
        if not self.acceptance:
            errors.append("acceptance is required")
        return errors


@dataclass
class TaskResult:
    task_id: str
    agent: str
    status: str = "ok"          # ok | blocked | failed | needs_human
    outputs: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    error: str = ""
    tokens: int = 0
