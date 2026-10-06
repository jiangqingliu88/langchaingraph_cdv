"""对指定输出目录跑完整回归 + 覆盖率（验证 sim 通过 + 真实覆盖率）。"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from layers_engine.l3_decision.domain.regression import run_full_regression as _run_full_regression

od = Path(sys.argv[1] if len(sys.argv) > 1 else 'output_jiang_20260819_205958')
reg = _run_full_regression(od)
print(f"top: {reg.get('top_module')}  uvm_test: {reg.get('uvm_test')}")
print(f"compile_passed: {reg.get('compile_passed')}  sim_passed: {reg.get('sim_passed')}")
print(f"coverage_pct: {reg.get('coverage_pct')}%")
cov = reg.get('coverage', {})
for k, v in cov.items():
    if isinstance(v, dict):
        print(f"  {k}: {v.get('pct')}% ({v.get('covered')}/{v.get('total')})")
    else:
        print(f"  {k}: {v}%")
