"""用生成文件的真实 process_in 体测编译。"""
import subprocess, tempfile
from pathlib import Path

od = Path('output_jiang_20260819_205718')
pred = od / 'env' / 'pred' / 'apb_predictor.sv'
txt = pred.read_text(encoding='utf-8')

# 提取 process_in 函数（65-97 行，含 body）
lines = txt.split('\n')
start = next(i for i, l in enumerate(lines) if 'virtual function void process_in' in l)
end = next(i for i in range(start, len(lines)) if lines[i].strip() == 'endfunction')
body = '\n'.join(lines[start:end + 1])
print('=== extracted body ===')
print(body)

questa = 'f:/questasim64_2024.1/win64'
uvm_src = 'f:/questasim64_2024.1/verilog_src/uvm-1.2/src'
base = '''
`ifndef TEST_PRED_SV
`define TEST_PRED_SV
import uvm_pkg::*;
`include "uvm_macros.svh"
class apb_seq_item extends uvm_sequence_item;
  rand bit [7:0] paddr, pwdata, prdata;
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
  logic [7:0] reg_ctrl = 8'h0;
  logic [7:0] reg_txdata = 8'h0;
  logic [7:0] reg_rxdata = 8'h0;
  logic [7:0] reg_status = 8'h0;
  function new(string name = "apb_predictor", uvm_component parent = null);
    super.new(name, parent);
  endfunction
'''

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    f = d / 'pred_real.sv'
    f.write_text(base + body + '\nendclass : apb_predictor\n`endif\n', encoding='utf-8')
    r = subprocess.run([f'{questa}/vlog.exe', '-sv', '-mfcu',
                        f'+incdir+{uvm_src}', f'{uvm_src}/uvm_pkg.sv', str(f)],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120, cwd=str(d))
    print('rc =', r.returncode)
    for l in (r.stdout + r.stderr).split('\n'):
        if '** Error' in l or 'near' in l:
            print(' ', l.strip()[:200])
    print('PASS' if r.returncode == 0 else 'FAIL')
