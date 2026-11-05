import sys, inspect, re
sys.path.insert(0, 'src')
from layers_engine.l3_decision.decision_engine import CoverageDrivenDecisionEngine
src = inspect.getsource(CoverageDrivenDecisionEngine.decide)
print('=== action_type 常量 ===')
for m in re.finditer(r"'([A-Z_]{3,})'", src):
    print('  ', m.group(1))
print('=== decide 逻辑（前 1800 字符）===')
print(src[:1800])
