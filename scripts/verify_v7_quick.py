"""重新生成环境 + 编译 + 回归验证（快速：不跑 LLM 完整闭环）。"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from layers_engine.l3_decision.domain.generator import generate_uvm, generate_rtl
from layers_engine.l3_decision.domain.regression import run_compile, run_full_regression

spec = Path('specs/apb_uart/apb_uart_spec.md').read_text(encoding='utf-8')
od = generate_uvm(spec)
generate_rtl(od, spec)
print('generated:', od)

# 验证 random_test 声明合法
rt = od / 'env' / 'tests' / 'apb_uart_env_random_test.sv'
txt = rt.read_text(encoding='utf-8')
assert 'int nt;\n    super.new' in txt, "FAIL: 声明仍在语句后"
print('random_test 声明顺序 OK')

r = run_compile(od)
print(f"compile: status={r.get('status')} errors={r.get('errors')} passed={r.get('passed')}")
if not r.get('passed'):
    log = Path(r['log_file']).read_text(encoding='utf-8', errors='replace')
    for line in log.split('\n'):
        if '** Error' in line:
            print('  ERR:', line.strip()[:160])

reg = run_full_regression(od, seed=1, num_transactions=50)
print(f"regress: sim_passed={reg.get('sim_passed')} cov={reg.get('coverage_pct')}%")
