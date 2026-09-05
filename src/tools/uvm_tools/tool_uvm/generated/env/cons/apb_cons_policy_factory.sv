// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     apb_cons_policy_factory.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// apb_cons_policy_factory.sv
// 自动生成的策略工厂

`include "APB_env_policy_combinator.sv"

class APB_env_policy_factory;
  static APB_env_constraint_policy policies[string];
  
  // 注册策略
  static function void register_policy(string name, APB_env_constraint_policy policy);
    policies[name] = policy;
  endfunction
  
  // 获取策略
  static function APB_env_constraint_policy get_policy(string name);
    if (policies.exists(name))
      return policies[name];
    else
      return null;
  endfunction
  
  // 创建默认组合器
  static function APB_env_policy_combinator create_default_combinator();
    APB_env_policy_combinator combo = new("combo");
    

    // 添加 apb_addr_align 策略
    apb_addr_align_policy apb_addr_align_p = apb_addr_align_policy::type_id::create("apb_addr_align_p");
    combo.add_policy(apb_addr_align_p);
    

    // 添加 apb_b2b_write 策略
    apb_b2b_write_policy apb_b2b_write_p = apb_b2b_write_policy::type_id::create("apb_b2b_write_p");
    combo.add_policy(apb_b2b_write_p);
    

    return combo;
  endfunction
  
  // 从 plusargs 创建组合器
  static function APB_env_policy_combinator create_from_plusargs();
    APB_env_policy_combinator combo = new("combo");
    string policy_list;
    
    if ($value$plusargs("APB_ENV_POLICY_LIST=%s", policy_list)) begin
      string policies_to_add[$];
      int start = 0, end;
      
      do begin
        end = policy_list.index(",", start);
        if (end == -1)
          policies_to_add.push_back(policy_list.substr(start, policy_list.len()-1));
        else
          policies_to_add.push_back(policy_list.substr(start, end-1));
        start = end + 1;
      end while (end != -1);
      
      foreach (policies_to_add[i]) begin
        APB_env_constraint_policy p = get_policy(policies_to_add[i]);
        if (p != null) begin
          // 创建新实例
          APB_env_constraint_policy new_p;
          $cast(new_p, p.clone());
          combo.add_policy(new_p);
        end
      end
    end else begin
      // 默认添加所有策略
      combo = create_default_combinator();
    end
    
    combo.configure_from_plusargs();
    return combo;
  endfunction
  
  // 从 YAML 创建组合器
  static function APB_env_policy_combinator create_from_yaml(string yaml_file);
    APB_env_policy_combinator combo = new("combo");
    // YAML 解析逻辑
    // ...
    return combo;
  endfunction
  
  // 注册所有策略
  static function void register_all_policies();

    register_policy("apb_addr_align", apb_addr_align_policy::type_id::create("apb_addr_align"));

    register_policy("apb_b2b_write", apb_b2b_write_policy::type_id::create("apb_b2b_write"));

  endfunction
endclass

// 自动注册
initial begin
  APB_env_policy_factory::register_all_policies();
end
