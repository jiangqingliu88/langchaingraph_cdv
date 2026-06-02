filepath = 'src/cli/commands.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 verify 的 run 函数，在里面加 WORKFLOWS
old = '''wf = WORKFLOWS.get(workflow, WORKFLOWS["full_verification"])'''

new = '''WORKFLOWS = {
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

content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
