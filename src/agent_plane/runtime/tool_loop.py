"""Bounded LLM tool loop —— 子图内部的“专家自己选工具”原语。

不是 LangChain `ToolNode` 的替代品，而是一个**协议简单、可审计**的 ReAct
变体：LLM 每步只输出 JSON（`tool` 或 `final`），执行器只按名字调用白名单工具，
把 observation 截断后喂回。这样：

  · 工具调用不经过 LLM 自由生成的可执行代码；
  · 每步都可记录 `tool_calls`，审计能回答“它为什么改这一刀”；
  · 步数有硬上限，子图不会无限循环。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import json
import re

from src.runtime_plane.tools.common.lib.llm_call import TEXT_SCHEMA, call_llm


@dataclass
class ToolCall:
    tool: str
    args: Dict[str, Any]
    observation: str
    ok: bool = True
    error: str = ""


@dataclass
class LoopResult:
    ok: bool
    answer: str = ""
    steps: int = 0
    tool_calls: List[ToolCall] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "answer": self.answer,
            "steps": self.steps,
            "tool_calls": [
                {"tool": c.tool, "args": c.args, "ok": c.ok,
                 "observation": c.observation[:2000], "error": c.error}
                for c in self.tool_calls
            ],
            "error": self.error,
        }


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates.extend(fenced)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start:end + 1])
    for raw in candidates:
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def _default_llm(prompt: str) -> str:
    return call_llm(prompt, "", "", output_schema=TEXT_SCHEMA,
                   prompt_version="agent-tool-loop-v1",
                   output_format="text")


def _tool_names(tools: Sequence[Any]) -> str:
    lines = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "")
        desc = str(getattr(tool, "description", "") or "")
        if name:
            lines.append(f"- {name}: {desc[:300]}")
    return "\n".join(lines)


def _invoke(tool: Any, args: Dict[str, Any]) -> str:
    if hasattr(tool, "invoke"):
        out = tool.invoke(args or {})
    elif callable(tool):
        out = tool(**(args or {}))
    else:
        raise TypeError(f"工具 {tool!r} 不可调用")
    if isinstance(out, str):
        return out
    return json.dumps(out, ensure_ascii=False, default=str)


def run_tool_loop(goal: str, tools: Sequence[Any], *,
                  llm: Optional[Callable[[str], str]] = None,
                  max_steps: int = 6,
                  context: str = "") -> LoopResult:
    """运行有界工具循环；`tools` 必须是带 `name`/`description`/`invoke` 的对象。"""
    if max_steps <= 0:
        return LoopResult(ok=False, error="max_steps 必须 > 0")
    by_name = {str(getattr(t, "name", "") or ""): t for t in tools}
    by_name.pop("", None)
    if not by_name:
        return LoopResult(ok=False, error="没有可用工具")

    llm = llm or _default_llm
    history: List[str] = []
    calls: List[ToolCall] = []
    system = (
        "你是芯片验证专家。你只能通过工具观察和修改环境。\n"
        f"目标：{goal}\n"
        f"工具：\n{_tool_names(tools)}\n"
        "每步只输出一个 JSON，不要输出其它文字：\n"
        '{"action":"tool","tool":"工具名","args":{...}}\n'
        '或 {"action":"final","answer":"结论"}\n'
        "不要猜测工具结果；必须调用工具验证。\n"
    )
    if context:
        system += f"\n当前上下文（截断）：\n{context[:4000]}\n"

    for step in range(1, max_steps + 1):
        prompt = system + "\n历史：\n" + ("\n".join(history) if history else "(空)")
        try:
            raw = llm(prompt)
        except Exception as exc:                       # noqa: BLE001
            return LoopResult(ok=False, steps=step, tool_calls=calls,
                              error=f"LLM 调用失败: {exc}")
        doc = _extract_json(raw)
        if not doc:
            history.append("observation: 上一步不是合法 JSON，请只输出 JSON")
            continue
        action = str(doc.get("action") or "").strip().lower()
        if action == "final":
            return LoopResult(ok=True, answer=str(doc.get("answer") or ""),
                              steps=step, tool_calls=calls)
        if action != "tool":
            history.append("observation: action 必须是 tool 或 final")
            continue
        name = str(doc.get("tool") or "").strip()
        args = doc.get("args") if isinstance(doc.get("args"), dict) else {}
        tool = by_name.get(name)
        if tool is None:
            history.append(f"observation: 未知工具 {name!r}；可用 {sorted(by_name)}")
            continue
        try:
            observation = _invoke(tool, args)
            calls.append(ToolCall(name, args, observation[:4000], ok=True))
            history.append(f"tool {name} -> {observation[:4000]}")
        except Exception as exc:                       # noqa: BLE001
            calls.append(ToolCall(name, args, "", ok=False, error=str(exc)))
            history.append(f"tool {name} 失败: {exc}")
    return LoopResult(ok=False, steps=max_steps, tool_calls=calls,
                      error=f"超过 max_steps={max_steps} 仍未 final")


__all__ = ["LoopResult", "ToolCall", "run_tool_loop"]
