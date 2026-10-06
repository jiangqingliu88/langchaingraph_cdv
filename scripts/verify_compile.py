"""验证 predictor 修复后整个环境能否编译（不带 coverage，快）。"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path

od = Path(sys.argv[1] if len(sys.argv) > 1 else 'output_jiang_20260819_205622')
from layers_engine.l3_decision.domain.regression import run_compile as _run_compile
r = _run_compile(od)
print(f"compile: status={r.get('status')} errors={r.get('errors')} passed={r.get('passed')}")
print(f"log: {r.get('log_file')}")
