"""权限策略 —— 哪些工具可以直接跑，哪些需要人点头。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict

_DESTRUCTIVE = re.compile(
    r"\b(rm|rmdir|del|erase|mv|move|git\s+(reset|checkout|clean)|"
    r"make\s+clean|truncate|format)\b", re.IGNORECASE)
_HIGH_RISK_PATH = re.compile(
    r"(^|/)(rtl|sv|env|agents|tb|coverage|data/contract_matrix)/|"
    r"(^|/)\.env", re.IGNORECASE)


@dataclass(frozen=True)
class PermissionDecision:
    action: str          # "allow" | "ask" | "deny"
    reason: str = ""


class PermissionPolicy:
    """沙箱内默认放行；`require_exec` 时命令类工具走人工批准。

    直接模式下 `protect_destructive=True` 时，删文件、破坏性 shell、改
    RTL/UVM/契约矩阵默认走审批。分析/新建普通文件仍放行。
    """

    def __init__(self, *, require_exec: bool = False, deny: tuple[str, ...] = (),
                 protect_destructive: bool = True):
        self.require_exec = bool(require_exec)
        self.deny = set(deny)
        self.protect_destructive = bool(protect_destructive)

    def decide(self, tool: str, risk: str, *,
               requires_approval: bool = False,
               args: Dict[str, Any] | None = None,
               direct: bool = False,
               protect_destructive: bool | None = None) -> PermissionDecision:
        if tool in self.deny:
            return PermissionDecision("deny", f"{tool} 在拒绝清单里")
        if requires_approval or (self.require_exec and risk == "exec"):
            return PermissionDecision("ask", f"{tool} 需要人工批准")
        protect = (self.protect_destructive if protect_destructive is None
                   else protect_destructive)
        if direct and protect:
            args = args or {}
            if tool == "delete_file":
                return PermissionDecision("ask", "直接模式删除文件需要确认")
            command = str(args.get("command") or "") if isinstance(args, dict) else ""
            if tool == "run_shell" and _DESTRUCTIVE.search(command):
                return PermissionDecision("ask", "破坏性 shell 命令需要确认")
            path = str((args or {}).get("path") or "")
            if tool in ("write_file", "str_replace") and _HIGH_RISK_PATH.search(path):
                return PermissionDecision("ask", f"高风险路径需要确认：{path}")
        return PermissionDecision("allow")
