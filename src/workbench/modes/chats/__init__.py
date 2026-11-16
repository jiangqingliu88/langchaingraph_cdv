"""九个 agent 的对话入口（Interfaces Plane）。

每个模块只声明自己的 `AGENT_ID`，真正对话统一走 `common.chat` →
`workbench.modes.interaction.turn`。`agent_chat.run_chat` 按 preset 名动态
import 本包下的同名模块；这里不做集中注册，增删一个对话入口不需要改本文件。
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Dict

#: preset 名 → 模块名（与 `workbench.modes.agent_modes.AGENT_MODES[].specialist` 一致）
CHAT_MODULES = (
    "agentic_chat", "mental_model", "formal", "uvm", "rtl_designer",
    "unit_testing", "functional_coverage", "debug", "workflows",
)


def module(name: str):
    """按 preset 名取对话模块；未知名字返回 None（调用方给可读错误）。"""
    key = str(name or "").strip()
    if key not in CHAT_MODULES:
        return None
    return import_module(f"{__name__}.{key}")


def chat(name: str, prompt: str, **kwargs: Any) -> Dict[str, Any]:
    target = module(name)
    if target is None:
        raise KeyError(f"未知对话入口：{name!r}")
    return target.chat(prompt, **kwargs)


__all__ = ["CHAT_MODULES", "module", "chat"]
