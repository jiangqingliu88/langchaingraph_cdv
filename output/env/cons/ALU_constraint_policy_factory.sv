// ALU_constraint_policy_factory.sv
// 自动生成的策略工厂

`include "ALU_env_policy_combinator.sv"

class ALU_env_policy_factory;
  static ALU_env_constraint_policy policies[string];
  
  // 注册策略
  static function void register_policy(string name, ALU_env_constraint_policy policy);
    policies[name] = policy;
  endfunction
  
  // 获取策略
  static function ALU_env_constraint_policy get_policy(string name);
    if (policies.exists(name))
      return policies[name];
    else
      return null;
  endfunction
  
  // 创建默认组合器
  static function ALU_env_policy_combinator create_default_combinator();
    ALU_env_policy_combinator combo = new("combo");
    

    // 添加 precision_consistency 策略
    precision_consistency_policy precision_consistency_p = precision_consistency_policy::type_id::create("precision_consistency_p");
    combo.add_policy(precision_consistency_p);
    

    // 添加 mem_capacity 策略
    mem_capacity_policy mem_capacity_p = mem_capacity_policy::type_id::create("mem_capacity_p");
    combo.add_policy(mem_capacity_p);
    

    // 添加 data_dependency 策略
    data_dependency_policy data_dependency_p = data_dependency_policy::type_id::create("data_dependency_p");
    combo.add_policy(data_dependency_p);
    

    // 添加 boundary_overflow 策略
    boundary_overflow_policy boundary_overflow_p = boundary_overflow_policy::type_id::create("boundary_overflow_p");
    combo.add_policy(boundary_overflow_p);
    

    // 添加 compute_mode 策略
    compute_mode_policy compute_mode_p = compute_mode_policy::type_id::create("compute_mode_p");
    combo.add_policy(compute_mode_p);
    

    // 添加 concurrent_access 策略
    concurrent_access_policy concurrent_access_p = concurrent_access_policy::type_id::create("concurrent_access_p");
    combo.add_policy(concurrent_access_p);
    

    // 添加 power_performance 策略
    power_performance_policy power_performance_p = power_performance_policy::type_id::create("power_performance_p");
    combo.add_policy(power_performance_p);
    

    return combo;
  endfunction
  
  // 从 plusargs 创建组合器
  static function ALU_env_policy_combinator create_from_plusargs();
    ALU_env_policy_combinator combo = new("combo");
    string policy_list;
    
    if ($value$plusargs("ALU_ENV_POLICY_LIST=%s", policy_list)) begin
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
        ALU_env_constraint_policy p = get_policy(policies_to_add[i]);
        if (p != null) begin
          // 创建新实例
          ALU_env_constraint_policy new_p;
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
  static function ALU_env_policy_combinator create_from_yaml(string yaml_file);
    ALU_env_policy_combinator combo = new("combo");
    // YAML 解析逻辑
    // ...
    return combo;
  endfunction
  
  // 注册所有策略
  static function void register_all_policies();

    register_policy("precision_consistency", precision_consistency_policy::type_id::create("precision_consistency"));

    register_policy("mem_capacity", mem_capacity_policy::type_id::create("mem_capacity"));

    register_policy("data_dependency", data_dependency_policy::type_id::create("data_dependency"));

    register_policy("boundary_overflow", boundary_overflow_policy::type_id::create("boundary_overflow"));

    register_policy("compute_mode", compute_mode_policy::type_id::create("compute_mode"));

    register_policy("concurrent_access", concurrent_access_policy::type_id::create("concurrent_access"));

    register_policy("power_performance", power_performance_policy::type_id::create("power_performance"));

  endfunction
endclass

// 自动注册
initial begin
  ALU_env_policy_factory::register_all_policies();
end