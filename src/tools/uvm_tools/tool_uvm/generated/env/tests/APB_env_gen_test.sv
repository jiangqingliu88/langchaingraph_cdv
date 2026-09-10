// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_gen_test.sv
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Gen Test: APB_env_gen_test
// 所有具体 Test 的基类

class APB_env_gen_test extends uvm_test;
  `uvm_component_utils(APB_env_gen_test)
    apb_master_sequence apb_master_seq;
    apb_slave_sequence apb_slave_seq;
  // 环境实例
  APB_env env;

  // 环境配置
  APB_env_config cfg;
 
  // 虚拟接口
  virtual apb_master_interface apb_master_vif;
  virtual apb_slave_interface apb_slave_vif;
  virtual apb_sys_env_interface apb_sys_env_vif;
  // pragma custom field_decl begin
  // pragma custom field_decl end
  function new(string name = "APB_env_gen_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 创建并配置环境
    env = APB_env::type_id::create("env", this);
    // harness 连接：把 DUT 侧 bind 的 interface 一次性 set 进环境 agent
    APB_bench_tb_top.u_dut.harness.set_vifs(env.get_full_name());

    // 创建并随机化配置
    cfg = APB_env_config::type_id::create("cfg");
    if (!cfg.randomize()) begin
      `uvm_fatal("CFG_RAND", "Failed to randomize environment configuration")
    end
    
    // 配置 Agent 模式（YAML agents 的 is_active；缺省 ACTIVE）
    cfg.apb_master_cfg.is_active = UVM_ACTIVE;
    cfg.apb_slave_cfg.is_active = UVM_PASSIVE;

    // 设置配置到 config_db
    uvm_config_db#(APB_env_config)::set(this, "env", "cfg", cfg);


    // pragma custom build_logic begin
    // pragma custom build_logic end

  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    `uvm_info("TEST", "APB_env_base_test elaborated", UVM_LOW)
  endfunction

  task configure_phase(uvm_phase phase);
    super.configure_phase(phase);
    `uvm_info(get_type_name(), "configure_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask

  task main_phase(uvm_phase phase);
    super.main_phase(phase);
    `uvm_info(get_type_name(), "main_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask

endclass : APB_env_gen_test

// SLPLIT SEQ
`define GEN_TOP_TC(tc_name, tc_com, tc_reg, tc_seq) \
class tc_name extends APB_env_gen_test; \
    `uvm_component_utils(tc_name) \
    function new(string name, uvm_component parent); \
    super.new(name, parent); \
endfunction \
virtual function void build_phase(uvm_phase phase); \
    super.build_phase(phase); \
    //different env_config_var var, cons BLOCK
    set_type_override_by_type(APB_env_config::get_type(),tc_com::get_type()); \
    //time driver split to DUT WORK
    uvm_config_db #(uvm_object_wrapper):set(this,"env.vsqr.configure_phase","default_sequence",tc_reg::type_id::get()); \
    uvm_config_db #(uvm_object_wrapper):set(this,"env.vsqr.main_phase","default_sequence",tc_seq::type_id::get()); \
endfunction \
endclass
