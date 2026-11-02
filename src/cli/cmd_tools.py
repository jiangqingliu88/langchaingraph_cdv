"""CLI 命令组：工具目录与 agent（tool / agent）。

从 `src/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
共享 helper 仍从 `commands` 导入，别在这里再造一份。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
from pathlib import Path  # noqa: F401

import click
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.cli.output import common_options, get_output_adapter  # noqa: F401
from src.cli.commands import (  # noqa: F401
    cli, console, AGENT_ALIASES, VerificationCLI,
)

@cli.group()
def tool():
    """工具发现与直接调用"""
    pass


@tool.command("list")
@click.option("--agent", "-a", "agent_name", help="列出某 Agent 的工具")
@click.option("--risk", "-r", type=click.Choice(["safe", "write", "danger"]), help="按风险等级过滤")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def tool_list(agent_name, risk, json_output):
    """列出所有已注册工具

    \b
    示例:
      vagent tool list                              # 所有工具
      vagent tool list --agent verify_architect     # 某 Agent 的工具
      vagent tool list --risk safe                  # 按风险等级过滤
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    all_tools = []
    for role, agent in app.registry.get_all_instances().items():
        if agent_name and role != agent_name and agent_name != role:
            continue
        for t in (agent.tools or []):
            tname = getattr(t, "name", str(t))
            tdesc = getattr(t, "description", "") or ""
            ttype = type(t).__name__
            # Determine risk from tool_system if registered
            risk_level = "safe"  # default
            all_tools.append({
                "name": tname, "description": str(tdesc)[:100],
                "agent": role, "type": ttype, "risk": risk_level,
            })

    if risk:
        all_tools = [t for t in all_tools if t["risk"] == risk]

    out.print_table(
        ["Tool", "Agent", "Risk", "Description"],
        [[t["name"], t["agent"], t["risk"], t["description"]] for t in all_tools],
        title=f"Tools ({len(all_tools)} registered)"
    )


@tool.command("show")
@click.argument("tool_name")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def tool_show(tool_name, json_output):
    """查看工具详情（Schema/描述/风险等级）

    \b
    示例:
      vagent tool show run_vcs
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    for role, agent in app.registry.get_all_instances().items():
        for t in (agent.tools or []):
            tname = getattr(t, "name", str(t))
            if tname == tool_name:
                info = {
                    "name": tname,
                    "description": getattr(t, "description", ""),
                    "agent": role,
                    "type": type(t).__name__,
                    "has_schema": hasattr(t, "args_schema"),
                }
                if hasattr(t, "args_schema") and t.args_schema:
                    info["schema"] = str(t.args_schema.schema())[:500]
                out.print_result(info, title=f"Tool: {tool_name}")
                return
    out.print_error(f"Tool '{tool_name}' not found")


@tool.command("call")
@click.argument("tool_name")
@click.option("--args", "-a", default="{}", help="JSON 参数字符串")
@click.option("--gap", help="Coverage gap 参数 (gen_test_sv)")
@click.option("--out", "out_path", help="输出路径参数")
@click.option("--path", help="文件路径参数 (read_report)")
def tool_call(tool_name, args, gap, out_path, path):
    """直接调用工具（绕过 LLM）

    \b
    示例:
      vagent tool call gen_test_sv --gap burst_16 --out test.sv
      vagent tool call read_report --path output/coverage.json
      vagent tool call run_vcs --args '{"tb":"tb_top.sv"}'
    """
    app = VerificationCLI()
    asyncio.run(app.initialize())

    for role, agent in app.registry.get_all_instances().items():
        for t in (agent.tools or []):
            tname = getattr(t, "name", str(t))
            if tname != tool_name:
                continue
            func = getattr(t, "func", None) or t

            # Build args
            call_args = {}
            try:
                call_args = json.loads(args)
            except json.JSONDecodeError:
                pass
            if gap:
                call_args["gap"] = gap
            if out_path:
                call_args["out_path"] = out_path
            if path:
                call_args["path"] = path

            try:
                if callable(func):
                    result = func(call_args.pop("input_str", str(call_args)), **call_args) if "input_str" in call_args else func(str(call_args))
                else:
                    result = str(t)
                console.print(Panel(str(result)[:2000], title=f"[yellow]{tool_name}[/yellow] ({role})"))
            except Exception as e:
                # Try simpler invocation
                try:
                    if callable(func):
                        result = func()
                        console.print(Panel(str(result)[:2000], title=f"[yellow]{tool_name}[/yellow] ({role})"))
                    else:
                        console.print(f"[red]Cannot call tool {tool_name}: {e}[/red]")
                except Exception as e2:
                    console.print(f"[red]Tool error: {e2}[/red]")
            return

    console.print(f"[red]Tool '{tool_name}' not found[/red]")


@tool.command("history")
@click.option("--limit", "-n", default=20, help="记录数量")
@click.option("--tool", "tool_filter", help="指定工具")
def tool_history(limit, tool_filter):
    """查看工具调用历史

    \b
    示例:
      vagent tool history                   # 最近 20 条
      vagent tool history --limit 50        # 最近 50 条
      vagent tool history --tool run_vcs    # 指定工具
    """
    try:
        from src.layers.l2_orchestration.communication.tool_system import ToolRegistry
        # 工具调用历史通过 debug_logger 追踪
        console.print("[dim]Tool call history:[/dim]")
        from src.layers.l2_orchestration.middleware.debug_logger import tracer
        # tracer doesn't have tool history directly, use file-based approach
        log_dir = Path("logs/execution")
        if log_dir.exists():
            for f in sorted(log_dir.glob("exec_*.jsonl"), reverse=True)[:3]:
                content = f.read_text(encoding="utf-8")
                for line in content.strip().split("\n")[:limit]:
                    try:
                        entry = json.loads(line)
                        if entry.get("event") == "tool_call":
                            tname = entry.get("tool", "?")
                            if tool_filter and tname != tool_filter:
                                continue
                            console.print(f"  [cyan]{entry.get('timestamp','')[:19]}[/cyan] "
                                          f"[yellow]{tname}[/yellow] by {entry.get('agent','')} "
                                          f"({entry.get('elapsed',0):.1f}s)")
                    except Exception:
                        pass
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@cli.group()
def agent():
    """Agent 管理与单独执行"""
    pass


@agent.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def agent_list(json_output):
    """列出所有 Agent + 摘要

    \b
    示例:
      vagent agent list
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    rows = []
    for alias, role in AGENT_ALIASES.items():
        inst = app.registry.get_agent_instance(role)
        if inst:
            m = inst.get_metrics()
            tool_count = len(inst.tools or [])
            produces = getattr(inst, "produces", "-") or "-"
            consumes = ", ".join(getattr(inst, "consumes", []) or []) or "-"
            rows.append([
                alias, inst.display_name, m.get("status", "?"),
                produces, consumes, str(tool_count),
                str(m.get("tasks_completed", 0)),
            ])
    out.print_table(
        ["Alias", "Name", "Status", "Produces", "Consumes", "Tools", "Tasks"],
        rows, title="Agent Overview"
    )


