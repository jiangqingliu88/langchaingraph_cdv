filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 先添加工作流配置
workflow_config = '''

# ============ Workflow Configs ============
WORKFLOWS = {
    "full_verification": {
        "name": "Full Verification",
        "phases": [
            {"name": "spec", "agent": "spec_and_test_planner", "input": ""},
            {"name": "arch", "agent": "verification_architect", "input": ".output", "depends": "spec"},
            {"name": "seq", "agent": "sequence_engineer", "input": ".output", "depends": "arch", "parallel_group": 1},
            {"name": "assert", "agent": "assertion_engineer", "input": ".output", "depends": "arch", "parallel_group": 1},
            {"name": "regress", "agent": "regression_manager", "input": ".output", "depends": ["seq", "assert"]},
            {"name": "cover", "agent": "coverage_manager", "input": ".output", "depends": "regress", "parallel_group": 2},
            {"name": "qa", "agent": "quality_assurance", "input": ".output", "depends": "cover"},
        ]
    },
    "quick_check": {
        "name": "Quick Check",
        "phases": [
            {"name": "spec", "agent": "spec_and_test_planner", "input": ""},
            {"name": "arch", "agent": "verification_architect", "input": ".output", "depends": "spec"},
            {"name": "qa", "agent": "quality_assurance", "input": ".output", "depends": "arch"},
        ]
    }
}
'''

# 找到 status 命令前插入
idx = content.find('@cli.command()\ndef status():')
content = content[:idx] + workflow_config + '\n' + content[idx:]

# 2. 替换 verify 命令
old_verify_start = "@cli.command()\n@click.argument('spec_file'"
old_verify_end = "asyncio.run(run())\n\n@cli.command()\ndef workflows():"

idx_start = content.find(old_verify_start)
idx_end = content.find(old_verify_end)

new_verify = '''@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
@click.option('--workflow', '-w', default='full_verification', help='full_verification or quick_check')
@click.option('--output', '-o', type=click.Path(), help='output JSON file')
@click.option('--bypass', is_flag=True, help='Use mock data, skip LLM')
def verify(spec_file, workflow, bypass, output):
    """Run full verification pipeline with orchestrator"""
    app = VerificationCLI()
    
    async def run():
        import time, json as j
        
        await app.initialize()
        
        with open(spec_file, 'r', encoding='utf-8') as f:
            spec = f.read()
        
        wf = WORKFLOWS.get(workflow, WORKFLOWS["full_verification"])
        phases = wf["phases"]
        
        console.print(Panel.fit(f"[bold]{wf['name']}[/bold]\\n{len(phases)} phases", title="Pipeline"))
        
        table = Table(title="Results")
        table.add_column("Phase")
        table.add_column("Agent")
        table.add_column("Status")
        table.add_column("Time")
        
        results = {}
        context = {"": {"output": spec}}
        
        for phase in phases:
            name = phase["name"]
            agent_role = phase["agent"]
            
            agent = app.registry.get_agent_instance(agent_role)
            if not agent:
                table.add_row(name, agent_role, "[red]N/A[/red]", "-")
                results[name] = "skip"
                continue
            
            # 解析输入
            inp_ref = phase.get("input", "")
            inp = spec
            if inp_ref.startswith("$") and "." in inp_ref:
                parts = inp_ref[1:].split(".")
                key = "$" + parts[0]
                if key in context:
                    inp = context[key].get(parts[1], spec)
            
            t0 = time.time()
            try:
                result = await agent.execute_task({"input": inp, "bypass": bypass})
                elapsed = time.time() - t0
                if result.success:
                    table.add_row(name, agent_role, "[green]OK[/green]", f"{elapsed:.1f}s")
                    context[f""] = result.data
                    results[name] = "passed"
                else:
                    table.add_row(name, agent_role, "[red]FAIL[/red]", f"{elapsed:.1f}s")
                    results[name] = "failed"
            except Exception as e:
                elapsed = time.time() - t0
                table.add_row(name, agent_role, "[red]ERR[/red]", f"{elapsed:.1f}s")
                results[name] = "error"
        
        console.print(table)
        passed = sum(1 for v in results.values() if v == "passed")
        console.print(f"\\n[bold]Result: {passed}/{len(phases)} passed[/bold]")
        
        if output:
            with open(output, "w", encoding="utf-8") as f:
                j.dump({"workflow": workflow, "results": results}, f, indent=2)
            console.print(f"[green]Saved: {output}[/green]")
    
    asyncio.run(run())

@cli.command()
def workflows():'''

content = content[:idx_start] + new_verify + content[idx_end:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
