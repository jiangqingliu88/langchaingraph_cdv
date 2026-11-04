// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_gen_test.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Gen Test: npu_sched_env_gen_test
// 所有具体 Test 的基类

class npu_sched_env_gen_test extends uvm_test;
  `uvm_component_utils(npu_sched_env_gen_test)
    npu_sched_in_master_sequence npu_sched_in_seq;
    npu_sched_out_master_sequence npu_sched_out_seq;
  // 环境实例
  npu_sched_env                   env;

  // 环境配置
  npu_sched_env_config            cfg;
 
  // 虚拟接口
  virtual npu_sched_in_interface      npu_sched_in_vif;
  virtual npu_sched_out_interface      npu_sched_out_vif;
  // pragma custom field_decl begin
  // pragma custom field_decl end
  function new(string name = "npu_sched_env_gen_test", uvm_component parent);
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
    super.main_phase(phase);
    `uvm_info(get_type_name(), "main_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);

    // **必须真启动序列** —— 这个类声明了 `<agent>_seq` 这些句柄却从不启动它们，
    // objection 起来就落，于是**一个激励都不发**。
    //
    // 它不是"少跑几条用例"，是**整条验证链静默失效**：DUT 的输入没人驱动 → 全 X
    // → 内部寄存器被 X 传播（`queue_level <= queue_level + (instr_valid ? 1 : 0)`，
    // `instr_valid` 是 X 就整个变 X）→ 覆盖率恒 0%、断言因 X 而报错。
    // 实测：这一条让 p0 6/7 全红，而**日志上看不出"没驱动"**（仿真正常跑完、
    // UVM 报告正常打印，只有把信号 examine 出来才看得到满屏的 x）。
    //
    // 两个条件都要（与 `test_directed.sv.j2` 同一套，那边的注释记着事故）：
    //   · `is_master` —— slave 实例是响应侧，没有自己的激励序列
    //   · `is_active` —— **passive 实例根本不创建 sequencer**，
    //     `_seq.start(null)` 会让序列永远等不到授权、objection 永不释放，
    //     一路挂到 PH_TIMEOUT（9200 秒仿真时间）。
    // **批次 test 走协调序列**：它在每个迭代里先建事务，再按 `batch_policy`
    // 指定的策略 `apply()`，然后发出。以前批次 test 只 `set` 了一个策略名，
    // 而 `main_phase` 启动的是 agent 的普通序列 —— **名字挂上了，没人用**。
    //
    // 属性 test 不设 `batch_policy`（它走 `<field>_int` 那条通道），所以照旧。
    begin
      string _batch_policy = "";
      if (uvm_config_db#(string)::get(null, "", "batch_policy", _batch_policy)
          && _batch_policy != "") begin
        npu_sched_env_coordinated_sequence _vseq;
        _vseq = npu_sched_env_coordinated_sequence::type_id::create("_vseq");
        _vseq.start(env.virtual_sqr);
      end else begin
        begin
          npu_sched_in_master_sequence _seq;
          _seq = npu_sched_in_master_sequence::type_id::create("_seq");
          _seq.start(env.npu_sched_in_agent_h.sequencer);
        end
      end
    end

    // pragma custom run_logic begin
    // pragma custom run_logic end

    phase.drop_objection(this);
  endtask

endclass : npu_sched_env_gen_test

// SPLIT SEQ（tc_reg / tc_seq 由调用者传入具体的 reg/seq 类名）
//
// **宏体里绝不能用 `//` 行注释**：`//` 会一直吃到行尾、**把续行符 `\` 一起吞掉**
//（LRM 里 `\` 是注释的最后一个字符），于是宏在那一行**提前结束**，后面几行变成
// 真实代码 → "near '(': syntax error, unexpected '('"。
// 要用注释就写 `/* ... */`，它不吃续行符。
//
// 另：`uvm_config_db #(T):set(...)` 少了一个冒号，必须是 `::set`。
`define GEN_TOP_TC(tc_name, tc_com, tc_reg, tc_seq) \
class tc_name extends npu_sched_env_gen_test; \
    `uvm_component_utils(tc_name) \
    function new(string name, uvm_component parent); \
    super.new(name, parent); \
endfunction \
virtual function void build_phase(uvm_phase phase); \
    super.build_phase(phase); \
    /* 替换 env_config 类型，把 BLOCK 约束换掉 */ \
    uvm_component::set_type_override_by_type(npu_sched_env_config::get_type(),tc_com::get_type()); \
    /* 把驱动时序拆到 DUT 侧 */ \
    uvm_config_db#(uvm_object_wrapper)::set(this,"env.vsqr.configure_phase","default_sequence",tc_reg::type_id::get()); \
    uvm_config_db#(uvm_object_wrapper)::set(this,"env.vsqr.main_phase","default_sequence",tc_seq::type_id::get()); \
endfunction \
endclass
