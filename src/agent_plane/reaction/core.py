"""各独立 Agent 的 openai-agents 入口。

这些 Agent 复用 SDK 的 Agent / Runner / Tool / Approval 机制，不再复制
另一套 LLM 调用循环。LangGraph Specialist 的既有路径保持为兼容入口。
"""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agents import Agent, Runner

from .sdk_model import ProjectBudgetedModel
from .sdk_tools import sdk_readonly_tools, sdk_unavailable_tool, to_sdk_tool

DEFAULT_READONLY_TOOLS = ("read_source", "list_source_files")


@dataclass(frozen=True)
class RoleSpec:
    role_id: str
    domain: str
    title: str
    responsibility: str
    inputs: tuple[str, ...]
    instructions: str
    allowed_tools: tuple[str, ...] = DEFAULT_READONLY_TOOLS
    max_steps: int = 6
    write_allowed: bool = False


def _bounded_payload(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "<truncated>"
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if any(t in str(key).lower() for t in ("api_key", "password", "token", "secret", "authorization"))
            else _bounded_payload(item, depth + 1)
            for key, item in list(value.items())[:28]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_payload(item, depth + 1) for item in value[:14]]
    if isinstance(value, str):
        return value[:12000]
    return value


class ReActAgent:
    """基类：每类角色拥有自己的 SDK Agent，而不是同名共享循环实例。

    ``workflow`` 是真正可作为 Runner.starting_agent 的 SDK Agent。工具包括
    受限 SourceAnchor 读取和子类已经确认的生成器/诊断器。
    """

    ROLE = RoleSpec("base", "meta", "Base agent", "generic role", (), "Inspect data with declared tools only.")

    def __init__(
        self,
        workspace_root: str | Path = ".",
        *,
        tools: list[Any] | None = None,
        decision_backend: Any | None = None,
        output_root: str | Path | None = None,
    ) -> None:
        self.root = Path(workspace_root).resolve()
        self.output_root = str(output_root) if output_root is not None else ""
        if self.output_root:
            requested = Path(output_root).resolve()
            try:
                requested.relative_to(self.root)
            except ValueError as exc:
                raise ValueError("output_root 必须在 workspace_root 之内") from exc
        self._tool_context: ContextVar[list[dict[str, Any]]] = ContextVar(
            f"react_tools_{self.role.role_id}_{id(self)}", default=None
        )
        factories = tools if tools is not None else self.build_tools(self.root, self.output_root)
        self._tools = self._validate_tools(factories)
        self.workflow = Agent(
            name=self.role.title,
            instructions=self._instructions(),
            model=ProjectBudgetedModel(self.role.role_id, direct_decider=decision_backend),
            tools=self._tools,
        )

    @property
    def role(self) -> RoleSpec:
        return self.ROLE

    # ── ChipStack 目录契约（R-020） ──

    @property
    def artifact_dir_name(self) -> str:
        """本角色在 run / design 目录下的固定子目录名。"""
        from src.agent_plane.domains import artifact_dir

        return artifact_dir(self.role.role_id)

    @property
    def artifact_root(self) -> Optional[Path]:
        """产物目录；没有显式 `output_root` 时返回 None（不伪造写权限）。"""
        if not self.output_root:
            return None
        return Path(self.output_root) / self.artifact_dir_name

    def ensure_artifact_root(self) -> Optional[Path]:
        """建好本 agent 的产物目录并返回；只应在已有 `output_root` 时调用。"""
        root = self.artifact_root
        if root is not None:
            (root / "logs").mkdir(parents=True, exist_ok=True)
        return root

    def _instructions(self) -> str:
        return (
            f"{self.role.instructions}\n"
            f"Required input categories: {self.role.inputs}.\n"
            "Do not invent tool results, processor output, source anchors or signoff evidence.\n"
            "Only registered tools can be used. Any unavailable operation must remain INCOMPLETE.\n"
            "A final proposal is a candidate, never a PASS without deterministic engine evidence.\n"
            "Use observations to decide the next step instead of claiming finished design understanding."
        )

    def build_tools(self, workspace_root: Path, output_root: str) -> list[Any]:
        return sdk_readonly_tools(workspace_root, self._tool_context) + self.backend_tools(workspace_root, output_root)

    def backend_tools(self, workspace_root, output_root):
        """子类把既有生成器放在这里；缺后端用显式 unavailable_tool。"""
        return []

    def _validate_tools(self, tools: list[Any]) -> list[Any]:
        allowed = set(self.role.allowed_tools)
        result = []
        names = set()
        from agents.tool import FunctionTool

        for tool in tools:
            if isinstance(tool, FunctionTool):
                name = tool.name
                if name not in allowed:
                    raise ValueError(f"{self.role.role_id} 未允许工具：{name}")
                if name in names:
                    raise ValueError(f"{self.role.role_id} 的工具重名：{name}")
                names.add(name)
                result.append(tool)
                continue
            # 旧项目工具经适配器进入 SDK；只读工具定义不能伪装成被拒绝的调用。
            if hasattr(tool, "on_invoke_tool"):
                raise TypeError("SDK Tool Invocation 不是工具定义，不能注册为工具")
            name = str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "")
            if name not in allowed:
                raise ValueError(f"{self.role.role_id} 未允许工具：{name}")
            if name in names:
                raise ValueError(f"{self.role.role_id} 的工具重名：{name}")
            names.add(name)
            if hasattr(tool, "name"):
                result.append(to_sdk_tool(tool, self._tool_context))
            else:
                result.append(tool)
        return result

    def require_approval_for_write_calls(self, tools: list[Any]) -> list[Any]:
        """写操作必须有 needs_approval；没有输出根目录的工具仍明确 NOT_RUN。"""
        if not self.output_root:
            return [
                sdk_unavailable_tool(getattr(tool, "name", "write_artifact"), "需要显式受限 output_root；当前未提供")
                for tool in tools
            ]
        for tool in tools:
            setattr(tool, "requires_approval", True)
        return tools

    async def ainvoke(
        self, goal: str, *, output_root=None, history: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        if not str(goal or "").strip():
            return {"status": "INCOMPLETE", "agent": self.role.role_id, "error": "missing_goal"}
        if output_root is not None and output_root != self.output_root:
            raise ValueError("写入 output_root 必须在创建 Agent 时声明，不能在调用中临时提权")
        token = self._tool_context.set([])
        try:
            if history is None:
                inputs: Any = goal
            else:
                if not all(isinstance(row, dict) for row in history):
                    raise ValueError("history 必须为 SDK Responses 输入项列表")
                inputs = list(history) + [{"role": "user", "content": goal}]
            result = await Runner.run(self.workflow, inputs, max_turns=self.role.max_steps)
            observations = list(self._tool_context.get() or [])
            return self._result(result, observations)
        except Exception as exc:  # noqa: BLE001 总失败与 agent 候选严格区分
            return {
                "status": "INCOMPLETE",
                "agent": self.role.role_id,
                "loop": "openai_agents_react",
                "error_type": type(exc).__name__,
                "reason": str(exc)[:1600],
            }
        finally:
            self._tool_context.reset(token)

    def invoke(self, goal: str, *, output_root=None, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return asyncio.run(self.ainvoke(goal, output_root=output_root, history=history))

    def _result(self, result: Any, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
        interruptions = list(getattr(result, "interruptions", []) or [])
        if interruptions:
            return {
                "status": "PENDING_HUMAN",
                "agent": self.role.role_id,
                "loop": "openai_agents_react",
                "interruptions": [_bounded_payload(i) for i in interruptions],
                "tool_calls": tool_calls,
                "verification": {"status": "UNVERIFIED"},
            }
        output = getattr(result, "final_output", "")
        try:
            content = json.loads(output) if isinstance(output, str) else output
        except json.JSONDecodeError:
            content = {"status": "CANDIDATE", "detail": output}
        if not isinstance(content, dict):
            content = {"status": "INCOMPLETE", "detail": str(output)}
        status = str(content.get("status") or "INCOMPLETE")
        detail = content.get("detail") or content.get("answer") or output
        reasons = []
        if status not in {"CANDIDATE", "INCOMPLETE", "PENDING_HUMAN"}:
            status, reasons = "INCOMPLETE", ["model returned non-contractual completion"]
        if any(
            isinstance(call.get("result"), dict) and call["result"].get("status") in {"INCOMPLETE", "NOT_RUN"}
            for call in tool_calls
        ):
            status = "INCOMPLETE"
            reasons.append("one or more backend tools were not completed")
        return {
            "status": status,
            "agent": self.role.role_id,
            "domain": self.role.domain,
            "loop": "openai_agents_react",
            "answer": detail,
            "candidate": True,
            "verification": {"status": "UNVERIFIED", "reason": "SDK/模型建议不是独立验证结论；查看真实工具调用"},
            "iterations": len(getattr(result, "raw_responses", []) or []),
            "history": [_bounded_payload(i) for i in result.new_items],
            "tool_calls": tool_calls,
            "reasons": reasons,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "role": self.role.role_id,
            "domain": self.role.domain,
            "title": self.role.title,
            "responsibility": self.role.responsibility,
            "inputs": list(self.role.inputs),
            "allowed_tools": list(self.role.allowed_tools),
            "loop": "openai_agents_react",
            "sdk": "openai-agents",
            "runner": type(self.workflow.__self__).__name__
            if hasattr(self.workflow, "__self__")
            else self.workflow.__class__.__name__,
            "max_turns": self.role.max_steps,
            "write_allowed": self.role.write_allowed and bool(self.output_root),
            "output_root_configured": bool(self.output_root),
        }


__all__ = ["ReActAgent", "RoleSpec", "DEFAULT_READONLY_TOOLS"]
