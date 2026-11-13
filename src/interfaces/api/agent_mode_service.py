"""长循环 agent 服务 —— CLI `vagent` / `-p` / REPL 的统一入口。

不 import `PipelineExecutionService`：agent 直接复用 `src/agent/runtime`，
确定性 verify/VPlan 内核由 harness 的 `run_verify` 工具按需调用。
默认是**直接模式**：工作区根就是项目根，agent 原地读写；会话/日志落在
`<project>/.signoffai/`。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.agent.runtime.harness import Harness, HarnessConfig
from src.runtime.session import Session
from src.runtime.workspace_manager import WorkspaceZones, _discover_project_root

DEFAULT_MAX_STEPS = 40
DEFAULT_MAX_ROUNDS = 2

Planner = Optional[Callable[[Dict[str, Any]], Any]]


def resolve_project_root(path: str | Path | None = None) -> Path:
    start = (Path(path).expanduser().resolve() if path
             else Path.cwd().resolve())
    return _discover_project_root(start, start)


def resolve_workspace(path: str | Path | None = None, *,
                      project_root: str | Path | None = None) -> WorkspaceZones:
    root = (Path(path).expanduser().resolve() if path
            else resolve_project_root(project_root))
    return WorkspaceZones.direct_mode(
        root, project_root=project_root or root)


def _config(project_root: Path, overrides: Dict[str, Any] | None = None) -> HarnessConfig:
    values: Dict[str, Any] = {
        "max_steps": DEFAULT_MAX_STEPS,
        "max_rounds": DEFAULT_MAX_ROUNDS,
        "max_tokens": 400_000,
        "emit_proposal": False,
        "project_root": str(project_root),
        "allow_unreviewed": True,
        "compaction": True,
    }
    values.update(overrides or {})
    return HarnessConfig(**values)


def _stage_runner(role: str, **kwargs: Any) -> Dict[str, Any]:
    from src.interfaces.api.stage_service import run_stage_executor
    return run_stage_executor(role, **kwargs)


def _exit_code(status: str) -> int:
    if status in ("proposal", "finished_no_proposal", "done"):
        return 0
    if status == "cancelled":
        return 130
    return 1


def _summary(result: Dict[str, Any], session: Dict[str, Any]) -> str:
    if result.get("status") == "proposal":
        proposal = result.get("proposal") or {}
        evidence = proposal.get("evidence") or {}
        return str(evidence.get("reasoning_trace")
                   or evidence.get("after") or "proposal emitted")
    if result.get("reason"):
        return str(result["reason"])
    if result.get("error"):
        return str(result["error"])
    return f"{result.get('status', 'unknown')} (state={session.get('state')})"


def envelope(result: Dict[str, Any], session: Session) -> Dict[str, Any]:
    projection = result.get("session") or session.projection()
    status = str(result.get("status") or projection.get("state") or "unknown")
    working = session.working or {}
    evidence = working.get("evidence") or {}
    return {
        "status": status,
        "exit_code": _exit_code(status),
        "session_id": projection.get("session_id"),
        "state": projection.get("state"),
        "summary": _summary(result, projection),
        "changed_files": working.get("changed_files") or [],
        "commands": evidence.get("commands") or [],
        "logs": evidence.get("logs") or [],
        "eda": working.get("eda") or {},
        "open_questions": working.get("open_questions") or [],
        "pending": result.get("pending") or projection.get("pending") or {},
        "proposal_id": result.get("proposal_id") or projection.get("proposal_id") or "",
        "error": result.get("error") or "",
        "session": projection,
    }


def agent_turn(prompt: str, *, workspace: str | Path | None = None,
               session_id: Optional[str] = None,
               project_root: str | Path | None = None,
               planner: Planner = None,
               config: Dict[str, Any] | None = None,
               max_steps: Optional[int] = None,
               stage_runner: Callable[..., Dict[str, Any]] | None = None
               ) -> Dict[str, Any]:
    """跑一个用户 turn。`session_id` 给出时沿用已有会话（多轮）。"""
    if not str(prompt or "").strip():
        return {"status": "invalid", "exit_code": 1, "error": "prompt 为空",
                "session_id": session_id or ""}
    zones = resolve_workspace(workspace, project_root=project_root)
    cfg = _config(zones.project_root(), config)
    harness = Harness(zones, config=cfg, planner=planner,
                      session_id=session_id,
                      stage_runner=stage_runner or _stage_runner)
    if session_id:
        result = harness.send(prompt, max_steps=max_steps)
    else:
        result = harness.run(prompt, max_steps=max_steps)
    return envelope(result, harness.session)


def resume_turn(session_id: str, *, workspace: str | Path | None = None,
                project_root: str | Path | None = None,
                approve: Optional[bool] = None, answer: str = "",
                plan: str = "", planner: Planner = None,
                config: Dict[str, Any] | None = None,
                stage_runner: Callable[..., Dict[str, Any]] | None = None
                ) -> Dict[str, Any]:
    zones = resolve_workspace(workspace, project_root=project_root)
    cfg = _config(zones.project_root(), config)
    harness = Harness(zones, config=cfg, planner=planner,
                      session_id=session_id,
                      stage_runner=stage_runner or _stage_runner)
    result = harness.resume(approve=approve, answer=answer, plan=plan)
    return envelope(result, harness.session)


def last_session(zones: WorkspaceZones) -> str:
    sessions = sorted((zones.harness_dir / "sessions").glob("*.json"))
    return sessions[-1].stem if sessions else ""


def render(result: Dict[str, Any]) -> None:
    """CLI 人类可读输出；失败也给足信息，不吞异常。"""
    status = result.get("status")
    icon = "✓" if result.get("exit_code") == 0 else "✗"
    print(f"{icon} {status}  session={result.get('session_id', '')}")
    if result.get("summary"):
        print(f"  {result['summary']}")
    changed = result.get("changed_files") or []
    if changed:
        print(f"  改动 {len(changed)} 个文件：")
        for row in changed[:20]:
            print(f"    {row.get('action', '?'):7} {row.get('path')}")
    eda = result.get("eda") or {}
    if eda:
        after = eda.get("after") or {}
        regression = after.get("regression") or {}
        if isinstance(regression, dict):
            regression = regression.get("status") or regression.get("failed")
        print(f"  EDA: regression={regression or '?'} "
              f"functional={after.get('functional_pct', '?')}% "
              f"run={eda.get('run_dir', '')}")
    pending = result.get("pending") or {}
    if pending:
        print(f"  等待人工：{pending.get('kind')} "
              f"{pending.get('question') or pending.get('tool') or ''}")
    if result.get("error"):
        print(f"  错误：{result['error']}")


__all__ = ["agent_turn", "resume_turn", "resolve_workspace",
           "resolve_project_root", "last_session", "render", "envelope"]
