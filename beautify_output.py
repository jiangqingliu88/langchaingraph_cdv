filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 analyze 命令的输出部分并美化
old_analyze_output = '''if result.success:
                console.print(Panel(result.data.get("output", "无输出"), title="规格分析结果", border_style="green"))
            else:
                console.print(f"[red]分析失败: {result.error}[/red]")'''

new_analyze_output = '''if result.success:
                output = result.data.get("output", "")
                # 检测内容类型并美化
                if 'class ' in output or 'module ' in output or 'endclass' in output:
                    console.print(Panel(Syntax(output, "systemverilog", theme="monokai", line_numbers=True), title="[bold green]Generated Code[/bold green]"))
                elif '{' in output and '}' in output:
                    try:
                        import json as j
                        data = j.loads(output)
                        table = Table(title="Analysis Result", show_header=True, header_style="bold cyan")
                        if isinstance(data, dict):
                            table.add_column("Key", style="cyan")
                            table.add_column("Value", style="green")
                            for k, v in data.items():
                                if isinstance(v, list):
                                    table.add_row(k, ", ".join(str(x) for x in v[:5]))
                                else:
                                    table.add_row(k, str(v)[:100])
                        console.print(table)
                    except:
                        console.print(Panel(output[:1000], title="[bold green]Result[/bold green]"))
                else:
                    console.print(Panel(output[:1000], title="[bold green]Result[/bold green]"))
            else:
                console.print(Panel(f"[red]{result.error}[/red]", title="[bold red]Error[/bold red]", border_style="red"))'''

content = content.replace(old_analyze_output, new_analyze_output)

# 美化 verify 的输出
old_verify_output = '''table.add_row(name, agent_role, "[green]OK[/green]", f"{elapsed:.1f}s")
                context[f""] = result.data
                results[name] = "passed"'''

new_verify_output = '''table.add_row(name, agent_role, "[green]OK[/green]", f"{elapsed:.1f}s")
                context[f""] = result.data
                results[name] = "passed"
                # 显示输出摘要
                out = result.data.get("output", "")
                if out:
                    out_preview = out[:80].replace('\n', ' ')
                    console.print(f"  [dim]{out_preview}...[/dim]")'''

content = content.replace(old_verify_output, new_verify_output)

# 在文件开头添加 Syntax 导入
old_import = 'from rich.panel import Panel'
new_import = '''from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box'''

content = content.replace(old_import, new_import)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
