"""验证 vopt 门禁：确定性模板应 PASS，LLM 多驱动 RTL 应 FAIL。"""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
from layers_engine.l3_decision.domain.generator import verify_rtl_compiles as _verify_rtl_compiles, _APB_UART_RTL

# 1. 确定性模板
tmp = Path('scripts/tmp_apb_uart.sv')
tmp.write_text(_APB_UART_RTL, encoding='utf-8')
ok, err = _verify_rtl_compiles(tmp)
print(f'deterministic template: {"PASS" if ok else "FAIL"}  {err[:150] if not ok else ""}')
tmp.unlink(missing_ok=True)

# 2. LLM 生成的多驱动 RTL
llm_rtl = Path('output_jiang_20260819_210107/rtl/apb_uart.sv')
if llm_rtl.exists():
    ok, err = _verify_rtl_compiles(llm_rtl)
    print(f'LLM multi-driver RTL:   {"PASS" if ok else "FAIL(gate caught it)"}  {err[:150] if not ok else ""}')
