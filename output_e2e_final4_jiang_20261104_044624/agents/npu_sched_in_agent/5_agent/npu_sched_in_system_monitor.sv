// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_in_system_monitor.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// ============================================================
// System Monitor: npu_sched_in_system_monitor
// ============================================================
// 系统级嗅探器：直接观察 npu_sched_in_system_if 上的全部端口实例，
//   不经过 agent —— 所有 agent 均 PASSIVE 时依然能观测整个系统。
//   sys_vif.master_if[i] → kind = MASTER, index = i
//   sys_vif.slave_if[i]  → kind = SLAVE,  index = i
// 由 npu_sched_in_system_config.system_monitor_enable 门控（0 = 不构建采集进程）

// ── 系统级事务：一次协议访问 + 来源标签 {kind, index} ──
class npu_sched_in_system_txn extends uvm_object;

  port_kind_enum kind = MASTER;  // 来源端口类型
  int            index;          // 端口实例下标
  time           timestamp;      // 采样时刻
  bit instr_valid;
  bit [7:0] instr_opcode;
  bit [2:0] instr_type;
  bit [2:0] instr_dtype;
  bit [7:0] instr_tile_id;
  bit [31:0] instr_src_addr;
  bit [31:0] instr_dst_addr;
  bit [1:0] barrier_type;
  bit [1:0] op_priority;

  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack/config_db 自动化）──
  // **必须放在字段声明之后**：这些宏展开成引用各字段的方法体，放在声明之前
  // Questa 判「Undefined variable」（实测：port_config / seq_item 都栽在这儿）。
  `uvm_object_utils_begin(npu_sched_in_system_txn)
    `uvm_field_enum(port_kind_enum, kind, UVM_DEFAULT)
    `uvm_field_int(index, UVM_DEFAULT)
    `uvm_field_int(instr_valid, UVM_DEFAULT)
    `uvm_field_int(instr_opcode, UVM_DEFAULT)
    `uvm_field_int(instr_type, UVM_DEFAULT)
    `uvm_field_int(instr_dtype, UVM_DEFAULT)
    `uvm_field_int(instr_tile_id, UVM_DEFAULT)
    `uvm_field_int(instr_src_addr, UVM_DEFAULT)
    `uvm_field_int(instr_dst_addr, UVM_DEFAULT)
    `uvm_field_int(barrier_type, UVM_DEFAULT)
    `uvm_field_int(op_priority, UVM_DEFAULT)
  `uvm_object_utils_end

  function new(string name = "npu_sched_in_system_txn");
    super.new(name);
  endfunction

endclass : npu_sched_in_system_txn

class npu_sched_in_system_monitor extends uvm_monitor;
  `uvm_component_utils(npu_sched_in_system_monitor)

  virtual npu_sched_in_system_if sys_vif;
  npu_sched_in_system_config  cfg;

  // 统一分析端口：系统内所有端口实例的采样结果（带 {kind, index} 标签）
  uvm_analysis_port #(npu_sched_in_system_txn) sys_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    sys_ap = new("sys_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual npu_sched_in_system_if)::get(this, "", "sys_vif", sys_vif))
      `uvm_fatal("NOVIF", "System interface not set")
    if (!uvm_config_db#(npu_sched_in_system_config)::get(this, "", "cfg", cfg))
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
  protected virtual task collect_port(virtual npu_sched_in_if vif,
                                      port_kind_enum kind, int index);
    wait (vif.rst_n == 1'b1);
    forever begin
      npu_sched_in_system_txn txn;
      txn = npu_sched_in_system_txn::type_id::create("txn");
      collect_transaction(vif, txn);
      txn.kind  = kind;
      txn.index = index;
      sys_ap.write(txn);
    end
  endtask

  // 一次完整访问的采样时序（协议相关；默认单拍）
  protected virtual task collect_transaction(virtual npu_sched_in_if vif,
                                             npu_sched_in_system_txn txn);
    // pragma custom collect_logic begin
    @(vif.mon_cb);
    txn.timestamp = $time;
    txn.instr_valid = vif.instr_valid;
    txn.instr_opcode = vif.instr_opcode;
    txn.instr_type = vif.instr_type;
    txn.instr_dtype = vif.instr_dtype;
    txn.instr_tile_id = vif.instr_tile_id;
    txn.instr_src_addr = vif.instr_src_addr;
    txn.instr_dst_addr = vif.instr_dst_addr;
    txn.barrier_type = vif.barrier_type;
    txn.op_priority = vif.op_priority;
    // pragma custom collect_logic end
  endtask
endclass : npu_sched_in_system_monitor
