filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加进度条导入
old_import = 'from rich.progress import Progress, SpinnerColumn, TextColumn'
new_import = '''from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn'''

content = content.replace(old_import, new_import)

# 2. 美化 verify 的进度反馈
old_verify = '''wf = WORKFLOWS.get(workflow, WORKFLOWS["full_verification"])
        phases = wf["phases"]
        
        console.print(Panel.fit(f"[bold]{wf['name']}[/bold]\\n{len(phases)} phases", title="Pipeline"))
        
        table = Table(title="Results")
        table.add_column("Phase")
        table.add_column("Agent")
        table.add_column("Status")
        table.add_column("Time")
        
        results = {}
        context = {"": {"output": spec}}'''

new_verify = '''wf = WORKFLOWS.get(workflow, WORKFLOWS["full_verification"])
        phases = wf["phases"]
        
        console.print(Panel.fit(f"[bold]{wf['name']}[/bold] | {len(phases)} phases | bypass={bypass}", title="Pipeline"))
        
        # Phase级别进度条
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            overall = progress.add_task("[cyan]Overall Pipeline", total=len(phases))
            
            results = {}
            context = {"": {"output": spec}}
            
            for i, phase in enumerate(phases):
                name = phase["name"]
                agent_role = phase["agent"]
                
                progress.update(overall, description=f"[cyan]Phase {i+1}/{len(phases)}: {name}")
                
                agent = app.registry.get_agent_instance(agent_role)
                if not agent:
                    results[name] = "skip"
                    progress.advance(overall)
                    continue
                
                inp_ref = phase.get("input", "")
                inp = spec
                if inp_ref.startswith("$") and "." in inp_ref:
                    parts = inp_ref[1:].split(".")
                    key = "$" + parts[0]
                    if key in context:
                        inp = context[key].get(parts[1], spec)
                
                import time
                t0 = time.time()
                retry_count = 0
                max_retries = 3
                result = None
                
                while retry_count <= max_retries:
                    try:
                        result = await agent.execute_task({"input": inp, "bypass": bypass})
                        if result.success:
                            break
                        retry_count += 1
                        if retry_count <= max_retries:
                            progress.console.print(f"  [yellow]Retry {retry_count}/{max_retries}[/yellow]")
                    except Exception as e:
                        retry_count += 1
                        if retry_count <= max_retries:
                            progress.console.print(f"  [yellow]Error retry {retry_count}: {e}[/yellow]")
                        else:
                            result = type('obj', (object,), {'success': False, 'error': str(e)})()
                
                elapsed = time.time() - t0
                
                if result and result.success:
                    progress.console.print(f"  [green]OK[/green] {name} ({elapsed:.1f}s)")
                    context[f""] = result.data
                    results[name] = {"status": "passed", "time": elapsed}
                else:
                    err_msg = getattr(result, 'error', 'unknown') if result else 'no result'
                    progress.console.print(f"  [yellow]DEGRADED[/yellow] {name} - {err_msg[:60]}")
                    results[name] = {"status": "degraded", "time": elapsed, "error": err_msg}
                    context[f""] = {"output": inp}
                
                progress.advance(overall)
        
        # 汇总报告
        passed = sum(1 for v in results.values() if v["status"] == "passed")
        degraded = sum(1 for v in results.values() if v["status"] == "degraded")
        total_time = sum(v["time"] for v in results.values())
        
        console.print()'''

# 替换旧代码
old_verify_block = '''table = Table(title="Results")
        table.add_column("Phase")
        table.add_column("Agent")
        table.add_column("Status")
        table.add_column("Time")
        
        results = {}
        context = {"": {"output": spec}}
        
        for phase in phases:'''

# 找到并删除旧的 table 和 for 循环
idx_table = content.find(old_verify_block)
if idx_table > 0:
    # 找到旧的 table 打印
    idx_end = content.find("console.print(table)", idx_table)
    idx_end2 = content.find("passed = sum", idx_table)
    
    # 删除旧代码块
    old_block_end = content.find('console.print(f"\\n[bold]Result:', idx_table)
    if old_block_end > 0:
        old_block_end = content.find('\n', old_block_end) + 1
    
    before = content[:idx_table]
    after = content[old_block_end:] if old_block_end > idx_table else content[idx_end2:]
    content = before + new_verify + after

# 更新结果输出
old_result = '''passed = sum(1 for v in results.values() if v == "passed")
        console.print(f"\\n[bold]Result: {passed}/{len(phases)} passed[/bold]")'''

new_result = '''console.print(Panel.fit(
            f"[bold]Pipeline Complete[/bold]\\n"
            f"[green]Passed: {passed}[/green] | [yellow]Degraded: {degraded}[/yellow] | Total: {len(phases)}\\n"
            f"Total time: {total_time:.1f}s",
            border_style="green" if degraded == 0 else "yellow"
        ))'''

content = content.replace(old_result, new_result)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
