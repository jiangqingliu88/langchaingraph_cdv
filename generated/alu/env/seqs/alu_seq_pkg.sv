// Seq Package: alu_seq_pkg
package alu_seq_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
    // 直接导入 Agent 包（SV import 不可传递）
  import ALU_in_pkg::*;
  import ALU_out_pkg::*;
  // 导入 env 包
  import alu_pkg::*;


  // 包含环境组件文件
  `include "alu_virtual_base_seq.sv"


endpackage : alu_seq_pkg