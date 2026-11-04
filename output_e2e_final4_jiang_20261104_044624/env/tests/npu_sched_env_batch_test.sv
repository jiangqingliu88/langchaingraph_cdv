// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_batch_test.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Batch Tests: npu_sched_env_batch_test
//
// **一条 batches: 条目 = 一个 UVM_TEST = 一个批次（专题）**。
//
// 与 `_attr_test.sv` 是两条平行的路：
//   attr  —— 一条 = 一个属性取值（`D_type = VECTOR`），名字由维度+取值推出来
//   batch —— 一条 = 一个批次（`TH-B02 指令类型`），名字由 case 模型的
//            `themes[].test` 给定（`npu_type_test`）
//
// ## 为什么批次也要有 test 类
//
// 回归里跑的是 `+UVM_TESTNAME=<批次名>`。没有这个类，UVM 直接
// `UVM_FATAL (INVTST) test 'npu_type_test' not found` —— 而**那条路径会被记成
// pass**（vsim 遇到未知 testname 仍然 exit 0，见 `_sim_run_cmd` 的注释）。
// 也就是说：批次跑不起来，反而看不出来。
//
// ## 类体里为什么不铺激励
//
// 类体里只 `set` 参数，不写约束逻辑本身 —— **传参数，不传行为**（跟 attr test
// 只 `set` 一个 `_int` 是同一种克制）。
//
// ## 约束是哪一侧的
//
// `batch_policy` 是**模型给的约束策略类名**（`theme_policy_map` 从 case 模型的
// `themes[].method` 推，与 `build_constraint` 生成的 `policies[].name` 同名）。
// sequence 拿这个名字去策略工厂查表建策略 —— 于是"这一批用哪条约束"**由模型
// 说了算**，而不是由回归命令行上的 plusargs 说了算。
//
// 空串 = 这一批没有模型给的约束（`policy` 键缺失或 method 认不出）：sequence
// 会退回默认组合器。**不报错** —— 那是"模型没声明"，不是"生成错了"。

// 生成一条批次 test。宏体内**只能用 /* */ 注释** —— `//` 会把行尾的反斜杠
// 一起吃掉，宏定义当场断在那一行（SV 宏的经典坑，别改回去）。
//
// **跟一句**：`/* */` 注释也只能**单行**、且**每个物理行都要以 `\` 结尾**。
// 宏体是靠行尾反斜杠粘成"逻辑一行"的，跨行的块注释中间那几行没有 `\`，
// 宏定义就在那里断掉了 —— 而且报的错在下游（`tc_name` 未声明），不在这一行。
// 长解释写在宏**外面**（就是上面这段），宏里只留代码。
//
// `batch_policy` 为什么要走**全局**通道（`set(null, "*", ...)`）而不是
// `set(this, "*", ...)`：sequence 的父链未必挂在 test 底下 —— `seq.start(sqr)`
// 建出来的 sequence 可以不挂 parent，那样 `this` 上下文的 set 它取不到；而
// **取不到的表现是"约束静默没生效、回归照样全绿"**，正是最难发现的那种。
// 全局通道与 tb_top 挂 vif 用的是同一个写法（`tb_top.sv.j2`）。
`define GEN_BATCH_TC(tc_name, tc_base, tc_theme, tc_dims, tc_method, tc_policy, tc_prio) \
class tc_name extends tc_base; \
    `uvm_component_utils(tc_name) \
    function new(string name, uvm_component parent); \
        super.new(name, parent); \
    endfunction \
    virtual function void build_phase(uvm_phase phase); \
        super.build_phase(phase); \
        uvm_config_db#(string)::set(this, "*", "batch_theme", tc_theme); \
        uvm_config_db#(string)::set(this, "*", "batch_dimensions", tc_dims); \
        uvm_config_db#(string)::set(this, "*", "batch_method", tc_method); \
        uvm_config_db#(string)::set(null, "*", "batch_policy", tc_policy); \
        uvm_config_db#(string)::set(this, "*", "batch_priority", tc_prio); \
    endfunction \
endclass


// ── 批次 test 1：TH-B01（D_decision，方法 D）──
// 约束策略：p_th_b01_directed
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b01_directed */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_basic_test, npu_sched_env_gen_test, "TH-B01", "D_decision", "D", "p_th_b01_directed", "P0")

// ── 批次 test 2：TH-B02（D_type，方法 RND）──
// 约束策略：p_th_b02_random
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b02_random */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_type_test, npu_sched_env_gen_test, "TH-B02", "D_type", "RND", "p_th_b02_random", "P0")

// ── 批次 test 3：TH-B03（D_dtype，方法 RND）──
// 约束策略：p_th_b03_random
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b03_random */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_dtype_test, npu_sched_env_gen_test, "TH-B03", "D_dtype", "RND", "p_th_b03_random", "P0")

// ── 批次 test 4：TH-B04（D_dep,D_decision，方法 G）──
// 约束策略：p_th_b04_combo
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b04_combo */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_dep_test, npu_sched_env_gen_test, "TH-B04", "D_dep,D_decision", "G", "p_th_b04_combo", "P1")

// ── 批次 test 5：TH-B05（D_dep，方法 SPCL）──
// 约束策略：p_th_b05_special
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b05_special */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_raw_stall_test, npu_sched_env_gen_test, "TH-B05", "D_dep", "SPCL", "p_th_b05_special", "P1")

// ── 批次 test 6：TH-B06（D_queue,D_decision，方法 SPCL）──
// 约束策略：p_th_b06_special
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b06_special */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_full_queue_test, npu_sched_env_gen_test, "TH-B06", "D_queue,D_decision", "SPCL", "p_th_b06_special", "P1")

// ── 批次 test 7：TH-B07（D_cluster,D_unit，方法 G）──
// 约束策略：p_th_b07_combo
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b07_combo */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_cluster_test, npu_sched_env_gen_test, "TH-B07", "D_cluster,D_unit", "G", "p_th_b07_combo", "P2")

// ── 批次 test 8：TH-B08（D_opcode,D_unit，方法 D）──
// 约束策略：p_th_b08_directed
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b08_directed */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_opcode_test, npu_sched_env_gen_test, "TH-B08", "D_opcode,D_unit", "D", "p_th_b08_directed", "P2")

// ── 批次 test 9：TH-B09（D_type,D_unit，方法 RND）──
// 约束策略：p_th_b09_random
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b09_random */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_dma_compute_test, npu_sched_env_gen_test, "TH-B09", "D_type,D_unit", "RND", "p_th_b09_random", "P3")

// ── 批次 test 10：TH-B10（D_pipeline，方法 RND）──
// 约束策略：p_th_b10_random
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b10_random */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_pipeline_test, npu_sched_env_gen_test, "TH-B10", "D_pipeline", "RND", "p_th_b10_random", "P3")

// ── 批次 test 11：TH-B11（D_queue,D_type,D_dtype,D_dep,D_unit,D_decision,D_cluster,D_opcode,D_seq,D_pipeline,D_priority,D_barrier，方法 RND）──
// 约束策略：p_th_b11_random
// 消费方（sequence）按 `batch_policy` 去策略工厂查表：
//   string policy;  /* p_th_b11_random */
//   uvm_config_db#(string)::get(null, "", "batch_policy", policy);
`GEN_BATCH_TC(npu_random_mix_test, npu_sched_env_gen_test, "TH-B11", "D_queue,D_type,D_dtype,D_dep,D_unit,D_decision,D_cluster,D_opcode,D_seq,D_pipeline,D_priority,D_barrier", "RND", "p_th_b11_random", "P3")

