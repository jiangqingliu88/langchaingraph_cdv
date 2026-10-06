"""验证 passive agent（intr）生成：无 driver 文件 + agent 无 driver 声明 + 编译通过。"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from layers_engine.l3_decision.domain.generator import generate_uvm as _generate_uvm
from layers_engine.l3_decision.domain.regression import run_compile as _run_compile

spec_text = Path('specs/apb_uart/apb_uart_spec.md').read_text(encoding='utf-8')
od = _generate_uvm(spec_text)
print('generated:', od)

# 1. intr 目录文件清单
intr_dir = od / 'agents' / 'intr'
print('intr files:', sorted(p.name for p in intr_dir.iterdir()))

# 2. intr_agent.sv 是否还有 driver 声明
agent_sv = (intr_dir / 'intr_agent.sv').read_text(encoding='utf-8') if (intr_dir / 'intr_agent.sv').exists() else ''
print('intr_agent has drv:', 'drv' in agent_sv, '| has sqr:', 'sqr' in agent_sv)

# 3. 编译
r = _run_compile(od)
print(f"compile: status={r.get('status')} errors={r.get('errors')} passed={r.get('passed')}")
if r.get('log_file') and Path(r['log_file']).exists():
    for line in Path(r['log_file']).read_text(encoding='utf-8', errors='replace').split('\n'):
        if '** Error' in line:
            print('  ERR:', line.strip()[:160])
