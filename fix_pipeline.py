filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 VerificationCLI 的 __init__ 并添加 get_pipeline
old = '''self.initialized = False
        self.agent_config = self._load_yaml_config()'''

new = '''self.initialized = False
        self.agent_config = self._load_yaml_config()
    
    def get_pipeline(self, name):
        return self.agent_config.get("pipelines", {}).get(name, {})
    
    def get_agent_config(self, role):
        return self.agent_config.get("agents", {}).get(role, {})'''

content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
