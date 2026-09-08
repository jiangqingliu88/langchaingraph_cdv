// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_direct_test.sv
//   作者:     -
//   创建时间: 2026-09-08 17:16:01
//   修改时间: 2026-09-08 17:16:01
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Directed Test: APB_env_directed_test
// 执行特定场景测试

class APB_env_directed_test extends APB_env_base_test;
  `uvm_component_utils(APB_env_directed_test)

  function new(string name = "APB_env_directed_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 定向测试配置
    cfg.apb_master_cfg.is_active = UVM_ACTIVE;
    cfg.apb_master_cfg.has_coverage = 1'b0;
    // pragma custom build_logic begin
    // pragma custom build_logic end
  endfunction

  virtual task configure_phase(uvm_phase phase);
    super.configure_phase(phase);
    `uvm_info(get_type_name(), "configure_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask

  virtual task main_phase(uvm_phase phase);
    super.main_phase(phase);
    `uvm_info(get_type_name(), "main_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);

    // 在所有 Agent Sequencer 上启动定向序列（is_master: False 的 slave 实例跳过）
    begin
      apb_master_sequence _seq;
      _seq = apb_master_sequence::type_id::create("_seq");
      _seq.start(env.apb_master_agent_h.sequencer);
    end

    // pragma custom run_logic begin
    // pragma custom run_logic end

    phase.drop_objection(this);
  endtask

endclass : APB_env_directed_test
