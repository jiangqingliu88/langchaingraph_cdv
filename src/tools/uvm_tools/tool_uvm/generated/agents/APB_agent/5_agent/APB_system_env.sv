// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_system_env.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// System Env: APB_system_env
// ============================================================
// 顶层系统环境：通过 APB_system_if 分发接口到各个 master/slave agent
//   sys_vif.master_if[i] → m_agents[i]
//   sys_vif.slave_if[i]  → s_agents[i]

class APB_system_env extends uvm_env;
  `uvm_component_utils(APB_system_env)

  APB_master_agent m_agents[];
  APB_slave_agent  s_agents[];

  APB_system_config sys_cfg;
  virtual APB_system_if sys_vif;

  function new(string name = "APB_system_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(APB_system_config)::get(this, "", "sys_cfg", sys_cfg);
    if (sys_cfg == null) `uvm_fatal("ENV", "sys_cfg not found")
    if (!uvm_config_db#(virtual APB_system_if)::get(this, "", "sys_vif", sys_vif))
      `uvm_fatal("NOVIF", "system interface not set")

    m_agents = new[sys_cfg.num_masters];
    foreach (m_agents[i]) begin
      m_agents[i] = APB_master_agent::type_id::create($sformatf("m_agent[%0d]", i), this);
      uvm_config_db#(APB_master_config)::set(this, $sformatf("m_agent[%0d]", i), "cfg", sys_cfg.master_cfgs[i]);
      if (sys_vif.master_if.size() > i) begin
        uvm_config_db#(virtual APB_if)::set(this, $sformatf("m_agent[%0d]", i), "vif", sys_vif.master_if[i]);
      end
    end

    s_agents = new[sys_cfg.num_slaves];
    foreach (s_agents[i]) begin
      s_agents[i] = APB_slave_agent::type_id::create($sformatf("s_agent[%0d]", i), this);
      uvm_config_db#(APB_slave_config)::set(this, $sformatf("s_agent[%0d]", i), "cfg", sys_cfg.slave_cfgs[i]);
      if (sys_vif.slave_if.size() > i) begin
        uvm_config_db#(virtual APB_if)::set(this, $sformatf("s_agent[%0d]", i), "vif", sys_vif.slave_if[i]);
      end
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
  endfunction

  function APB_master_sequencer get_master_sequencer(int idx = 0);
    return m_agents[idx].sequencer;
  endfunction

  function APB_slave_sequencer get_slave_sequencer(int idx = 0);
    return s_agents[idx].sequencer;
  endfunction

endclass : APB_system_env
