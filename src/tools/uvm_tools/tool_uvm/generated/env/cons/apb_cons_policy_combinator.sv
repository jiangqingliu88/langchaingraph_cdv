// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     apb_cons_policy_combinator.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// apb_cons_policy_combinator.sv
// 自动生成的策略组合器

`include "APB_env_constraint_policies.sv"

class APB_env_policy_combinator extends APB_env_constraint_policy;
  `uvm_object_utils(APB_env_policy_combinator)
  
  // 策略列表
  APB_env_constraint_policy policies[$];
  
  // 组合模式
  typedef enum {

    APPLY_ALL,

    APPLY_WEIGHTED,

    APPLY_FIRST_MATCH,

    APPLY_SEQUENTIAL,

    APPLY_CHAIN

  } apply_mode_e;
  
  apply_mode_e apply_mode = APPLY_ALL;
  
  // 统计
  int apply_count[$];
  int verify_count[$];
  
  function void add_policy(APB_env_constraint_policy policy);
    policies.push_back(policy);
    apply_count.push_back(0);
    verify_count.push_back(0);
  endfunction
  
  function void remove_policy(string policy_name);
    for (int i = 0; i < policies.size(); i++) begin
      if (policies[i].policy_name == policy_name) begin
        policies.delete(i);
        apply_count.delete(i);
        verify_count.delete(i);
        break;
      end
    end
  endfunction
  
  function APB_env_constraint_policy get_policy(string policy_name);
    foreach (policies[i]) begin
      if (policies[i].policy_name == policy_name)
        return policies[i];
    end
    return null;
  endfunction
  
  virtual function void apply(ref APB_env_policy_context ctx);
    // 按优先级排序
    sort_by_priority();
    
    case (apply_mode)
      APPLY_ALL: begin
        for (int i = 0; i < policies.size(); i++) begin
          if (policies[i].enabled) begin
            policies[i].apply(ctx);
            apply_count[i]++;
          end
        end
      end
      
      APPLY_WEIGHTED: begin
        int idx = select_weighted();
        if (idx >= 0) begin
          policies[idx].apply(ctx);
          apply_count[idx]++;
        end
      end
      
      APPLY_FIRST_MATCH: begin
        for (int i = 0; i < policies.size(); i++) begin
          if (policies[i].enabled && should_apply(i, ctx)) begin
            policies[i].apply(ctx);
            apply_count[i]++;
            break;
          end
        end
      end
      
      APPLY_SEQUENTIAL: begin
        APB_env_policy_context temp_ctx = new();
        temp_ctx.copy(ctx);
        
        for (int i = 0; i < policies.size(); i++) begin
          if (policies[i].enabled) begin
            policies[i].apply(temp_ctx);
            apply_count[i]++;
          end
        end
        
        ctx.copy(temp_ctx);
      end
      
      APPLY_CHAIN: begin
        APB_env_policy_context chain_ctx = new();
        chain_ctx.copy(ctx);
        
        for (int i = 0; i < policies.size(); i++) begin
          if (policies[i].enabled) begin
            APB_env_policy_context output_ctx = new();
            output_ctx.copy(chain_ctx);
            policies[i].apply(output_ctx);
            apply_count[i]++;
            chain_ctx = output_ctx;
          end
        end
        
        ctx.copy(chain_ctx);
      end
    endcase
  endfunction
  
  virtual function bit verify(ref APB_env_policy_context ctx);
    bit result = 1;
    for (int i = 0; i < policies.size(); i++) begin
      if (policies[i].enabled) begin
        if (!policies[i].verify(ctx)) begin
          `uvm_warning(get_name(), $sformatf("Policy %s verification failed",
                     policies[i].policy_name))
          result = 0;
        end
        verify_count[i]++;
      end
    end
    return result;
  endfunction
  
  function void sort_by_priority();
    for (int i = 0; i < policies.size() - 1; i++) begin
      for (int j = 0; j < policies.size() - i - 1; j++) begin
        if (policies[j].priority > policies[j+1].priority) begin
          // 交换策略
          APB_env_constraint_policy temp_p = policies[j];
          policies[j] = policies[j+1];
          policies[j+1] = temp_p;
          
          // 交换统计
          int temp_c = apply_count[j];
          apply_count[j] = apply_count[j+1];
          apply_count[j+1] = temp_c;
          
          temp_c = verify_count[j];
          verify_count[j] = verify_count[j+1];
          verify_count[j+1] = temp_c;
        end
      end
    end
  endfunction
  
  function int select_weighted();
    int total_weight = 0;
    for (int i = 0; i < policies.size(); i++) begin
      if (policies[i].enabled)
        total_weight += policies[i].priority;
    end
    
    if (total_weight == 0) return -1;
    
    int rand_weight = $urandom_range(0, total_weight - 1);
    int acc = 0;
    
    for (int i = 0; i < policies.size(); i++) begin
      if (policies[i].enabled) begin
        acc += policies[i].priority;
        if (rand_weight < acc)
          return i;
      end
    end
    
    return -1;
  endfunction
  
  virtual function bit should_apply(int idx, ref APB_env_policy_context ctx);
    // 可以基于上下文判断是否应用
    return 1;
  endfunction
  
  function void configure_from_plusargs();
    string mode_str;
    if ($value$plusargs("APB_ENV_POLICY_MODE=%s", mode_str)) begin
      case (mode_str)

        "APPLY_ALL": apply_mode = APPLY_ALL;

        "APPLY_WEIGHTED": apply_mode = APPLY_WEIGHTED;

        "APPLY_FIRST_MATCH": apply_mode = APPLY_FIRST_MATCH;

        "APPLY_SEQUENTIAL": apply_mode = APPLY_SEQUENTIAL;

        "APPLY_CHAIN": apply_mode = APPLY_CHAIN;

      endcase
    end
    
    for (int i = 0; i < policies.size(); i++) begin
      policies[i].parse_plusargs();
      
      string disable_arg = {"NO_", policies[i].policy_name};
      if ($test$plusargs(disable_arg))
        policies[i].disable();
      
      string enable_arg = {"ENABLE_", policies[i].policy_name};
      if ($test$plusargs(enable_arg))
        policies[i].enable();
      
      string priority_arg = {policies[i].policy_name, "_PRIORITY=%d"};
      int new_priority;
      if ($value$plusargs(priority_arg, new_priority))
        policies[i].priority = new_priority;
    end
  endfunction
  
  function void report_stats();
    `uvm_info(get_name(), "========================================", UVM_NONE)
    `uvm_info(get_name(), "Policy Statistics:", UVM_NONE)
    for (int i = 0; i < policies.size(); i++) begin
      `uvm_info(get_name(), $sformatf("  %s: apply=%0d, verify=%0d, %s",
                 policies[i].policy_name, 
                 apply_count[i], 
                 verify_count[i],
                 policies[i].get_stats()), UVM_NONE)
    end
    `uvm_info(get_name(), "========================================", UVM_NONE)
  endfunction
endclass
