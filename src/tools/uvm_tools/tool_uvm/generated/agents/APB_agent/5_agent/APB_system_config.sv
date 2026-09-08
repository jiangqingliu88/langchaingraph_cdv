// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_system_config.sv
//   作者:     -
//   创建时间: 2026-09-07 23:32:17
//   修改时间: 2026-09-07 23:32:17
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// System Config: APB_system_config
// ============================================================

class APB_system_config extends uvm_object;
  `uvm_object_utils(APB_system_config)

  int num_masters = 1;
  int num_slaves  = 1;

  APB_master_config master_cfgs[];
  APB_slave_config  slave_cfgs[];

  int addr_width = 32;
  int data_width = 32;
  int id_width   = 4;

  function new(string name = "APB_system_config");
    super.new(name);
  endfunction

  function void init_config(int m_num = 1, int s_num = 1);
    num_masters = m_num;
    num_slaves  = s_num;
    master_cfgs = new[num_masters];
    slave_cfgs  = new[num_slaves];
    foreach (master_cfgs[i]) begin
      master_cfgs[i] = APB_master_config::type_id::create($sformatf("m_cfg_%0d", i));
      master_cfgs[i].is_active = UVM_ACTIVE;
      master_cfgs[i].addr_width = addr_width;
      master_cfgs[i].data_width = data_width;
    end
    foreach (slave_cfgs[i]) begin
      slave_cfgs[i] = APB_slave_config::type_id::create($sformatf("s_cfg_%0d", i));
      slave_cfgs[i].is_active = UVM_ACTIVE;
      slave_cfgs[i].response_mode = SEQUENCER_DRIVEN;
      slave_cfgs[i].addr_width = addr_width;
      slave_cfgs[i].data_width = data_width;
    end
  endfunction
endclass : APB_system_config
