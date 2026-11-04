// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_constraint_policy.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// npu_sched_env_constraint_policy.sv
// 自动生成的约束策略基类

`ifndef NPU_SCHED_ENV_CONSTRAINT_POLICY_SV
`define NPU_SCHED_ENV_CONSTRAINT_POLICY_SV

// 策略上下文
class npu_sched_env_policy_context extends uvm_object;
  `uvm_object_utils(npu_sched_env_policy_context)
  
  // 事务存储

  npu_sched_in_master_seq_item npu_sched_in_trans;

  npu_sched_out_master_seq_item npu_sched_out_trans;

  
  // 元数据
  string scenario_name;
  int iteration;
  int total_iterations;
  int timestamp;
  
  function new(string name = "npu_sched_env_policy_context");
    super.new(name);
  endfunction
  
  // 获取事务
  function uvm_object get_transaction(string name);
    case (name)

      "npu_sched_in": return npu_sched_in_trans;

      "npu_sched_out": return npu_sched_out_trans;

      default: return null;
    endcase
  endfunction
  
  // 设置事务
  function void set_transaction(string name, uvm_object trans);
    case (name)

      "npu_sched_in": begin
        if (!$cast(npu_sched_in_trans, trans))
          `uvm_error("CONTEXT", $sformatf("Cannot cast to npu_sched_in_master_seq_item"))
      end

      "npu_sched_out": begin
        if (!$cast(npu_sched_out_trans, trans))
          `uvm_error("CONTEXT", $sformatf("Cannot cast to npu_sched_out_master_seq_item"))
      end

      default: `uvm_warning("CONTEXT", $sformatf("Unknown transaction: %s", name))
    endcase
  endfunction
  
  // 复制上下文
  function void copy(npu_sched_env_policy_context other);
    this.scenario_name = other.scenario_name;
    this.iteration = other.iteration;
    this.total_iterations = other.total_iterations;
    this.timestamp = other.timestamp;

    this.npu_sched_in_trans = other.npu_sched_in_trans;

    this.npu_sched_out_trans = other.npu_sched_out_trans;

  endfunction
endclass

// 策略基类
class npu_sched_env_constraint_policy extends uvm_object;
  `uvm_object_utils(npu_sched_env_constraint_policy)
  
  string policy_name;
  bit enabled = 1;
  // `priority` 是 SV 关键字 —— 不能当成员名（这些文件以前从没编译过）
  int policy_priority = 100;
  string params[string];
  
  function new(string name = "npu_sched_env_constraint_policy");
    super.new(name);
  endfunction
  
  // 应用约束
  virtual function void apply(ref npu_sched_env_policy_context ctx);
    // 子类实现
  endfunction
  
  // 验证一致性
  virtual function bit verify(ref npu_sched_env_policy_context ctx);
    return 1;
  endfunction
  
  // 获取统计
  virtual function string get_stats();
    return "";
  endfunction
  
  // 解析参数
  // **SV 的 string 没有 `index()` 方法**（那是别的语言的写法学来的）——
  // 只有 len/getc/substr/atoi 这些。这里手写一个查找。
  static function int index_of(string s, string ch, int from);
    for (int i = from; i < s.len(); i++)
      if (s.substr(i, i) == ch)
        return i;
    return -1;
  endfunction

  virtual function void parse_params(string param_str);
    // **SV 要求块内声明先于语句**（不像 C++ 可以随处声明）。原来把
    // `string kv;` / `int eq_pos` 写在语句中间，vlog 直接报
    // "Illegal declaration after the statement" —— 这些文件以前从没编译过。
    int start = 0, stop;
    string kv;
    int eq_pos;
    string key;
    string value;
    do begin
      stop = index_of(param_str, ",", start);
      if (stop == -1)
        kv = param_str.substr(start, param_str.len()-1);
      else
        kv = param_str.substr(start, stop-1);

      eq_pos = index_of(kv, "=", 0);
      if (eq_pos != -1) begin
        key = kv.substr(0, eq_pos-1);
        value = kv.substr(eq_pos+1, kv.len()-1);
        params[key] = value;
      end
      start = stop + 1;
    end while (stop != -1);
  endfunction

  // 子类可覆写；基类默认从 plusargs 的 `<策略名>_PARAMS=` 串解析。
  // **这个方法以前只在子类里调 `super.parse_plusargs()`，基类根本没有它** ——
  // 11 个策略类各自报 "Unresolved reference to 'parse_plusargs'"。
  virtual function void parse_plusargs();
    string s;
    if ($value$plusargs({policy_name, "_PARAMS=%s"}, s))
      parse_params(s);
  endfunction
  
  // `disable` 是 SV 关键字（disable statement）—— 不能当方法名。
  function void disable_policy();
    enabled = 0;
  endfunction
  
  function void enable_policy();
    enabled = 1;
  endfunction
endclass

`endif // NPU_SCHED_ENV_CONSTRAINT_POLICY_SV
