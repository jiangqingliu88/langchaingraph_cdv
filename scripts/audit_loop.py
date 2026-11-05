import os

print('=== 决策链路环节盘点 ===')
checks = [
    ('L3 决策引擎 (旧 layers)', 'src/layers/l3_decision/decision_engine.py'),
    ('L3 决策引擎 (五层副本)', 'src/layers_engine/l3_decision/decision_engine.py'),
    ('引擎 decision_callback', 'src/layers_engine/l2_orchestration/engine/query.py'),
    ('决策闭环驱动器 (旧 execution.py)', 'src/layers/l2_orchestration/execution.py'),
    ('verify_orchestrator', 'src/layers_engine/l1_infrastructure/verify_orchestrator.py'),
    ('EDA 编译', 'src/tools/common/lib/compile.py'),
    ('EDA 仿真', 'src/tools/common/lib/loopback.py'),
    ('覆盖率收集', 'src/tools/execution/regression_tools/regression_framwork/src/regression_framework/adapters/regression_runner.py'),
    ('扩种/定向激励', 'src/tools/testcase_tools/tools.py'),
]
for name, path in checks:
    ok = os.path.exists(path)
    print(f'  [{"OK" if ok else "MISSING"}] {name}')
