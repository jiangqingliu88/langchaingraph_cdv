filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 verify 中执行 agent 的部分并增强
old = '''t0 = time.time()
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
                results[name] = "error"'''

new = '''t0 = time.time()
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
                        console.print(f"  [yellow]Retry {retry_count}/{max_retries} for {name}...[/yellow]")
                except Exception as e:
                    retry_count += 1
                    if retry_count <= max_retries:
                        console.print(f"  [yellow]Error, retry {retry_count}/{max_retries}: {e}[/yellow]")
                    else:
                        result = type('obj', (object,), {'success': False, 'error': str(e)})()
            
            elapsed = time.time() - t0
            
            if result and result.success:
                table.add_row(name, agent_role, "[green]OK[/green]", f"{elapsed:.1f}s")
                context[f""] = result.data
                results[name] = "passed"
            else:
                # 降级：记录失败但继续执行
                err_msg = getattr(result, 'error', 'unknown') if result else 'no result'
                table.add_row(name, agent_role, f"[yellow]DEGRADED[/yellow] (retries: {retry_count})", f"{elapsed:.1f}s")
                results[name] = f"degraded: {err_msg[:50]}"
                # 继续传递上一个阶段的输出作为降级输入
                context[f""] = {"output": inp}'''

content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
