// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_in_loopback_env.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Loopback Env: npu_sched_in_loopback_env
// ============================================================
// master-drive → slave-monitor 闭环自检：
//   master driver 驱动事务 → interface 内部信号回环 → slave monitor 观察
//   **master driver 驱动出去的事务 = expected**，slave monitor 的抓包 = actual
//
// 为什么 expected 取 **driver** 而不是 master monitor：
//   loopback 里 tb 把**同一个**接口实例发给 master / slave 两个 agent
//   （见 `<ag>_loopback_tb.sv` 的注释：两个独立实例会被 vopt-12003 拒掉），
//   于是 master monitor 和 slave monitor 在采**同一组信号** ——
//   拿它们互比就是"同一个接口读两遍"，恒真，driver 一个信号都不驱动也照样 PASS。
//   换成 driver 驱动出去的事务，"发出去的 vs 总线上看到的"才是真正的自检。
import uvm_pkg::*;
import npu_sched_in_pkg::*;
// `MASTER` / `SLAVE`（port_kind_enum）住在公共包里；SV 的 import **不传递**，
// `npu_sched_in_pkg` 带不进来 —— 不显式 import 就是
// "Undefined variable: 'MASTER'"（见下面的 mcfg.port_kind 赋值）。
import common_typedefs_pkg::*;
`include "uvm_macros.svh"

class npu_sched_in_loopback_env extends uvm_env;
  `uvm_component_utils(npu_sched_in_loopback_env)

  npu_sched_in_master_agent master_agent_h;
  npu_sched_in_slave_agent  slave_agent_h;
  npu_sched_in_loopback_scb  scb_h;

  function new(string name = "npu_sched_in_loopback_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    // ⚠️ 声明必须排在**块内所有语句之前**（SV 规则）：`super.build_phase(phase);`
    // 已经是语句，声明写在它后面就是
    // "Illegal declaration after the statement ... Declarations must precede statements"。
    npu_sched_in_port_config mcfg;
    npu_sched_in_port_config  scfg;
    virtual npu_sched_in_if mvif;
    virtual npu_sched_in_if svif;

    super.build_phase(phase);

    // ── vif **按 agent 各取各的** ──
    // tb 把接口 set 到**每个 agent 的路径**上（`*.master_agent_h*` / `*.slave_agent_h*`），
    // 所以这里也按同样的路径各取一次，而不是自己 get 一个笼统的 `""`。
    // 用笼统路径的话，tb 那边按 agent 分发的 set 一个都匹配不到 env →
    // 0 时刻 `[NOVIF] Virtual interface not set` 直接挂。
    // master / slave 各拿哪个接口，在这两行上是**看得见的**。
    if (!uvm_config_db#(virtual npu_sched_in_if)::get(this, "master_agent_h", "vif", mvif))
      `uvm_fatal("NOVIF", "master_agent_h 的 virtual interface 没设")
    if (!uvm_config_db#(virtual npu_sched_in_if)::get(this, "slave_agent_h", "vif", svif))
      `uvm_fatal("NOVIF", "slave_agent_h 的 virtual interface 没设")

    // loopback 自检拓扑固定（master 驱动 → slave 监控），不随 env 配置变化：
    // master 必须 ACTIVE 才能注入激励；slave 保持 PASSIVE 避免驱动响应端口干扰比对
    mcfg = npu_sched_in_port_config::type_id::create("mcfg");
    mcfg.vif = mvif;
    mcfg.is_active = UVM_ACTIVE;
    mcfg.port_kind = MASTER;

    scfg = npu_sched_in_port_config::type_id::create("scfg");
    scfg.vif = svif;
    scfg.is_active = UVM_PASSIVE;  // slave 仅监控，不响应
    scfg.port_kind = SLAVE;

    uvm_config_db#(npu_sched_in_port_config)::set(this, "master_agent_h", "cfg", mcfg);
    uvm_config_db#(npu_sched_in_port_config)::set(this, "slave_agent_h", "cfg", scfg);

    master_agent_h = npu_sched_in_master_agent::type_id::create("master_agent_h", this);
    slave_agent_h  = npu_sched_in_slave_agent::type_id::create("slave_agent_h", this);
    scb_h          = npu_sched_in_loopback_scb::type_id::create("scb_h", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    // expected ← **master driver 驱动出去的事务**（`driver.driven_ap`）
    // actual   ← slave monitor 的抓包（`slave_mon_ap`）
    //
    // 注：monitor 的抓包端口分 `master_mon_ap` / `slave_mon_ap` 两个名字，没有笼统的
    // `mon_ap` —— 写错就是 "Could not find field/method name (mon_ap)"。
    // 这里**故意**不用 `master_mon_ap`：那也是 monitor 的抓包（见文件头说明）。
    master_agent_h.driver.driven_ap.connect(scb_h.expected_export);
    slave_agent_h.monitor.slave_mon_ap.connect(scb_h.actual_export);
  endfunction

endclass : npu_sched_in_loopback_env
