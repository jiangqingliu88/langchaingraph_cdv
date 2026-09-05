// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════════════
// Testpoint TC Package: APB_env_tc_pkg
// 来源: testpoint xlsx（仅 approved 行生成可编译代码，其余注释保留）
// 定向约束类与拆 seq 骨架见 {module}_tc_constraints.svh
// ════════════════════════════════════════════════════════════════
package APB_env_tc_pkg;
  import uvm_pkg::*;
  import APB_env_test_pkg::*;
  `include "uvm_macros.svh"
  `include "APB_env_tc_constraints.svh"   // 定向约束 seq_item_c + flow_seq 骨架

// ── APB_FEAT_WR/APB_TP_001 [P0] APB back-to-back 写传输 — 连续两次写、第二次无等待态，检查 psel 保持与 pslverr=0
//    checker: sb:apb_scb
//    func_coverage: apb_write_b2b_cross; apb_wr_err_cp
//    constraint_policy: apb_policy_b2b
//    iterations: 100
//    定向约束: paddr==32'h1000; pwrite==1; pwdata inside {[0:255]};
//    拆 seq: apb_random_wr_seq(10); apb_b2b_wr_seq(1); apb_read_cmp_seq(1);
class APB_env_gen_test_APB_TP_001 extends APB_env_gen_test;
  `uvm_component_utils(APB_env_gen_test_APB_TP_001)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 环境约束重载
    set_type_override_by_type(APB_env_config::get_type(), apb_config_b2b_override::get_type());
    // testpoint 定向约束（APB_env_gen_test_APB_TP_001_seq_item_c，见 tc_constraints.svh）
    set_type_override_by_type(apb_master_seq_item::get_type(), APB_env_gen_test_APB_TP_001_seq_item_c::get_type());
    // configure_phase 配置序列 / main_phase 事务序列
    uvm_config_db #(uvm_object_wrapper)::set(this,"env.vsqr.configure_phase","default_sequence",apb_cfg_seq::type_id::get());
    uvm_config_db #(uvm_object_wrapper)::set(this,"env.vsqr.main_phase","default_sequence",apb_b2b_wr_seq::type_id::get());
  endfunction
endclass : APB_env_gen_test_APB_TP_001

// ── APB_FEAT_ERR/APB_TP_002 [P1] 错误响应注入 — slave 注入 pslverr=1，master 侧应采到错误响应并上报
//    checker: sb:apb_scb; assert:assert_pslverr_ack
//    func_coverage: apb_err_resp_cp
//    拆 seq: apb_err_inject_seq(50);
//    [status=REVIEWED] 待补充断言清单后通过
// class APB_env_gen_test_APB_TP_002 extends APB_env_gen_test;
//   `uvm_component_utils(APB_env_gen_test_APB_TP_002)
// 
//   function new(string name, uvm_component parent);
//     super.new(name, parent);
//   endfunction
// 
//   function void build_phase(uvm_phase phase);
//     super.build_phase(phase);
//     // 环境约束重载
//     set_type_override_by_type(APB_env_config::get_type(), APB_env_config::get_type());
//     // configure_phase 配置序列 / main_phase 事务序列
//     uvm_config_db #(uvm_object_wrapper)::set(this,"env.vsqr.configure_phase","default_sequence",apb_cfg_seq::type_id::get());
//     uvm_config_db #(uvm_object_wrapper)::set(this,"env.vsqr.main_phase","default_sequence",apb_err_inject_seq::type_id::get());
//   endfunction
// endclass : APB_env_gen_test_APB_TP_002
// 

endpackage : APB_env_tc_pkg
