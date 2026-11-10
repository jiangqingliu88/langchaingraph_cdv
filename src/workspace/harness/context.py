"""上下文预算 —— token 估算、tool-result pruner、基础 compaction。

对齐 DeepSeek Harness 的 `token-meter` + `compaction-basic` +
`compaction-tool-result-pruner`。压缩是**确定性的**：不额外调 LLM，避免
压缩本身变成一次不可审计的生成；被裁掉的内容仍在磁盘（日志/文件）里。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .session import Session


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)


def estimate_messages(messages: List[Dict[str, Any]]) -> int:
    return sum(estimate_tokens(m.get("content", ""))
               + estimate_tokens(m.get("tool_calls", "")) for m in messages)


class Compactor:
    def __init__(self, max_tokens: int = 200_000, *, keep_recent: int = 6,
                 prune_chars: int = 1_200):
        self.max_tokens = int(max_tokens)
        self.keep_recent = keep_recent
        self.prune_chars = prune_chars

    def maybe_compact(self, session: Session) -> bool:
        if estimate_messages(session.messages) <= self.max_tokens * 3 // 4:
            return False
        self._prune_tool_results(session)
        if estimate_messages(session.messages) > self.max_tokens * 3 // 4:
            self._summarize_old(session)
        session.compactions += 1
        return True

    def _prune_tool_results(self, session: Session) -> None:
        tool_indexes = [i for i, m in enumerate(session.messages)
                        if m.get("role") == "tool"]
        for index in tool_indexes[:-self.keep_recent]:
            message = session.messages[index]
            content = message.get("content")
            text = content if isinstance(content, str) else json.dumps(
                content, ensure_ascii=False, default=str)
            if len(text) <= self.prune_chars:
                continue
            message["content"] = {
                "pruned": True,
                "chars": len(text),
                "head": text[:400],
                "tail": text[-200:],
                "note": "完整内容在 staging 日志/文件里",
            }
            message["pruned"] = True

    def _summarize_old(self, session: Session) -> None:
        keep = self.keep_recent * 2
        if len(session.messages) <= keep + 1:
            return
        prefix = [m for m in session.messages[:1] if m.get("role") == "system"]
        dropped = session.messages[len(prefix):-keep]
        kept = session.messages[-keep:]
        summary = {
            "role": "system",
            "content": ("[compacted] 省略了 {} 条较早消息；当前状态：round={} "
                        "changed_files={} commands={} logs={}").format(
                len(dropped), session.round,
                len(session.working.get("changed_files") or []),
                len((session.working.get("evidence") or {}).get("commands") or []),
                len((session.working.get("evidence") or {}).get("logs") or [])),
            "compacted": True,
        }
        session.messages = prefix + [summary] + kept


def prompt_messages(session: Session, system_prompt: str,
                    *, skills_section: str = "") -> List[Dict[str, Any]]:
    system = system_prompt
    if skills_section:
        system = f"{system}\n\n{skills_section}"
    summary = (f"\n\n[harness] state={session.state} round={session.round} "
               f"plan={'set' if session.plan else 'none'} "
               f"changed={len(session.working.get('changed_files') or [])}")
    return ([{"role": "system", "content": system + summary}]
            + list(session.messages))
