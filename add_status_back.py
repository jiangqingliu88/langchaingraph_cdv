filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old = "@cli.command()\ndef history():"
new = '''@cli.command()
def status():
    """View all agent status"""
    app = VerificationCLI()
    async def run():
        await app.initialize()
        table = Table(title="Agent Status")
        table.add_column("Agent", style="cyan")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Tasks")
        for role, agent in app.registry.get_all_instances().items():
            try:
                m = agent.get_metrics()
                table.add_row(m.get("display_name", role), role, m.get("status", "?"), str(m.get("tasks_completed", 0)))
            except:
                table.add_row(role, role, "error", "0")
        console.print(table)
    asyncio.run(run())

@cli.command()
def history():'''

content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
