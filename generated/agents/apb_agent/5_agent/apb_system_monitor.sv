// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_system_monitor.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// ============================================================
// System Monitor: apb_system_monitor
// ============================================================
// 系统级嗅探器：直接观察 apb_system_if 上的全部端口实例，
//   不经过 agent —— 所有 agent 均 PASSIVE 时依然能观测整个系统。
//   sys_vif.master_if[i] → kind = MASTER, index = i
//   sys_vif.slave_if[i]  → kind = SLAVE,  index = i
// 由 apb_system_config.system_monitor_enable 门控（0 = 不构建采集进程）

// ── 系统级事务：一次协议访问 + 来源标签 {kind, index} ──
class apb_system_txn extends uvm_object;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack/config_db 自动化）──
  `uvm_object_utils_begin(apb_system_txn)
    `uvm_field_enum(port_kind_enum, kind, UVM_DEFAULT)
    `uvm_field_int(index, UVM_DEFAULT)
    `uvm_field_int(paddr, UVM_DEFAULT)
    `uvm_field_int(pwrite, UVM_DEFAULT)
    `uvm_field_int(pwdata, UVM_DEFAULT)
    `uvm_field_int(prdata, UVM_DEFAULT)
    `uvm_field_int(pslverr, UVM_DEFAULT)
  `uvm_object_utils_end

  port_kind_enum kind = MASTER;  // 来源端口类型
  int            index;          // 端口实例下标
  time           timestamp;      // 采样时刻
  bit [ADDR_WIDTH-1:0] paddr;
  bit pwrite;
  bit [DATA_WIDTH-1:0] pwdata;
  bit [DATA_WIDTH-1:0] prdata;
  bit pslverr;

  function new(string name = "apb_system_txn");
    super.new(name);
  endfunction

endclass : apb_system_txn

class apb_system_monitor extends uvm_monitor;
  `uvm_component_utils(apb_system_monitor)

  virtual apb_system_if sys_vif;
  apb_system_config  cfg;

  // 统一分析端口：系统内所有端口实例的采样结果（带 {kind, index} 标签）
  uvm_analysis_port #(apb_system_txn) sys_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    sys_ap = new("sys_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual apb_system_if)::get(this, "", "sys_vif", sys_vif))
      `uvm_fatal("NOVIF", "System interface not set")
    if (!uvm_config_db#(apb_system_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "System config not set")
  endfunction

  task main_phase(uvm_phase phase);
    super.main_phase(phase);
    if (!cfg.system_monitor_enable) begin
      `uvm_info(get_type_name(), "system_monitor_enable = 0, system monitor idle", UVM_LOW)
      return;
    end
    `uvm_info(get_type_name(), $sformatf("main_phase: sniff m%0d + s%0d ports",
              cfg.num_masters, cfg.num_slaves), UVM_MEDIUM)
    // 每个端口实例一个独立采集进程（各自等待自己的复位释放，互不阻塞）
    // monitor 的 forever 循环不 raise objection（避免悬挂）
    for (int i = 0; i < cfg.num_masters && i < $size(sys_vif.master_if); i++) begin
      automatic int idx = i;
      fork
        collect_port(sys_vif.master_if[idx], MASTER, idx);
      join_none
    end
    for (int i = 0; i < cfg.num_slaves && i < $size(sys_vif.slave_if); i++) begin
      automatic int idx = i;
      fork
        collect_port(sys_vif.slave_if[idx], SLAVE, idx);
      join_none
    end
  endtask

  // 单个端口实例的采集循环：复位释放 → 采一次 → 打标签 → 写 sys_ap
  protected virtual task collect_port(virtual apb_if vif,
                                      port_kind_enum kind, int index);
    wait (vif.presetn == 1'b1);
    forever begin
      apb_system_txn txn;
      txn = apb_system_txn::type_id::create("txn");
      collect_transaction(vif, txn);
      txn.kind  = kind;
      txn.index = index;
      sys_ap.write(txn);
    end
  endtask

  // 一次完整访问的采样时序（协议相关；默认单拍）
  protected virtual task collect_transaction(virtual apb_if vif,
                                             apb_system_txn txn);
    // pragma custom collect_logic begin
    @(vif.mon_cb);
    txn.timestamp = $time;
    txn.paddr = vif.paddr;
    txn.pwrite = vif.pwrite;
    txn.pwdata = vif.pwdata;
    txn.prdata = vif.prdata;
    txn.pslverr = vif.pslverr;
    // pragma custom collect_logic end
  endtask
endclass : apb_system_monitor
