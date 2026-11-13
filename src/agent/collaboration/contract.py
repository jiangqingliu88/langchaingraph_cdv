"""Subagent Task Contract —— 子 Agent 的任务边界与结构化返回。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

VALID_STATUS = ("PENDING", "RUNNING", "COMPLETED", "BLOCKED", "FAILED",
                "TIMEOUT", "CANCELLED")


@dataclass
class SubagentContract:
    task_id: str
    agent_type: str
    objective: str
    parent_task_id: str = ""
    scope: Dict[str, List[str]] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    deliverables: List[str] = field(default_factory=list)
    acceptance: List[str] = field(default_factory=list)
    timeout_s: int = 600
    status: str = "PENDING"
    fingerprint: str = ""

    def validate(self) -> List[str]:
        issues: List[str] = []
        for key in ("task_id", "agent_type", "objective"):
            if not str(getattr(self, key) or "").strip():
                issues.append(f"{key} 不能为空")
        if self.status not in VALID_STATUS:
            issues.append(f"未知 status: {self.status}")
        if not isinstance(self.scope, dict):
            issues.append("scope 必须是对象")
        return issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "agent_type": self.agent_type,
            "objective": self.objective,
            "scope": self.scope,
            "constraints": list(self.constraints),
            "deliverables": list(self.deliverables),
            "acceptance": list(self.acceptance),
            "timeout_s": int(self.timeout_s),
            "status": self.status,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "SubagentContract":
        return cls(
            task_id=str(doc.get("task_id") or ""),
            agent_type=str(doc.get("agent_type") or ""),
            objective=str(doc.get("objective") or ""),
            parent_task_id=str(doc.get("parent_task_id") or ""),
            scope=dict(doc.get("scope") or {}),
            constraints=[str(c) for c in (doc.get("constraints") or [])],
            deliverables=[str(d) for d in (doc.get("deliverables") or [])],
            acceptance=[str(a) for a in (doc.get("acceptance") or [])],
            timeout_s=int(doc.get("timeout_s") or 600),
            status=str(doc.get("status") or "PENDING"),
            fingerprint=str(doc.get("fingerprint") or ""),
        )


@dataclass
class SubagentResult:
    task_id: str
    status: str = "FAILED"
    summary: str = ""
    findings: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    recommended_next_actions: List[str] = field(default_factory=list)
    validation: List[str] = field(default_factory=list)
    fingerprint: str = ""
    validated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "findings": list(self.findings),
            "artifacts": list(self.artifacts),
            "unresolved": list(self.unresolved),
            "recommended_next_actions": list(self.recommended_next_actions),
            "validation": list(self.validation),
            "fingerprint": self.fingerprint,
            "validated": bool(self.validated),
        }

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "SubagentResult":
        return cls(
            task_id=str(doc.get("task_id") or ""),
            status=str(doc.get("status") or "FAILED"),
            summary=str(doc.get("summary") or ""),
            findings=[dict(f) for f in (doc.get("findings") or [])
                      if isinstance(f, dict)],
            artifacts=[str(a) for a in (doc.get("artifacts") or [])],
            unresolved=[str(u) for u in (doc.get("unresolved") or [])],
            recommended_next_actions=[
                str(a) for a in (doc.get("recommended_next_actions") or [])],
            validation=[str(v) for v in (doc.get("validation") or [])],
            fingerprint=str(doc.get("fingerprint") or ""),
            validated=bool(doc.get("validated")),
        )


__all__ = ["SubagentContract", "SubagentResult", "VALID_STATUS"]
