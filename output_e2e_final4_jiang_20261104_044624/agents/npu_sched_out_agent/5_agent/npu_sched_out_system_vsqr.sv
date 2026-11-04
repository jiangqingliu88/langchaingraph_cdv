// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_system_vsqr.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// System Virtual Sequencer: npu_sched_out_system_vsqr
// ============================================================
// 系统级虚拟 sequencer —— 自身不产生 transaction，只持有**同一协议下**
// 所有 master/slave 子 sequencer 的句柄，供虚拟序列跨端口协调激励。
//
//   npu_sched_out_system_env
//     ├── m_agents[0..N-1]  → npu_sched_out_master_sequencer
//     └── s_agents[0..M-1]  → npu_sched_out_slave_sequencer
//                  ↓ system_env.connect_phase 直接赋值
//   npu_sched_out_system_vsqr.master_sqr[] / .slave_sqr[]
//
// 与 env 级虚拟 sequencer 的分工：
//   那个跨**不同协议**（apb / uart / intr …），句柄是具名成员；
//   这个跨**同一协议的多个实例**（数量由 sys_cfg.num_masters / num_slaves 决定），
//   因此句柄用动态数组——实例数在编译期未知，不能写成具名成员。
//
// 为什么这里没有 system_env 成员：
//   本类与 system_env 会互相引用（env 持有 vsqr 句柄，vsqr 又要知道 env 才能取
//   子 sequencer），彼此都写会形成 SystemVerilog 的循环类型依赖（必须先声明后
//   使用，二者无法都排在前面）。故对齐 env 级 vsqr 的做法：**由上层 env 直接
//   赋值子 sequencer 句柄**，本类不引用 env 类型，依赖方向单向 env → vsqr。

