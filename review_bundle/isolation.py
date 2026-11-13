"""子 Agent 隔离：独立工作区 + 受限写工具。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.core.runtime.atomic import atomic_write_json, atomic_write_text

from ...zones import WorkspaceZones, WorkspaceError

_WRITE_TOOLS = {"write_file", "delete_file", "str_replace"}
_SHELL_TOOLS = {"run_shell", "job_start", "run_verify", "run_stage"}


class SubagentWorkspace:
    """`.signoffai/subagents/<task_id>/` —— 任务书、事件、产物、结果。"""

    def __init__(self, zones: WorkspaceZones, task_id: str):
        self.root = zones.harness_dir / "subagents" / str(task_id)
        self.workspace_dir = self.root / "workspace"
        self.logs_dir = self.root / "logs"

    def ensure(self) -> "SubagentWorkspace":
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        return self

    def write_json(self, name: str, value: Any) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return atomic_write_json(self.root / name, value)

    def read_json(self, name: str, default: Any = None) -> Any:
        try:
            return json.loads((self.root / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def write_text(self, name: str, text: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return atomic_write_text(self.root / name, text)

    def write_artifact(self, name: str, text: str) -> Path:
        self.ensure()
        path = self.workspace_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return atomic_write_text(path, text)

    def record_event(self, kind: str, **data: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(),
               "kind": kind, **data}
        with (self.root / "events.jsonl").open("a", encoding="utf-8",
                                               newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def list_artifacts(self) -> List[str]:
        if not self.workspace_dir.is_dir():
            return []
        return sorted(p.relative_to(self.workspace_dir).as_posix()
                      for p in self.workspace_dir.rglob("*") if p.is_file())


class ScopedTools:
    """包住 SandboxTools：工具白名单 + 写路径白名单。

    **不给子 Agent 全局写权限**：写只能落到自己的 workspace 或 contract 声明的
    scope.write；超出范围直接拒绝，而不是等主 Agent 事后发现文件被改。
    """

    def __init__(self, base: Any, zones: WorkspaceZones, *,
                 allowed_tools: Iterable[str] | None = None,
                 write_roots: Iterable[str | Path] = (),
                 allow_exec: bool = True):
        self.base = base
        self.zones = zones
        self.allowed = set(allowed_tools) if allowed_tools else None
        self.write_roots = [self._resolve(root) for root in write_roots]
        self.allow_exec = bool(allow_exec)

    def _resolve(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.zones.staging_path(str(value))
        return path.expanduser().resolve()

    def _allowed_write(self, rel: str) -> bool:
        try:
            target = self.zones.staging_path(rel)
        except WorkspaceError:
            return False
        for root in self.write_roots:
            try:
                target.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def call(self, tool: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
        args = dict(args or {})
        if self.allowed is not None and tool not in self.allowed:
            return {"ok": False, "tool": tool,
                    "error": f"子 Agent 不允许调用工具：{tool}"}
        if tool in _WRITE_TOOLS and not self._allowed_write(
                str(args.get("path") or "")):
            return {"ok": False, "tool": tool,
                    "error": "写路径不在子 Agent scope.write 内"}
        if tool in _SHELL_TOOLS and not self.allow_exec:
            return {"ok": False, "tool": tool,
                    "error": "子 Agent 不允许执行 EDA/命令"}
        return self.base.call(tool, args)


__all__ = ["SubagentWorkspace", "ScopedTools"]
