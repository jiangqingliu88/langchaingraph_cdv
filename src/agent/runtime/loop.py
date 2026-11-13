"""兼容入口 —— `SandboxLoop` 现在是 harness 的薄封装。

完整状态机 / 回填 / 压缩 / goal rounds / 会话恢复都在 `src/agent/runtime/`；
这里保留旧 API（`SandboxLoop(zones, llm=...).run(task)`），避免调用方和旧测试
跟着改。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .harness import Harness, HarnessConfig
from src.runtime.sandbox import SandboxTools
from src.runtime.workspace_manager import WorkspaceZones

_CONFIG_KEYS = {
    "max_rounds", "max_tool_errors", "max_tokens", "plan_first",
    "require_plan_approval", "require_exec_approval", "allow_subagent",
    "emit_proposal", "compaction", "event_sink",
}


class SandboxLoop:
    def __init__(self, zones: WorkspaceZones, *,
                 llm=None, tools: Optional[SandboxTools] = None,
                 max_steps: int = 12, config: Optional[HarnessConfig] = None,
                 **config_kwargs):
        self.zones = zones
        extra = {k: v for k, v in config_kwargs.items() if k in _CONFIG_KEYS}
        self.config = config or HarnessConfig(max_steps=max_steps, **extra)
        self.harness = Harness(zones, config=self.config,
                               planner=llm, tools=tools)
        self.last_error = ""

    def run(self, task: str, *, max_steps: Optional[int] = None) -> Dict[str, Any]:
        result = self.harness.run(task, max_steps=max_steps)
        self.last_error = self.harness.session.last_error
        return result

    def resume(self, **kwargs) -> Dict[str, Any]:
        return self.harness.resume(**kwargs)

    @property
    def session(self):
        return self.harness.session
