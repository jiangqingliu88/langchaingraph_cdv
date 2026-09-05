// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_loopback_env.sv
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
// Loopback Env: APB_loopback_env
// ============================================================
// master-drive → slave-monitor 闭环自检：
//   master driver 驱动事务 → interface 内部信号回环 → slave monitor 观察
//   master monitor 的抓包 = expected，slave monitor 的抓包 = actual
import uvm_pkg::*;
import APB_pkg::*;
`include "uvm_macros.svh"

class APB_loopback_env extends uvm_env;
  `uvm_component_utils(APB_loopback_env)

  APB_master_agent master_agent_h;
  APB_slave_agent  slave_agent_h;
  APB_loopback_scb  scb_h;

  function new(string name = "APB_loopback_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    APB_master_config mcfg;
    APB_slave_config  scfg;
    virtual APB_if vif;

    if (!uvm_config_db#(virtual APB_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")

    // loopback 自检拓扑固定（master 驱动 → slave 监控），不随 YAML is_active 变化：
    // master 必须 ACTIVE 才能注入激励；slave 保持 PASSIVE 避免驱动响应端口干扰比对
    mcfg = APB_master_config::type_id::create("mcfg");
    mcfg.vif = vif;
    mcfg.is_active = UVM_ACTIVE;

    scfg = APB_slave_config::type_id::create("scfg");
    scfg.vif = vif;
    scfg.is_active = UVM_PASSIVE;  // slave 仅监控，不响应

    uvm_config_db#(APB_master_config)::set(this, "master_agent_h", "cfg", mcfg);
    uvm_config_db#(APB_slave_config)::set(this, "slave_agent_h", "cfg", scfg);

    master_agent_h = APB_master_agent::type_id::create("master_agent_h", this);
    slave_agent_h  = APB_slave_agent::type_id::create("slave_agent_h", this);
    scb_h          = APB_loopback_scb::type_id::create("scb_h", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    master_agent_h.monitor.mon_ap.connect(scb_h.expected_export);
    slave_agent_h.monitor.mon_ap.connect(scb_h.actual_export);
  endfunction

endclass : APB_loopback_env
