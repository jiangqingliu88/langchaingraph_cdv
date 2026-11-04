// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_policy_factory.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// npu_sched_env_policy_factory.sv
// 自动生成的策略工厂

`include "npu_sched_env_policy_combinator.sv"

class npu_sched_env_policy_factory;
  static npu_sched_env_constraint_policy policies[string];
  static bit registered = 0;

  // **懒注册**：这些文件被 include 进 env_pkg，而 package 作用域里不能写
  // `initial`（vlog: "near initial: syntax error, expecting class"）。
  // 所以改成第一次真正查表时再注册 —— 语义等价，位置合法。
  static function void ensure_registered();
    if (!registered) begin
      register_all_policies();
      registered = 1;
    end
  endfunction

  // 注册策略
  static function void register_policy(string name, npu_sched_env_constraint_policy policy);
    policies[name] = policy;
  endfunction
  
  // 获取策略
  static function npu_sched_env_constraint_policy get_policy(string name);
    if (policies.exists(name))
      return policies[name];
    else
      return null;
  endfunction
  
  // 创建默认组合器
  static function npu_sched_env_policy_combinator create_default_combinator();
    npu_sched_env_policy_combinator combo = new("combo");
    // **先声明、后语句**：SV 不允许在语句之后声明变量（vlog：
    // "Illegal declaration after the statement"）。原来每个策略的声明
    // 和 `add_policy` 交错写在一起 —— 这些文件以前从没进过编译。

    p_th_b01_directed_policy p_th_b01_directed_p;

    p_th_b02_random_policy p_th_b02_random_p;

    p_th_b03_random_policy p_th_b03_random_p;

    p_th_b04_combo_policy p_th_b04_combo_p;

    p_th_b05_special_policy p_th_b05_special_p;

    p_th_b06_special_policy p_th_b06_special_p;

    p_th_b07_combo_policy p_th_b07_combo_p;

    p_th_b08_directed_policy p_th_b08_directed_p;

    p_th_b09_random_policy p_th_b09_random_p;

    p_th_b10_random_policy p_th_b10_random_p;

    p_th_b11_random_policy p_th_b11_random_p;



    // 添加 p_th_b01_directed 策略
    p_th_b01_directed_p = p_th_b01_directed_policy::type_id::create("p_th_b01_directed_p");
    combo.add_policy(p_th_b01_directed_p);

    // 添加 p_th_b02_random 策略
    p_th_b02_random_p = p_th_b02_random_policy::type_id::create("p_th_b02_random_p");
    combo.add_policy(p_th_b02_random_p);

    // 添加 p_th_b03_random 策略
    p_th_b03_random_p = p_th_b03_random_policy::type_id::create("p_th_b03_random_p");
    combo.add_policy(p_th_b03_random_p);

    // 添加 p_th_b04_combo 策略
    p_th_b04_combo_p = p_th_b04_combo_policy::type_id::create("p_th_b04_combo_p");
    combo.add_policy(p_th_b04_combo_p);

    // 添加 p_th_b05_special 策略
    p_th_b05_special_p = p_th_b05_special_policy::type_id::create("p_th_b05_special_p");
    combo.add_policy(p_th_b05_special_p);

    // 添加 p_th_b06_special 策略
    p_th_b06_special_p = p_th_b06_special_policy::type_id::create("p_th_b06_special_p");
    combo.add_policy(p_th_b06_special_p);

    // 添加 p_th_b07_combo 策略
    p_th_b07_combo_p = p_th_b07_combo_policy::type_id::create("p_th_b07_combo_p");
    combo.add_policy(p_th_b07_combo_p);

    // 添加 p_th_b08_directed 策略
    p_th_b08_directed_p = p_th_b08_directed_policy::type_id::create("p_th_b08_directed_p");
    combo.add_policy(p_th_b08_directed_p);

    // 添加 p_th_b09_random 策略
    p_th_b09_random_p = p_th_b09_random_policy::type_id::create("p_th_b09_random_p");
    combo.add_policy(p_th_b09_random_p);

    // 添加 p_th_b10_random 策略
    p_th_b10_random_p = p_th_b10_random_policy::type_id::create("p_th_b10_random_p");
    combo.add_policy(p_th_b10_random_p);

    // 添加 p_th_b11_random 策略
    p_th_b11_random_p = p_th_b11_random_policy::type_id::create("p_th_b11_random_p");
    combo.add_policy(p_th_b11_random_p);

    return combo;
  endfunction
  
  // 从 plusargs 创建组合器
  static function npu_sched_env_policy_combinator create_from_plusargs();
    npu_sched_env_policy_combinator combo = new("combo");
    string policy_list;
    ensure_registered();
    
    if ($value$plusargs("NPU_SCHED_ENV_POLICY_LIST=%s", policy_list)) begin
      string policies_to_add[$];
      int start = 0, stop;
      
      do begin
        // SV 的 string **没有 index()**（只有 len/getc/substr…）—— 手写查找
        stop = -1;
        for (int _i = start; _i < policy_list.len(); _i++)
          if (policy_list.substr(_i, _i) == ",") begin
            stop = _i;
            break;
          end
        if (stop == -1)
          policies_to_add.push_back(policy_list.substr(start, policy_list.len()-1));
        else
          policies_to_add.push_back(policy_list.substr(start, stop-1));
        start = stop + 1;
      end while (stop != -1);
      
      foreach (policies_to_add[i]) begin
        npu_sched_env_constraint_policy p = get_policy(policies_to_add[i]);
        if (p != null) begin
          // 创建新实例
          npu_sched_env_constraint_policy new_p;
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
  
  // 从**批次**创建组合器（模型给的约束策略名）
  //
  // 名字由批次 test 类在 build_phase 里 `set(null, "*", "batch_policy", ...)`
  // 挂进来（那个名字是 `theme_policy_map` 从 case 模型的 `themes[].method` 推的，
  // 与 `build_constraint` 的 `policies[].name` 同名）。**约束因此由模型说了算** ——
  // 而 `create_from_plusargs()` 那条路是"由回归命令行说了算"。
  //
  // 三种情况，**都不是错误**：
  //   · 取不到 `batch_policy`（根本不在批次 test 下跑）→ 默认组合器；
  //   · 取到空串（这一批的模型没声明 method）→ 默认组合器；
  //   · 取到名字但表里没有（模型与策略生成不同步）→ 默认组合器 + 一句 `uvm_info`。
  // 不报 `uvm_error`：那是"模型没声明"，不是"生成错了"。真要抓不同步，
  // 看生成物里 `batch_policy` 那个名字在 `register_all_policies()` 里有没有。
  static function npu_sched_env_policy_combinator create_from_batch();
    npu_sched_env_policy_combinator combo = new("combo");
    string policy_name = "";
    ensure_registered();

    if (!uvm_config_db#(string)::get(null, "", "batch_policy", policy_name) ||
        policy_name == "") begin
      // 没有模型给的约束 —— 退回默认组合器（全部策略）。
      combo = create_default_combinator();
    end else begin
      npu_sched_env_constraint_policy p = get_policy(policy_name);
      if (p != null) begin
        npu_sched_env_constraint_policy new_p;
        $cast(new_p, p.clone());
        combo.add_policy(new_p);
      end else begin
        `uvm_info("CONS_FACTORY",
                  $sformatf("batch_policy=%s 在策略表里没有 —— 退回默认组合器", policy_name),
                  UVM_LOW)
        combo = create_default_combinator();
      end
    end

    combo.configure_from_plusargs();
    return combo;
  endfunction

  // 从 YAML 创建组合器
  static function npu_sched_env_policy_combinator create_from_yaml(string yaml_file);
    npu_sched_env_policy_combinator combo = new("combo");
    // YAML 解析逻辑
    // ...
    return combo;
  endfunction
  
  // 注册所有策略
  static function void register_all_policies();

    register_policy("p_th_b01_directed", p_th_b01_directed_policy::type_id::create("p_th_b01_directed"));

    register_policy("p_th_b02_random", p_th_b02_random_policy::type_id::create("p_th_b02_random"));

    register_policy("p_th_b03_random", p_th_b03_random_policy::type_id::create("p_th_b03_random"));

    register_policy("p_th_b04_combo", p_th_b04_combo_policy::type_id::create("p_th_b04_combo"));

    register_policy("p_th_b05_special", p_th_b05_special_policy::type_id::create("p_th_b05_special"));

    register_policy("p_th_b06_special", p_th_b06_special_policy::type_id::create("p_th_b06_special"));

    register_policy("p_th_b07_combo", p_th_b07_combo_policy::type_id::create("p_th_b07_combo"));

    register_policy("p_th_b08_directed", p_th_b08_directed_policy::type_id::create("p_th_b08_directed"));

    register_policy("p_th_b09_random", p_th_b09_random_policy::type_id::create("p_th_b09_random"));

    register_policy("p_th_b10_random", p_th_b10_random_policy::type_id::create("p_th_b10_random"));

    register_policy("p_th_b11_random", p_th_b11_random_policy::type_id::create("p_th_b11_random"));

  endfunction
endclass
