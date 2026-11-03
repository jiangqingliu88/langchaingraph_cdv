"""显式结果状态 —— 把"吞掉的异常"变成下游可判的字段。

签核链路里最坏的不是失败，而是**失败被静默吞掉**：索引没写进去、CAS 没落盘，
日志里若只留一行 warning，质量门只能看到"产物缺失"，说不清是"没做"还是
"做了没写成"。这里给关键写入端一个统一的三态：

    ok          成功
    degraded    部分失败（主流程可继续，但有东西没写成）
    unavailable 前置条件缺失（没数据 / 没权限 / 没工具）

`issues` 原文保留异常信息。用法：

    from src.core.runtime.outcome import Outcome
    self._last = Outcome.success()     # 或 Outcome.degraded("...")
    if not self._last.ok: event_store.append(...)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Outcome:
    status: str = "ok"
    issues: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @classmethod
    def success(cls) -> "Outcome":
        return cls(status="ok")

    @classmethod
    def degraded(cls, issue: str) -> "Outcome":
        return cls(status="degraded", issues=[str(issue)])

    @classmethod
    def unavailable(cls, issue: str) -> "Outcome":
        return cls(status="unavailable", issues=[str(issue)])

    def add(self, issue: str) -> "Outcome":
        self.issues.append(str(issue))
        if self.status == "ok":
            self.status = "degraded"
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "ok": self.ok, "issues": list(self.issues)}


__all__ = ["Outcome"]
