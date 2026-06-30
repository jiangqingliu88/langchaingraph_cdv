// ALU_constraint_constraint_policies.sv
// 自动生成的具体策略实现

`include "ALU_env_constraint_policy.sv"


// ============================================================
// precision_consistency: 精度一致性策略
// ============================================================
class precision_consistency_policy extends ALU_env_constraint_policy;
  `uvm_object_utils(precision_consistency_policy)
  

  // enforce_match

  bit enforce_match;




  // cfg 事务句柄
  ALU_cfg_transaction cfg_trans;

  // weight 事务句柄
  ALU_weight_transaction weight_trans;

  // input 事务句柄
  ALU_input_transaction input_trans;


  function new(string name = "precision_consistency_policy");
    super.new(name);
    policy_name = "precision_consistency";
    priority = 1;
    

    // 初始化参数

    enforce_match = true;


  endfunction
  
  virtual function void apply(ref ALU_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 cfg 事务
    if (!$cast(cfg_trans, ctx.get_transaction("cfg"))) begin
      `uvm_warning(get_name(), "Cannot get cfg transaction")
      return;
    end

    // 获取 weight 事务
    if (!$cast(weight_trans, ctx.get_transaction("weight"))) begin
      `uvm_warning(get_name(), "Cannot get weight transaction")
      return;
    end

    // 获取 input 事务
    if (!$cast(input_trans, ctx.get_transaction("input"))) begin
      `uvm_warning(get_name(), "Cannot get input transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "precision_consistency": begin
        // 精度一致性约束
        if (enforce_match) begin
          weight_trans.precision = cfg_trans.precision;
          input_trans.precision = cfg_trans.precision;
        end
        
        // 根据精度设置数据范围
        case (cfg_trans.precision)
          INT8: begin
            foreach (weight_trans.data[i])
              weight_trans.data[i] inside {[-128:127]};
            foreach (input_trans.data[i])
              input_trans.data[i] inside {[-128:127]};
          end
          INT16: begin
            foreach (weight_trans.data[i])
              weight_trans.data[i] inside {[-32768:32767]};
            foreach (input_trans.data[i])
              input_trans.data[i] inside {[-32768:32767]};
          end
        endcase
      end
      

    endcase
  endfunction
  
  virtual function bit verify(ref ALU_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("enforce_match=%0d ", enforce_match)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 enforce_match 参数
    if (params.exists("enforce_match"))
      $sscanf(params["enforce_match"], "%d", enforce_match);

  endfunction
endclass


// ============================================================
// mem_capacity: 存储容量策略
// ============================================================
class mem_capacity_policy extends ALU_env_constraint_policy;
  `uvm_object_utils(mem_capacity_policy)
  

  // addr_boundary

  int addr_boundary[];




  // weight 事务句柄
  ALU_weight_transaction weight_trans;

  // input 事务句柄
  ALU_input_transaction input_trans;


  function new(string name = "mem_capacity_policy");
    super.new(name);
    policy_name = "mem_capacity";
    priority = 2;
    

    // 初始化参数

    addr_boundary = [4096, 8192, 16384];


  endfunction
  
  virtual function void apply(ref ALU_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 weight 事务
    if (!$cast(weight_trans, ctx.get_transaction("weight"))) begin
      `uvm_warning(get_name(), "Cannot get weight transaction")
      return;
    end

    // 获取 input 事务
    if (!$cast(input_trans, ctx.get_transaction("input"))) begin
      `uvm_warning(get_name(), "Cannot get input transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "mem_capacity": begin
        // 存储容量约束
        int max_addr = addr_boundary[cfg_trans.mem_size];
        
        // 地址不能超出范围
        if (weight_trans.addr >= max_addr)
          weight_trans.addr = weight_trans.addr % max_addr;
        if (input_trans.addr >= max_addr)
          input_trans.addr = input_trans.addr % max_addr;
        
        // 数据数量约束
        int max_cnt = max_addr / 4;
        if (weight_trans.count > max_cnt)
          weight_trans.count = max_cnt;
        if (input_trans.count > max_cnt)
          input_trans.count = max_cnt;
      end
      

    endcase
  endfunction
  
  virtual function bit verify(ref ALU_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("addr_boundary=%0d ", addr_boundary)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 addr_boundary 参数
    if (params.exists("addr_boundary"))
      $sscanf(params["addr_boundary"], "%d", addr_boundary);

  endfunction
endclass


// ============================================================
// data_dependency: 数据依赖策略
// ============================================================
class data_dependency_policy extends ALU_env_constraint_policy;
  `uvm_object_utils(data_dependency_policy)
  

  // dep_type

  string dep_type;


  // pipeline_depth

  int pipeline_depth;




  // weight 事务句柄
  ALU_weight_transaction weight_trans;

  // input 事务句柄
  ALU_input_transaction input_trans;

  // output 事务句柄
  ALU_output_transaction output_trans;


  function new(string name = "data_dependency_policy");
    super.new(name);
    policy_name = "data_dependency";
    priority = 3;
    

    // 初始化参数

    dep_type = "CROSS";


    // 初始化参数

    pipeline_depth = 1;


  endfunction
  
  virtual function void apply(ref ALU_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 weight 事务
    if (!$cast(weight_trans, ctx.get_transaction("weight"))) begin
      `uvm_warning(get_name(), "Cannot get weight transaction")
      return;
    end

    // 获取 input 事务
    if (!$cast(input_trans, ctx.get_transaction("input"))) begin
      `uvm_warning(get_name(), "Cannot get input transaction")
      return;
    end

    // 获取 output 事务
    if (!$cast(output_trans, ctx.get_transaction("output"))) begin
      `uvm_warning(get_name(), "Cannot get output transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "data_dependency": begin
        static ALU_env_policy_context last_ctx[$];
        
        // 数据依赖约束
        case (dep_type)
          "WEIGHT_DEPENDENT": begin
            input_trans.count = weight_trans.count;
          end
          "INPUT_DEPENDENT": begin
            weight_trans.count = input_trans.count;
          end
          "CROSS_DEPENDENT": begin
            int min_cnt = (weight_trans.count < input_trans.count) ? 
                           weight_trans.count : input_trans.count;
            weight_trans.count = min_cnt;
            input_trans.count = min_cnt;
          end
        endcase
        
        // 输出数量等于输入数量
        output_trans.count = input_trans.count;
        
        // 流水线依赖
        if (pipeline_depth > 0 && last_ctx.size() >= pipeline_depth) begin
          ALU_env_policy_context prev_ctx = last_ctx[0];
          // 从上次输出获取依赖数据
          // input_trans.data[0] = prev_ctx.output_trans.data[prev_ctx.output_trans.count-1];
        end
        
        // 保存当前上下文
        last_ctx.push_back(ctx);
        while (last_ctx.size() > pipeline_depth + 1)
          last_ctx.pop_front();
      end
      

    endcase
  endfunction
  
  virtual function bit verify(ref ALU_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("dep_type=%0d ", dep_type)};

    stats = {stats, $sformatf("pipeline_depth=%0d ", pipeline_depth)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 dep_type 参数
    if (params.exists("dep_type"))
      $sscanf(params["dep_type"], "%d", dep_type);

    // 解析 pipeline_depth 参数
    if (params.exists("pipeline_depth"))
      $sscanf(params["pipeline_depth"], "%d", pipeline_depth);

  endfunction
endclass


// ============================================================
// boundary_overflow: 边界溢出策略
// ============================================================
class boundary_overflow_policy extends ALU_env_constraint_policy;
  `uvm_object_utils(boundary_overflow_policy)
  

  // boundary_type

  string boundary_type;




  // weight 事务句柄
  ALU_weight_transaction weight_trans;

  // input 事务句柄
  ALU_input_transaction input_trans;


  function new(string name = "boundary_overflow_policy");
    super.new(name);
    policy_name = "boundary_overflow";
    priority = 4;
    

    // 初始化参数

    boundary_type = "NORMAL";


  endfunction
  
  virtual function void apply(ref ALU_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 weight 事务
    if (!$cast(weight_trans, ctx.get_transaction("weight"))) begin
      `uvm_warning(get_name(), "Cannot get weight transaction")
      return;
    end

    // 获取 input 事务
    if (!$cast(input_trans, ctx.get_transaction("input"))) begin
      `uvm_warning(get_name(), "Cannot get input transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "boundary_overflow": begin
        case (boundary_type)
          "BOUNDARY": begin
            for (int i = 0; i < weight_trans.count; i++)
              weight_trans.data[i] = (i % 2 == 0) ? -128 : 127;
            for (int i = 0; i < input_trans.count; i++)
              input_trans.data[i] = (i % 2 == 0) ? -128 : 127;
          end
          "OVERFLOW": begin
            for (int i = 0; i < weight_trans.count; i++)
              weight_trans.data[i] = 127;
            for (int i = 0; i < input_trans.count; i++)
              input_trans.data[i] = 127;
          end
          "UNDERFLOW": begin
            for (int i = 0; i < weight_trans.count; i++)
              weight_trans.data[i] = -128;
            for (int i = 0; i < input_trans.count; i++)
              input_trans.data[i] = -128;
          end
        endcase
      end
      

    endcase
  endfunction
  
  virtual function bit verify(ref ALU_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("boundary_type=%0d ", boundary_type)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 boundary_type 参数
    if (params.exists("boundary_type"))
      $sscanf(params["boundary_type"], "%d", boundary_type);

  endfunction
endclass


// ============================================================
// compute_mode: 计算模式策略
// ============================================================
class compute_mode_policy extends ALU_env_constraint_policy;
  `uvm_object_utils(compute_mode_policy)
  

  // profiles

  int profiles[];




  // cfg 事务句柄
  ALU_cfg_transaction cfg_trans;

  // weight 事务句柄
  ALU_weight_transaction weight_trans;

  // input 事务句柄
  ALU_input_transaction input_trans;

  // output 事务句柄
  ALU_output_transaction output_trans;


  function new(string name = "compute_mode_policy");
    super.new(name);
    policy_name = "compute_mode";
    priority = 5;
    

    // 初始化参数

    profiles = [];


  endfunction
  
  virtual function void apply(ref ALU_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 cfg 事务
    if (!$cast(cfg_trans, ctx.get_transaction("cfg"))) begin
      `uvm_warning(get_name(), "Cannot get cfg transaction")
      return;
    end

    // 获取 weight 事务
    if (!$cast(weight_trans, ctx.get_transaction("weight"))) begin
      `uvm_warning(get_name(), "Cannot get weight transaction")
      return;
    end

    // 获取 input 事务
    if (!$cast(input_trans, ctx.get_transaction("input"))) begin
      `uvm_warning(get_name(), "Cannot get input transaction")
      return;
    end

    // 获取 output 事务
    if (!$cast(output_trans, ctx.get_transaction("output"))) begin
      `uvm_warning(get_name(), "Cannot get output transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "compute_mode": begin
        case (cfg_trans.compute_op)
          LINEAR: begin
            foreach (weight_trans.data[i])
              weight_trans.data[i] inside {[-10:10]};
            foreach (input_trans.data[i])
              input_trans.data[i] inside {[-100:100]};
          end
          RELU: begin
            foreach (weight_trans.data[i])
              weight_trans.data[i] inside {[0:1]};
            foreach (input_trans.data[i])
              input_trans.data[i] inside {[-50:200]};
          end
          POOLING: begin
            foreach (weight_trans.data[i])
              weight_trans.data[i] inside {[1:10]};
            foreach (input_trans.data[i])
              input_trans.data[i] inside {[0:255]};
          end
        endcase
        
        // 计算输出
        output_trans.compute_op = cfg_trans.compute_op;
        // output_trans.compute_from_input(input_trans, weight_trans);
      end
      

    endcase
  endfunction
  
  virtual function bit verify(ref ALU_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("profiles=%0d ", profiles)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 profiles 参数
    if (params.exists("profiles"))
      $sscanf(params["profiles"], "%d", profiles);

  endfunction
endclass


// ============================================================
// concurrent_access: 并发访问策略
// ============================================================
class concurrent_access_policy extends ALU_env_constraint_policy;
  `uvm_object_utils(concurrent_access_policy)
  

  // num_ports

  int num_ports;


  // conflict_prob

  real conflict_prob;




  // weight 事务句柄
  ALU_weight_transaction weight_trans;

  // input 事务句柄
  ALU_input_transaction input_trans;


  function new(string name = "concurrent_access_policy");
    super.new(name);
    policy_name = "concurrent_access";
    priority = 6;
    

    // 初始化参数

    num_ports = 4;


    // 初始化参数

    conflict_prob = 0.1;


  endfunction
  
  virtual function void apply(ref ALU_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 weight 事务
    if (!$cast(weight_trans, ctx.get_transaction("weight"))) begin
      `uvm_warning(get_name(), "Cannot get weight transaction")
      return;
    end

    // 获取 input 事务
    if (!$cast(input_trans, ctx.get_transaction("input"))) begin
      `uvm_warning(get_name(), "Cannot get input transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "concurrent_access": begin
        static int current_port = 0;
        
        // 端口分配
        input_trans.addr = (input_trans.addr & ~3) | current_port;
        weight_trans.addr = (weight_trans.addr & ~3) | current_port;
        
        current_port = (current_port + 1) % num_ports;
        
        // 冲突概率
        if ($urandom_range(0, 100) < conflict_prob * 100) begin
          weight_trans.addr = input_trans.addr;
          `uvm_warning(get_name(), "Address conflict generated")
        end
      end
      

    endcase
  endfunction
  
  virtual function bit verify(ref ALU_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("num_ports=%0d ", num_ports)};

    stats = {stats, $sformatf("conflict_prob=%0d ", conflict_prob)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 num_ports 参数
    if (params.exists("num_ports"))
      $sscanf(params["num_ports"], "%d", num_ports);

    // 解析 conflict_prob 参数
    if (params.exists("conflict_prob"))
      $sscanf(params["conflict_prob"], "%d", conflict_prob);

  endfunction
endclass


// ============================================================
// power_performance: 功耗性能策略
// ============================================================
class power_performance_policy extends ALU_env_constraint_policy;
  `uvm_object_utils(power_performance_policy)
  

  // power_mode

  string power_mode;




  // cfg 事务句柄
  ALU_cfg_transaction cfg_trans;

  // weight 事务句柄
  ALU_weight_transaction weight_trans;

  // input 事务句柄
  ALU_input_transaction input_trans;


  function new(string name = "power_performance_policy");
    super.new(name);
    policy_name = "power_performance";
    priority = 7;
    

    // 初始化参数

    power_mode = "BALANCED";


  endfunction
  
  virtual function void apply(ref ALU_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 cfg 事务
    if (!$cast(cfg_trans, ctx.get_transaction("cfg"))) begin
      `uvm_warning(get_name(), "Cannot get cfg transaction")
      return;
    end

    // 获取 weight 事务
    if (!$cast(weight_trans, ctx.get_transaction("weight"))) begin
      `uvm_warning(get_name(), "Cannot get weight transaction")
      return;
    end

    // 获取 input 事务
    if (!$cast(input_trans, ctx.get_transaction("input"))) begin
      `uvm_warning(get_name(), "Cannot get input transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      "power_performance": begin
        case (power_mode)
          "LOW_POWER": begin
            cfg_trans.precision = INT8;
            cfg_trans.mem_size = CFG_SIZE_4KB;
            if (weight_trans.count > 10) weight_trans.count = 10;
            if (input_trans.count > 10) input_trans.count = 10;
          end
          "HIGH_PERFORMANCE": begin
            cfg_trans.precision = INT16;
            cfg_trans.mem_size = CFG_SIZE_16KB;
            if (weight_trans.count < 50) weight_trans.count = 50;
            if (input_trans.count < 50) input_trans.count = 50;
          end
          "BALANCED": begin
            cfg_trans.precision = INT8;
            cfg_trans.mem_size = CFG_SIZE_8KB;
          end
        endcase
      end
      

    endcase
  endfunction
  
  virtual function bit verify(ref ALU_env_policy_context ctx);
    // 验证一致性
    return 1;
  endfunction
  
  virtual function string get_stats();
    string stats = "";

    stats = $sformatf("params: ");

    stats = {stats, $sformatf("power_mode=%0d ", power_mode)};


    return stats;
  endfunction
  
  virtual function void parse_plusargs();
    super.parse_plusargs();

    // 解析 power_mode 参数
    if (params.exists("power_mode"))
      $sscanf(params["power_mode"], "%d", power_mode);

  endfunction
endclass

