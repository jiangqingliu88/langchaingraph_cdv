// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_in_reg_adapter.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Reg Adapter: npu_sched_in_reg_adapter
// ============================================================
// RAL 集成：uvm_reg_bus_op ↔ npu_sched_in_master_seq_item 双向转换。
//
// **按端口名认信号**，不按固定字段名。这里原来是写死 `addr` 的 —— 而 APB 的
// 事务字段叫 `paddr` / `pwdata` / `prdata` / `pslverr`，一个都对不上。
// 后果是 `reg2bus` 只设了个 xact_type：**地址和数据一个字都没驱动**，
// 任何寄存器访问都打到地址 0、写 0；`bus2reg` 也不回填 `rw.data`，
// 读到的永远是空 —— 整套 RAL 是"静默全错"，比直接报错难查得多。
//
// 匹配规则（按端口 dir 分两侧，各找第一个命中；不命中就不生成那一行）：
//   addr  : output 侧名字含 addr    （paddr）
//   we    : output 侧名字含 write   （pwrite）
//   wdata : output 侧名字含 wdata / data  （pwdata）
//   rdata : input  侧名字含 rdata / data  （prdata）
//   err   : input  侧名字含 err     （pslverr）

class npu_sched_in_reg_adapter extends uvm_reg_adapter;
  `uvm_object_utils(npu_sched_in_reg_adapter)

  int m_bytes_per_word = 4;

  function new(string name = "npu_sched_in_reg_adapter");
    super.new(name);
    // **0，不是 1。** 生成的 master driver 不 `put_response` —— 它是**就地**
    // 把读到的数据写回同一条 req（见 driver_master 的 APB 分支）。设成 1 的话
    // UVM 会去响应队列里等一条永远不来的响应，寄存器读直接挂死。
    supports_byte_enable = 0;
    provides_responses   = 0;
  endfunction

  function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
    npu_sched_in_master_seq_item req =
        npu_sched_in_master_seq_item::type_id::create("reg_req");
    req.xact_type = (rw.kind == UVM_READ) ? READ : WRITE;
    req.instr_src_addr = rw.addr;
    return req;
  endfunction

  function void bus2reg(uvm_sequence_item bus_item, ref uvm_reg_bus_op rw);
    npu_sched_in_master_seq_item rsp;
    if (!$cast(rsp, bus_item)) begin
      `uvm_fatal("REG_ADAPTER",
                 "bus2reg 拿到的不是 npu_sched_in_master_seq_item —— 适配器接错总线了")
      return;
    end
    rw.kind = (rsp.xact_type == READ) ? UVM_READ : UVM_WRITE;
    rw.addr = rsp.instr_src_addr;
    rw.status = UVM_IS_OK;
  endfunction
endclass : npu_sched_in_reg_adapter
