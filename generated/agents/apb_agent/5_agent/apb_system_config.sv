// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_system_config.sv
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
// System Config: apb_system_config
// ============================================================

class apb_system_config extends uvm_object;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack/config_db 自动化）──
  `uvm_object_utils_begin(apb_system_config)
    `uvm_field_int(num_masters, UVM_DEFAULT)
    `uvm_field_int(num_slaves, UVM_DEFAULT)
    `uvm_field_array_object(master_cfgs, UVM_DEFAULT)
    `uvm_field_array_object(slave_cfgs, UVM_DEFAULT)
  `uvm_object_utils_end

  int num_masters = 1;
  int num_slaves  = 1;
  bit system_monitor_enable =0;
  apb_port_config master_cfgs[];
  apb_port_config  slave_cfgs[];

  function new(string name = "apb_system_config");
    super.new(name);
  endfunction

  function void create_sub_cfgs(int m_num = 1, int s_num = 1);
    num_masters = m_num;
    num_slaves  = s_num;
    master_cfgs = new[num_masters];
    slave_cfgs  = new[num_slaves];
    foreach (master_cfgs[i]) begin
      master_cfgs[i] = apb_port_config::type_id::create($sformatf("m_cfg_%0d", i));
      master_cfgs[i].port_kind = MASTER;
    end
    foreach (slave_cfgs[i]) begin
      slave_cfgs[i] = apb_port_config::type_id::create($sformatf("s_cfg_%0d", i));
      slave_cfgs[i].port_kind = SLAVE;
      slave_cfgs[i].response_mode = SEQUENCER_DRIVEN;
    end
  endfunction
endclass : apb_system_config
