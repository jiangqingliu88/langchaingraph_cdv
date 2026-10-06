import sys, json
sys.path.insert(0, 'src')
from layers_engine.l3_decision.driver import run_coverage_decision_loop

result = run_coverage_decision_loop(
    spec_path='specs/apb_uart/apb_uart_spec.md',
    target=30.0,
    max_rounds=1,
    agent='apb_uart_in',
)
print('\n' + '=' * 60)
print('决策闭环结果(7-agent):')
print(f'  状态: {result["status"]}')
print(f'  最终覆盖率: {result["final_coverage"]}% (target {result["target"]}%)')
print(f'  耗时: {result["elapsed_s"]}s')
print('  决策序列:')
for d in result['decisions']:
    print(f'    round {d["round"]}: {d["action"]} (coverage={d.get("coverage", "?")}%) {d["reason"][:50]}')
print('  phases:')
for p in result['phases']:
    print(f'    {p["name"]}: {p["status"]} agent={p.get("agent", "?")}')
print('  signoff.audit_opinion:', result.get('signoff', {}).get('audit_opinion', '')[:100])
print('=' * 60)