class npu_sched_out_system_vsqr extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils(npu_sched_out_system_vsqr)

  // ═══════════════════════════════════════════════════════════════
  // 1. 子 Sequencer 句柄（由 system_env.connect_phase 赋值）
  // ═══════════════════════════════════════════════════════════════

  npu_sched_out_master_sequencer master_sqr[];
  npu_sched_out_slave_sequencer  slave_sqr[];

  // ═══════════════════════════════════════════════════════════════
  // 2. 配置句柄
  // ═══════════════════════════════════════════════════════════════

  npu_sched_out_system_config sys_cfg;

  // ═══════════════════════════════════════════════════════════════
  // 3. 内部状态
  // ═══════════════════════════════════════════════════════════════

  protected bit bound = 0;          // 句柄是否已绑定（未绑定时用句柄会空指针）
  protected bit debug_enabled = 0;

  // ═══════════════════════════════════════════════════════════════
  // 4. 构造函数
  // ═══════════════════════════════════════════════════════════════

  function new(string name = "npu_sched_out_system_vsqr", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // ═══════════════════════════════════════════════════════════════
  // 5. build_phase —— 取 sys_cfg 定规模
  // ═══════════════════════════════════════════════════════════════
  // 子 sequencer 本体由各 agent 自己创建（agent_master/agent_slave 的
  // build_phase），这里只按数量开辟句柄数组，不重复创建。

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(npu_sched_out_system_config)::get(this, "", "sys_cfg", sys_cfg)) begin
      `uvm_fatal("VSQR_NOCFG",
                 "sys_cfg not found —— system_env 需 set(this, \"system_vsqr\", \"sys_cfg\", sys_cfg)")
    end
    master_sqr = new[sys_cfg.num_masters];
    slave_sqr  = new[sys_cfg.num_slaves];
  endfunction

  // ═══════════════════════════════════════════════════════════════
  // 6. 绑定：由 system_env.connect_phase 调用
  // ═══════════════════════════════════════════════════════════════

  // 标记绑定完成。子句柄数组由 env 直接逐个赋值（见 env 侧注释），
  // 这里只负责置位与校验，因此不需要（也不能）接收 env 句柄。
  virtual function void mark_bound();
    int missing = 0;
    foreach (master_sqr[i]) if (master_sqr[i] == null) missing++;
    foreach (slave_sqr[i])  if (slave_sqr[i] == null)  missing++;
    if (missing > 0)
      `uvm_warning("VSQR_UNBOUND",
                   $sformatf("仍有 %0d 个子 sequencer 未赋值，虚拟序列可能空指针", missing))
    bound = 1;
    if (debug_enabled)
      `uvm_info(get_name(),
                $sformatf("bound %0d master / %0d slave sequencers",
                          master_sqr.size(), slave_sqr.size()), UVM_LOW)
  endfunction

  // ═══════════════════════════════════════════════════════════════
  // 7. 访问器
  // ═══════════════════════════════════════════════════════════════

  function bit is_bound();
    return bound;
  endfunction

  function int num_masters();
    return master_sqr.size();
  endfunction

  function int num_slaves();
    return slave_sqr.size();
  endfunction

  function npu_sched_out_master_sequencer get_master_sqr(int idx = 0);
    if (idx < 0 || idx >= master_sqr.size()) begin
      `uvm_fatal("VSQR_IDX",
                 $sformatf("master idx %0d 越界 [0,%0d)", idx, master_sqr.size()))
    end
    return master_sqr[idx];
  endfunction

  function npu_sched_out_slave_sequencer get_slave_sqr(int idx = 0);
    if (idx < 0 || idx >= slave_sqr.size()) begin
      `uvm_fatal("VSQR_IDX",
                 $sformatf("slave idx %0d 越界 [0,%0d)", idx, slave_sqr.size()))
    end
    return slave_sqr[idx];
  endfunction

  // 全部 master / slave 子配置（虚拟序列按端口改参数时用）
  function void get_master_cfgs(ref npu_sched_out_port_config cfgs[]);
    cfgs = new[master_sqr.size()];
    foreach (master_sqr[i]) if (master_sqr[i] != null) cfgs[i] = master_sqr[i].cfg;
  endfunction

  function void get_slave_cfgs(ref npu_sched_out_port_config cfgs[]);
    cfgs = new[slave_sqr.size()];
    foreach (slave_sqr[i]) if (slave_sqr[i] != null) cfgs[i] = slave_sqr[i].cfg;
  endfunction

  // ═══════════════════════════════════════════════════════════════
  // 8. 协调辅助
  // ═══════════════════════════════════════════════════════════════

  // 等句柄绑定完成（虚拟序列启动前调用，避免对 null 句柄发 sequence）
  virtual task wait_bound(int timeout_ns = 0);
    int waited = 0;
    while (!bound) begin
      if (timeout_ns > 0 && waited >= timeout_ns) begin
        `uvm_fatal("VSQR_UNBOUND",
                   $sformatf("等待绑定超时（%0d ns）：system_env 是否调用了 mark_bound？",
                             timeout_ns))
      end
      #1ns;
      waited++;
    end
  endtask

  // 给所有子 sequencer 下发同一份配置参数（如统一改响应延迟）
  virtual function void broadcast_master_cfg(npu_sched_out_port_config proto);
    foreach (master_sqr[i]) begin
      if (master_sqr[i] == null || master_sqr[i].cfg == null) continue;
      master_sqr[i].cfg.copy(proto);
    end
  endfunction

  virtual function void broadcast_slave_cfg(npu_sched_out_port_config proto);
    foreach (slave_sqr[i]) begin
      if (slave_sqr[i] == null || slave_sqr[i].cfg == null) continue;
      slave_sqr[i].cfg.copy(proto);
    end
  endfunction

  // ═══════════════════════════════════════════════════════════════
  // 9. 调试
  // ═══════════════════════════════════════════════════════════════

  virtual function void set_debug(bit en);
    debug_enabled = en;
  endfunction

  virtual function void dump_state();
    `uvm_info(get_name(),
              $sformatf("system_vsqr: bound=%0d masters=%0d slaves=%0d",
                        bound, master_sqr.size(), slave_sqr.size()), UVM_LOW)
    foreach (master_sqr[i]) if (master_sqr[i] != null)
      `uvm_info(get_name(),
                $sformatf("  master[%0d] = %s", i, master_sqr[i].get_full_name()), UVM_LOW)
    foreach (slave_sqr[i]) if (slave_sqr[i] != null)
      `uvm_info(get_name(),
                $sformatf("  slave[%0d]  = %s", i, slave_sqr[i].get_full_name()), UVM_LOW)
  endfunction

endclass : npu_sched_out_system_vsqr
