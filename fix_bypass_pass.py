filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old = 'r = await agent.execute_task({"input": prev})'
new = 'r = await agent.execute_task({"input": prev, "bypass": bypass})'

content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
