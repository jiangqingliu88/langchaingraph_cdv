// Test Package: alu_test_pkg
package alu_test_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
    // 直接导入 Agent 包（SV import 不可传递）
  import ALU_in_pkg::*;
  import ALU_out_pkg::*;
  // 导入 env 包
  import alu_pkg::*;



  // 包含环境组件文件
  `include "alu_base_test.sv"


endpackage : alu_test_pkg