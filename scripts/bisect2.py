"""进一步二分：if/case/else-if/case 组合定位。"""
import subprocess, tempfile
from pathlib import Path

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

variants = {
    'G_if_case_else': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    if (t.pwrite) begin
      case (t.paddr[3:0])
        4'h0: reg_ctrl = t.pwdata;
        default: ;
      endcase
    end else begin
      case (t.paddr[3:0])
        4'h0: pred.prdata = reg_ctrl;
        default: pred.prdata = 8'h00;
      endcase
    end
  endfunction
''',
    'H_if_case_elseif': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    if (t.pwrite) begin
      case (t.paddr[3:0])
        4'h0: reg_ctrl = t.pwdata;
        default: ;
      endcase
    end else if (t.psel) begin
      case (t.paddr[3:0])
        4'h0: pred.prdata = reg_ctrl;
        default: pred.prdata = 8'h00;
      endcase
    end
  endfunction
''',
    'I_begin_else': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    if (t.pwrite) begin
      reg_ctrl = t.pwdata;
    end else if (t.psel) begin
      pred.prdata = reg_ctrl;
    end
  endfunction
''',
    'J_nested2': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
    if (t.pwrite) begin
      if (t.psel && t.penable) begin
        reg_ctrl = t.pwdata;
      end
    end else if (t.psel) begin
      pred.prdata = reg_ctrl;
    end
  endfunction
''',
    'K_hc_lower': '''  virtual function void process_in(apb_seq_item t, ref apb_seq_item pred);
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
        print(f'{name}: {"FAIL " + str(errs[0].strip()[:130]) if errs else "PASS"}')
