filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 替换 verify 中执行 phase 的循环，支持并行
old_loop = '''for i, phase in enumerate(phases):
                name = phase["name"]
                agent_role = phase["agent"]
                
                progress.update(overall, description=f"[cyan]Phase {i+1}/{len(phases)}: {name}")
                
                agent = app.registry.get_agent_instance(agent_role)
                if not agent:
                    results[name] = "skip"
                    progress.advance(overall)
                    continue'''

new_loop = '''# 按 parallel_group 分组
                groups = {}
                for phase in phases:
                    g = phase.get("parallel_group", 0)
                    if g not in groups:
                        groups[g] = []
                    groups[g].append(phase)
                
                import asyncio as aio
                
                for g, group_phases in sorted(groups.items()):
                    if g == 0:
                        # 串行执行
                        for phase in group_phases:
                            name = phase["name"]
                            agent_role = phase["agent"]
                            await _execute_phase(name, agent_role, phase, app, bypass, inp, spec, context, results, progress, overall)
                    else:
                        # 并行执行
                        progress.console.print(f"[cyan]Parallel group {g}: {[p['name'] for p in group_phases]}[/cyan]")
                        tasks = [_execute_phase(p["name"], p["agent"], p, app, bypass, inp, spec, context, results, progress, overall) for p in group_phases]
                        await aio.gather(*tasks)
                
                break  # 跳出外层循环，因为已经内部分组处理了

        # 定义 phase 执行函数
        async def _execute_phase(name, agent_role, phase, app, bypass, inp, spec, context, results, progress, overall):
            progress.update(overall, description=f"[cyan]{name}")
            
            agent = app.registry.get_agent_instance(agent_role)
            if not agent:
                results[name] = {"status": "skip", "time": 0}
                progress.advance(overall)
                return'''

content = content.replace(old_loop, new_loop)

# 修复后续的循环体缩进（去掉原来的缩进）
old_body = '''                
                inp_ref = phase.get("input", "")'''

new_body = '''            
            inp_ref = phase.get("input", "")'''

content = content.replace(old_body, new_body)

# 修复后续的 agent 获取
old_agent = '''                agent = app.registry.get_agent_instance(agent_role)
                if not agent:
                    results[name] = "skip"
                    progress.advance(overall)
                    continue
                
                inp_ref = phase.get("input", "")'''

new_agent = '''            
            inp_ref = phase.get("input", "")'''

content = content.replace(old_agent, new_agent)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