@agent.command("show")
@click.argument("role")
@click.option("--tools", is_flag=True, help="列出该 Agent 的工具")
@click.option("--contract", is_flag=True, help="显示 consumes/produces/min_score")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def agent_show(role, tools, contract, json_output):
    """查看单个 Agent 详情

    \b
    示例:
      vagent agent show spec                    # 查看 spec agent
      vagent agent show spec --tools            # 列出工具
      vagent agent show spec --contract         # 显示 I/O 契约
    """
    out = get_output_adapter(json_output)
    app = VerificationCLI()
    asyncio.run(app.initialize())

    resolved_role = role
    inst = app.registry.get_agent_instance(resolved_role)
    if not inst:
        out.print_error(f"Agent '{role}' not found. Available: {', '.join(AGENT_ALIASES.keys())}")
        return

    info = {
        "alias": role,
        "role": resolved_role,
        "display_name": inst.display_name,
        "description": inst.description,
        "status": inst.status.value if hasattr(inst.status, "value") else str(inst.status),
        "task_type": getattr(inst, "task_type", "N/A"),
        "produces": getattr(inst, "produces", "-"),
        "consumes": getattr(inst, "consumes", []),
        "min_score": getattr(inst, "min_score", 50),
        "max_retries": getattr(inst, "max_retries", 2),
        "metrics": inst.get_metrics(),
    }

    if tools:
        tool_list = []
        for t in (inst.tools or []):
            tname = getattr(t, "name", str(t))
            tdesc = getattr(t, "description", "") or ""
            tool_list.append({"name": tname, "description": str(tdesc)[:120]})
        info["tools"] = tool_list

    out.print_result(info, title=f"Agent: {inst.display_name}")


@agent.command("run")
@click.argument("role")
@click.option("--input", "-i", "input_text", help="JSON 输入文本")
@click.option("--spec", "-s", "spec_file", type=click.Path(exists=True), help="从文件读取输入")
@click.option("--dry-run", is_flag=True, help="不真正执行，只打印会调用哪些工具")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def agent_run(role, input_text, spec_file, dry_run, json_output):
    """单独执行某个 Agent

    \b
    示例:
      vagent agent run spec --input '{"spec":{"features":["add","sub"]}}'
      vagent agent run spec --spec alu_spec.md
      vagent agent run spec --spec alu_spec.md --dry-run
    """
    out = get_output_adapter(json_output)
    resolved_role = role
    service = PipelineExecutionService.get_instance()

    if dry_run:
        app = VerificationCLI()
        asyncio.run(app.initialize())
        inst = app.registry.get_agent_instance(resolved_role)
        if not inst:
            out.print_error(f"Agent '{role}' not found")
            return
        tool_names = [getattr(t, "name", str(t)) for t in (inst.tools or [])]
        consumes = getattr(inst, "consumes", [])
        produces = getattr(inst, "produces", "-")
        out.print_result({
            "agent": role,
            "tools_will_call": tool_names,
            "consumes": consumes,
            "produces": produces,
        }, title=f"Dry Run: {inst.display_name}")
        return

    input_content = input_text or ""
    if spec_file:
        input_content = Path(spec_file).read_text(encoding="utf-8")

    if not input_content:
        out.print_error("No input provided. Use --input or --spec.")
        return

    async def run():
        result = await service.run_single_agent(resolved_role, input_content)
        return result

    result = asyncio.run(run())

    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    elif result["success"]:
        output = result.get("output", "")
        console.print(Panel(str(output)[:2000], title=f"[green]{role} output[/green]"))
    else:
        out.print_error(result.get("error", "Unknown error"))
