"""Standalone subagent runner —— 进程级隔离入口。

由 `SubagentManager` 以 `python -m src.agent.collaboration.runner`
启动；每个子 Agent 有自己的进程、Harness、session、TaskStore 和 workspace。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from src.runtime.sandbox import SandboxTools
from src.runtime.workspace_manager import WorkspaceZones
from ..runtime.harness import Harness, HarnessConfig
from .contract import SubagentContract, SubagentResult
from .factory import AGENT_TYPES, ROLE_PROMPTS
from .isolation import ScopedTools, SubagentWorkspace


def _mapped_status(raw: str) -> str:
    return {
        "finished_no_proposal": "COMPLETED",
        "proposal": "COMPLETED",
        "done": "COMPLETED",
        "blocked": "BLOCKED",
        "cancelled": "CANCELLED",
        "timeout": "TIMEOUT",
    }.get(str(raw or ""), "FAILED")


def run(contract_path: Path, prompt_path: Path, project_root: Path) -> int:
    contract = SubagentContract.from_dict(
        json.loads(contract_path.read_text(encoding="utf-8")))
    prompt = prompt_path.read_text(encoding="utf-8", errors="replace")
    spec = AGENT_TYPES.get(contract.agent_type)
    if spec is None:
        raise KeyError(f"未知 agent_type: {contract.agent_type}")

    zones = WorkspaceZones.direct_mode(project_root)
    workspace = SubagentWorkspace(zones, contract.task_id).ensure()
    write_roots = [str(workspace.workspace_dir)]
    for prefix in (contract.scope or {}).get("write") or []:
        write_roots.append(str(zones.staging_path(prefix)))
    tools = ScopedTools(
        SandboxTools(zones), zones,
        allowed_tools=spec.allowed_tools,
        write_roots=write_roots,
        allow_exec=any(t in spec.allowed_tools
                       for t in ("run_shell", "run_verify", "run_stage")),
    )
    cfg = HarnessConfig(
        max_steps=max(1, spec.max_steps),
        max_steps_per_subgoal=0,
        max_rounds=1,
        plan_first=False,
        require_plan_approval=False,
        require_exec_approval=False,
        allow_subagent=False,
        emit_proposal=False,
        compaction=True,
        role_prompt=ROLE_PROMPTS.get(contract.agent_type, ""),
        project_root=str(project_root),
    )
    harness = Harness(zones, config=cfg, tools=tools)
    raw = harness.run(prompt, max_steps=spec.max_steps)
    session = harness.session
    result = SubagentResult(
        task_id=contract.task_id,
        status=_mapped_status(raw.get("status")),
        summary=str(raw.get("reason") or raw.get("summary")
                    or raw.get("error") or session.last_error),
        artifacts=workspace.list_artifacts(),
        unresolved=list(session.working.get("open_questions") or []),
        fingerprint=contract.fingerprint,
        validated=False,
    )
    target = workspace.root / "runner_result.json"
    target.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="run one isolated subagent")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--prompt", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return run(args.contract, args.prompt, args.project_root.resolve())
    except Exception as exc:                     # noqa: BLE001 结果要落盘，不能只 stderr
        try:
            contract = SubagentContract.from_dict(
                json.loads(args.contract.read_text(encoding="utf-8")))
            workspace = SubagentWorkspace(
                WorkspaceZones.direct_mode(args.project_root.resolve()),
                contract.task_id).ensure()
            workspace.write_json("runner_result.json", SubagentResult(
                task_id=contract.task_id, status="FAILED",
                summary=f"{type(exc).__name__}: {exc}").to_dict())
        except Exception:                        # noqa: BLE001
            pass
        print(f"subagent runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
