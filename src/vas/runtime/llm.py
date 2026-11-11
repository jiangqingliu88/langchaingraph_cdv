"""LLM Adapter 1.0 — 可替换的后端，不绑定具体厂商。"""
from __future__ import annotations

from typing import Any, Dict, Protocol


class LLMUnavailable(RuntimeError):
    pass


class LLMAdapter(Protocol):
    name: str

    def complete(self, prompt: str, schema: Dict[str, Any] | None = None) -> Dict[str, Any]:
        ...


class NullLLM:
    name = "null"

    def complete(self, prompt: str, schema: Dict[str, Any] | None = None) -> Dict[str, Any]:
        raise LLMUnavailable("LLM_UNAVAILABLE: no adapter configured")


def call_adapter(adapter: LLMAdapter, prompt: str,
                 schema: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return adapter.complete(prompt, schema)
