"""Tool 契约 —— 名字/schema/风险级别；harness 按它做审批与 prompt。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str                              # read | write | exec | control
    input_schema: Dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False


def _schema(**properties) -> Dict[str, Any]:
    return {"type": "object", "properties": properties}


TOOL_SPECS: List[ToolSpec] = [
    ToolSpec("read_file", "Read a file from the workspace/project.", "read",
             _schema(path={"type": "string"}, zone={"type": "string"})),
    ToolSpec("list_files", "List files/dirs under a path.", "read",
             _schema(path={"type": "string"}, zone={"type": "string"})),
    ToolSpec("search", "Regex search over files.", "read",
             _schema(pattern={"type": "string"}, path={"type": "string"},
                     zone={"type": "string"}, glob={"type": "string"})),
    ToolSpec("read_playbook", "Read a discovered playbook by name.", "read",
             _schema(name={"type": "string"})),
    ToolSpec("project_map", "Inventory project resources (rtl/verification/coverage/env/spec/model).",
             "read", _schema(kind={"type": "string"}, limit={"type": "integer"})),
    ToolSpec("read_project_file", "Read a project file (read-only; secrets excluded).",
             "read", _schema(path={"type": "string"})),
    ToolSpec("search_project", "Regex search over project resources (read-only).",
             "read", _schema(pattern={"type": "string"}, kind={"type": "string"},
                             glob={"type": "string"})),
    ToolSpec("write_file", "Write a file inside the workspace/project.", "write",
             _schema(path={"type": "string"}, content={"type": "string"},
                              allow_rerun={"type": "boolean"})),
    ToolSpec("delete_file", "Delete a file inside the workspace/project.", "write",
             _schema(path={"type": "string"}, allow_rerun={"type": "boolean"})),
    ToolSpec("str_replace", "Replace old text with new text (first match; all=true for every match).",
             "write", _schema(path={"type": "string"}, old={"type": "string"},
                              new={"type": "string"}, all={"type": "boolean"},
                              allow_rerun={"type": "boolean"})),
    ToolSpec("run_shell", "Run a command with cwd=workspace/project root.", "exec",
             _schema(command={}, timeout={"type": "integer"},
                     allow_rerun={"type": "boolean"})),
    ToolSpec("run_verify", "Run vplan execute on a project and return EDA evidence.",
             "exec", _schema(project={"type": "string"}, run_dir={"type": "string"},
                             target={"type": "number"}, timeout={"type": "integer"},
                             allow_rerun={"type": "boolean"})),
    ToolSpec("run_stage",
             "Run one deterministic stage executor (front/design/model/verify/ops/"
             "coverage/debug/audit) in a run dir and return its structured summary.",
             "exec", _schema(role={"type": "string",
                                   "enum": ["front", "design", "model", "verify",
                                            "ops", "coverage", "debug", "audit"]},
                             run={"type": "string"}, input_text={"type": "string"},
                             params={"type": "object"}, ctx={"type": "object"},
                             timeout={"type": "integer"},
                             allow_rerun={"type": "boolean"})),
    ToolSpec("collect_evidence", "Read structured evidence from a run directory.", "read",
             _schema(run_dir={"type": "string"}, target={"type": "number"})),
    ToolSpec("compare_evidence", "Compare coverage/regression between two evidence sets.",
             "read", _schema(before={}, after={})),
    ToolSpec("export_evidence", "Package run evidence into an exchangeable zip (writes under staging/).",
             "write", _schema(run_dir={"type": "string"}, out={"type": "string"})),
    ToolSpec("job_start", "Start a background command.", "exec",
             _schema(command={}, name={"type": "string"})),
    ToolSpec("job_output", "Read a background job's log tail.", "read",
             _schema(job_id={"type": "string"}, tail={"type": "integer"})),
    ToolSpec("job_kill", "Terminate a background job.", "exec",
             _schema(job_id={"type": "string"})),
    ToolSpec("todo_write", "Replace the session todo list.", "control",
             _schema(todos={"type": "array"})),
    ToolSpec("spawn_subagent",
             "Spawn an isolated specialized subagent under a task contract; "
             "returns structured result/artifacts only (no child chat history).",
             "exec", _schema(task={"type": "string"}, max_steps={"type": "integer"},
                             agent_type={"type": "string"},
                             objective={"type": "string"},
                             task_id={"type": "string"},
                             contract={"type": "object"},
                             deliverables={"type": "array"},
                             acceptance={"type": "array"},
                             constraints={"type": "array"})),
    ToolSpec("spawn_subagents",
             "Spawn multiple independent subagents concurrently; returns one "
             "structured result per task (no child chat history).",
             "exec", _schema(tasks={"type": "array"},
                             max_workers={"type": "integer"})),
    ToolSpec("complete_subgoal", "Mark the active subgoal done (with evidence summary).",
             "control", _schema(summary={"type": "string"}, evidence={})),
    ToolSpec("block_subgoal", "Mark the active subgoal blocked (becomes an open question).",
             "control", _schema(reason={"type": "string"})),
    ToolSpec("ask_user", "Pause and ask the human a question.", "control",
             _schema(question={"type": "string"}, options={"type": "array"})),
    ToolSpec("propose", "Finish with a proposal (change + evidence + questions).",
             "control", _schema(before={}, after={}, reasoning_trace={},
                                open_questions={"type": "array"})),
    ToolSpec("finish", "Finish and report the result (what changed, EDA evidence, open issues).",
             "control", _schema(reason={"type": "string"},
                                summary={"type": "string"})),
]

TOOL_BY_NAME: Dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}

TOOL_NAMES = tuple(TOOL_BY_NAME)


def tool_specs_prompt() -> str:
    lines = []
    for spec in TOOL_SPECS:
        lines.append(f"- {spec.name} (risk={spec.risk}): {spec.description}")
    return "\n".join(lines)
