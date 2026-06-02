filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 在文件末尾 main() 之前添加 REPL 命令
repl_command = '''
@cli.command()
@click.option('--bypass', is_flag=True, help='Use mock data, skip LLM')
def repl(bypass):
    """Interactive REPL mode - chat with verification agents"""
    app = VerificationCLI()
    
    async def init():
        await app.initialize()
        console.print("[green]All agents ready. Type 'help' for commands, 'quit' to exit.[/green]")
        return app
    
    app = asyncio.run(init())
    
    context = {"spec": "", "last_output": ""}
    
    console.print(Panel.fit(
        "[bold cyan]IC Verification REPL[/bold cyan]\\n"
        "Commands: analyze <spec> | plan | arch | seq | assert | cover | debug | qa | help | quit",
        title="Welcome"
    ))
    
    while True:
        try:
            cmd = console.input("[bold cyan]ic-verify>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\\n[dim]Goodbye![/dim]")
            break
        
        if not cmd:
            continue
        
        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        
        if action == 'quit' or action == 'exit':
            console.print("[dim]Goodbye![/dim]")
            break
        
        elif action == 'help':
            console.print("""
[bold]Available commands:[/bold]
  [cyan]analyze <spec>[/cyan]  - Analyze design specification
  [cyan]plan[/cyan]           - Generate test plan from last analysis
  [cyan]arch[/cyan]           - Generate UVM architecture
  [cyan]seq[/cyan]            - Generate test sequences
  [cyan]assert[/cyan]         - Generate SVA assertions
  [cyan]cover[/cyan]          - Coverage analysis
  [cyan]debug[/cyan]          - Debug analysis
  [cyan]qa[/cyan]             - Quality review
  [cyan]status[/cyan]         - Show agent status
  [cyan]context[/cyan]        - Show current context
  [cyan]clear[/cyan]          - Clear context
  [cyan]quit[/cyan]           - Exit REPL
""")
        
        elif action == 'status':
            table = Table(title="Agent Status")
            table.add_column("Agent")
            table.add_column("Status")
            for role, agent in app.registry.get_all_instances().items():
                try:
                    m = agent.get_metrics()
                    table.add_row(m.get("display_name", role), m.get("status", "?"))
                except:
                    table.add_row(role, "error")
            console.print(table)
        
        elif action == 'context':
            console.print(f"[dim]Spec length: {len(context['spec'])} chars[/dim]")
            console.print(f"[dim]Last output: {context['last_output'][:100]}...[/dim]")
        
        elif action == 'clear':
            context = {"spec": "", "last_output": ""}
            console.print("[green]Context cleared[/green]")
        
        elif action == 'analyze':
            spec_text = arg if arg else context.get("spec", "")
            if not spec_text:
                console.print("[red]No spec provided. Use: analyze <spec_text>[/red]")
                continue
            context["spec"] = spec_text
            agent = app.registry.get_agent_instance("spec_and_test_planner")
            if agent:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Analyzing..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": spec_text, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Analysis[/green]"))
        
        elif action == 'plan':
            agent = app.registry.get_agent_instance("spec_and_test_planner")
            inp = context.get("last_output", context.get("spec", ""))
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Planning..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": f"Generate test plan from: {inp}", "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Test Plan[/green]"))
        
        elif action == 'arch':
            agent = app.registry.get_agent_instance("verification_architect")
            inp = context.get("last_output", context.get("spec", ""))
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Designing architecture..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    output = result.data.get("output", "")
                    context["last_output"] = output
                    if 'class ' in output or 'module ' in output:
                        console.print(Syntax(output[:500], "systemverilog", theme="monokai"))
                    else:
                        console.print(Panel(output[:500], title="[green]Architecture[/green]"))
        
        elif action == 'seq':
            agent = app.registry.get_agent_instance("sequence_engineer")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Generating sequences..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Syntax(context["last_output"][:500], "systemverilog", theme="monokai"))
        
        elif action == 'assert':
            agent = app.registry.get_agent_instance("assertion_engineer")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Generating assertions..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Syntax(context["last_output"][:500], "systemverilog", theme="monokai"))
        
        elif action == 'cover':
            agent = app.registry.get_agent_instance("coverage_manager")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Analyzing coverage..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Coverage[/green]"))
        
        elif action == 'debug':
            agent = app.registry.get_agent_instance("debug_engineer")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Debugging..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]Debug[/green]"))
        
        elif action == 'qa':
            agent = app.registry.get_agent_instance("quality_assurance")
            inp = context.get("last_output", "")
            if agent and inp:
                with Progress(SpinnerColumn(), TextColumn("[cyan]Reviewing..."), console=console) as p:
                    t = p.add_task("")
                    agent.config["bypass"] = bypass
                    result = asyncio.run(agent.execute_task({"input": inp, "bypass": bypass}))
                    p.update(t, completed=True)
                if result.success:
                    context["last_output"] = result.data.get("output", "")
                    console.print(Panel(context["last_output"][:500], title="[green]QA Review[/green]"))
        
        else:
            console.print(f"[red]Unknown command: {action}. Type 'help'[/red]")

'''

# 在 main() 之前插入
old_main = '\ndef main():'
content = content.replace(old_main, repl_command + old_main)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
