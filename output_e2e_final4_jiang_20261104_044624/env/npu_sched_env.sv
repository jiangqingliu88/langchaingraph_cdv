// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Environment: npu_sched_env
// 自动生成，不要手动修改

class npu_sched_env extends uvm_env;
  `uvm_component_utils(npu_sched_env)
  `ifdef USE_SC_MODEL_CHECK
    npu_sched_env_sc_pred_env npu_sched_env_sc_pred;
  `endif
  // ═══════════════════════════════════════
  // 时钟复位 Agent（可多个）
  // ═══════════════════════════════════════
  clk_rst_agent clk_clk_rst_agent_h;
  // vif 句柄：tb_top 是唯一能实例化接口的地方，它把 virtual clk_rst_if 放进
  // config_db，本 env 取出来再转发给 clk_rst agent（见 build_phase）。
  // 不声明这个成员、直接写 `clk_vif` 的话是 "Undefined variable"。
  virtual clk_rst_if clk_vif;
  // 配置对象
  npu_sched_env_config cfg;

  // ── Register Model（RAL，可选，由 YAML register_model 列表决定）──

  // Agent 实例
  npu_sched_in_master_agent npu_sched_in_agent_h;
  npu_sched_out_master_agent npu_sched_out_agent_h;

  // Sub-env 实例

  // VIP env 实例（外部 VIP 集成）

  // Analysis 组件（predictor 等）

  // Scoreboard

  // 功能覆盖率模型（env 级，跨 agent covergroup）
  npu_sched_env_coverage env_cov;
  npu_sched_env_sim_end sim_end_h;   // 仿真自动结束组件（watchdog + auto finish）

  // TLM 连接
  uvm_analysis_port #(npu_sched_in_master_seq_item) npu_sched_in_agent_ap;
  uvm_analysis_port #(npu_sched_out_master_seq_item) npu_sched_out_agent_ap;

  // Analysis Exports / Ports（env 级 TLM 端口，由 YAML analysis_exports/analysis_ports 配置）
 // Sequencer 中央管理（virtual_sequencer 在 seq_pkg 中，env_pkg 不可直接引用）
  npu_sched_env_virtual_sequencer virtual_sqr;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 获取环境配置
    if (!uvm_config_db#(npu_sched_env_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Environment configuration not set")
    if (!uvm_config_db#(virtual clk_rst_if)::get(this, "", "clk_vif", clk_vif))
      `uvm_fatal("NOVIF", "clk_rst_if clk_vif 没从 config_db 传进来（tb_top 负责 set）")
  `ifdef USE_SC_MODEL_CHECK
    npu_sched_env_sc_pred=npu_sched_env_sc_pred_env::type_id::create("npu_sched_env_sc_pred", this);
  `endif
    // ─── 创建时钟复位 Agent ───
    begin
      clk_rst_config clk_clk_cfg;
      clk_clk_cfg = clk_rst_config::type_id::create("clk_clk_cfg");
      
      // 时钟配置
      clk_clk_cfg.clk_period_ps    = 10000;
      clk_clk_cfg.clk_duty_cycle   = 50;
      clk_clk_cfg.clk_start_value  = 0;
      clk_clk_cfg.clk_jitter_ps    = 0;
      
      // 找到对应的复位配置
      // 为 clk 配置复位（使用第一个复位作为默认）
      clk_clk_cfg.rst_assert_cycles = 10;
      clk_clk_cfg.rst_recover_cycles = 5;
      // 注：原为 `true` —— 渲染出小写的 true/false，
      // 而**那不是合法的 SystemVerilog**（SV 没有 true/false 字面量），
      // vlog 报 "Undefined variable: 'true'"。要用 1'b1 / 1'b0。
      clk_clk_cfg.rst_active_low = 1'b1;
      // 注：这里原来还有一行 `rst_cfg.reset_type = ASYNC_SYNC_DEASSERT;` —— **两边都不存在**：
      //   · `clk_rst_config` 里没有 `reset_type` 这个字段（只有 rst_active_low /
      //     rst_assert_cycles / rst_recover_cycles / rst_start_value）
      //   · `ASYNC_SYNC_DEASSERT` 也不是任何地方的枚举值，裸标识符 → "Undefined variable"
      // YAML 里写了 `reset_type:` 的话目前**是被忽略的** —— 要支持它，得先在
      // `clk_rst_config.svh` 里加字段与枚举，那是公共库的改动，不在这里顺手做。
      
      clk_clk_rst_agent_h = clk_rst_agent::type_id::create("clk_clk_rst_agent_h", this);
      // cfg 走**精确路径**（agent 自己在 build_phase 里 get 这一份）。
      uvm_config_db#(clk_rst_config)::set(this, "clk_clk_rst_agent_h", "cfg", clk_clk_cfg);
      // vif 必须走**带 `.*` 的通配路径**：真正要 vif 的是 agent 底下的 drv / rst_drv / mon，
      // 它们的查找路径是 `..._clk_rst_agent_h.drv`。uvm_config_db 的 set 路径是当
      // **正则**用的（`*` → `.*`），写死 `"clk_clk_rst_agent_h"` 只匹配**本级**，
      // 子组件一路 get 不到 → `uvm_fatal("[VIF] Clock interface not set")`。
      uvm_config_db#(virtual clk_rst_if)::set(this, "clk_clk_rst_agent_h.*", "vif", clk_vif);
    end
    // 创建 Agent 并设置配置
    npu_sched_in_agent_h = npu_sched_in_master_agent::type_id::create("npu_sched_in_agent_h", this);
    uvm_config_db#(npu_sched_in_port_config)::set(this, "npu_sched_in_agent_h", "cfg", cfg.npu_sched_in_cfg);
    npu_sched_out_agent_h = npu_sched_out_master_agent::type_id::create("npu_sched_out_agent_h", this);
    uvm_config_db#(npu_sched_out_port_config)::set(this, "npu_sched_out_agent_h", "cfg", cfg.npu_sched_out_cfg);

    // ─── Register Model（RAL）创建 ───

    // 创建 Sub-env

    // 创建 VIP env

    // 创建 Analysis 组件

    // 创建 Scoreboard

    // 创建功能覆盖率模型（env_cov）
    env_cov = npu_sched_env_coverage::type_id::create("env_cov", this);

    // 创建仿真自动结束组件（watchdog + 全部 objection 清零后 $finish）
    sim_end_h = npu_sched_env_sim_end::type_id::create("sim_end_h", this);

    // 创建 Analysis Ports
    npu_sched_in_agent_ap = new("npu_sched_in_agent_ap", this);
    npu_sched_out_agent_ap = new("npu_sched_out_agent_ap", this);

    // 创建 Analysis Exports / Ports

    // 创建 Virtual Sequencer（virtual_sequencer 在 seq_pkg 中，env_pkg 不可引用）
    virtual_sqr = npu_sched_env_virtual_sequencer::type_id::create("virtual_sqr", this);
    uvm_config_db#(npu_sched_env_config)::set(this, "virtual_sqr", "cfg", cfg);

    // pragma custom build_logic begin
    // pragma custom build_logic end
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);

    // 连接子 Sequencer 到 Virtual Sequencer（直接赋值，规避 config_db 时序/作用域问题）
    virtual_sqr.npu_sched_in_sqr = npu_sched_in_agent_h.sequencer;
    virtual_sqr.npu_sched_out_sqr = npu_sched_out_agent_h.sequencer;

    // 连接 Agent Monitor 到 Analysis Ports
    npu_sched_in_agent_h.monitor.master_mon_ap.connect(npu_sched_in_agent_ap);
    npu_sched_out_agent_h.monitor.master_mon_ap.connect(npu_sched_out_agent_ap);

    // 连接 Analysis Ports 到功能覆盖率模型（env_cov）
    npu_sched_in_agent_ap.connect(env_cov.npu_sched_in_export);
    npu_sched_out_agent_ap.connect(env_cov.npu_sched_out_export);

    // ─── Register Model（RAL）连接 ───

    // Analysis Ports 连接（connected_to）

    // TLM 连接（显式 driver → receiver）

    // pragma custom connect_logic begin
    // pragma custom connect_logic end

  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    // 打印环境拓扑
    `uvm_info("ENV_TOPOLOGY", "Environment npu_sched_env structure:", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Agent: npu_sched_in_agent_h", UVM_LOW)
    `uvm_info("ENV_TOPOLOGY", "  Agent: npu_sched_out_agent_h", UVM_LOW)
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
      // **等真实的复位释放，不睡写死的时长。**
      //
      // 原来是 `#200ns;`（注释写着"施加复位"，其实复位是 clk_rst agent 驱动的，
      // 这里什么都没做，只是在拖时间）。而 `assert_cycles: 10` 的复位在
      // **100ns 就释放了** —— 于是 `reset_phase` 比真实复位晚结束 ~100ns，而
      // UVM 的运行子相位是**顺序**的（reset → configure → main）：`main_phase`
      // 因此被推迟到复位释放之后才开始。
      //
      // 那段窗口里复位已释放、却**没有任何人在驱动** DUT 的输入 —— 而 DUT 的
      // 寄存器是 `always_ff @(posedge clk)`：
      //
      //     queue_level <= queue_level + (instr_valid && !full ? 1 : 0) - …
      //
      // `instr_valid` 还是 X → `queue_level` **被锁成 X**，此后 `X + 1 = X`
      // **再也回不来**（异步复位早已结束）。表现是：仿真正常跑完、UVM 报告正常
      // 打印、vsim 退出码 0，而覆盖率恒 0%、断言因 X 全部报错 ——
      // 从日志上看不出"没人驱动"，只有把信号 `examine` 出来才看得到满屏的 x。
      //
      // 驱动器那边的约定是"复位释放之后才驱动"（`main_phase` 里的
      // `wait (vif.rst_n == …)`），所以这里要做的不是提前驱动，而是**别拖**：
      // 复位一释放就让相位往下走，驱动器随即接管。
      wait (clk_vif.rst_active[0] == 0);
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
  // TEST_PASS / TEST_FAIL 图案
  //
  // `_report_patterns.sv.j2` 里是**两个函数定义**（print_test_pass /
  // print_test_fail），所以它属于**类作用域** —— 放在 report_phase 的
  // `endfunction` **之后**才对。（别挪进 report_phase 里面：那会变成函数套函数。）
  //
  // 这里原来在 include 之后**还多跟了一个 `endfunction`** —— 渲染出来就是
  // 「类里凭空多一个 endfunction」，vlog 判 "near 'endfunction': syntax error"，
  // 而报错位置会指到几百行之外，很难往这儿联想。
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

  function void final_phase(uvm_phase phase);
      super.final_phase(phase);
      `uvm_info(get_name(), "final_phase", UVM_LOW)
      // 关闭文件
      // 最终清理
  endfunction
endclass : npu_sched_env
