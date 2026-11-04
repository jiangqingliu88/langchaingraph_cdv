// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_test_pkg.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Test Package: npu_sched_env_test_pkg
package npu_sched_env_test_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
    // 直接导入 Agent 包（SV import 不可传递）
    //
    // 用 `agent.interface`（协议名，如 apb）而**不是** `agent.name`
    //（实例名，如 apb_master）—— 真实的包叫 `apb_pkg`。这里原来写的是 agent.name，
    // 生成 `import apb_master_pkg::*`：一个不存在的包。
  import npu_sched_in_pkg::*;
  import npu_sched_in_typedefs_pkg::*;
  import npu_sched_in_parameters_pkg::*;
  import npu_sched_out_pkg::*;
  import npu_sched_out_typedefs_pkg::*;
  import npu_sched_out_parameters_pkg::*;
  // 导入 env 包（apb_env / apb_env_config 这些类住在里面）
  import npu_sched_env_pkg::*;
  // 环境序列在 seq 包里，测试要用（apb_master_sequence 这些）——
  // **只能 import seq_pkg**，因为 seq 类都定义在那个 package 内。
  import npu_sched_env_seq_pkg::*;



  // 包含环境组件文件
  `include "npu_sched_env_base_test.sv"
  `include "npu_sched_env_direct_test.sv"
  `include "npu_sched_env_gen_test.sv"

  // 属性测试（一条 environment.tests = 一个 UVM_TEST = 一个属性取值）
  `include "npu_sched_env_attr_test.sv"

  // 批次测试（一条 environment.batches = 一个 UVM_TEST = 一个批次/专题）。
  //
  // ⚠️ **必须 include 进来**：`_batch_test.sv` 不产在这个包里，包外也没人单独编它
  //（filelist 只收 `env/tests/` 下的 **package**，不是每个 .sv）——漏掉这一句，
  // 那些类就**根本没被编译过**，而回归里 `+UVM_TESTNAME=npu_basic_test` 撞
  // `UVM_FATAL (INVTST) not found`（实测：p0 里 1 条批次测试挂在这）。
  // 类体 extends 的是 `_gen_test`（上面已 include），所以这句要排在它之后。
  `include "npu_sched_env_batch_test.sv"


endpackage : npu_sched_env_test_pkg
