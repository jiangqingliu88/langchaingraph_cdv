"""Workspace zones —— main / staging / proposal / gate.

这一层只做三件事：

  · **分区**：`main/`（签核过的内容，沙箱只读）、`staging/`（可写、可丢弃）、
    `proposals/`（窄接口）、`gate/`（裁决报告与账本）。
  · **隔离**：沙箱的写操作只能落在 `staging/`；`main/` 只由 `gate.promote`
    写入。
  · **窄通道**：staging → main 的唯一路径是 Proposal，且必须过 Gate。

通用 agent loop 在 `workspace.staging.loop`；裁决在 `workspace.gate`。
"""
from .zones import WorkspaceError, WorkspaceZones
from .proposal.schema import Proposal, new_proposal

__all__ = ["WorkspaceError", "WorkspaceZones", "Proposal", "new_proposal"]
