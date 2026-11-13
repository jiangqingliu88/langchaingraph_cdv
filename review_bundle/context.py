"""上下文预算 —— token 估算、tool-result pruner、基础 compaction。

对齐 DeepSeek Harness 的 `token-meter` + `compaction-basic` +
`compaction-tool-result-pruner`。压缩是**确定性的**：不额外调 LLM，避免
压缩本身变成一次不可审计的生成；被裁掉的内容仍在磁盘（日志/文件）里。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

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
                 prune_chars: int = 1_200,
                 audit: Callable[[Dict[str, Any]], None] | None = None,
                 fact_ids: Callable[[], List[str]] | None = None):
        self.max_tokens = int(max_tokens)
        self.keep_recent = keep_recent
        self.prune_chars = prune_chars
        self.audit = audit
        self.fact_ids = fact_ids

    def maybe_compact(self, session: Session) -> bool:
        before_tokens = estimate_messages(session.messages)
        if before_tokens <= self.max_tokens * 3 // 4:
            return False
        before_count = len(session.messages)
        self._prune_tool_results(session)
        if estimate_messages(session.messages) > self.max_tokens * 3 // 4:
            self._summarize_old(session)
        session.compactions += 1
        if self.audit is not None:
            try:
                self.audit({
                    "summary_version": session.compactions,
                    "source_event_range": [0, before_count],
                    "preserved_fact_ids": (self.fact_ids() if self.fact_ids
                                           else []),
                    "dropped_context_refs": max(
                        0, before_count - len(session.messages)),
                    "token_before": before_tokens,
                    "token_after": estimate_messages(session.messages),
                })
            except Exception:                 # noqa: BLE001 审计不能拖垮压缩
                pass
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


def _transcript(session: Session) -> List[Dict[str, Any]]:
    """把内部消息压成纯文本 chat 转录。

    DeepSeek 思考模式要求 assistant 消息回传 `reasoning_content`；我们的
    `record_assistant` 只存 thought + `tool_calls`，直接回传会被 API 拒绝
    （400 invalid_request_error）。所以这里**不发原生 tool_calls**：assistant
    的调用折成文本，tool 结果折成 user observation。
    """
    rows: List[Dict[str, Any]] = []
    for message in session.messages:
        role = str(message.get("role") or "")
        content = message.get("content")
        if role == "tool":
            name = str(message.get("name") or "tool")
            args = message.get("args")
            call = f" args={args}" if isinstance(args, dict) and args else ""
            rows.append({"role": "user",
                         "content": f"[observation:{name}{call}] {content}"})
            continue
        if role == "assistant" and message.get("tool_calls"):
            # 只保留 thought；不要把 tool_call 协议文本喂回去，否则模型会模仿
            # 成“散文 + [tool_call]”，破坏 JSON 决策协议。
            text = str(content or "").strip()
            if text:
                rows.append({"role": "assistant", "content": text})
            continue
        if role in ("system", "user", "assistant"):
            rows.append({"role": role, "content": str(content or "")})
    return rows


def prompt_messages(session: Session, system_prompt: str,
                    *, playbooks_section: str = "",
                    extra_sections: str = "") -> List[Dict[str, Any]]:
    system = system_prompt
    if playbooks_section:
        system = f"{system}\n\n{playbooks_section}"
    if extra_sections:
        system = f"{system}\n\n{extra_sections}"
    summary = (f"\n\n[harness] state={session.state} round={session.round} "
               f"plan={'set' if session.plan else 'none'} "
               f"changed={len(session.working.get('changed_files') or [])}")
    return ([{"role": "system", "content": system + summary}]
            + _transcript(session))
