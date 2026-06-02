fp = 'src/cli/commands.py'
with open(fp, 'r', encoding='utf-8') as f:
    c = f.read()

old = 'from rich.panel import Panel'
new = '''from src.database.repository import save_task, save_pipeline_run, get_recent_tasks
from src.database.connection import init_db
from rich.panel import Panel'''
c = c.replace(old, new)

old2 = 'def main():'
new2 = '''@cli.command()
def history():
    async def run():
        await init_db()
        tasks = await get_recent_tasks(20)
        table = Table(title='Task History')
        table.add_column('Agent')
        table.add_column('Status')
        table.add_column('Time')
        for t in tasks:
            table.add_row(t['agent'], t['status'], f\"{t['time']:.1f}s\")
        console.print(table)
    asyncio.run(run())

def main():'''
c = c.replace(old2, new2)

with open(fp, 'w', encoding='utf-8') as f:
    f.write(c)
print('done')
