// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     APB_env.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Environment: APB_env
// 自动生成，不要手动修改

class APB_env extends uvm_env;
  `uvm_component_utils(APB_env)
  `ifdef USE_SC_MODEL_CHECK
    APB_env_sc_pred_env APB_env_sc_pred;
  `endif
  // ═══════════════════════════════════════
  // 时钟复位 Agent（可多个）
  // ═══════════════════════════════════════
  clk_rst_agent pclk_clk_rst_agent_h;
  // 配置对象
  APB_env_config cfg;

  // ── Register Model（RAL，可选，由 YAML register_model 列表决定）──
  apb_ral_pkg::apb_reg_block apb_reg_block;
  apb_reg_adapter apb_reg_adapter;
  uvm_reg_predictor #(apb_master_seq_item) apb_reg_predictor;  // 预测器需要指定总线事务类型

  // Agent 实例
  apb_master_agent apb_master_agent_h;
  apb_slave_agent apb_slave_agent_h;

  // Sub-env 实例
  apb_system_env apb_sys_env;

  // VIP env 实例（外部 VIP 集成）

  // Analysis 组件（predictor 等）
  apb_predictor apb_pred;

  // Scoreboard
  typedef in_order_scoreboard#(apb_master_seq_item, apb_master_seq_item) apb_scb_t;     // 参数化类特化：<类>#(<params>) 的别名
  apb_scb_t apb_scb;

  // 功能覆盖率模型（env 级，跨 agent covergroup）
  APB_env_coverage env_cov;
  APB_env_sim_end sim_end_h;   // 仿真自动结束组件（watchdog + auto finish）

  // TLM 连接
  uvm_analysis_port #(apb_master_seq_item) apb_master_agent_ap;
  uvm_analysis_port #(apb_slave_seq_item) apb_slave_agent_ap;

  // Analysis Exports / Ports（env 级 TLM 端口，由 YAML analysis_exports/analysis_ports 配置）
 // Sequencer 中央管理（virtual_sequencer 在 seq_pkg 中，env_pkg 不可直接引用）
  APB_env_virtual_sequencer virtual_sqr;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 获取环境配置
    if (!uvm_config_db#(APB_env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Environment configuration not set")
  `ifdef USE_SC_MODEL_CHECK
    APB_env_sc_pred=APB_env_sc_pred_env::type_id::create("APB_env_sc_pred", this);
  `endif
    // ─── 创建时钟复位 Agent ───
    begin
      clk_rst_config pclk_clk_cfg;
      pclk_clk_cfg = clk_rst_config::type_id::create("pclk_clk_cfg");
      
      // 时钟配置
      pclk_clk_cfg.clk_period_ps    = 10000;
      pclk_clk_cfg.clk_duty_cycle   = 50;
      pclk_clk_cfg.clk_start_value  = 0;
      pclk_clk_cfg.clk_jitter_ps    = 0;
      
      // 找到对应的复位配置
      // 为 pclk 配置复位（使用第一个复位作为默认）
      pclk_clk_cfg.rst_assert_cycles = 10;
      pclk_clk_cfg.rst_recover_cycles = 5;
      pclk_clk_cfg.rst_active_low = true;
      pclk_clk_cfg.reset_type = ASYNC_SYNC_DEASSERT;
      
      pclk_clk_rst_agent_h = clk_rst_agent::type_id::create("pclk_clk_rst_agent_h", this);
      uvm_config_db#(clk_rst_config)::set(this, "pclk_clk_rst_agent_h", "cfg", pclk_clk_cfg);
      uvm_config_db#(virtual clk_rst_if)::set(this, "pclk_clk_rst_agent_h", "vif", pclk_vif);
    end
    // 创建 Agent 并设置配置
    apb_master_agent_h = apb_master_agent::type_id::create("apb_master_agent_h", this);
    uvm_config_db#(apb_port_config)::set(this, "apb_master_agent_h", "cfg", cfg.apb_master_cfg);
    apb_slave_agent_h = apb_slave_agent::type_id::create("apb_slave_agent_h", this);
    uvm_config_db#(apb_port_config)::set(this, "apb_slave_agent_h", "cfg", cfg.apb_slave_cfg);

    // ─── Register Model（RAL）创建 ───
    apb_reg_block = apb_ral_pkg::apb_reg_block::type_id::create("apb_reg_block", this);
    apb_reg_block.build();       // 显式调用 build()
    apb_reg_block.lock_model();  // 锁定模型，防止后续修改
    apb_reg_adapter = apb_reg_adapter::type_id::create("apb_reg_adapter", this);
    apb_reg_predictor = uvm_reg_predictor #(apb_master_seq_item)::type_id::create("apb_reg_predictor", this);
    // reg model 暴露到 config_db（reg 自检序列等通过 "*" 获取）
    uvm_config_db#(uvm_reg_block)::set(this, "*", "reg_model", apb_reg_block);

    // 创建 Sub-env
    apb_sys_env = apb_system_env::type_id::create("apb_sys_env", this);

    // 创建 VIP env

    // 创建 Analysis 组件
    apb_pred = apb_predictor::type_id::create("apb_pred", this);

    // 创建 Scoreboard
    apb_scb = apb_scb_t::type_id::create("apb_scb", this);

    // 创建功能覆盖率模型（env_cov）
    env_cov = APB_env_coverage::type_id::create("env_cov", this);

    // 创建仿真自动结束组件（watchdog + 全部 objection 清零后 $finish）
    sim_end_h = APB_env_sim_end::type_id::create("sim_end_h", this);

    // 创建 Analysis Ports
    apb_master_agent_ap = new("apb_master_agent_ap", this);
    apb_slave_agent_ap = new("apb_slave_agent_ap", this);

    // 创建 Analysis Exports / Ports

    // 创建 Virtual Sequencer（virtual_sequencer 在 seq_pkg 中，env_pkg 不可引用）
    virtual_sqr = APB_env_virtual_sequencer::type_id::create("virtual_sqr", this);
    uvm_config_db#(APB_env_config)::set(this, "virtual_sqr", "cfg", cfg);

    // pragma custom build_logic begin
    // pragma custom build_logic end
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);

    // 连接子 Sequencer 到 Virtual Sequencer（直接赋值，规避 config_db 时序/作用域问题）
    virtual_sqr.apb_master_sqr = apb_master_agent_h.sequencer;
    virtual_sqr.apb_slave_sqr = apb_slave_agent_h.sequencer;

    // 连接 Agent Monitor 到 Analysis Ports
    apb_master_agent_h.monitor.mon_ap.connect(apb_master_agent_ap);
    apb_slave_agent_h.monitor.slave_mon_ap.connect(apb_slave_agent_ap);

    // 连接 Analysis Ports 到功能覆盖率模型（env_cov）
    apb_master_agent_ap.connect(env_cov.apb_master_export);
    apb_slave_agent_ap.connect(env_cov.apb_slave_export);

    // ─── Register Model（RAL）连接 ───
    // 1. 将寄存器模型的地址映射（default_map）连接到序列器和适配器
    apb_reg_block.default_map.set_sequencer(apb_master_agent_h.sequencer, apb_reg_adapter);
    apb_reg_block.default_map.set_auto_predict(0);
    // 2. 配置预测器（显式预测模式）
    apb_reg_predictor.map = apb_reg_block.default_map;
    apb_reg_predictor.adapter = apb_reg_adapter;
    apb_master_agent_ap.connect(apb_reg_predictor.bus_in);

    // Analysis Ports 连接（connected_to）

    // TLM 连接（显式 driver → receiver）
    apb_master_agent_ap.connect(apb_pred.in_export);
    apb_pred.out_port.connect(apb_scb.expected_analysis_export);
    apb_slave_agent_ap.connect(apb_scb.actual_analysis_export);

    // pragma custom connect_logic begin
    // pragma custom connect_logic end

  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    // 打印环境拓扑
    `uvm_info("ENV_TOPOLOGY", "Environment APB_env structure:", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Agent: apb_master_agent_h", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Agent: apb_slave_agent_h", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Scoreboard: apb_scb", UVM_LOW)
  endfunction

  function void start_of_simulation_phase(uvm_phase phase);
      super.start_of_simulation_phase(phase);
      `uvm_info(get_name(), "start_of_simulation_phase", UVM_LOW)
      // 显示 banner
      // 初始化统计
  endfunction
  task configure_phase(uvm_phase phase);
        super.configure_phase(phase);
        `uvm_info(get_name(), "configure_phase: start", UVM_MEDIUM)
        phase.raise_objection(this);
        phase.drop_objection(this);
  endtask
    
  task pre_reset_phase(uvm_phase phase);
      super.pre_reset_phase(phase);
      `uvm_info(get_name(), "pre_reset_phase", UVM_HIGH)
      phase.raise_objection(this);
      #100ns;
      phase.drop_objection(this);
  endtask
  
  task reset_phase(uvm_phase phase);
      super.reset_phase(phase);
      `uvm_info(get_name(), "reset_phase", UVM_HIGH)
      phase.raise_objection(this);
      // 施加复位
      #200ns;
      phase.drop_objection(this);
  endtask
  
  task main_phase(uvm_phase phase);
      super.main_phase(phase);
      `uvm_info(get_name(), "main_phase", UVM_LOW)
      phase.raise_objection(this);
      // 主要测试激励
      // ...
      phase.drop_objection(this);
  endtask
  
  task shutdown_phase(uvm_phase phase);
      super.shutdown_phase(phase);
      `uvm_info(get_name(), "shutdown_phase", UVM_HIGH)
      phase.raise_objection(this);
      #100ns;
      phase.drop_objection(this);
  endtask
  
  // ============================================================
  // Post-processing Phases (自底向上执行)
  // ============================================================
  
  function void extract_phase(uvm_phase phase);
      super.extract_phase(phase);
      `uvm_info(get_name(), "extract_phase", UVM_LOW)
      // 从组件提取最终数据
      // 收集计数器
  endfunction
  
  function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      `uvm_info(get_name(), "check_phase", UVM_LOW)
      // 检查最终状态
      // 验证数据完整性
  endfunction
  //========================================================================
  // report_phase - 统计并打印图案
  //========================================================================
  function void report_phase(uvm_phase phase);
      uvm_report_server server;
      int error_count;
      int fatal_count;
      
      super.report_phase(phase);
      
      // 获取全局报告服务器
      server = uvm_report_server::get_server();
      
      // 获取错误和致命错误计数
      error_count = server.get_severity_count(UVM_ERROR);
      fatal_count = server.get_severity_count(UVM_FATAL);
      
      // 打印分隔线
      `uvm_info(get_name(), "\n", UVM_NONE)
      `uvm_info(get_name(), "================================================================================", UVM_NONE)
      
      // 根据结果打印图案
      if (error_count > 0 || fatal_count > 0) begin
          print_test_fail();
      end else begin
          print_test_pass();
      end
      
      `uvm_info(get_name(), "================================================================================", UVM_NONE)
      `uvm_info(get_name(), "\n", UVM_NONE)
      
  endfunction
  
  //========================================================================
  // TEST_PASS / TEST_FAIL 图案（include 片段，见 _report_patterns.sv.j2）
  //========================================================================
// ════════════════════════════════════════════════════════════
// 报告图案片段（被 environment.sv.j2 include，减少主模板体量）
// ════════════════════════════════════════════════════════════
  function void print_test_pass();
      `uvm_info(get_name(), "", UVM_NONE)
      `uvm_info(get_name(), "    ████████╗███████╗███████╗████████╗", UVM_NONE)
      `uvm_info(get_name(), "    ╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝", UVM_NONE)
      `uvm_info(get_name(), "       ██║   █████╗  ███████╗   ██║   ", UVM_NONE)
      `uvm_info(get_name(), "       ██║   ██╔══╝  ╚════██║   ██║   ", UVM_NONE)
      `uvm_info(get_name(), "       ██║   ███████╗███████║   ██║   ", UVM_NONE)
      `uvm_info(get_name(), "       ╚═╝   ╚══════╝╚══════╝   ╚═╝   ", UVM_NONE)
      `uvm_info(get_name(), "                                       ", UVM_NONE)
      `uvm_info(get_name(), "    ██████╗  █████╗ ███████╗███████╗   ", UVM_NONE)
      `uvm_info(get_name(), "    ██╔══██╗██╔══██╗██╔════╝██╔════╝   ", UVM_NONE)
      `uvm_info(get_name(), "    ██████╔╝███████║███████╗███████╗   ", UVM_NONE)
      `uvm_info(get_name(), "    ██╔═══╝ ██╔══██║╚════██║╚════██║   ", UVM_NONE)
      `uvm_info(get_name(), "    ██║     ██║  ██║███████║███████║   ", UVM_NONE)
      `uvm_info(get_name(), "    ╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝   ", UVM_NONE)
      `uvm_info(get_name(), "                                       ", UVM_NONE)
      `uvm_info(get_name(), "                         ✓  TEST PASSED  ✓                         ", UVM_NONE)
  endfunction

  function void print_test_fail();
      `uvm_info(get_name(), "", UVM_NONE)
      `uvm_info(get_name(), "    ████████╗███████╗███████╗████████╗", UVM_NONE)
      `uvm_info(get_name(), "    ╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝", UVM_NONE)
      `uvm_info(get_name(), "       ██║   █████╗  ███████╗   ██║   ", UVM_NONE)
      `uvm_info(get_name(), "       ██║   ██╔══╝  ╚════██║   ██║   ", UVM_NONE)
      `uvm_info(get_name(), "       ██║   ███████╗███████║   ██║   ", UVM_NONE)
      `uvm_info(get_name(), "       ╚═╝   ╚══════╝╚══════╝   ╚═╝   ", UVM_NONE)
      `uvm_info(get_name(), "                                       ", UVM_NONE)
      `uvm_info(get_name(), "    ███████╗ █████╗ ██╗██╗     ███████╗", UVM_NONE)
      `uvm_info(get_name(), "    ██╔════╝██╔══██╗██║██║     ██╔════╝", UVM_NONE)
      `uvm_info(get_name(), "    █████╗  ███████║██║██║     █████╗  ", UVM_NONE)
      `uvm_info(get_name(), "    ██╔══╝  ██╔══██║██║██║     ██╔══╝  ", UVM_NONE)
      `uvm_info(get_name(), "    ██║     ██║  ██║██║███████╗███████╗", UVM_NONE)
      `uvm_info(get_name(), "    ╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝", UVM_NONE)
      `uvm_info(get_name(), "                                       ", UVM_NONE)
      `uvm_info(get_name(), "                         ✗  TEST FAILED  ✗                         ", UVM_NONE)
  endfunction

  endfunction
  function void final_phase(uvm_phase phase);
      super.final_phase(phase);
      `uvm_info(get_name(), "final_phase", UVM_LOW)
      // 关闭文件
      // 最终清理
  endfunction
endclass : APB_env
