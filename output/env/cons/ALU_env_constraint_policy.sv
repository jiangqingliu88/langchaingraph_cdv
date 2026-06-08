// ALU_constraint_constraint_policy.sv
// 自动生成的约束策略基类

`ifndef ALU_ENV_CONSTRAINT_POLICY_SV
`define ALU_ENV_CONSTRAINT_POLICY_SV

// 策略上下文
class ALU_env_policy_context extends uvm_object;
  `uvm_object_utils(ALU_env_policy_context)
  
  // 事务存储

  ALU_cfg_transaction cfg_trans;

  ALU_weight_transaction weight_trans;

  ALU_input_transaction input_trans;

  ALU_output_transaction output_trans;

  
  // 元数据
  string scenario_name;
  int iteration;
  int total_iterations;
  int timestamp;
  
  function new(string name = "ALU_env_policy_context");
    super.new(name);
  endfunction
  
  // 获取事务
  function uvm_object get_transaction(string name);
    case (name)

      "cfg": return cfg_trans;

      "weight": return weight_trans;

      "input": return input_trans;

      "output": return output_trans;

      default: return null;
    endcase
  endfunction
  
  // 设置事务
  function void set_transaction(string name, uvm_object trans);
    case (name)

      "cfg": begin
        if (!$cast(cfg_trans, trans))
          `uvm_error("CONTEXT", $sformatf("Cannot cast to ALU_cfg_transaction"))
      end

      "weight": begin
        if (!$cast(weight_trans, trans))
          `uvm_error("CONTEXT", $sformatf("Cannot cast to ALU_weight_transaction"))
      end

      "input": begin
        if (!$cast(input_trans, trans))
          `uvm_error("CONTEXT", $sformatf("Cannot cast to ALU_input_transaction"))
      end

      "output": begin
        if (!$cast(output_trans, trans))
          `uvm_error("CONTEXT", $sformatf("Cannot cast to ALU_output_transaction"))
      end

      default: `uvm_warning("CONTEXT", $sformatf("Unknown transaction: %s", name))
    endcase
  endfunction
  
  // 复制上下文
  function void copy(ALU_env_policy_context other);
    this.scenario_name = other.scenario_name;
    this.iteration = other.iteration;
    this.total_iterations = other.total_iterations;
    this.timestamp = other.timestamp;

    this.cfg_trans = other.cfg_trans;

    this.weight_trans = other.weight_trans;

    this.input_trans = other.input_trans;

    this.output_trans = other.output_trans;

  endfunction
endclass

// 策略基类
class ALU_env_constraint_policy extends uvm_object;
  `uvm_object_utils(ALU_env_constraint_policy)
  
  string policy_name;
  bit enabled = 1;
  int priority = 100;
  string params[string];
  
  function new(string name = "ALU_env_constraint_policy");
    super.new(name);
  endfunction
  
  // 应用约束
  virtual function void apply(ref ALU_env_policy_context ctx);
    // 子类实现
  endfunction
  
  // 验证一致性
  virtual function bit verify(ref ALU_env_policy_context ctx);
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

`endif // ALU_ENV_CONSTRAINT_POLICY_SV