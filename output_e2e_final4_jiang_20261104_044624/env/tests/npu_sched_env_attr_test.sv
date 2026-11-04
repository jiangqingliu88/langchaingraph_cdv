// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_attr_test.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Attribute Tests: npu_sched_env_attr_test
//
// **一条 tests: 条目 = 一个 UVM_TEST = 一个属性取值**（维度 × 取值）。
// 属性经 uvm_config_db 传递，键 <key>_int 是机器可读的整型通道 ——
// **取值的中文只出现在注释里，不进 SV 字面量**（字面量会被比较、被打印，
// 掺进非 ASCII 是 locale 隐患；注释没有这个问题）。
//
// 消费方（env / sequence / driver）读 <key>_int 之后按自己的语义解释 ——
// 本模板不知道也不该知道「0/10/50/100 分别代表什么」。

// 生成一条属性 test。两条注意：
//   1. 宏体内**只能用 /* */ 注释** —— `//` 会把行尾的反斜杠一起吃掉，
//      宏定义当场断在那一行（SV 宏的经典坑，别改回去）。
//   2. 宏**不收中文取值**：可读的取值由上面那行 `// ── 属性 test N：… ──`
//      注释承载。把中文当宏参数传，源码里就会出现非 ASCII 的字符串字面量 ——
//      那正是这套设计要避开的。
`define GEN_ATTR_TC(tc_name, tc_base, tc_key, tc_int, tc_field) \
class tc_name extends tc_base; \
    `uvm_component_utils(tc_name) \
    function new(string name, uvm_component parent); \
        super.new(name, parent); \
    endfunction \
    virtual function void build_phase(uvm_phase phase); \
        super.build_phase(phase); \
        /* 本 test 的属性取值见上方注释；机器通道是下面这个 int */ \
        uvm_config_db#(int)::set(this, "*", {tc_key, "_int"}, tc_int); \
        /* 激励通道：绑定了事务字段的维度，把它一并钉在字段名下。 */ \
        /* sequence 读 "<字段>_int" 并约束事务；空的（观测型维度）不设。 */ \
        if (tc_field != "") \
            uvm_config_db#(int)::set(this, "*", {tc_field, "_int"}, tc_int); \
    endfunction \
endclass


