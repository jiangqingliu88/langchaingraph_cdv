filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在 __init__ 中添加 agent_config 和 get_agent_config
old_init = '''self.initialized = False
    
    async def initialize'''

new_init = '''self.initialized = False
        self.agent_config = {}
    
    def get_agent_config(self, role):
        return self.agent_config.get("agents", {}).get(role, {})
    
    async def initialize'''

content = content.replace(old_init, new_init)

# 2. 修复重复的 workflows
old_dup = '''@cli.command()
def workflows():asyncio.run(run())

@cli.command()
def workflows():'''

new_single = '''@cli.command()
def workflows():'''

content = content.replace(old_dup, new_single)

# 3. 删除重复的 create_project
old_dup2 = '''@cli.command()
@click.argument('project_name')
@click.option('--description', '-d', help='项目描述')
def create_project(project_name, description):
    """创建新的验证项目"""
    console.print(f"[green]创建项目: {project_name}[/green]")
    console.print(f"描述: {description or '无'}")

@cli.command()'''

new_single2 = '''@cli.command()'''

if old_dup2 in content:
    content = content.replace(old_dup2, new_single2)

# 4. 删除重复导入
content = content.replace('''from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn''',
'''from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
from rich import box''')

content = content.replace('''from rich.syntax import Syntax
from rich import print as rprint
import json''', 'import json')

# 修复 double import
content = content.replace('''from rich.table import Table
import yaml
from pathlib import Path''', '''from rich.table import Table
import yaml''')

content = content.replace('''import asyncio
import sys
from pathlib import Path
from typing import Optional
import click''', '''import asyncio
import sys
from pathlib import Path
from typing import Optional
import click
import json''')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
