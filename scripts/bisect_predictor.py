"""二分定位 predictor 95 行 'near end' 错误。"""
import subprocess, sys, tempfile
from pathlib import Path

od = Path('output_jiang_20260819_205718')
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

body = '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    pred.paddr   = t.paddr;
    pred.pwdata  = t.pwdata;
    pred.pwrite  = t.pwrite;
    pred.psel    = t.psel;
    pred.penable = t.penable;
    pred.prdata  = 8'h00;
    pred.req_id  = t.req_id;

    if (t.pwrite) begin
      if (t.psel && t.penable) begin
        case (t.paddr[3:0])
        4'h0: reg_ctrl = t.pwdata;
        4'h4: reg_txdata = t.pwdata;
        4'hc: reg_status = t.pwdata;
          default: ;
        endcase
      end
    end else if (t.psel) begin
      case (t.paddr[3:0])
        4'h0: pred.prdata = reg_ctrl;
        4'h4: pred.prdata = reg_txdata;
        4'h8: pred.prdata = reg_rxdata;
        4'hc: pred.prdata = reg_status;
          default: pred.prdata = 8'h00;
        endcase
      end
    end
  endfunction
'''

# 变体 A: 全 body
# 变体 B: 无 case 的 if
# 变体 C: 只有 else-if
variants = {
    'A_full': body,
    'B_simple_if': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    pred.paddr = t.paddr;
    pred.prdata = 8'h00;
    if (t.pwrite) begin
      if (t.psel && t.penable) begin
        reg_ctrl = t.pwdata;
      end
    end
  endfunction
''',
    'C_else_if': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    pred.paddr = t.paddr;
    if (t.pwrite) begin
      reg_ctrl = t.pwdata;
    end else if (t.psel) begin
      pred.prdata = reg_ctrl;
    end
  endfunction
''',
    'D_case_only': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    case (t.paddr[3:0])
      4'h0: pred.prdata = reg_ctrl;
      4'h4: pred.prdata = reg_txdata;
      4'h8: pred.prdata = reg_rxdata;
      4'hc: pred.prdata = reg_status;
      default: pred.prdata = 8'h00;
    endcase
  endfunction
''',
    'E_case_in_if': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    if (t.pwrite) begin
      case (t.paddr[3:0])
        4'h0: reg_ctrl = t.pwdata;
        default: ;
      endcase
    end
  endfunction
''',
    'F_mixed_hc': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    case (t.paddr[3:0])
      4'hc: pred.prdata = reg_status;
      default: pred.prdata = 8'h00;
    endcase
  endfunction
''',
}

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    for name, b in variants.items():
        f = d / f'pred_{name}.sv'
        f.write_text(base + b + 'endclass : apb_predictor\n`endif\n', encoding='utf-8')
        r = subprocess.run([f'{questa}/vlog.exe', '-sv', '-mfcu',
                            f'+incdir+{uvm_src}', f'{uvm_src}/uvm_pkg.sv', str(f)],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=120, cwd=str(d))
        errs = [l for l in (r.stdout + r.stderr).split('\n') if '** Error' in l]
        print(f'{name}: {"FAIL " + str(errs[0].strip()[:120]) if errs else "PASS"}')
