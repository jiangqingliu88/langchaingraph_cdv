// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_constraint_policy.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// apb_cons_constraint_policy.sv
// 自动生成的约束策略基类

`ifndef APB_ENV_CONSTRAINT_POLICY_SV
`define APB_ENV_CONSTRAINT_POLICY_SV

// 策略上下文
class APB_env_policy_context extends uvm_object;
  `uvm_object_utils(APB_env_policy_context)
  
  // 事务存储

  APB_master_seq_item apb_master_trans;

  
  // 元数据
  string scenario_name;
  int iteration;
  int total_iterations;
  int timestamp;
  
  function new(string name = "APB_env_policy_context");
    super.new(name);
  endfunction
  
  // 获取事务
  function uvm_object get_transaction(string name);
    case (name)

      "apb_master": return apb_master_trans;

      default: return null;
    endcase
  endfunction
  
  // 设置事务
  function void set_transaction(string name, uvm_object trans);
    case (name)

      "apb_master": begin
        if (!$cast(apb_master_trans, trans))
          `uvm_error("CONTEXT", $sformatf("Cannot cast to APB_master_seq_item"))
      end

      default: `uvm_warning("CONTEXT", $sformatf("Unknown transaction: %s", name))
    endcase
  endfunction
  
  // 复制上下文
  function void copy(APB_env_policy_context other);
    this.scenario_name = other.scenario_name;
    this.iteration = other.iteration;
    this.total_iterations = other.total_iterations;
    this.timestamp = other.timestamp;

    this.apb_master_trans = other.apb_master_trans;

  endfunction
endclass

// 策略基类
class APB_env_constraint_policy extends uvm_object;
  `uvm_object_utils(APB_env_constraint_policy)
  
  string policy_name;
  bit enabled = 1;
  int priority = 100;
  string params[string];
  
  function new(string name = "APB_env_constraint_policy");
    super.new(name);
  endfunction
  
  // 应用约束
  virtual function void apply(ref APB_env_policy_context ctx);
    // 子类实现
  endfunction
  
  // 验证一致性
  virtual function bit verify(ref APB_env_policy_context ctx);
    return 1;
  endfunction
  
  // 获取统计
  virtual function string get_stats();
    return "";
  endfunction
  
  // 解析参数
  virtual function void parse_params(string param_str);
    int start = 0, end;
    do begin
      end = param_str.index(",", start);
      string kv;
      if (end == -1)
        kv = param_str.substr(start, param_str.len()-1);
      else
        kv = param_str.substr(start, end-1);
      
      int eq_pos = kv.index("=");
      if (eq_pos != -1) begin
        string key = kv.substr(0, eq_pos-1);
        string value = kv.substr(eq_pos+1, kv.len()-1);
        params[key] = value;
      end
      start = end + 1;
    end while (end != -1);
  endfunction
  
  function void disable();
    enabled = 0;
  endfunction
  
  function void enable();
    enabled = 1;
  endfunction
endclass

`endif // APB_ENV_CONSTRAINT_POLICY_SV
