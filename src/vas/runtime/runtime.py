"""Agent Runtime 1.0 — 生命周期、权限、预算、trace；不执行业务逻辑。"""
from __future__ import annotations

from typing import Callable, Dict

from ..contracts import TaskContract, TaskResult
from .context import AgentContext
from .permissions import assert_task
from .registry import get_agent


Handler = Callable[[TaskContract, AgentContext], TaskResult]


class AgentRuntime:
    def __init__(self, handlers: Dict[str, Handler] | None = None):
        self.handlers = dict(handlers or {})

    def register(self, task_type: str, handler: Handler) -> None:
        self.handlers[task_type] = handler

    def run(self, contract: TaskContract, ctx: AgentContext) -> TaskResult:
        errors = contract.validate_contract()
        if errors:
            return TaskResult(task_id=contract.id, agent=contract.agent,
                              status="failed", error="; ".join(errors))
        spec = get_agent(contract.agent)
        try:
            assert_task(spec, contract.type)
        except PermissionError as exc:
            return TaskResult(task_id=contract.id, agent=contract.agent,
                              status="failed", error=str(exc))
        handler = self.handlers.get(contract.type)
        if handler is None:
            return TaskResult(task_id=contract.id, agent=contract.agent,
                              status="blocked",
                              error=f"no handler for task {contract.type!r}")

        last: TaskResult | None = None
        for attempt in range(1, spec.max_attempts + 1):
            ctx.record({"event": "agent.start", "agent": contract.agent,
                        "task": contract.id, "attempt": attempt})
            try:
                result = handler(contract, ctx)
            except Exception as exc:                   # noqa: BLE001
                result = TaskResult(task_id=contract.id, agent=contract.agent,
                                    status="failed", error=str(exc))
            result.task_id = contract.id
            result.agent = contract.agent
            ctx.record({"event": "agent.result", "agent": contract.agent,
                        "task": contract.id, "status": result.status,
                        "error": result.error})
            last = result
            if result.status in ("ok", "needs_human"):
                return result
        assert last is not None
        return last


__all__ = ["AgentRuntime", "Handler"]
