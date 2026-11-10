"""权限策略 —— 哪些工具可以直接跑，哪些需要人点头。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDecision:
    action: str          # "allow" | "ask" | "deny"
    reason: str = ""


class PermissionPolicy:
    """沙箱内默认放行；`require_exec` 时命令类工具走人工批准。"""

    def __init__(self, *, require_exec: bool = False, deny: tuple[str, ...] = ()):
        self.require_exec = bool(require_exec)
        self.deny = set(deny)

    def decide(self, tool: str, risk: str, *, requires_approval: bool = False) -> PermissionDecision:
        if tool in self.deny:
            return PermissionDecision("deny", f"{tool} 在拒绝清单里")
        if requires_approval or (self.require_exec and risk == "exec"):
            return PermissionDecision("ask", f"{tool} 需要人工批准")
        return PermissionDecision("allow")
