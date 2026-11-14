"""对话与终端共用 Agent 的入口；不是另一套 LLM 调用链。"""

from __future__ import annotations

import json

import click

from src.workbench.cli.commands import cli


@cli.command("chat")
@click.argument("prompt", required=False, default="")
@click.option(
    "--mode",
    "interaction_mode",
    type=click.Choice(["chat", "plan", "verify"]),
    default="chat",
    show_default=True,
    help="对话 / 待审查计划 / 显式验证执行",
)
@click.option("--workspace", type=click.Path(file_okay=False, path_type=str), default=None)
@click.option("--session", "session_id", default="", help="继续 Agent 会话；等待审批时用 resume")
@click.option("--resume", "resume_id", default="", help="恢复一个已挂起的 Agent 会话")
@click.option("--approve", type=click.Choice(["yes", "no"]), default="yes", show_default=True)
@click.option("--answer", default="", help="resume 时回答 ask_user")
@click.option("--plan-text", default="", help="resume 时提供经过人审的调整计划")
@click.option("--repl", is_flag=True, help="进入既有多轮终端 REPL（不重建 Agent）")
@click.option("--json", "json_output", is_flag=True)
def chat_command(
    prompt: str,
    interaction_mode: str,
    workspace: str | None,
    session_id: str,
    resume_id: str,
    approve: str,
    answer: str,
    plan_text: str,
    repl: bool,
    json_output: bool,
):
    """自然语言交互；显式 --mode verify 才进入确定性验证主链。"""
    if repl:
        if prompt or interaction_mode != "chat" or session_id or resume_id:
            raise click.UsageError("--repl 不接受 prompt、mode、session 或 resume")
        from src.workbench.cli.repl import run_interactive

        raise SystemExit(run_interactive(workspace=workspace))
    if resume_id:
        if interaction_mode == "verify":
            raise click.UsageError("Agent 会话恢复不能与 verify 模式混用")
        from src.workbench.api.agent_mode_service import render, resume_turn

        result = resume_turn(resume_id, workspace=workspace, approve=approve == "yes", answer=answer, plan=plan_text)
        if not json_output:
            render(result)
    else:
        from src.workbench.api.agent_mode_service import render
        from src.workbench.modes.interaction import turn

        if not prompt.strip():
            raise click.UsageError("请提供对话内容，或使用 --repl 进入多轮终端")
        result = turn(prompt, mode=interaction_mode, workspace=workspace, session_id=session_id or None)
        if not json_output:
            render(result)
    if interaction_mode == "verify":
        from src.workbench.modes.verify_mode import exit_code

        code = exit_code(result)
    else:
        code = int(result.get("exit_code", 0))
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    raise SystemExit(code)
