"""按 agent 分发对话（CLI 与 GUI 共用）。

`workbench/modes/chats/<agent>.py` 是每个 agent 的对话入口；这里只负责
"agent id → 对应 chat 模块 + 结果展示"，不重复实现 Harness。
"""

from __future__ import annotations

import json
from typing import Any


def run_chat(
    agent_id: str, prompt: str, *, workspace: str | None = None, session_id: str | None = None, frontend: str = "cli"
) -> dict[str, Any]:
    from .agent_modes import get_mode
    from .chats import module as chat_module

    preset = get_mode(agent_id)
    module = chat_module(preset.specialist)
    if module is None:
        raise KeyError(f"未知对话入口：{preset.specialist!r}（agent={agent_id}）")
    return module.chat(prompt, workspace=workspace, session_id=session_id, frontend=frontend)


def chat_and_render(
    agent_id: str,
    prompt: str,
    *,
    workspace: str | None = None,
    session_id: str | None = None,
    json_output: bool = False,
) -> None:
    """跑一次对话并按 CLI 口径展示（JSON 或人类可读）。"""
    import click

    from src.workbench.cli.commands import console

    from .agent_modes import get_mode

    preset = get_mode(agent_id)
    try:
        result = run_chat(agent_id, prompt, workspace=workspace, session_id=session_id)
    except Exception as exc:  # noqa: BLE001 CLI 边界统一展示
        raise click.ClickException(f"{preset.label} 对话失败：{exc}") from exc
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return
    status = result.get("status") or result.get("verdict") or "unknown"
    summary = result.get("summary") or result.get("reason") or ""
    console.print(f"[green]✓ {preset.label}[/green] status={status} session={result.get('session_id', '') or '-'}")
    if summary:
        console.print(f"  {summary}")
    if result.get("error"):
        console.print(f"  [red]错误：{result['error']}[/red]")


__all__ = ["run_chat", "chat_and_render"]
