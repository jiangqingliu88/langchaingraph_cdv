"""会话 —— 消息、工作状态、用量、待决动作，以及磁盘上的快照/恢复。"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.core.runtime.atomic import atomic_write_json

from .workspace_manager import WorkspaceZones


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    return f"H-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _default_working() -> Dict[str, Any]:
    return {
        "changed_files": [],
        "evidence": {"commands": [], "logs": []},
        "reads": {},
        "todos": [],
        "subagents": [],
        "jobs": [],
        "runs": [],
        "open_questions": [],
        "last_observation": "",
    }


@dataclass
class Session:
    session_id: str
    task: str
    state: str = "new"
    round: int = 1
    step: int = 0
    goal: Dict[str, Any] = field(default_factory=dict)
    plan: str = ""
    plan_approved: bool = False
    subgoals: List[Dict[str, Any]] = field(default_factory=list)
    active_subgoal: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    working: Dict[str, Any] = field(default_factory=_default_working)
    usage: Dict[str, Any] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0,
                                 "estimated": True})
    pending: Dict[str, Any] = field(default_factory=dict)
    proposal_id: str = ""
    last_error: str = ""
    earlier_turns: List[Dict[str, Any]] = field(default_factory=list)
    compactions: int = 0
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()
        self.updated_at = _now()

    # ── 序列化 ────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "harness_session_v1",
            "session_id": self.session_id,
            "task": self.task,
            "state": self.state,
            "round": self.round,
            "step": self.step,
            "goal": self.goal,
            "plan": self.plan,
            "plan_approved": self.plan_approved,
            "subgoals": self.subgoals,
            "active_subgoal": self.active_subgoal,
            "messages": self.messages,
            "working": self.working,
            "usage": self.usage,
            "pending": self.pending,
            "proposal_id": self.proposal_id,
            "last_error": self.last_error,
            "earlier_turns": self.earlier_turns,
            "compactions": self.compactions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "Session":
        return cls(
            session_id=str(doc.get("session_id") or new_session_id()),
            task=str(doc.get("task") or ""),
            state=str(doc.get("state") or "new"),
            round=int(doc.get("round") or 1),
            step=int(doc.get("step") or 0),
            goal=dict(doc.get("goal") or {}),
            plan=str(doc.get("plan") or ""),
            plan_approved=bool(doc.get("plan_approved")),
            subgoals=[dict(row) for row in (doc.get("subgoals") or [])],
            active_subgoal=str(doc.get("active_subgoal") or ""),
            messages=list(doc.get("messages") or []),
            working=dict(doc.get("working") or _default_working()),
            usage=dict(doc.get("usage") or {}),
            pending=dict(doc.get("pending") or {}),
            proposal_id=str(doc.get("proposal_id") or ""),
            last_error=str(doc.get("last_error") or ""),
            earlier_turns=[dict(row) for row in (doc.get("earlier_turns") or [])],
            compactions=int(doc.get("compactions") or 0),
            created_at=str(doc.get("created_at") or ""),
            updated_at=str(doc.get("updated_at") or ""),
        )

    def save(self, zones: WorkspaceZones) -> Path:
        self.updated_at = _now()
        return atomic_write_json(zones.session_path(self.session_id), self.to_dict())

    @classmethod
    def load(cls, zones: WorkspaceZones, session_id: str) -> "Session":
        path = zones.session_path(session_id)
        if not path.is_file():
            raise FileNotFoundError(f"session 不存在：{session_id}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(doc)

    # ── 消息 ──────────────────────────────────────────────────────────────

    def append(self, role: str, content: Any, **meta: Any) -> Dict[str, Any]:
        message = {"role": role, "content": content,
                   "ts": _now(), **{k: v for k, v in meta.items() if v is not None}}
        self.messages.append(message)
        return message

    def begin_turn(self, text: str, max_rounds: int = 2) -> None:
        """开启新的一轮对话：保留 plan/working/usage，清理上一轮的进展。"""
        from . import goal

        if self.task:
            self.earlier_turns = (self.earlier_turns or [])[-9:] + [{
                "task": self.task, "plan": self.plan,
                "proposal_id": self.proposal_id,
                "last_error": self.last_error,
            }]
        self.task = str(text or "").strip()
        self.goal = goal.new_goal(self.task, max_rounds)
        self.round = 1
        self.subgoals = []
        self.active_subgoal = ""
        self.pending = {}
        self.plan = ""
        self.plan_approved = False
        self.proposal_id = ""
        self.last_error = ""
        self.append("user", self.task)

    def projection(self) -> Dict[str, Any]:
        working = self.working or {}
        evidence = working.get("evidence") or {}
        return {
            "session_id": self.session_id,
            "task": self.task,
            "state": self.state,
            "round": self.round,
            "step": self.step,
            "goal": self.goal,
            "plan": self.plan,
            "plan_approved": self.plan_approved,
            "subgoals": self.subgoals,
            "active_subgoal": self.active_subgoal,
            "changed_files": working.get("changed_files") or [],
            "commands": evidence.get("commands") or [],
            "logs": evidence.get("logs") or [],
            "todos": working.get("todos") or [],
            "subagents": working.get("subagents") or [],
            "jobs": working.get("jobs") or [],
            "runs": working.get("runs") or [],
            "open_questions": working.get("open_questions") or [],
            "usage": self.usage,
            "compactions": self.compactions,
            "pending": self.pending,
            "proposal_id": self.proposal_id,
            "last_error": self.last_error,
            "earlier_turns": self.earlier_turns,
            "message_count": len(self.messages),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
