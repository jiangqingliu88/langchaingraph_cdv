"""Proposal 的固定形状：变更 + 证据 + 待决问题。

Gate 只能**机械校验**结构；因此结构必须窄、字段必须少：

```
{
  "schema": "proposal_v1",
  "proposal_id": "P-20261110-...",
  "task": "补齐 module A 覆盖率",
  "author": "sandbox",
  "status": "submitted",
  "base": {"main_fingerprint": "<sha256>"},
  "changed_files": [{"path": "staging/rtl/a.sv", "action": "modify", "sha256": "..."}],
  "evidence": {
    "before": "coverage 82%",
    "after": "coverage 94%",
    "commands": [{"cmd": "sim ...", "exit_code": 0, "log": "staging/.evidence/001.log"}],
    "logs": ["staging/.evidence/001.log"],
    "reasoning_trace": "..."
  },
  "open_questions": ["line 47 的复位行为未验证"],
  "gate": {"report": "gate/P-....json", "ok": true, "human_required": true}
}
```

`open_questions` 不是弱点：循环主动交还不确定的地方，人工门据此决定。
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.runtime_plane.core.runtime.atomic import atomic_write_json
from src.runtime_plane.workspace_manager import WorkspaceError, WorkspaceZones

SCHEMA = "proposal_v1"
STATUSES = ("draft", "submitted", "accepted", "rejected", "promoted")
ACTIONS = ("add", "modify", "delete")
_SHA = re.compile(r"^[0-9a-f]{64}$")

PROPOSAL_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["schema", "proposal_id", "task", "changed_files", "evidence"],
    "additionalProperties": False,
    "properties": {
        "schema": {"const": SCHEMA},
        "proposal_id": {"type": "string", "minLength": 1},
        "task": {"type": "string", "minLength": 1},
        "author": {"type": "string"},
        "created_at": {"type": "string"},
        "status": {"enum": list(STATUSES)},
        "base": {
            "type": "object",
            "properties": {"main_fingerprint": {"type": "string"}},
        },
        "changed_files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "action"],
                "properties": {
                    "path": {"type": "string"},
                    "action": {"enum": list(ACTIONS)},
                    "sha256": {"type": "string"},
                },
            },
        },
        "evidence": {
            "type": "object",
            "required": ["before", "after", "commands", "logs", "reasoning_trace"],
            "properties": {
                "before": {"type": "string"},
                "after": {"type": "string"},
                "commands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["cmd", "exit_code"],
                        "properties": {
                            "cmd": {"type": "string"},
                            "exit_code": {"type": "integer"},
                            "log": {"type": "string"},
                        },
                    },
                },
                "logs": {"type": "array", "items": {"type": "string"}},
                "reasoning_trace": {"type": "string"},
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "gate": {"type": "object"},
    },
}


class ProposalError(ValueError):
    pass


@dataclass
class Proposal:
    proposal_id: str
    task: str
    changed_files: List[Dict[str, str]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    open_questions: List[str] = field(default_factory=list)
    author: str = "sandbox"
    status: str = "submitted"
    created_at: str = ""
    base: Dict[str, str] = field(default_factory=dict)
    gate: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    # ── 序列化 ────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "proposal_id": self.proposal_id,
            "task": self.task,
            "author": self.author,
            "created_at": self.created_at,
            "status": self.status,
            "base": dict(self.base),
            "changed_files": [dict(row) for row in self.changed_files],
            "evidence": json.loads(json.dumps(self.evidence, default=str)),
            "open_questions": list(self.open_questions),
            "gate": dict(self.gate),
        }

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "Proposal":
        return cls(
            proposal_id=str(doc.get("proposal_id") or ""),
            task=str(doc.get("task") or ""),
            changed_files=[dict(r) for r in (doc.get("changed_files") or [])],
            evidence=dict(doc.get("evidence") or {}),
            open_questions=[str(q) for q in (doc.get("open_questions") or [])],
            author=str(doc.get("author") or "sandbox"),
            status=str(doc.get("status") or "submitted"),
            created_at=str(doc.get("created_at") or ""),
            base=dict(doc.get("base") or {}),
            gate=dict(doc.get("gate") or {}),
        )

    def save(self, zones: WorkspaceZones) -> Path:
        return atomic_write_json(zones.proposal_path(self.proposal_id), self.to_dict())

    @classmethod
    def load(cls, zones: WorkspaceZones, proposal_id: str) -> "Proposal":
        path = zones.proposal_path(proposal_id)
        if not path.is_file():
            raise ProposalError(f"proposal 不存在：{proposal_id}")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProposalError(f"proposal 读不出来：{proposal_id}（{exc}）") from exc
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
            raise ProposalError(f"proposal schema 不对：{proposal_id}")
        return cls.from_dict(doc)

    # ── 校验（结构 + 可选的 staging 证据）────────────────────────────────

    def validate(self, zones: Optional[WorkspaceZones] = None) -> List[str]:
        errors: List[str] = []
        if not self.proposal_id:
            errors.append("proposal_id 为空")
        if not self.task.strip():
            errors.append("task 为空")
        if self.status not in STATUSES:
            errors.append(f"未知 status：{self.status}")
        self._validate_files(zones, errors)
        self._validate_evidence(zones, errors)
        if not isinstance(self.open_questions, list):
            errors.append("open_questions 必须是数组")
        return errors

    def _validate_files(self, zones: Optional[WorkspaceZones],
                        errors: List[str]) -> None:
        seen: set[str] = set()
        for index, row in enumerate(self.changed_files):
            path, action = str(row.get("path") or ""), str(row.get("action") or "")
            if not path:
                errors.append(f"changed_files[{index}].path 为空")
                continue
            if path in seen:
                errors.append(f"changed_files 重复：{path}")
            seen.add(path)
            if action not in ACTIONS:
                errors.append(f"{path}: 未知 action {action!r}")
            sha = str(row.get("sha256") or "")
            if action in ("add", "modify") and not _SHA.match(sha):
                errors.append(f"{path}: sha256 必须是 64 位小写 hex")
            if zones is not None:
                self._validate_file_zones(path, action, zones, errors)

    @staticmethod
    def _validate_file_zones(path: str, action: str,
                             zones: WorkspaceZones, errors: List[str]) -> None:
        try:
            target = zones.zone_path(path, "staging",
                                     must_exist=(action != "delete"))
            main_target = zones.sibling_path(path, "main",
                                             must_exist=(action == "delete"))
        except WorkspaceError as exc:
            errors.append(f"{path}: {exc}")
            return
        if action == "delete" and target.exists():
            errors.append(f"{path}: delete 但 staging 里仍然存在")
        if action == "add" and main_target.exists():
            errors.append(f"{path}: add 但 main 里已经有同名文件")

    def _validate_evidence(self, zones: Optional[WorkspaceZones],
                           errors: List[str]) -> None:
        evidence = self.evidence or {}
        for key in ("before", "after", "reasoning_trace"):
            if not str(evidence.get(key) or "").strip():
                errors.append(f"evidence.{key} 为空")
        commands = evidence.get("commands")
        if not isinstance(commands, list) or not commands:
            errors.append("evidence.commands 为空（至少要有一条可复现命令）")
        else:
            for index, command in enumerate(commands):
                if not isinstance(command, dict) or not str(command.get("cmd") or "").strip():
                    errors.append(f"evidence.commands[{index}].cmd 为空")
                    continue
                if type(command.get("exit_code")) is not int:
                    errors.append(f"evidence.commands[{index}].exit_code 必须是整数")
        logs = evidence.get("logs")
        if not isinstance(logs, list) or not logs:
            errors.append("evidence.logs 为空")
            return
        for index, log in enumerate(logs):
            if not isinstance(log, str) or not log:
                errors.append(f"evidence.logs[{index}] 为空")
                continue
            if zones is not None:
                try:
                    zones.zone_path(log, "staging", must_exist=True)
                except WorkspaceError as exc:
                    errors.append(f"evidence.logs[{index}]: {exc}")


def new_proposal(task: str, zones: WorkspaceZones, *,
                 evidence: Dict[str, Any],
                 open_questions: Optional[List[str]] = None,
                 author: str = "sandbox") -> Proposal:
    """按 staging 当前差异生成一份 submitted proposal。"""
    if not task.strip():
        raise ProposalError("task 为空")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    proposal = Proposal(
        proposal_id=f"P-{stamp}-{uuid.uuid4().hex[:6]}",
        task=task,
        changed_files=zones.changed_files(),
        evidence=evidence,
        open_questions=list(open_questions or []),
        author=author,
        status="submitted",
        base={"main_fingerprint": zones.fingerprint("main")},
    )
    errors = proposal.validate(zones)
    if errors:
        raise ProposalError("; ".join(errors))
    return proposal
