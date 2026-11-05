import sys, inspect, re
sys.path.insert(0, 'src')
from layers_engine.l3_decision.decision_engine import CoverageDrivenDecisionEngine
src = inspect.getsource(CoverageDrivenDecisionEngine.decide)
actions = set()
for m in re.finditer(r"action_type\s*=\s*['\"](\w+)['\"]", src):
    actions.add(m.group(1))
print('决策动作:', sorted(actions))
