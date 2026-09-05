// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     apb_cons_constraint_policies.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// apb_cons_constraint_policies.sv
// 自动生成的具体策略实现

`include "APB_env_constraint_policy.sv"


// ============================================================
// apb_addr_align: APB 地址 4 字节对齐（组合示例: applies_to 可列多个端口）
// ============================================================
class apb_addr_align_policy extends APB_env_constraint_policy;
  `uvm_object_utils(apb_addr_align_policy)
  

  // align

  int align;




  // apb_master 事务句柄
  APB_master_seq_item apb_master_trans;


  function new(string name = "apb_addr_align_policy");
    super.new(name);
    policy_name = "apb_addr_align";
    priority = 10;
    

    // 初始化参数

    align = 4;


  endfunction
  
  virtual function void apply(ref APB_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 apb_master 事务
    if (!$cast(apb_master_trans, ctx.get_transaction("apb_master"))) begin
      `uvm_warning(get_name(), "Cannot get apb_master transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "apb_addr_align": begin
        // APB 地址对齐（示例策略；applies_to 端口 = apb_master）
        apb_master_trans.paddr = (apb_master_trans.paddr / align) * align;
      end


    endcase
  endfunction
  
  virtual function bit verify(ref APB_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("align=%0d ", align)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 align 参数
    if (params.exists("align"))
      $sscanf(params["align"], "%d", align);

  endfunction
endclass


// ============================================================
// apb_b2b_write: 背靠背写组合（与 addr_align 在 APPLY_ALL 下同时生效）
// ============================================================
class apb_b2b_write_policy extends APB_env_constraint_policy;
  `uvm_object_utils(apb_b2b_write_policy)
  



  // apb_master 事务句柄
  APB_master_seq_item apb_master_trans;


  function new(string name = "apb_b2b_write_policy");
    super.new(name);
    policy_name = "apb_b2b_write";
    priority = 20;
    

  endfunction
  
  virtual function void apply(ref APB_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 apb_master 事务
    if (!$cast(apb_master_trans, ctx.get_transaction("apb_master"))) begin
      `uvm_warning(get_name(), "Cannot get apb_master transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

    endcase
  endfunction
  
  virtual function bit verify(ref APB_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

  endfunction
endclass

