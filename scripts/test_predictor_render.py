"""验证 predictor 模板渲染缩进 + vlog 编译（standalone，不跑 LLM）。"""
import sys, json, subprocess, tempfile
from pathlib import Path
sys.path.insert(0, 'src')

from src.tools.checking.spec_tools.main import analyze_specification
from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _gen_apb_register_model

# 1. 取 registers → model_body
spec = json.loads(analyze_specification(open('specs/apb_uart/apb_uart_spec.md', encoding='utf-8').read()))
state, body = _gen_apb_register_model(spec['registers'])
print('[1] model_body lines:')
for ln in body.split('\n'):
    print(f'    {repr(ln)}')

# 2. 模拟模板渲染：{{ pred.model_body | indent(4, false) }}
from jinja2 import Environment
env = Environment()
tpl = env.from_string('virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);\n'
                      '{{ model_body | indent(4, false) }}\n'
                      '  endfunction')
rendered = tpl.render(model_body=body)
print('[2] rendered:')
for ln in rendered.split('\n'):
    print(f'    {repr(ln)}')

# 3. 写一个最小可编译的 predictor（用真实文件 + UVM incdir）
pred_src = '''
`ifndef APB_PREDICTOR_PRED_SV
`define APB_PREDICTOR_PRED_SV
import uvm_pkg::*;
`include "uvm_macros.svh"
class apb_seq_item extends uvm_sequence_item;
  rand bit [7:0] paddr;
  rand bit [7:0] pwdata;
  rand bit [7:0] prdata;
  rand bit pwrite, psel, penable;
  rand bit [31:0] req_id;
  `uvm_object_utils_begin(apb_seq_item)
    `uvm_field_int(paddr, UVM_ALL_ON)
    `uvm_field_int(pwdata, UVM_ALL_ON)
    `uvm_field_int(prdata, UVM_ALL_ON)
    `uvm_field_int(pwrite, UVM_ALL_ON)
    `uvm_field_int(psel, UVM_ALL_ON)
    `uvm_field_int(penable, UVM_ALL_ON)
    `uvm_field_int(req_id, UVM_ALL_ON)
  `uvm_object_utils_end
  function new(string name = "apb_seq_item"); super.new(name); endfunction
endclass
class apb_predictor extends uvm_component;
  `uvm_component_utils(apb_predictor)
  function new(string name = "apb_predictor", uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
''' + rendered + '''
  endfunction
endclass : apb_predictor
`endif
'''

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    f = d / 'apb_predictor.sv'
    f.write_text(pred_src, encoding='utf-8')
    questa = 'f:/questasim64_2024.1/win64'
    uvm_src = 'f:/questasim64_2024.1/verilog_src/uvm-1.2/src'
    r = subprocess.run([f'{questa}/vlog.exe', '-sv', '-mfcu',
                        f'+incdir+{uvm_src}', f'{uvm_src}/uvm_pkg.sv',
                        str(f)],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120, cwd=str(d))
    print('[3] vlog rc =', r.returncode)
    errs = [l for l in (r.stdout + r.stderr).split('\n') if '** Error' in l]
    for e in errs[:10]:
        print('    ERR:', e)
    print('    PASS' if r.returncode == 0 and not errs else '    FAIL')