// ── 属性 test 1：D_queue = 0 ──
// 测试点：TP-NPUSCH-D_QUEUE-0（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：0 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p0_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p0_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p0_test)
  function new(string name = "npu_sched_env_d_queue_p0_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 0))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 2：D_queue = 1 ──
// 测试点：TP-NPUSCH-D_QUEUE-1（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：1 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p1_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p1_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p1_test)
  function new(string name = "npu_sched_env_d_queue_p1_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 1))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 3：D_queue = 7 ──
// 测试点：TP-NPUSCH-D_QUEUE-7（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：7 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p7_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p7_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p7_test)
  function new(string name = "npu_sched_env_d_queue_p7_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 7))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 4：D_queue = 8 ──
// 测试点：TP-NPUSCH-D_QUEUE-8（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：8 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p8_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p8_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p8_test)
  function new(string name = "npu_sched_env_d_queue_p8_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 8))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 5：D_queue = 15 ──
// 测试点：TP-NPUSCH-D_QUEUE-15（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：15 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p15_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p15_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p15_test)
  function new(string name = "npu_sched_env_d_queue_p15_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 15))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 6：D_queue = 16 ──
// 测试点：TP-NPUSCH-D_QUEUE-16（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：16 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p16_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p16_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p16_test)
  function new(string name = "npu_sched_env_d_queue_p16_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 16))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 7：D_queue = 24 ──
// 测试点：TP-NPUSCH-D_QUEUE-24（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：24 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p24_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p24_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p24_test)
  function new(string name = "npu_sched_env_d_queue_p24_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 24))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 8：D_queue = 25 ──
// 测试点：TP-NPUSCH-D_QUEUE-25（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：25 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p25_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p25_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p25_test)
  function new(string name = "npu_sched_env_d_queue_p25_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 25))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 9：D_queue = 31 ──
// 测试点：TP-NPUSCH-D_QUEUE-31（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：31 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p31_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p31_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p31_test)
  function new(string name = "npu_sched_env_d_queue_p31_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 31))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 10：D_queue = 32 ──
// 测试点：TP-NPUSCH-D_QUEUE-32（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_queue;  /* 取值：32 */
//   if (!uvm_config_db#(int)::get(this, "", "d_queue_int", attr_d_queue))
//     `uvm_fatal("ATTR", "d_queue_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_queue_p32_test
// **后门到达**：该维度没有输入引脚（内部状态/输出），用 `uvm_hdl_force`
// 把层次路径摆到目标值，采完覆盖再 release。签核里会单列为
// `BACKDOOR_HIT`，**不冒充激励覆盖**。
class npu_sched_env_d_queue_p32_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_queue_p32_test)
  function new(string name = "npu_sched_env_d_queue_p32_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual task main_phase(uvm_phase phase);
    phase.raise_objection(this);
    // 复位在 100ns 释放；先让 DUT 稳定几个沿，再强制内部状态
    #(200ns);
    if (!uvm_hdl_force("npu_sched_bench_tb_top.u_npu_sched.queue_level", 32))
      `uvm_error("BACKDOOR", "force 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    // 覆盖探针在时钟沿采样；保持足够长时间确保命中
    #(200ns);
    if (!uvm_hdl_release("npu_sched_bench_tb_top.u_npu_sched.queue_level"))
      `uvm_warning("BACKDOOR", "release 失败：npu_sched_bench_tb_top.u_npu_sched.queue_level")
    #(50ns);
    phase.drop_objection(this);
  endtask
endclass

// ── 属性 test 11：D_type = MAC ──
// 测试点：TP-NPUSCH-D_TYPE-MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_type;  /* 取值：MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_type_int", attr_d_type))
//     `uvm_fatal("ATTR", "d_type_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_type` 承载 —— 本 test 会
//   set("instr_type_int", 0)，master sequence 读它
//   并约束 `instr_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_type_pMAC_test
`GEN_ATTR_TC(npu_sched_env_d_type_pMAC_test, npu_sched_env_gen_test, "d_type", 0, "instr_type")

// ── 属性 test 12：D_type = VECTOR ──
// 测试点：TP-NPUSCH-D_TYPE-VECTOR（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_type;  /* 取值：VECTOR */
//   if (!uvm_config_db#(int)::get(this, "", "d_type_int", attr_d_type))
//     `uvm_fatal("ATTR", "d_type_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_type` 承载 —— 本 test 会
//   set("instr_type_int", 1)，master sequence 读它
//   并约束 `instr_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_type_pVECTOR_test
`GEN_ATTR_TC(npu_sched_env_d_type_pVECTOR_test, npu_sched_env_gen_test, "d_type", 1, "instr_type")

// ── 属性 test 13：D_type = SCALAR ──
// 测试点：TP-NPUSCH-D_TYPE-SCALAR（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_type;  /* 取值：SCALAR */
//   if (!uvm_config_db#(int)::get(this, "", "d_type_int", attr_d_type))
//     `uvm_fatal("ATTR", "d_type_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_type` 承载 —— 本 test 会
//   set("instr_type_int", 2)，master sequence 读它
//   并约束 `instr_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_type_pSCALAR_test
`GEN_ATTR_TC(npu_sched_env_d_type_pSCALAR_test, npu_sched_env_gen_test, "d_type", 2, "instr_type")

// ── 属性 test 14：D_type = DMA ──
// 测试点：TP-NPUSCH-D_TYPE-DMA（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_type;  /* 取值：DMA */
//   if (!uvm_config_db#(int)::get(this, "", "d_type_int", attr_d_type))
//     `uvm_fatal("ATTR", "d_type_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_type` 承载 —— 本 test 会
//   set("instr_type_int", 3)，master sequence 读它
//   并约束 `instr_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_type_pDMA_test
`GEN_ATTR_TC(npu_sched_env_d_type_pDMA_test, npu_sched_env_gen_test, "d_type", 3, "instr_type")

// ── 属性 test 15：D_dtype = INT8 ──
// 测试点：TP-NPUSCH-D_DTYPE-INT8（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dtype;  /* 取值：INT8 */
//   if (!uvm_config_db#(int)::get(this, "", "d_dtype_int", attr_d_dtype))
//     `uvm_fatal("ATTR", "d_dtype_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_dtype` 承载 —— 本 test 会
//   set("instr_dtype_int", 0)，master sequence 读它
//   并约束 `instr_dtype`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_dtype_pINT8_test
`GEN_ATTR_TC(npu_sched_env_d_dtype_pINT8_test, npu_sched_env_gen_test, "d_dtype", 0, "instr_dtype")

// ── 属性 test 16：D_dtype = FP16 ──
// 测试点：TP-NPUSCH-D_DTYPE-FP16（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dtype;  /* 取值：FP16 */
//   if (!uvm_config_db#(int)::get(this, "", "d_dtype_int", attr_d_dtype))
//     `uvm_fatal("ATTR", "d_dtype_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_dtype` 承载 —— 本 test 会
//   set("instr_dtype_int", 1)，master sequence 读它
//   并约束 `instr_dtype`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_dtype_pFP16_test
`GEN_ATTR_TC(npu_sched_env_d_dtype_pFP16_test, npu_sched_env_gen_test, "d_dtype", 1, "instr_dtype")

// ── 属性 test 17：D_dtype = BF16 ──
// 测试点：TP-NPUSCH-D_DTYPE-BF16（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dtype;  /* 取值：BF16 */
//   if (!uvm_config_db#(int)::get(this, "", "d_dtype_int", attr_d_dtype))
//     `uvm_fatal("ATTR", "d_dtype_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_dtype` 承载 —— 本 test 会
//   set("instr_dtype_int", 2)，master sequence 读它
//   并约束 `instr_dtype`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_dtype_pBF16_test
`GEN_ATTR_TC(npu_sched_env_d_dtype_pBF16_test, npu_sched_env_gen_test, "d_dtype", 2, "instr_dtype")

// ── 属性 test 18：D_dtype = FP32 ──
// 测试点：TP-NPUSCH-D_DTYPE-FP32（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dtype;  /* 取值：FP32 */
//   if (!uvm_config_db#(int)::get(this, "", "d_dtype_int", attr_d_dtype))
//     `uvm_fatal("ATTR", "d_dtype_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_dtype` 承载 —— 本 test 会
//   set("instr_dtype_int", 3)，master sequence 读它
//   并约束 `instr_dtype`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_dtype_pFP32_test
`GEN_ATTR_TC(npu_sched_env_d_dtype_pFP32_test, npu_sched_env_gen_test, "d_dtype", 3, "instr_dtype")

// ── 属性 test 19：D_dep = NONE ──
// 测试点：TP-NPUSCH-D_DEP-NONE（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dep;  /* 取值：NONE */
//   if (!uvm_config_db#(int)::get(this, "", "d_dep_int", attr_d_dep))
//     `uvm_fatal("ATTR", "d_dep_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_dep_pNONE_test
`GEN_ATTR_TC(npu_sched_env_d_dep_pNONE_test, npu_sched_env_gen_test, "d_dep", 0, "")

// ── 属性 test 20：D_dep = RAW ──
// 测试点：TP-NPUSCH-D_DEP-RAW（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dep;  /* 取值：RAW */
//   if (!uvm_config_db#(int)::get(this, "", "d_dep_int", attr_d_dep))
//     `uvm_fatal("ATTR", "d_dep_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_dep_pRAW_test
`GEN_ATTR_TC(npu_sched_env_d_dep_pRAW_test, npu_sched_env_gen_test, "d_dep", 1, "")

// ── 属性 test 21：D_dep = WAW ──
// 测试点：TP-NPUSCH-D_DEP-WAW（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dep;  /* 取值：WAW */
//   if (!uvm_config_db#(int)::get(this, "", "d_dep_int", attr_d_dep))
//     `uvm_fatal("ATTR", "d_dep_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_dep_pWAW_test
`GEN_ATTR_TC(npu_sched_env_d_dep_pWAW_test, npu_sched_env_gen_test, "d_dep", 2, "")

// ── 属性 test 22：D_dep = WAR ──
// 测试点：TP-NPUSCH-D_DEP-WAR（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_dep;  /* 取值：WAR */
//   if (!uvm_config_db#(int)::get(this, "", "d_dep_int", attr_d_dep))
//     `uvm_fatal("ATTR", "d_dep_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_dep_pWAR_test
`GEN_ATTR_TC(npu_sched_env_d_dep_pWAR_test, npu_sched_env_gen_test, "d_dep", 3, "")

// ── 属性 test 23：D_unit = MAC ──
// 测试点：TP-NPUSCH-D_UNIT-MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_unit;  /* 取值：MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_unit_int", attr_d_unit))
//     `uvm_fatal("ATTR", "d_unit_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_unit_pMAC_test
`GEN_ATTR_TC(npu_sched_env_d_unit_pMAC_test, npu_sched_env_gen_test, "d_unit", 0, "")

// ── 属性 test 24：D_unit = VECTOR ──
// 测试点：TP-NPUSCH-D_UNIT-VECTOR（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_unit;  /* 取值：VECTOR */
//   if (!uvm_config_db#(int)::get(this, "", "d_unit_int", attr_d_unit))
//     `uvm_fatal("ATTR", "d_unit_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_unit_pVECTOR_test
`GEN_ATTR_TC(npu_sched_env_d_unit_pVECTOR_test, npu_sched_env_gen_test, "d_unit", 1, "")

// ── 属性 test 25：D_unit = SCALAR ──
// 测试点：TP-NPUSCH-D_UNIT-SCALAR（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_unit;  /* 取值：SCALAR */
//   if (!uvm_config_db#(int)::get(this, "", "d_unit_int", attr_d_unit))
//     `uvm_fatal("ATTR", "d_unit_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_unit_pSCALAR_test
`GEN_ATTR_TC(npu_sched_env_d_unit_pSCALAR_test, npu_sched_env_gen_test, "d_unit", 2, "")

// ── 属性 test 26：D_unit = DMA ──
// 测试点：TP-NPUSCH-D_UNIT-DMA（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_unit;  /* 取值：DMA */
//   if (!uvm_config_db#(int)::get(this, "", "d_unit_int", attr_d_unit))
//     `uvm_fatal("ATTR", "d_unit_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_unit_pDMA_test
`GEN_ATTR_TC(npu_sched_env_d_unit_pDMA_test, npu_sched_env_gen_test, "d_unit", 3, "")

// ── 属性 test 27：D_decision = ISSUED ──
// 测试点：TP-NPUSCH-D_DECISION-ISSUED（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_decision;  /* 取值：ISSUED */
//   if (!uvm_config_db#(int)::get(this, "", "d_decision_int", attr_d_decision))
//     `uvm_fatal("ATTR", "d_decision_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_decision_pISSUED_test
`GEN_ATTR_TC(npu_sched_env_d_decision_pISSUED_test, npu_sched_env_gen_test, "d_decision", 0, "")

// ── 属性 test 28：D_decision = STALLED ──
// 测试点：TP-NPUSCH-D_DECISION-STALLED（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_decision;  /* 取值：STALLED */
//   if (!uvm_config_db#(int)::get(this, "", "d_decision_int", attr_d_decision))
//     `uvm_fatal("ATTR", "d_decision_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_decision_pSTALLED_test
`GEN_ATTR_TC(npu_sched_env_d_decision_pSTALLED_test, npu_sched_env_gen_test, "d_decision", 1, "")

// ── 属性 test 29：D_decision = BLOCKED ──
// 测试点：TP-NPUSCH-D_DECISION-BLOCKED（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_decision;  /* 取值：BLOCKED */
//   if (!uvm_config_db#(int)::get(this, "", "d_decision_int", attr_d_decision))
//     `uvm_fatal("ATTR", "d_decision_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_decision_pBLOCKED_test
`GEN_ATTR_TC(npu_sched_env_d_decision_pBLOCKED_test, npu_sched_env_gen_test, "d_decision", 2, "")

// ── 属性 test 30：D_decision = FLUSHED ──
// 测试点：TP-NPUSCH-D_DECISION-FLUSHED（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_decision;  /* 取值：FLUSHED */
//   if (!uvm_config_db#(int)::get(this, "", "d_decision_int", attr_d_decision))
//     `uvm_fatal("ATTR", "d_decision_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_decision_pFLUSHED_test
`GEN_ATTR_TC(npu_sched_env_d_decision_pFLUSHED_test, npu_sched_env_gen_test, "d_decision", 3, "")

// ── 属性 test 31：D_cluster = 0 ──
// 测试点：TP-NPUSCH-D_CLUSTER-0（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_cluster;  /* 取值：0 */
//   if (!uvm_config_db#(int)::get(this, "", "d_cluster_int", attr_d_cluster))
//     `uvm_fatal("ATTR", "d_cluster_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_cluster_p0_test
`GEN_ATTR_TC(npu_sched_env_d_cluster_p0_test, npu_sched_env_gen_test, "d_cluster", 0, "")

// ── 属性 test 32：D_cluster = 1 ──
// 测试点：TP-NPUSCH-D_CLUSTER-1（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_cluster;  /* 取值：1 */
//   if (!uvm_config_db#(int)::get(this, "", "d_cluster_int", attr_d_cluster))
//     `uvm_fatal("ATTR", "d_cluster_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_cluster_p1_test
`GEN_ATTR_TC(npu_sched_env_d_cluster_p1_test, npu_sched_env_gen_test, "d_cluster", 1, "")

// ── 属性 test 33：D_cluster = 2 ──
// 测试点：TP-NPUSCH-D_CLUSTER-2（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_cluster;  /* 取值：2 */
//   if (!uvm_config_db#(int)::get(this, "", "d_cluster_int", attr_d_cluster))
//     `uvm_fatal("ATTR", "d_cluster_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_cluster_p2_test
`GEN_ATTR_TC(npu_sched_env_d_cluster_p2_test, npu_sched_env_gen_test, "d_cluster", 2, "")

// ── 属性 test 34：D_cluster = 3 ──
// 测试点：TP-NPUSCH-D_CLUSTER-3（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_cluster;  /* 取值：3 */
//   if (!uvm_config_db#(int)::get(this, "", "d_cluster_int", attr_d_cluster))
//     `uvm_fatal("ATTR", "d_cluster_int 没设上")
// **观测型维度**：模型没有声明 `stimulus.field` —— 该取值不是事务字段，
//   没法通过激励钉住（通常是 DUT 内部量 / 输出端口 / 派生量）。
//   本 test 只跑激励并把 config_db 通道打开，**不建立取值差异**；
//   要让它真正生效，得在模型里写：
//     stimulus:
//       field: <seq_item 上的 rand 字段名>
// 类名 npu_sched_env_d_cluster_p3_test
`GEN_ATTR_TC(npu_sched_env_d_cluster_p3_test, npu_sched_env_gen_test, "d_cluster", 3, "")

// ── 属性 test 35：D_opcode = MAC_INT8 ──
// 测试点：TP-NPUSCH-D_OPCODE-MAC_INT8（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：MAC_INT8 */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 0)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pMAC_INT8_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pMAC_INT8_test, npu_sched_env_gen_test, "d_opcode", 0, "instr_opcode")

// ── 属性 test 36：D_opcode = MAC_FP16 ──
// 测试点：TP-NPUSCH-D_OPCODE-MAC_FP16（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：MAC_FP16 */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 1)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pMAC_FP16_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pMAC_FP16_test, npu_sched_env_gen_test, "d_opcode", 1, "instr_opcode")

// ── 属性 test 37：D_opcode = MAC_BF16 ──
// 测试点：TP-NPUSCH-D_OPCODE-MAC_BF16（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：MAC_BF16 */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 2)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pMAC_BF16_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pMAC_BF16_test, npu_sched_env_gen_test, "d_opcode", 2, "instr_opcode")

// ── 属性 test 38：D_opcode = VEC_ADD ──
// 测试点：TP-NPUSCH-D_OPCODE-VEC_ADD（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：VEC_ADD */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 3)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pVEC_ADD_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pVEC_ADD_test, npu_sched_env_gen_test, "d_opcode", 3, "instr_opcode")

// ── 属性 test 39：D_opcode = VEC_MUL ──
// 测试点：TP-NPUSCH-D_OPCODE-VEC_MUL（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：VEC_MUL */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 4)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pVEC_MUL_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pVEC_MUL_test, npu_sched_env_gen_test, "d_opcode", 4, "instr_opcode")

// ── 属性 test 40：D_opcode = VEC_RELU ──
// 测试点：TP-NPUSCH-D_OPCODE-VEC_RELU（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：VEC_RELU */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 5)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pVEC_RELU_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pVEC_RELU_test, npu_sched_env_gen_test, "d_opcode", 5, "instr_opcode")

// ── 属性 test 41：D_opcode = LOAD ──
// 测试点：TP-NPUSCH-D_OPCODE-LOAD（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：LOAD */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 6)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pLOAD_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pLOAD_test, npu_sched_env_gen_test, "d_opcode", 6, "instr_opcode")

// ── 属性 test 42：D_opcode = STORE ──
// 测试点：TP-NPUSCH-D_OPCODE-STORE（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：STORE */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 7)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pSTORE_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pSTORE_test, npu_sched_env_gen_test, "d_opcode", 7, "instr_opcode")

// ── 属性 test 43：D_opcode = DMA_READ ──
// 测试点：TP-NPUSCH-D_OPCODE-DMA_READ（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：DMA_READ */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 8)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pDMA_READ_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pDMA_READ_test, npu_sched_env_gen_test, "d_opcode", 8, "instr_opcode")

// ── 属性 test 44：D_opcode = DMA_WRITE ──
// 测试点：TP-NPUSCH-D_OPCODE-DMA_WRITE（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_opcode;  /* 取值：DMA_WRITE */
//   if (!uvm_config_db#(int)::get(this, "", "d_opcode_int", attr_d_opcode))
//     `uvm_fatal("ATTR", "d_opcode_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 9)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_opcode_pDMA_WRITE_test
`GEN_ATTR_TC(npu_sched_env_d_opcode_pDMA_WRITE_test, npu_sched_env_gen_test, "d_opcode", 9, "instr_opcode")

// ── 属性 test 45：D_seq = MAC_MAC ──
// 测试点：TP-NPUSCH-D_SEQ-MAC_MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_seq;  /* 取值：MAC_MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_seq_int", attr_d_seq))
//     `uvm_fatal("ATTR", "d_seq_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 0)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_seq_pMAC_MAC_test
// **sequence 场景**：adjacent_opcode_pair
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_seq_pMAC_MAC_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_seq_pMAC_MAC_test)
  function new(string name = "npu_sched_env_d_seq_pMAC_MAC_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_seq_int", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 0);
  endfunction
endclass

// ── 属性 test 46：D_seq = LOAD_MAC ──
// 测试点：TP-NPUSCH-D_SEQ-LOAD_MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_seq;  /* 取值：LOAD_MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_seq_int", attr_d_seq))
//     `uvm_fatal("ATTR", "d_seq_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 1)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_seq_pLOAD_MAC_test
// **sequence 场景**：adjacent_opcode_pair
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_seq_pLOAD_MAC_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_seq_pLOAD_MAC_test)
  function new(string name = "npu_sched_env_d_seq_pLOAD_MAC_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_seq_int", 1);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 6);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 0);
  endfunction
endclass

// ── 属性 test 47：D_seq = MAC_STORE ──
// 测试点：TP-NPUSCH-D_SEQ-MAC_STORE（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_seq;  /* 取值：MAC_STORE */
//   if (!uvm_config_db#(int)::get(this, "", "d_seq_int", attr_d_seq))
//     `uvm_fatal("ATTR", "d_seq_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 2)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_seq_pMAC_STORE_test
// **sequence 场景**：adjacent_opcode_pair
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_seq_pMAC_STORE_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_seq_pMAC_STORE_test)
  function new(string name = "npu_sched_env_d_seq_pMAC_STORE_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_seq_int", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 7);
  endfunction
endclass

// ── 属性 test 48：D_seq = DMA_MAC ──
// 测试点：TP-NPUSCH-D_SEQ-DMA_MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_seq;  /* 取值：DMA_MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_seq_int", attr_d_seq))
//     `uvm_fatal("ATTR", "d_seq_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 3)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_seq_pDMA_MAC_test
// **sequence 场景**：adjacent_opcode_pair
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_seq_pDMA_MAC_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_seq_pDMA_MAC_test)
  function new(string name = "npu_sched_env_d_seq_pDMA_MAC_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_seq_int", 3);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 8);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 0);
  endfunction
endclass

// ── 属性 test 49：D_seq = VEC_MAC ──
// 测试点：TP-NPUSCH-D_SEQ-VEC_MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_seq;  /* 取值：VEC_MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_seq_int", attr_d_seq))
//     `uvm_fatal("ATTR", "d_seq_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 4)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_seq_pVEC_MAC_test
// **sequence 场景**：adjacent_opcode_pair
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_seq_pVEC_MAC_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_seq_pVEC_MAC_test)
  function new(string name = "npu_sched_env_d_seq_pVEC_MAC_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_seq_int", 4);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 3);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 0);
  endfunction
endclass

// ── 属性 test 50：D_seq = SCALAR_MAC ──
// 测试点：TP-NPUSCH-D_SEQ-SCALAR_MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_seq;  /* 取值：SCALAR_MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_seq_int", attr_d_seq))
//     `uvm_fatal("ATTR", "d_seq_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 5)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_seq_pSCALAR_MAC_test
// **sequence 场景**：adjacent_opcode_pair
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_seq_pSCALAR_MAC_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_seq_pSCALAR_MAC_test)
  function new(string name = "npu_sched_env_d_seq_pSCALAR_MAC_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_seq_int", 5);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 0);
  endfunction
endclass

// ── 属性 test 51：D_pipeline = NONE ──
// 测试点：TP-NPUSCH-D_PIPELINE-NONE（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_pipeline;  /* 取值：NONE */
//   if (!uvm_config_db#(int)::get(this, "", "d_pipeline_int", attr_d_pipeline))
//     `uvm_fatal("ATTR", "d_pipeline_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 0)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_pipeline_pNONE_test
// **sequence 场景**：pipeline_overlap
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_pipeline_pNONE_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_pipeline_pNONE_test)
  function new(string name = "npu_sched_env_d_pipeline_pNONE_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_pipeline_int", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 1);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 0);
  endfunction
endclass

// ── 属性 test 52：D_pipeline = MAC_MAC ──
// 测试点：TP-NPUSCH-D_PIPELINE-MAC_MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_pipeline;  /* 取值：MAC_MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_pipeline_int", attr_d_pipeline))
//     `uvm_fatal("ATTR", "d_pipeline_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 1)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_pipeline_pMAC_MAC_test
// **sequence 场景**：pipeline_overlap
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_pipeline_pMAC_MAC_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_pipeline_pMAC_MAC_test)
  function new(string name = "npu_sched_env_d_pipeline_pMAC_MAC_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_pipeline_int", 1);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 0);
  endfunction
endclass

// ── 属性 test 53：D_pipeline = MAC_DMA ──
// 测试点：TP-NPUSCH-D_PIPELINE-MAC_DMA（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_pipeline;  /* 取值：MAC_DMA */
//   if (!uvm_config_db#(int)::get(this, "", "d_pipeline_int", attr_d_pipeline))
//     `uvm_fatal("ATTR", "d_pipeline_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 2)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_pipeline_pMAC_DMA_test
// **sequence 场景**：pipeline_overlap
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_pipeline_pMAC_DMA_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_pipeline_pMAC_DMA_test)
  function new(string name = "npu_sched_env_d_pipeline_pMAC_DMA_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_pipeline_int", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 8);
  endfunction
endclass

// ── 属性 test 54：D_pipeline = VEC_MAC ──
// 测试点：TP-NPUSCH-D_PIPELINE-VEC_MAC（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_pipeline;  /* 取值：VEC_MAC */
//   if (!uvm_config_db#(int)::get(this, "", "d_pipeline_int", attr_d_pipeline))
//     `uvm_fatal("ATTR", "d_pipeline_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 3)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_pipeline_pVEC_MAC_test
// **sequence 场景**：pipeline_overlap
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_pipeline_pVEC_MAC_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_pipeline_pVEC_MAC_test)
  function new(string name = "npu_sched_env_d_pipeline_pVEC_MAC_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_pipeline_int", 3);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 2);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 3);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 0);
  endfunction
endclass

// ── 属性 test 55：D_pipeline = MULTI_OP ──
// 测试点：TP-NPUSCH-D_PIPELINE-MULTI_OP（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_pipeline;  /* 取值：MULTI_OP */
//   if (!uvm_config_db#(int)::get(this, "", "d_pipeline_int", attr_d_pipeline))
//     `uvm_fatal("ATTR", "d_pipeline_int 没设上")
// **激励绑定**：该取值由事务字段 `instr_opcode` 承载 —— 本 test 会
//   set("instr_opcode_int", 4)，master sequence 读它
//   并约束 `instr_opcode`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_pipeline_pMULTI_OP_test
// **sequence 场景**：pipeline_overlap
// 逐笔取值写进 `instr_opcode_seq_*` 通道，master sequence 每笔事务按序取值。
// 这是"相邻指令组合"这类测试点唯一能建立确定差异的方式 —— 单个字段取值
// 表达不了时序。缺 `sequence_values` 的 sequence 维度不会走到这里（见
// 上面的观测型分支），**不拿一个空场景冒充已实现**。
class npu_sched_env_d_pipeline_pMULTI_OP_test extends npu_sched_env_gen_test;
  `uvm_component_utils(npu_sched_env_d_pipeline_pMULTI_OP_test)
  function new(string name = "npu_sched_env_d_pipeline_pMULTI_OP_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(int)::set(this, "*", "d_pipeline_int", 4);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_len", 3);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_0", 0);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_1", 3);
    uvm_config_db#(int)::set(this, "*", "instr_opcode_seq_2", 8);
  endfunction
endclass

// ── 属性 test 56：D_priority = HIGH_FIRST ──
// 测试点：TP-NPUSCH-D_PRIORITY-HIGH_FIRST（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_priority;  /* 取值：HIGH_FIRST */
//   if (!uvm_config_db#(int)::get(this, "", "d_priority_int", attr_d_priority))
//     `uvm_fatal("ATTR", "d_priority_int 没设上")
// **激励绑定**：该取值由事务字段 `op_priority` 承载 —— 本 test 会
//   set("op_priority_int", 0)，master sequence 读它
//   并约束 `op_priority`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_priority_pHIGH_FIRST_test
`GEN_ATTR_TC(npu_sched_env_d_priority_pHIGH_FIRST_test, npu_sched_env_gen_test, "d_priority", 0, "op_priority")

// ── 属性 test 57：D_priority = LOW_FIRST ──
// 测试点：TP-NPUSCH-D_PRIORITY-LOW_FIRST（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_priority;  /* 取值：LOW_FIRST */
//   if (!uvm_config_db#(int)::get(this, "", "d_priority_int", attr_d_priority))
//     `uvm_fatal("ATTR", "d_priority_int 没设上")
// **激励绑定**：该取值由事务字段 `op_priority` 承载 —— 本 test 会
//   set("op_priority_int", 1)，master sequence 读它
//   并约束 `op_priority`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_priority_pLOW_FIRST_test
`GEN_ATTR_TC(npu_sched_env_d_priority_pLOW_FIRST_test, npu_sched_env_gen_test, "d_priority", 1, "op_priority")

// ── 属性 test 58：D_priority = SAME_PRIO ──
// 测试点：TP-NPUSCH-D_PRIORITY-SAME_PRIO（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_priority;  /* 取值：SAME_PRIO */
//   if (!uvm_config_db#(int)::get(this, "", "d_priority_int", attr_d_priority))
//     `uvm_fatal("ATTR", "d_priority_int 没设上")
// **激励绑定**：该取值由事务字段 `op_priority` 承载 —— 本 test 会
//   set("op_priority_int", 2)，master sequence 读它
//   并约束 `op_priority`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_priority_pSAME_PRIO_test
`GEN_ATTR_TC(npu_sched_env_d_priority_pSAME_PRIO_test, npu_sched_env_gen_test, "d_priority", 2, "op_priority")

// ── 属性 test 59：D_priority = ROUND_ROBIN ──
// 测试点：TP-NPUSCH-D_PRIORITY-ROUND_ROBIN（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_priority;  /* 取值：ROUND_ROBIN */
//   if (!uvm_config_db#(int)::get(this, "", "d_priority_int", attr_d_priority))
//     `uvm_fatal("ATTR", "d_priority_int 没设上")
// **激励绑定**：该取值由事务字段 `op_priority` 承载 —— 本 test 会
//   set("op_priority_int", 3)，master sequence 读它
//   并约束 `op_priority`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_priority_pROUND_ROBIN_test
`GEN_ATTR_TC(npu_sched_env_d_priority_pROUND_ROBIN_test, npu_sched_env_gen_test, "d_priority", 3, "op_priority")

// ── 属性 test 60：D_barrier = NONE ──
// 测试点：TP-NPUSCH-D_BARRIER-NONE（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_barrier;  /* 取值：NONE */
//   if (!uvm_config_db#(int)::get(this, "", "d_barrier_int", attr_d_barrier))
//     `uvm_fatal("ATTR", "d_barrier_int 没设上")
// **激励绑定**：该取值由事务字段 `barrier_type` 承载 —— 本 test 会
//   set("barrier_type_int", 0)，master sequence 读它
//   并约束 `barrier_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_barrier_pNONE_test
`GEN_ATTR_TC(npu_sched_env_d_barrier_pNONE_test, npu_sched_env_gen_test, "d_barrier", 0, "barrier_type")

// ── 属性 test 61：D_barrier = TILE_BARRIER ──
// 测试点：TP-NPUSCH-D_BARRIER-TILE_BARRIER（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_barrier;  /* 取值：TILE_BARRIER */
//   if (!uvm_config_db#(int)::get(this, "", "d_barrier_int", attr_d_barrier))
//     `uvm_fatal("ATTR", "d_barrier_int 没设上")
// **激励绑定**：该取值由事务字段 `barrier_type` 承载 —— 本 test 会
//   set("barrier_type_int", 1)，master sequence 读它
//   并约束 `barrier_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_barrier_pTILE_BARRIER_test
`GEN_ATTR_TC(npu_sched_env_d_barrier_pTILE_BARRIER_test, npu_sched_env_gen_test, "d_barrier", 1, "barrier_type")

// ── 属性 test 62：D_barrier = OP_BARRIER ──
// 测试点：TP-NPUSCH-D_BARRIER-OP_BARRIER（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_barrier;  /* 取值：OP_BARRIER */
//   if (!uvm_config_db#(int)::get(this, "", "d_barrier_int", attr_d_barrier))
//     `uvm_fatal("ATTR", "d_barrier_int 没设上")
// **激励绑定**：该取值由事务字段 `barrier_type` 承载 —— 本 test 会
//   set("barrier_type_int", 2)，master sequence 读它
//   并约束 `barrier_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_barrier_pOP_BARRIER_test
`GEN_ATTR_TC(npu_sched_env_d_barrier_pOP_BARRIER_test, npu_sched_env_gen_test, "d_barrier", 2, "barrier_type")

// ── 属性 test 63：D_barrier = CLUSTER_BARRIER ──
// 测试点：TP-NPUSCH-D_BARRIER-CLUSTER_BARRIER（覆盖仓 / 回归级 / 签核判据都按这个编号对齐）
// 维度通道（env / 其它消费方按需打开）：
//   int attr_d_barrier;  /* 取值：CLUSTER_BARRIER */
//   if (!uvm_config_db#(int)::get(this, "", "d_barrier_int", attr_d_barrier))
//     `uvm_fatal("ATTR", "d_barrier_int 没设上")
// **激励绑定**：该取值由事务字段 `barrier_type` 承载 —— 本 test 会
//   set("barrier_type_int", 3)，master sequence 读它
//   并约束 `barrier_type`，所以这个 test 的激励**确实与其它取值不同**。
// 类名 npu_sched_env_d_barrier_pCLUSTER_BARRIER_test
`GEN_ATTR_TC(npu_sched_env_d_barrier_pCLUSTER_BARRIER_test, npu_sched_env_gen_test, "d_barrier", 3, "barrier_type")

