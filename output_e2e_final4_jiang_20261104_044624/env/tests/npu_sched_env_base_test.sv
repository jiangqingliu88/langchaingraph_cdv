// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_base_test.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Base Test: npu_sched_env_base_test
// 所有具体 Test 的基类

class npu_sched_env_base_test extends uvm_test;
  `uvm_component_utils(npu_sched_env_base_test)

  // 环境实例
  npu_sched_env env;

  // 环境配置
  npu_sched_env_config cfg;
 
  // 虚拟接口
  virtual npu_sched_in_interface npu_sched_in_vif;
  virtual npu_sched_out_interface npu_sched_out_vif;
  // pragma custom field_decl begin
  // pragma custom field_decl end
  function new(string name = "npu_sched_env_base_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 创建并配置环境
    env = npu_sched_env::type_id::create("env", this);

    // 创建并随机化配置
    cfg = npu_sched_env_config::type_id::create("cfg");
    if (!cfg.randomize()) begin
      `uvm_fatal("CFG_RAND", "Failed to randomize environment configuration")
    end
    
    // 配置 Agent 模式（YAML agents 的 is_active；缺省 ACTIVE）
    cfg.npu_sched_in_cfg.is_active = UVM_ACTIVE;
    cfg.npu_sched_out_cfg.is_active = UVM_PASSIVE;

    // 设置配置到 config_db
    uvm_config_db#(npu_sched_env_config)::set(this, "env", "cfg", cfg);

    // pragma custom build_logic begin
    // pragma custom build_logic end

  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    `uvm_info("TEST", "npu_sched_env_base_test elaborated", UVM_LOW)
  endfunction

  task configure_phase(uvm_phase phase);
    super.configure_phase(phase);
    `uvm_info(get_type_name(), "configure_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask

  task main_phase(uvm_phase phase);
    npu_sched_in_master_sequence npu_sched_in_seq;
    // 随机种子管理（+SEED=<n> 复现回归）
    int seed;
    super.main_phase(phase);
    `uvm_info(get_type_name(), "main_phase: start", UVM_MEDIUM)
    if ($value$plusargs("SEED=%0d", seed)) begin
      // UVM 1.2 的 `uvm_root` **没有** `set_seed()`（那是别的版本/公司内部扩展），
      // 调它报 "Field/method name (set_seed) not found"。用 SV 原生的
      // `$urandom(seed)`：带初值调用 = 给全局随机数发生器重新播种。
      // （Makefile 里本来也传了 `+ntb_random_seed`，两者并存不冲突。）
      void'($urandom(seed));
      `uvm_info(get_type_name(), $sformatf("SEED=%0d", seed), UVM_LOW)
    end
    phase.raise_objection(this);
    npu_sched_in_seq = npu_sched_in_master_sequence::type_id::create("npu_sched_in_seq");
    npu_sched_in_seq.start(env.npu_sched_in_agent_h.sequencer);
    // pragma custom run_logic begin
    // pragma custom run_logic end
    #1us;
    phase.drop_objection(this);
  endtask

endclass : npu_sched_env_base_test
