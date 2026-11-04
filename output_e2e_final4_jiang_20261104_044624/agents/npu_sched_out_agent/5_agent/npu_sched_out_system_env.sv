// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_system_env.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// System Env: npu_sched_out_system_env
// ============================================================
// 顶层系统环境：通过 npu_sched_out_system_if 分发接口到各个 master/slave agent
//   sys_vif.master_if[i] → m_agents[i]
//   sys_vif.slave_if[i]  → s_agents[i]

class npu_sched_out_system_env extends uvm_env;
  `uvm_component_utils(npu_sched_out_system_env)

  npu_sched_out_master_agent m_agents[];
  npu_sched_out_slave_agent  s_agents[];

  npu_sched_out_system_config sys_cfg;
  virtual npu_sched_out_system_if sys_vif;

  // 系统级嗅探器（sys_cfg.system_monitor_enable = 1 时才构建）
  npu_sched_out_system_monitor sys_monitor;

  // 系统级虚拟 sequencer：持有同协议全部 master/slave 子 sequencer 句柄，
  // 供虚拟序列跨端口协调（句柄在 connect_phase 由本 env 赋值）
  npu_sched_out_system_vsqr system_vsqr;

  function new(string name = "npu_sched_out_system_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    void'(uvm_config_db#(npu_sched_out_system_config)::get(this, "", "sys_cfg", sys_cfg));
    if (sys_cfg == null) `uvm_fatal("ENV", "sys_cfg not found")
    if (!uvm_config_db#(virtual npu_sched_out_system_if)::get(this, "", "sys_vif", sys_vif))
      `uvm_fatal("NOVIF", "system interface not set")

    m_agents = new[sys_cfg.num_masters];
    foreach (m_agents[i]) begin
      m_agents[i] = npu_sched_out_master_agent::type_id::create($sformatf("m_agent[%0d]", i), this);
      uvm_config_db#(npu_sched_out_port_config)::set(this, $sformatf("m_agent[%0d]", i), "cfg", sys_cfg.master_cfgs[i]);
      if ($size(sys_vif.master_if) > i) begin
        uvm_config_db#(virtual npu_sched_out_if)::set(this, $sformatf("m_agent[%0d]", i), "vif", sys_vif.master_if[i]);
      end
    end

    s_agents = new[sys_cfg.num_slaves];
    foreach (s_agents[i]) begin
      s_agents[i] = npu_sched_out_slave_agent::type_id::create($sformatf("s_agent[%0d]", i), this);
      uvm_config_db#(npu_sched_out_port_config)::set(this, $sformatf("s_agent[%0d]", i), "cfg", sys_cfg.slave_cfgs[i]);
      if ($size(sys_vif.slave_if) > i) begin
        uvm_config_db#(virtual npu_sched_out_if)::set(this, $sformatf("s_agent[%0d]", i), "vif", sys_vif.slave_if[i]);
      end
    end

    // 系统级 monitor：直接嗅探 sys_vif 全端口，与各 agent 的 monitor 并行
    if (sys_cfg.system_monitor_enable) begin
      uvm_config_db#(npu_sched_out_system_config)::set(this, "sys_monitor", "cfg", sys_cfg);
      uvm_config_db#(virtual npu_sched_out_system_if)::set(this, "sys_monitor", "sys_vif", sys_vif);
      sys_monitor = npu_sched_out_system_monitor::type_id::create("sys_monitor", this);
    end

    // 系统级 virtual sequencer：先传 sys_cfg（vsqr.build_phase 靠它定句柄数组规模），
    // 再创建。子 sequencer 句柄在 connect_phase 赋值。
    uvm_config_db#(npu_sched_out_system_config)::set(this, "system_vsqr", "sys_cfg", sys_cfg);
    system_vsqr = npu_sched_out_system_vsqr::type_id::create("system_vsqr", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);

    // 子 sequencer 句柄由本 env 直接赋值。vsqr 刻意不引用 env 类型
    // （二者互引会构成 SystemVerilog 循环类型依赖，见 vsqr 模板头部说明），
    // 故这里直接逐个写数组，而非让 vsqr 从 config_db 反查。
    for (int i = 0; i < sys_cfg.num_masters && i < system_vsqr.master_sqr.size(); i++)
      system_vsqr.master_sqr[i] = m_agents[i].sequencer;
    for (int i = 0; i < sys_cfg.num_slaves && i < system_vsqr.slave_sqr.size(); i++)
      system_vsqr.slave_sqr[i] = s_agents[i].sequencer;
    system_vsqr.mark_bound();
  endfunction

  function npu_sched_out_master_sequencer get_master_sequencer(int idx = 0);
    return m_agents[idx].sequencer;
  endfunction

  function npu_sched_out_slave_sequencer get_slave_sequencer(int idx = 0);
    return s_agents[idx].sequencer;
  endfunction

endclass : npu_sched_out_system_env
