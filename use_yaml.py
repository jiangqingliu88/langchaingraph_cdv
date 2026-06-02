filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 添加 yaml 导入
old_import = 'from rich.panel import Panel'
new_import = '''import yaml
from pathlib import Path
from rich.panel import Panel'''

content = content.replace(old_import, new_import)

# 在 VerificationCLI 类中添加配置加载
old_init = 'def __init__(self):\n        self.settings = Settings.get_instance()\n        self.registry = AgentRegistry.get_instance()\n        self.orchestrator = None\n        self.initialized = False'

new_init = '''def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = AgentRegistry.get_instance()
        self.orchestrator = None
        self.initialized = False
        self.agent_config = self._load_yaml_config()
    
    def _load_yaml_config(self):
        config_path = Path("config/agent_config.yaml")
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {}
    
    def get_agent_config(self, role):
        return self.agent_config.get("agents", {}).get(role, {})
    
    def get_pipeline(self, name):
        return self.agent_config.get("pipelines", {}).get(name, {})'''

content = content.replace(old_init, new_init)

# 更新 verify 使用 YAML 配置的 pipeline
old_wf = '''WORKFLOWS = {
            "full_verification": {
                "name": "Full Verification",
                "phases": [
                    {"name": "spec", "agent": "spec_and_test_planner", "input": ""},
                    {"name": "arch", "agent": "verification_architect", "input": ".output"},
                    {"name": "seq", "agent": "sequence_engineer", "input": ".output"},
                    {"name": "assert", "agent": "assertion_engineer", "input": ".output"},
                    {"name": "regress", "agent": "regression_manager", "input": ".output"},
                    {"name": "cover", "agent": "coverage_manager", "input": ".output"},
                    {"name": "qa", "agent": "quality_assurance", "input": ".output"},
                ]
            },
            "quick_check": {
                "name": "Quick Check",
                "phases": [
                    {"name": "spec", "agent": "spec_and_test_planner", "input": ""},
                    {"name": "arch", "agent": "verification_architect", "input": ".output"},
                    {"name": "qa", "agent": "quality_assurance", "input": ".output"},
                ]
            }
        }
        wf = WORKFLOWS.get(workflow, WORKFLOWS["full_verification"])'''

new_wf = '''# 优先从 YAML 加载，fallback 到硬编码
        wf = app.get_pipeline(workflow)
        if not wf or not wf.get("phases"):
            # fallback
            wf = {
                "name": workflow,
                "phases": [
                    {"name": "spec", "agent": "spec_and_test_planner", "input": ""},
                    {"name": "arch", "agent": "verification_architect", "input": ".output"},
                    {"name": "qa", "agent": "quality_assurance", "input": ".output"},
                ]
            }'''

content = content.replace(old_wf, new_wf)

# 更新 retry 使用 YAML 配置
old_retry = 'max_retries = 3'
new_retry = '''cfg = app.get_agent_config(agent_role)
                max_retries = cfg.get("retry", {}).get("max_retries", 3)'''

content = content.replace(old_retry, new_retry)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
