// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     APB_env_reg_smoke_seq.sv
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
// Reg Smoke Sequence: APB_env_reg_smoke_seq
// 寄存器自检（P1-3）：写 → 读回 → 比对，每个寄存器逐一遍历
// 前提: register_model 已配置（env build_phase 创建 + config_db set reg_model）
// 用法: 在 vsqr 上启动，或作为 configure_phase 配置序列
// ============================================================

class APB_env_reg_smoke_seq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(APB_env_reg_smoke_seq)

  uvm_reg_block reg_model;
  int mismatch_count = 0;
  int checked_count  = 0;

  function new(string name = "APB_env_reg_smoke_seq");
    super.new(name);
  endfunction

  virtual task body();
    uvm_reg regs[$];
    uvm_status_e status;
    uvm_reg_data_t wdata, rdata;

    if (!uvm_config_db#(uvm_reg_block)::get(get_sequencer(), "", "reg_model", reg_model))
      `uvm_fatal("REG_SMOKE", "reg_model not found in config_db")

    `uvm_info(get_name(), $sformatf("Reg smoke start: %s", reg_model.get_full_name()), UVM_LOW)

    reg_model.reset("HARD");

    reg_model.get_registers(regs);
    foreach (regs[i]) begin
      // 只对可写寄存器做写读回比对（read-only 寄存器只读）
      if (regs[i].get_rights() != "RW") begin
        `uvm_info(get_name(), $sformatf("skip %s (rights=%s)",
                   regs[i].get_name(), regs[i].get_rights()), UVM_HIGH)
        continue;
      end
      wdata = $urandom();
      regs[i].write(status, wdata);
      regs[i].read(status, rdata);
      checked_count++;
      if (wdata !== rdata) begin
        mismatch_count++;
        `uvm_error(get_name(), $sformatf("reg %s mismatch: w=0x%0h r=0x%0h",
                   regs[i].get_name(), wdata, rdata))
      end
    end

    `uvm_info(get_name(), $sformatf("Reg smoke done: checked=%0d mismatch=%0d",
               checked_count, mismatch_count), UVM_NONE)
  endtask
endclass : APB_env_reg_smoke_seq
