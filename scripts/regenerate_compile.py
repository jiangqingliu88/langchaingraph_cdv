"""重新生成 UVM 环境并编译（验证 predictor 模板修复）。"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from layers_engine.l3_decision.domain.generator import generate_uvm
from layers_engine.l3_decision.domain.regression import run_compile as _run_compile

spec_text = Path('specs/apb_uart/apb_uart_spec.md').read_text(encoding='utf-8')
od = _generate_uvm(spec_text)
print('generated:', od)
r = _run_compile(od)
print(f"compile: status={r.get('status')} errors={r.get('errors')} passed={r.get('passed')}")
if r.get('log_file') and Path(r['log_file']).exists():
    log = Path(r['log_file']).read_text(encoding='utf-8', errors='replace')
    for line in log.split('\n'):
        if '** Error' in line:
            print('  ERR:', line.strip()[:160])
