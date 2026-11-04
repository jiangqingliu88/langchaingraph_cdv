// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_direct_test.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Directed Test: npu_sched_env_directed_test
// 执行特定场景测试

class npu_sched_env_directed_test extends npu_sched_env_base_test;
  `uvm_component_utils(npu_sched_env_directed_test)

  function new(string name = "npu_sched_env_directed_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 定向测试配置
    cfg.npu_sched_in_cfg.is_active = UVM_ACTIVE;
    cfg.npu_sched_in_cfg.has_coverage = 1'b0;
    cfg.npu_sched_out_cfg.is_active = UVM_PASSIVE;
    cfg.npu_sched_out_cfg.has_coverage = 1'b0;
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

    // 在**有 sequencer 的** Agent 上启动定向序列。
    //
    // 两个条件都要：
    //   · `is_master` —— slave 实例是响应侧，没有自己的激励序列
    //   · `is_active` —— **passive 实例根本不创建 sequencer**
    //     （agent 模板里 `sequencer` 只在 `cfg.is_active == UVM_ACTIVE` 时 create）。
    // 光看 is_master 会在 passive agent 上 `_seq.start(null)` —— sequencer 是 null，
    // 序列永远等不到 `start_item` 的授权，main_phase 的 objection 永不释放，
    // 一路挂到 UVM 的 PH_TIMEOUT（9200 秒仿真时间）。
    // 实测：intr 是 passive，整条定向测试就此超时，回归 23 条全红。
    begin
      npu_sched_in_master_sequence _seq;
      _seq = npu_sched_in_master_sequence::type_id::create("_seq");
      _seq.start(env.npu_sched_in_agent_h.sequencer);
    end

    // pragma custom run_logic begin
    // pragma custom run_logic end

    phase.drop_objection(this);
  endtask

endclass : npu_sched_env_directed_test
