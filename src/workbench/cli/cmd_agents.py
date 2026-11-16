"""`vagent agents` —— 9 个 agent 的统一入口 + 每个 agent 的专属命令。

两种用法等价：
    vagent agents chat uvm "分析这份 testplan"
    vagent uvm chat "分析这份 testplan"

已有命令组（formal / debug）在自己的文件里挂 `chat`，避免重复注册同名
Click group；其余 agent 在这里动态生成。
"""

from __future__ import annotations

import json

import click

from src.workbench.cli.commands import cli, console
from src.workbench.modes.agent_chat import chat_and_render
from src.workbench.modes.agent_modes import AGENT_MODES

#: 已有同名 Click group 的 agent：chat 子命令在各自 cmd_*.py 里注册。
_EXISTING_GROUPS = {"formal", "debug"}
#: 与既有命令重名的 agent：换一个命令名（`vagent workflows` 已用于列七 Agent）。
_COMMAND_OVERRIDES = {"workflows": "workflow"}


def _command_name(agent_id: str) -> str:
    return _COMMAND_OVERRIDES.get(agent_id, agent_id.replace("_", "-"))


def _chat_options(fn):
    fn = click.argument("prompt")(fn)
    fn = click.option("--workspace", default=None, help="项目工作区（默认当前目录）")(fn)
    fn = click.option("--session", "session_id", default=None, help="沿用既有 session")(fn)
    fn = click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")(fn)
    return fn


def _chat_command(agent_id: str):
    @click.command("chat")
    @_chat_options
    def _cmd(prompt, workspace, session_id, json_output):
        """与该 agent 对话一轮。"""
        chat_and_render(agent_id, prompt, workspace=workspace, session_id=session_id, json_output=json_output)

    return _cmd


@cli.group("agents")
def agent_group():
    """9 个 agent：列出、按 agent 对话（与旧的 `vagent agent` 执行器命令区分）。"""


@agent_group.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def agent_list(json_output):
    """列出 9 个 agent、对应目录与交互方式。"""
    rows = [
        {
            "id": m.id,
            "label": m.label,
            "directory": f"src/agent_plane/specialists/{m.specialist}",
            "interaction": m.interaction,
            "action": m.action,
            "command": f"vagent {_command_name(m.id)} chat '<prompt>'",
            "general_command": f"vagent agents chat {m.id} '<prompt>'",
        }
        for m in AGENT_MODES
    ]
    if json_output:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for row in rows:
        console.print(f"  {row['id']:<20} → {row['directory']}  ({row['interaction']})  {row['command']}")


@agent_group.command("chat")
@click.argument("agent_id")
@_chat_options
def agent_chat(agent_id, prompt, workspace, session_id, json_output):
    """通用入口：`vagent agents chat <agent_id> <prompt>`。"""
    chat_and_render(agent_id, prompt, workspace=workspace, session_id=session_id, json_output=json_output)


def _agent_group(preset) -> click.Group:
    @click.group(name=_command_name(preset.id), help=f"{preset.label}：{preset.description}")
    def _group():
        pass

    _group.add_command(_chat_command(preset.id))
    return _group


for _preset in AGENT_MODES:
    if _preset.id in _EXISTING_GROUPS:
        continue
    cli.add_command(_agent_group(_preset))


__all__ = ["agent_group"]
