filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''wf = app.get_pipeline(workflow)
        if not wf or not wf.get("phases"):'''

new = '''# 从 YAML 配置或 agent_config 加载
        pipelines = app.agent_config.get("pipelines", {}) if hasattr(app, 'agent_config') else {}
        wf = pipelines.get(workflow, {})
        if not wf or not wf.get("phases"):'''

content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
