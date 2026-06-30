// Environment: alu
// 自动生成，不要手动修改

class alu extends uvm_env;
  `uvm_component_utils(alu)
  `ifdef USE_SC_MODEL_CHECK
    alu_sc_pred_env alu_sc_pred;
  `endif
  // ═══════════════════════════════════════
  // 时钟复位 Agent（可多个）
  // ═══════════════════════════════════════
  clk_rst_agent _clk_rst_agent_h;
  clk_rst_agent _clk_rst_agent_h;
  // 配置对象
  alu_config cfg;

  // Agent 实例
  ALU_in_agent ALU_in_agent_h;
  ALU_out_agent ALU_out_agent_h;

  // Scoreboard 实例
  uvm_scoreboard alu_scoreboard_h;
  uvm_scoreboard alu_coverage_collector_h;

  // TLM 连接
  uvm_analysis_port #(ALU_in_seq_item) ALU_in_agent_ap;
  uvm_analysis_port #(ALU_out_seq_item) ALU_out_agent_ap;
 // Sequencer 中央管理（virtual_sequencer 在 seq_pkg 中，env_pkg 不可直接引用）
  alu_virtual_sequencer virtual_sqr;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 获取环境配置
    if (!uvm_config_db #(alu_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Environment configuration not set")
  `ifdef USE_SC_MODEL_CHECK
    alu_sc_pred=alu_sc_pred_env::type_id::create("alu_sc_pred", this);
  `endif
    // ─── 创建时钟复位 Agent ───
    begin
      clk_rst_config _clk_cfg;
      _clk_cfg = clk_rst_config::type_id::create("_clk_cfg");
      
      // 时钟配置
      _clk_cfg.clk_period_ps    = 10000;
      _clk_cfg.clk_duty_cycle   = 50;
      _clk_cfg.clk_start_value  = 0;
      _clk_cfg.clk_jitter_ps    = 0;
      
      // 找到对应的复位配置
      // 为  配置复位（使用第一个复位作为默认）
      _clk_cfg.rst_assert_cycles = 10;
      _clk_cfg.rst_recover_cycles = 5;
      _clk_cfg.rst_active_low = ;
      _clk_cfg.reset_type = ASYNC_SYNC_DEASSERT;
      
      _clk_rst_agent_h = clk_rst_agent::type_id::create("_clk_rst_agent_h", this);
      uvm_config_db #(clk_rst_config)::set(this, "_clk_rst_agent_h", "cfg", _clk_cfg);
      uvm_config_db #(virtual clk_rst_if)::set(this, "_clk_rst_agent_h", "vif", _vif);
    end
    begin
      clk_rst_config _clk_cfg;
      _clk_cfg = clk_rst_config::type_id::create("_clk_cfg");
      
      // 时钟配置
      _clk_cfg.clk_period_ps    = 10000;
      _clk_cfg.clk_duty_cycle   = 50;
      _clk_cfg.clk_start_value  = 0;
      _clk_cfg.clk_jitter_ps    = 0;
      
      // 找到对应的复位配置
      // 为  配置复位（使用第一个复位作为默认）
      _clk_cfg.rst_assert_cycles = 10;
      _clk_cfg.rst_recover_cycles = 5;
      _clk_cfg.rst_active_low = ;
      _clk_cfg.reset_type = ASYNC_SYNC_DEASSERT;
      
      _clk_rst_agent_h = clk_rst_agent::type_id::create("_clk_rst_agent_h", this);
      uvm_config_db #(clk_rst_config)::set(this, "_clk_rst_agent_h", "cfg", _clk_cfg);
      uvm_config_db #(virtual clk_rst_if)::set(this, "_clk_rst_agent_h", "vif", _vif);
    end
    // 创建 Agent 并设置配置
    ALU_in_agent_h = ALU_in_agent::type_id::create("ALU_in_agent_h", this);
    uvm_config_db #(ALU_in_config)::set(this, "ALU_in_agent_h", "cfg", cfg.ALU_in_cfg);
    ALU_out_agent_h = ALU_out_agent::type_id::create("ALU_out_agent_h", this);
    uvm_config_db #(ALU_out_config)::set(this, "ALU_out_agent_h", "cfg", cfg.ALU_out_cfg);

    // 创建 Scoreboard
    if (cfg.has_scoreboard) begin
      // uvm_scoreboard 基类无 type_id，改用 new()
      alu_scoreboard_h = new("alu_scoreboard_h", this);
    end
    if (cfg.has_scoreboard) begin
      // uvm_scoreboard 基类无 type_id，改用 new()
      alu_coverage_collector_h = new("alu_coverage_collector_h", this);
    end

    // 创建 Analysis Ports
    ALU_in_agent_ap = new("ALU_in_agent_ap", this);
    ALU_out_agent_ap = new("ALU_out_agent_ap", this);

    // 创建 Virtual Sequencer（virtual_sequencer 在 seq_pkg 中，env_pkg 不可引用）
    virtual_sqr = alu_virtual_sequencer::type_id::create("virtual_sqr", this);
    uvm_config_db #(alu_config)::set(this, "virtual_sqr", "cfg", cfg);
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    
    // 连接 Agent Monitor 到 Analysis Ports
    ALU_in_agent_h.mon.item_collected_port.connect(ALU_in_agent_ap);
    ALU_out_agent_h.mon.item_collected_port.connect(ALU_out_agent_ap);

    // 连接 Analysis Ports 到 Scoreboard（uvm_scoreboard 基类无 analysis_export，需子类化）
    // TODO: 创建 uvm_scoreboard 子类并注册 uvm_component_utils
    //if (cfg.has_scoreboard) begin
    //  ALU_in_agent_ap.connect(alu_scoreboard_h.analysis_export);
    //  ALU_out_agent_ap.connect(alu_scoreboard_h.analysis_export);
    //end
    //if (cfg.has_scoreboard) begin
    //  ALU_in_agent_ap.connect(alu_coverage_collector_h.analysis_export);
    //  ALU_out_agent_ap.connect(alu_coverage_collector_h.analysis_export);
    //end

  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    // 打印环境拓扑
    `uvm_info("ENV_TOPOLOGY", "Environment alu structure:", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Agent: ALU_in_agent_h", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Agent: ALU_out_agent_h", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Scoreboard: alu_scoreboard_h", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Scoreboard: alu_coverage_collector_h", UVM_LOW)
  endfunction

  function void start_of_simulation_phase(uvm_phase phase);
      super.start_of_simulation_phase(phase);
      `uvm_info(get_name(), "start_of_simulation_phase", UVM_LOW)
      // 显示 banner
      // 初始化统计
  endfunction
  task run_phase(uvm_phase phase);
        super.run_phase(phase);
        `uvm_info(get_name(), "run_phase", UVM_LOW)
        // ⚠️ 需要 raise_objection / drop_objection
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
  // TEST_PASS 图案（与你显示的一致）
  //========================================================================
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
  
  //========================================================================
  // TEST_FAIL 图案
  //========================================================================
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
  function void final_phase(uvm_phase phase);
      super.final_phase(phase);
      `uvm_info(get_name(), "final_phase", UVM_LOW)
      // 关闭文件
      // 最终清理
  endfunction
endclass : alu