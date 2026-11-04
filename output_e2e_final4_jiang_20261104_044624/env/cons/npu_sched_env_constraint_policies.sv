// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_constraint_policies.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// npu_sched_env_constraint_policies.sv
// 自动生成的具体策略实现

`include "npu_sched_env_constraint_policy.sv"


// ============================================================
// p_th_b01_directed: 批次1 基础发射（D → APPLY_FIRST_MATCH） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b01_directed_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b01_directed_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b01_directed_policy");
    super.new(name);
    policy_name = "p_th_b01_directed";
    policy_priority = 10;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b02_random: 批次2 指令类型（RND → APPLY_WEIGHTED） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b02_random_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b02_random_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b02_random_policy");
    super.new(name);
    policy_name = "p_th_b02_random";
    policy_priority = 10;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **模型编译出来的约束**（`build_constraint` 的 `assignments`）：
      // 只对声明了 `stimulus.field` 的维度生成 —— 观测型维度没有输入引脚，
      // 给它们编约束就是造假。`cycle` 让每个合法取值都轮到；`random` 用于 RND。
      "p_th_b02_random": begin

        // npu_sched_in.instr_type ← random
        //（合法取值：0, 1, 2, 3）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 3))


            0: npu_sched_in_trans.instr_type = 0;

            1: npu_sched_in_trans.instr_type = 1;

            2: npu_sched_in_trans.instr_type = 2;

            3: npu_sched_in_trans.instr_type = 3;

          endcase
        end

      end


      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b03_random: 批次3 数据类型（RND → APPLY_WEIGHTED） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b03_random_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b03_random_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b03_random_policy");
    super.new(name);
    policy_name = "p_th_b03_random";
    policy_priority = 10;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **模型编译出来的约束**（`build_constraint` 的 `assignments`）：
      // 只对声明了 `stimulus.field` 的维度生成 —— 观测型维度没有输入引脚，
      // 给它们编约束就是造假。`cycle` 让每个合法取值都轮到；`random` 用于 RND。
      "p_th_b03_random": begin

        // npu_sched_in.instr_dtype ← random
        //（合法取值：0, 1, 2, 3）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 3))


            0: npu_sched_in_trans.instr_dtype = 0;

            1: npu_sched_in_trans.instr_dtype = 1;

            2: npu_sched_in_trans.instr_dtype = 2;

            3: npu_sched_in_trans.instr_dtype = 3;

          endcase
        end

      end


      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b04_combo: 批次4 依赖探索（G → APPLY_ALL） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b04_combo_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b04_combo_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b04_combo_policy");
    super.new(name);
    policy_name = "p_th_b04_combo";
    policy_priority = 20;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b05_special: 批次5 RAW 停顿（SPCL → APPLY_SEQUENTIAL） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b05_special_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b05_special_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b05_special_policy");
    super.new(name);
    policy_name = "p_th_b05_special";
    policy_priority = 20;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b06_special: 批次6 队列压力（SPCL → APPLY_SEQUENTIAL） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b06_special_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b06_special_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b06_special_policy");
    super.new(name);
    policy_name = "p_th_b06_special";
    policy_priority = 20;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b07_combo: 批次7 多簇并发（G → APPLY_ALL） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b07_combo_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b07_combo_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b07_combo_policy");
    super.new(name);
    policy_name = "p_th_b07_combo";
    policy_priority = 30;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b08_directed: 批次8 操作码覆盖（D → APPLY_FIRST_MATCH） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b08_directed_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b08_directed_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b08_directed_policy");
    super.new(name);
    policy_name = "p_th_b08_directed";
    policy_priority = 30;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **模型编译出来的约束**（`build_constraint` 的 `assignments`）：
      // 只对声明了 `stimulus.field` 的维度生成 —— 观测型维度没有输入引脚，
      // 给它们编约束就是造假。`cycle` 让每个合法取值都轮到；`random` 用于 RND。
      "p_th_b08_directed": begin

        // npu_sched_in.instr_opcode ← cycle
        //（合法取值：0, 1, 2, 3, 4, 5, 6, 7, 8, 9）
        if (npu_sched_in_trans != null) begin

          case (ctx.iteration % 10)


            0: npu_sched_in_trans.instr_opcode = 0;

            1: npu_sched_in_trans.instr_opcode = 1;

            2: npu_sched_in_trans.instr_opcode = 2;

            3: npu_sched_in_trans.instr_opcode = 3;

            4: npu_sched_in_trans.instr_opcode = 4;

            5: npu_sched_in_trans.instr_opcode = 5;

            6: npu_sched_in_trans.instr_opcode = 6;

            7: npu_sched_in_trans.instr_opcode = 7;

            8: npu_sched_in_trans.instr_opcode = 8;

            9: npu_sched_in_trans.instr_opcode = 9;

          endcase
        end

      end


      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b09_random: 批次9 DMA 与计算并发（RND → APPLY_WEIGHTED） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b09_random_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b09_random_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b09_random_policy");
    super.new(name);
    policy_name = "p_th_b09_random";
    policy_priority = 40;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **模型编译出来的约束**（`build_constraint` 的 `assignments`）：
      // 只对声明了 `stimulus.field` 的维度生成 —— 观测型维度没有输入引脚，
      // 给它们编约束就是造假。`cycle` 让每个合法取值都轮到；`random` 用于 RND。
      "p_th_b09_random": begin

        // npu_sched_in.instr_type ← random
        //（合法取值：0, 1, 2, 3）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 3))


            0: npu_sched_in_trans.instr_type = 0;

            1: npu_sched_in_trans.instr_type = 1;

            2: npu_sched_in_trans.instr_type = 2;

            3: npu_sched_in_trans.instr_type = 3;

          endcase
        end

      end


      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b10_random: 批次10 流水重叠（RND → APPLY_WEIGHTED） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b10_random_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b10_random_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b10_random_policy");
    super.new(name);
    policy_name = "p_th_b10_random";
    policy_priority = 40;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **模型编译出来的约束**（`build_constraint` 的 `assignments`）：
      // 只对声明了 `stimulus.field` 的维度生成 —— 观测型维度没有输入引脚，
      // 给它们编约束就是造假。`cycle` 让每个合法取值都轮到；`random` 用于 RND。
      "p_th_b10_random": begin

        // npu_sched_in.instr_opcode ← random
        //（合法取值：0, 1, 2, 3, 4）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 4))


            0: npu_sched_in_trans.instr_opcode = 0;

            1: npu_sched_in_trans.instr_opcode = 1;

            2: npu_sched_in_trans.instr_opcode = 2;

            3: npu_sched_in_trans.instr_opcode = 3;

            4: npu_sched_in_trans.instr_opcode = 4;

          endcase
        end

      end


      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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


// ============================================================
// p_th_b11_random: 批次11 随机混合（RND → APPLY_WEIGHTED） —— case 模型生成，协议参数待填
// ============================================================
class p_th_b11_random_policy extends npu_sched_env_constraint_policy;
  `uvm_object_utils(p_th_b11_random_policy)
  



  // npu_sched_in 事务句柄
  npu_sched_in_master_seq_item npu_sched_in_trans;

  // npu_sched_out 事务句柄
  npu_sched_out_master_seq_item npu_sched_out_trans;


  function new(string name = "p_th_b11_random_policy");
    super.new(name);
    policy_name = "p_th_b11_random";
    policy_priority = 40;
    

  endfunction
  
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    if (!enabled) return;
    

    // 获取 npu_sched_in 事务
    if (!$cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_in transaction")
      return;
    end

    // 获取 npu_sched_out 事务
    if (!$cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"))) begin
      `uvm_warning(get_name(), "Cannot get npu_sched_out transaction")
      return;
    end


    // 应用策略约束
    case (policy_name)

      // **模型编译出来的约束**（`build_constraint` 的 `assignments`）：
      // 只对声明了 `stimulus.field` 的维度生成 —— 观测型维度没有输入引脚，
      // 给它们编约束就是造假。`cycle` 让每个合法取值都轮到；`random` 用于 RND。
      "p_th_b11_random": begin

        // npu_sched_in.instr_type ← random
        //（合法取值：0, 1, 2, 3）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 3))


            0: npu_sched_in_trans.instr_type = 0;

            1: npu_sched_in_trans.instr_type = 1;

            2: npu_sched_in_trans.instr_type = 2;

            3: npu_sched_in_trans.instr_type = 3;

          endcase
        end

        // npu_sched_in.instr_dtype ← random
        //（合法取值：0, 1, 2, 3）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 3))


            0: npu_sched_in_trans.instr_dtype = 0;

            1: npu_sched_in_trans.instr_dtype = 1;

            2: npu_sched_in_trans.instr_dtype = 2;

            3: npu_sched_in_trans.instr_dtype = 3;

          endcase
        end

        // npu_sched_in.instr_opcode ← random
        //（合法取值：0, 1, 2, 3, 4, 5, 6, 7, 8, 9）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 9))


            0: npu_sched_in_trans.instr_opcode = 0;

            1: npu_sched_in_trans.instr_opcode = 1;

            2: npu_sched_in_trans.instr_opcode = 2;

            3: npu_sched_in_trans.instr_opcode = 3;

            4: npu_sched_in_trans.instr_opcode = 4;

            5: npu_sched_in_trans.instr_opcode = 5;

            6: npu_sched_in_trans.instr_opcode = 6;

            7: npu_sched_in_trans.instr_opcode = 7;

            8: npu_sched_in_trans.instr_opcode = 8;

            9: npu_sched_in_trans.instr_opcode = 9;

          endcase
        end

        // npu_sched_in.instr_opcode ← random
        //（合法取值：0, 1, 2, 3, 4, 5）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 5))


            0: npu_sched_in_trans.instr_opcode = 0;

            1: npu_sched_in_trans.instr_opcode = 1;

            2: npu_sched_in_trans.instr_opcode = 2;

            3: npu_sched_in_trans.instr_opcode = 3;

            4: npu_sched_in_trans.instr_opcode = 4;

            5: npu_sched_in_trans.instr_opcode = 5;

          endcase
        end

        // npu_sched_in.instr_opcode ← random
        //（合法取值：0, 1, 2, 3, 4）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 4))


            0: npu_sched_in_trans.instr_opcode = 0;

            1: npu_sched_in_trans.instr_opcode = 1;

            2: npu_sched_in_trans.instr_opcode = 2;

            3: npu_sched_in_trans.instr_opcode = 3;

            4: npu_sched_in_trans.instr_opcode = 4;

          endcase
        end

        // npu_sched_in.op_priority ← random
        //（合法取值：0, 1, 2, 3）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 3))


            0: npu_sched_in_trans.op_priority = 0;

            1: npu_sched_in_trans.op_priority = 1;

            2: npu_sched_in_trans.op_priority = 2;

            3: npu_sched_in_trans.op_priority = 3;

          endcase
        end

        // npu_sched_in.barrier_type ← random
        //（合法取值：0, 1, 2, 3）
        if (npu_sched_in_trans != null) begin

          case ($urandom_range(0, 3))


            0: npu_sched_in_trans.barrier_type = 0;

            1: npu_sched_in_trans.barrier_type = 1;

            2: npu_sched_in_trans.barrier_type = 2;

            3: npu_sched_in_trans.barrier_type = 3;

          endcase
        end

      end


      // **这个 `default` 不能省。** 上面那 8 个分支是**内置策略名**（按验证主题
      // 命名：`precision_consistency` / `mem_capacity` / …，见
      // `semantic_check.BUILTIN_POLICIES`）；而 `build_constraint` 从 case 模型
      // 推出来的名字是**按专题 + 方法**命名的（`p_th_b02_random`）—— 两套一个都
      // 对不上，于是这里的 `case` 会**一个分支都没有**。
      //
      // 而空 `case` 不是"什么都不做"，是**编译错误**：
      //     vlog-13302  Empty case statement. SystemVerilog syntax requires at least one branch.
      // （实测：11 个策略 = 11 条 error，整个 env_pkg 连带编不过。）
      // 所以留一个 default，把"没有约束体"这件事从**编译期**挪到**运行期**，
      // 并且在生成物里说清楚 —— 见 `build_constraint` 的 notes：策略是**结构骨架**，
      // 协议参数是领域知识，模型里没有，只能人补。
      default: begin
        `uvm_info(get_name(),
                  "apply(): 该策略无内置约束体 —— 协议约束待人补（模板只给骨架）",
                  UVM_HIGH)
      end
    endcase
  endfunction
  
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
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

