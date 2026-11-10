"""Workspace 服务 —— CLI 与 Workbench 共用（main / staging / proposal / gate）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.workspace import WorkspaceError, WorkspaceZones
from src.workspace.gate import approve_gate as _approve_gate
from src.workspace.gate import promote as _promote
from src.workspace.gate import run_gate as _run_gate
from src.workspace.harness.session import Session
from src.workspace.proposal.schema import Proposal, ProposalError


def _zones(root: str | Path) -> WorkspaceZones:
    return WorkspaceZones(root).ensure()


def _error(exc: Exception) -> Dict[str, Any]:
    return {"error": str(exc)}


def init_workspace(root: str | Path,
                   from_dir: str | Path | None = None,
                   project_root: str | Path | None = None) -> Dict[str, Any]:
    try:
        zones = WorkspaceZones.init(root, from_dir, project_root=project_root)
    except (WorkspaceError, OSError) as exc:
        return _error(exc)
    return {
        "ok": True,
        "root": str(zones.root),
        "zones": {"main": str(zones.main), "staging": str(zones.staging),
                  "proposals": str(zones.proposals), "gate": str(zones.gate)},
        "main_fingerprint": zones.fingerprint("main"),
        "project_root": str(zones.project_root()),
    }


def list_resources(root: str | Path, kind: str = "",
                   limit: int = 200) -> Dict[str, Any]:
    try:
        zones = _zones(root)
        from src.workspace.resources import ProjectResources
        inventory = ProjectResources(zones.project_root()).inventory(kind, limit)
    except (WorkspaceError, OSError, ValueError) as exc:
        return _error(exc)
    return {"ok": True, "root": str(zones.root),
            "project_root": str(zones.project_root()), **inventory}


def export_evidence(run_dir: str | Path,
                    out: str | Path | None = None) -> Dict[str, Any]:
    """把 run 的证据导出成可交换 zip（v2 签核包优先，否则结构化证据）。"""
    try:
        from src.workspace.harness.domain import export_evidence as _export
        return {"ok": True, **_export(run_dir, out)}
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}


def workspace_status(root: str | Path) -> Dict[str, Any]:
    try:
        zones = _zones(root)
        proposals = list_proposals(root)
    except (WorkspaceError, OSError) as exc:
        return _error(exc)
    return {
        "ok": True,
        "root": str(zones.root),
        "main_fingerprint": zones.fingerprint("main"),
        "staging_changed": zones.changed_files(),
        "proposals": proposals.get("proposals", []),
    }


def list_proposals(root: str | Path) -> Dict[str, Any]:
    try:
        zones = _zones(root)
    except (WorkspaceError, OSError) as exc:
        return _error(exc)
    rows: List[Dict[str, Any]] = []
    for path in sorted(zones.proposals.glob("*.json")):
        try:
            proposal = Proposal.load(zones, path.stem)
        except ProposalError as exc:
            rows.append({"proposal_id": path.stem, "error": str(exc)})
            continue
        rows.append({"proposal_id": proposal.proposal_id,
                     "task": proposal.task, "status": proposal.status,
                     "changed": len(proposal.changed_files),
                     "open_questions": len(proposal.open_questions),
                     "gate": dict(proposal.gate)})
    return {"ok": True, "root": str(zones.root), "proposals": rows}


def reset_staging(root: str | Path) -> Dict[str, Any]:
    """丢弃沙箱：staging 恢复成 main 的副本（proposal/gate 不动）。"""
    try:
        zones = _zones(root)
        zones.reset_staging()
    except (WorkspaceError, OSError) as exc:
        return _error(exc)
    return {"ok": True, "root": str(zones.root),
            "staging_changed": zones.changed_files()}


def create_proposal(root: str | Path, task: str, *, before: str, after: str,
                    reasoning_trace: str, commands: Iterable[str] = (),
                    open_questions: Iterable[str] = (),
                    eda_run: str | None = None,
                    target: float = 0.0) -> Dict[str, Any]:
    """手工通道：基于 staging 现有改动造 proposal；`--run` 的命令真跑并记日志。"""
    try:
        zones = _zones(root)
    except (WorkspaceError, OSError) as exc:
        return _error(exc)
    if not any(str(x).strip() for x in (before, after, reasoning_trace)):
        return {"error": "before / after / reasoning_trace 都不能为空"}
    from src.workspace.staging.tools import SandboxTools
    tools = SandboxTools(zones)
    recorded = []
    for command in commands:
        outcome = tools.call("run_shell", {"command": command})
        if not outcome.get("ok"):
            return {"error": f"命令执行失败：{outcome.get('error')}"}
        result = outcome.get("result") or {}
        recorded.append({"cmd": str(result.get("command")),
                         "exit_code": int(result.get("exit_code", 1)),
                         "log": str(result.get("log") or "")})
    if not recorded:
        return {"error": "proposal 需要证据：至少给一条 --run 命令"}
    evidence = {"before": before, "after": after,
                "commands": recorded,
                "logs": [row["log"] for row in recorded if row["log"]],
                "reasoning_trace": reasoning_trace}
    if eda_run:
        from src.workspace.harness.domain import collect_evidence
        eda = collect_evidence(eda_run, target=target)
        evidence["eda"] = {"after": eda, "target": target,
                           "run_dir": eda.get("run_dir", "")}
    try:
        from src.workspace.proposal.schema import ProposalError, new_proposal
        proposal = new_proposal(
            task, zones, evidence=evidence,
            open_questions=[str(q) for q in open_questions])
        proposal.save(zones)
    except ProposalError as exc:
        return {"error": str(exc)}
    return {"ok": True, "proposal_id": proposal.proposal_id,
            "path": str(zones.proposal_path(proposal.proposal_id)),
            "changed_files": proposal.changed_files,
            "commands": recorded}


def run_sandbox(root: str | Path, task: str, *, max_steps: int = 12,
                llm=None, session_id: str | None = None,
                **config) -> Dict[str, Any]:
    try:
        zones = _zones(root)
        from src.workspace.harness.harness import Harness, HarnessConfig
        harness = Harness(zones, config=HarnessConfig(max_steps=max_steps, **config),
                          planner=llm, session_id=session_id)
        return harness.run(task)
    except (WorkspaceError, OSError) as exc:
        return _error(exc)


def resume_sandbox(root: str | Path, session_id: str, *, approve=None,
                   answer: str = "", plan: str = "", llm=None,
                   **config) -> Dict[str, Any]:
    try:
        zones = _zones(root)
        from src.workspace.harness.harness import Harness, HarnessConfig
        harness = Harness(zones, config=HarnessConfig(**config),
                          planner=llm, session_id=session_id)
        return harness.resume(approve=approve, answer=answer, plan=plan)
    except (WorkspaceError, OSError, FileNotFoundError) as exc:
        return _error(exc)


def list_sessions(root: str | Path) -> Dict[str, Any]:
    try:
        zones = _zones(root)
    except (WorkspaceError, OSError) as exc:
        return _error(exc)
    rows = []
    for path in sorted((zones.harness_dir / "sessions").glob("*.json")):
        try:
            session = Session.load(zones, path.stem)
        except Exception as exc:                 # noqa: BLE001 坏会话照列
            rows.append({"session_id": path.stem, "error": str(exc)})
            continue
        rows.append({"session_id": session.session_id, "task": session.task,
                     "state": session.state, "round": session.round,
                     "step": session.step, "proposal_id": session.proposal_id})
    return {"ok": True, "root": str(zones.root), "sessions": rows}


def run_gate(root: str | Path, proposal_id: str,
             extra_checks: Iterable = (), profile: str = "default") -> Dict[str, Any]:
    try:
        zones = _zones(root)
        proposal = Proposal.load(zones, proposal_id)
    except (WorkspaceError, ProposalError, OSError) as exc:
        return _error(exc)
    hooks = list(extra_checks)
    if profile == "eda":
        from src.workspace.gate.domain_checks import eda_evidence
        hooks.append(eda_evidence)
    return _run_gate(proposal, zones, extra_checks=hooks)


def approve_gate(root: str | Path, proposal_id: str, *, by: str,
                 comment: str = "") -> Dict[str, Any]:
    try:
        zones = _zones(root)
        proposal = Proposal.load(zones, proposal_id)
    except (WorkspaceError, ProposalError, OSError) as exc:
        return _error(exc)
    return _approve_gate(proposal, zones, by=by, comment=comment)


def promote(root: str | Path, proposal_id: str, *, by: str = "",
            force: bool = False) -> Dict[str, Any]:
    try:
        zones = _zones(root)
        proposal = Proposal.load(zones, proposal_id)
    except (WorkspaceError, ProposalError, OSError) as exc:
        return _error(exc)
    return _promote(proposal, zones, by=by, force=force)


__all__ = ["init_workspace", "workspace_status", "reset_staging",
           "list_resources", "list_proposals", "list_sessions",
           "create_proposal", "run_sandbox", "resume_sandbox",
           "export_evidence", "run_gate", "approve_gate", "promote"]
