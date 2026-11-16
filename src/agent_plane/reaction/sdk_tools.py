"""把已存在的 LangChain/项目工具转成 openai-agents FunctionTool。"""

from __future__ import annotations

import inspect
import json
from contextvars import ContextVar
from typing import Any

from agents import function_tool

from src.agent_plane.reaction.tools import list_source_files, named_tool, read_source, unavailable_tool
from src.agent_plane.runtime.tool_loop import _invoke


def _bounded(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "<truncated>"
    if isinstance(value, dict):
        output = {}
        for key, item in list(value.items())[:24]:
            lowered = str(key).lower()
            if any(term in lowered for term in ("api_key", "password", "token", "authorization", "secret")):
                output[key] = "<redacted>"
            else:
                output[key] = _bounded(item, depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        return [_bounded(item, depth + 1) for item in value[:12]]
    if isinstance(value, str):
        return value[:8000]
    return value


def _serialized(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _decode_arguments(args: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    try:
        doc = json.loads(args or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("工具参数必须是 JSON 对象或 JSON 字符串") from exc
    # 本适配器对 LLM 暴露 args 为 JSON 字符串。兼容旧的 action.tool args 格式。
    if isinstance(doc, dict) and set(doc) == {"args"}:
        nested = doc["args"]
        if isinstance(nested, str):
            doc = json.loads(nested or "{}")
        elif isinstance(nested, dict):
            doc = nested
    if not isinstance(doc, dict):
        raise ValueError("工具 args 必须解码为 JSON 对象")
    return doc


def _failure(_context, exception: Exception) -> str:
    return json.dumps(
        {
            "status": "INCOMPLETE",
            "error_type": type(exception).__name__,
            "detail": str(exception)[:1000],
        },
        ensure_ascii=False,
    )


def to_sdk_tool(tool: Any, context: ContextVar[list[dict[str, Any]]]) -> Any:
    """适配实际工具，不生成独立 invoke 分支，并让审批/结果交由 SDK 管理。"""
    name = str(getattr(tool, "name", "") or getattr(tool, "__name__", ""))
    description = str(getattr(tool, "description", "") or getattr(tool, "__doc__", "") or name)
    needs_approval = bool(getattr(tool, "requires_approval", False))

    if not name:
        raise ValueError("SDK 工具必须有稳定 name")

    if hasattr(tool, "invoke"):

        async def call(args: str = "{}") -> str:
            params = _decode_arguments(args)
            try:
                raw = _invoke(tool, params)
                if inspect.isawaitable(raw):
                    raw = await raw
                result = _serialized(raw)
            except Exception as exc:  # 工具真正的失败不写成成功结果
                result = json.dumps(
                    {
                        "status": "INCOMPLETE",
                        "error_type": type(exc).__name__,
                        "detail": str(exc)[:1000],
                    },
                    ensure_ascii=False,
                )
            rows = context.get()
            if rows is not None:
                rows.append({"tool": name, "args": _bounded(params), "result": _bounded(result)})
            return result
    elif callable(tool):

        async def call(**kwargs):
            try:
                raw = tool(**kwargs)
                if inspect.isawaitable(raw):
                    raw = await raw
                result = _serialized(raw)
            except Exception as exc:
                result = json.dumps(
                    {"status": "INCOMPLETE", "error_type": type(exc).__name__, "detail": str(exc)[:1000]},
                    ensure_ascii=False,
                )
            rows = context.get()
            if rows is not None:
                rows.append({"tool": name, "args": _bounded(kwargs), "result": _bounded(result)})
            return result
    else:
        raise TypeError(f"{name} 必须支持 invoke 或 callable")

    call.__name__ = name
    call.__doc__ = description
    return function_tool(
        name_override=name,
        description_override=description,
        failure_error_function=_failure,
        needs_approval=needs_approval,
    )(call)


def sdk_readonly_tools(root, context: ContextVar[list[dict[str, Any]]]) -> list[Any]:
    return [
        to_sdk_tool(
            named_tool(
                "read_source", "受限源读取：file path + optional line range/quote", lambda args: read_source(root, args)
            ),
            context,
        ),
        to_sdk_tool(
            named_tool(
                "list_source_files", "列出受限目录中的文本项目录（不递归）", lambda args: list_source_files(root, args)
            ),
            context,
        ),
    ]


def sdk_unavailable_tool(name: str, reason: str) -> Any:
    # 注册能力名，也显示尚未实现：绝不以不可用结果填充成功状态。
    return named_tool(
        name,
        "adapter not configured",
        lambda _args: {
            "status": "NOT_RUN",
            "reason": reason,
            "capability_executed": False,
        },
    )


__all__ = ["to_sdk_tool", "sdk_readonly_tools", "sdk_unavailable_tool", "unavailable_tool"]
