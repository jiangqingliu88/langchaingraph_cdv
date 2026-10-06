"""验证 7-agent 闭环覆盖率收敛（seed 递增 → 覆盖率递增）。"""
import sys
sys.path.insert(0, 'src')
from layers_engine.l3_decision.driver import run_coverage_decision_loop

result = run_coverage_decision_loop(
    spec_path='specs/apb_uart/apb_uart_spec.md',
    target=25.0,
    max_rounds=3,
)
print('\n' + '=' * 60)
print('收敛验证:')
print(f'  状态: {result["status"]}  最终覆盖率: {result["final_coverage"]}% (target {result["target"]}%)')
print('  覆盖率历史:')
hist = [p for p in result['phases'] if p['name'].startswith('coverage')]
for p in hist:
    print(f'    {p["name"]}: {p["coverage"]}%')
print('  决策序列:')
for d in result['decisions']:
    print(f'    round {d["round"]}: {d["action"]} (coverage={d.get("coverage", "?")}%)')
g = result.get('signoff', {}).get('gates', {})
print(f'  签核门禁: compile={g.get("compile_passed")} sim={g.get("sim_passed")} coverage_met={g.get("coverage_met")}')
print('=' * 60)
