"""单测 predictor 文件编译（真实文件 + UVM incdir）。"""
import subprocess, sys
from pathlib import Path

od = Path(sys.argv[1] if len(sys.argv) > 1 else 'output_jiang_20260819_205718')
pred = od / 'env' / 'pred' / 'apb_predictor.sv'
questa = 'f:/questasim64_2024.1/win64'
uvm_src = 'f:/questasim64_2024.1/verilog_src/uvm-1.2/src'

# 用 RegressionRunner 的方式编译整个环境，但只看 predictor
r = subprocess.run(
    [f'{questa}/vlog.exe', '-sv', '-mfcu', '+acc',
     f'+incdir+{uvm_src}', f'{uvm_src}/uvm_pkg.sv',
     str((od / 'agents' / 'apb' / 'apb_pkg.sv').resolve()),
     str((od / 'agents' / 'intr' / 'intr_pkg.sv').resolve()),
     str((od / 'agents' / 'uart' / 'uart_pkg.sv').resolve()),
     str((od / 'env' / 'apb_uart_env_pkg.sv').resolve()),
     ],
    capture_output=True, text=True, encoding='utf-8', errors='replace',
    timeout=120, cwd=str(od.resolve()))
print('rc =', r.returncode)
for line in (r.stdout + r.stderr).split('\n'):
    if '** Error' in line or 'near' in line:
        print(' ', line.strip()[:200])
print('PASS' if r.returncode == 0 else 'FAIL')
