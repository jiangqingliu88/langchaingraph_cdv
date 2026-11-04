// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_coverage.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Env Coverage: npu_sched_env_coverage
// 环境级功能覆盖率模型（跨 agent 的语义级 covergroup，自动生成）
//
// ── 为什么**每个 agent 一个 covergroup**，而不是揉成一个 ──
// 揉成一个 `cg_env` 时，每个 coverpoint 都写成 `<某 agent>_item.<字段>`，
// 而 `write_<agent>` 里无条件 `cg_env.sample()` —— 采样会把**所有** coverpoint
// 都求值一遍，包括**另一个 agent 尚未产生过事务**的那个句柄。
// 那个句柄此时是 null，求值 `<null>.<字段>` 就是 Questa 的
//   ** Fatal: (SIGSEGV) Bad handle or reference.
// 实测：只跑 master 侧、slave 还没抓到任何事务时，master 的第一笔就崩。
// 拆开之后，`cg_<agent>` 只引用本 agent 的 item，天然不会互相牵连。
//
// 另外 `*_item` 一律在 new() 里建好**非空占位对象**：万一某个 covergroup 在
// item 还是 null 的时候被 sample（比如跨 agent 的 cross），也不会解引用空句柄。

// 为每个 agent 声明独立的 analysis_imp（不同 seq_item 类型）
`uvm_analysis_imp_decl(_npu_sched_in)
`uvm_analysis_imp_decl(_npu_sched_out)

class npu_sched_env_coverage extends uvm_component;
  `uvm_component_utils(npu_sched_env_coverage)

  // 分析端口：接收各 agent 的 monitor 采样
  uvm_analysis_imp_npu_sched_in #(npu_sched_in_master_seq_item, npu_sched_env_coverage) npu_sched_in_export;
  uvm_analysis_imp_npu_sched_out #(npu_sched_out_master_seq_item, npu_sched_env_coverage) npu_sched_out_export;

  // 采样项（保存最新采样的 transaction，供 covergroup 采样）
  npu_sched_in_master_seq_item npu_sched_in_item;
  npu_sched_out_master_seq_item npu_sched_out_item;

  // ── npu_sched_in 的功能覆盖率 ──
  //
  // **多位字段只分三个值类（0 / 1 / 其余），这不是省事，是必须**：
  // 不给 coverpoint 写 bins，仿真器会把整个取值空间自动分箱 —— 8 位就是 256 个
  // bin，下面那句 `cross_all` 再把两个这样的 coverpoint 一乘就是几万个 bin。
  // 那种模型随机激励永远填不满：实测 4360 个 bin 只命中 64 个（1.46%），
  // 于是"功能覆盖率"这个数字常年趴在地上，既收敛不了、也看不出该往哪使劲。
  // 分箱后同一个 cross 是 3×3 —— 是定向激励能收敛的粒度。
  // 真正的领域粒度在策略包的 `coverage_bins`（语义化 cross）里，不靠自动分箱。
  covergroup cg_npu_sched_in;
    cp_instr_valid: coverpoint npu_sched_in_item.instr_valid;
    cp_instr_opcode: coverpoint npu_sched_in_item.instr_opcode {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:255]};
    }
    cp_instr_type: coverpoint npu_sched_in_item.instr_type {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:7]};
    }
    cp_instr_dtype: coverpoint npu_sched_in_item.instr_dtype {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:7]};
    }
    cp_instr_tile_id: coverpoint npu_sched_in_item.instr_tile_id {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:255]};
    }
    cp_instr_src_addr: coverpoint npu_sched_in_item.instr_src_addr {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:4294967295]};
    }
    cp_instr_dst_addr: coverpoint npu_sched_in_item.instr_dst_addr {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:4294967295]};
    }
    cp_barrier_type: coverpoint npu_sched_in_item.barrier_type {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:3]};
    }
    cp_op_priority: coverpoint npu_sched_in_item.op_priority {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:3]};
    }
    // cross: npu_sched_in 的关键信号组合（语义级）
    cross_all: cross cp_instr_valid, cp_instr_opcode;
  endgroup : cg_npu_sched_in

  // ── npu_sched_out 的功能覆盖率 ──
  //
  // **多位字段只分三个值类（0 / 1 / 其余），这不是省事，是必须**：
  // 不给 coverpoint 写 bins，仿真器会把整个取值空间自动分箱 —— 8 位就是 256 个
  // bin，下面那句 `cross_all` 再把两个这样的 coverpoint 一乘就是几万个 bin。
  // 那种模型随机激励永远填不满：实测 4360 个 bin 只命中 64 个（1.46%），
  // 于是"功能覆盖率"这个数字常年趴在地上，既收敛不了、也看不出该往哪使劲。
  // 分箱后同一个 cross 是 3×3 —— 是定向激励能收敛的粒度。
  // 真正的领域粒度在策略包的 `coverage_bins`（语义化 cross）里，不靠自动分箱。
  covergroup cg_npu_sched_out;
    cp_issue_valid: coverpoint npu_sched_out_item.issue_valid;
    cp_issue_unit: coverpoint npu_sched_out_item.issue_unit {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:7]};
    }
    cp_issue_decision: coverpoint npu_sched_out_item.issue_decision {   // 值类：0 / 1 / 其余
      bins v_zero = {0};
      bins v_one  = {1};
      bins v_rest = {[2:3]};
    }
    // cross: npu_sched_out 的关键信号组合（语义级）
    cross_all: cross cp_issue_valid, cp_issue_unit;
  endgroup : cg_npu_sched_out
  // ── DUT 信号的功能覆盖率（**第二条采样通道**）──
  //
  // 上面那些 `cg_<agent>` 采的是 **monitor 的事务对象** —— 只看得到**激励侧**。
  // 队列水位、依赖类型、发射决策这些**内部状态**与输出端口，事务里根本没有，
  // 也永远不会出现在 monitor 的采样里。
  //
  // 所以另有一条：`bind` 进 DUT 的**接口**（`coverage/npu_sched_cov_if.sv`）把信号引出来，
  // 本组件持 `virtual npu_sched_cov_if` 句柄、**时钟沿**采样。`bind` 的端口连接
  // 表达式在**目标模块作用域**里求值，所以输入端口 / 输出端口 / 内部寄存器
  // 一视同仁 —— 内部名直接连得过来（vlog + vopt 实测通过）。
  //
  // ⚠️ **句柄是 tb_top 挂进来的**（`config_db` 的 "cov_vif"，路径
  // `npu_sched` 的实例下 `u_npu_sched_cov_if`）。挂不上就
  // `uvm_fatal` —— 那是个**接线错误**，不是"这次没覆盖率"：静默跑完会给出一个
  // 恒 0% 的数字，比停下来更难查。
  virtual npu_sched_cov_if cov_vif;

  covergroup cg_dut;
    cp_queue_level: coverpoint cov_vif.queue_level {   // queue_level
      bins empty = {0};
      bins low = {[1:7]};
      bins mid = {[8:15]};
      bins high = {[16:24]};
      bins near_full = {[25:31]};
      bins full = {32};
      illegal_bins illegal_over = {[33:$]};
    }
    cp_instr_type: coverpoint cov_vif.instr_type {   // instr_type
      bins mac = {0};
      bins vector = {1};
      bins scalar = {2};
      bins dma = {3};
    }
    cp_instr_dtype: coverpoint cov_vif.instr_dtype {   // instr_dtype
      bins int8 = {0};
      bins fp16 = {1};
      bins bf16 = {2};
      bins fp32 = {3};
    }
    cp_dep_type: coverpoint cov_vif.dep_type {   // dep_type
      bins no_dep = {0};
      bins raw = {1};
      bins waw = {2};
      bins war = {3};
    }
    cp_issue_unit: coverpoint cov_vif.issue_unit {   // issue_unit
      bins mac = {0};
      bins vector = {1};
      bins scalar = {2};
      bins dma = {3};
    }
    cp_issue_decision: coverpoint cov_vif.issue_decision {   // issue_decision
      bins issued = {0};
      bins stalled = {1};
      bins blocked = {2};
      bins flushed = {3};
    }
    cp_cluster_id: coverpoint cov_vif.cluster_id {   // cluster_id
      bins c0 = {0};
      bins c1 = {1};
      bins c2 = {2};
      bins c3 = {3};
      illegal_bins illegal_cluster = {[4:$]};
    }
    cp_instr_opcode: coverpoint cov_vif.instr_opcode {   // instr_opcode
      bins mac_i8 = {0};
      bins mac_fp16 = {1};
      bins mac_bf16 = {2};
      bins vec_add = {3};
      bins vec_mul = {4};
      bins vec_relu = {5};
      bins load = {6};
      bins store = {7};
      bins dma_rd = {8};
      bins dma_wr = {9};
    }
    cp_instr_seq: coverpoint cov_vif.instr_seq {   // instr_seq
      bins mac_mac = {0};
      bins load_mac = {1};
      bins mac_store = {2};
      bins dma_mac = {3};
      bins vec_mac = {4};
      bins scalar_mac = {5};
    }
    cp_pipeline_state: coverpoint cov_vif.pipeline_state {   // pipeline_state
      bins no_overlap = {0};
      bins mac_mac_overlap = {1};
      bins mac_dma_overlap = {2};
      bins vec_mac_overlap = {3};
      bins multi_op_overlap = {4};
    }
    cp_op_priority: coverpoint cov_vif.op_priority {   // op_priority
      bins high_first = {0};
      bins low_first = {1};
      bins same_priority = {2};
      bins round_robin = {3};
    }
    cp_barrier_type: coverpoint cov_vif.barrier_type {   // barrier_type
      bins no_barrier = {0};
      bins tile_barrier = {1};
      bins op_barrier = {2};
      bins cluster_barrier = {3};
    }
  endgroup : cg_dut

  // ── 测试点位图（`coverage/tp_bitmap.json`）──
  //
  // 第 i 位 = 第 i 条 TP（位序 = testpoints.yaml 的序号，**一旦发布不重排**）。
  // 仓首次命中时置位（之后保持为 1）并打一行 `[TP_HIT]` —— 打开波形就能看到
  // "到这一刻为止点亮了哪几个测试点"，日志里也能 grep 到归属。
  bit [69:0] tp_hit_logged = '0;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    npu_sched_in_export = new("npu_sched_in_export", this);
    // 非空占位：防止 covergroup 在首个事务到来前解引用空句柄（SIGSEGV）
    npu_sched_in_item = npu_sched_in_master_seq_item::type_id::create("npu_sched_in_item");
    npu_sched_out_export = new("npu_sched_out_export", this);
    // 非空占位：防止 covergroup 在首个事务到来前解引用空句柄（SIGSEGV）
    npu_sched_out_item = npu_sched_out_master_seq_item::type_id::create("npu_sched_out_item");
    cg_npu_sched_in = new();
    cg_npu_sched_out = new();
    cg_dut = new();
  endfunction

  // ── DUT 检查（**真 pass 的"比对"那一半**）──
  //
  // 判据：真 pass = **SCB 报 `mismatched=0`** + 断言不报错。断言那半由 SVA 承担
  //（bind 进 DUT）；这一半在 env 里逐拍求值**同一组规则**，把结论收口成一行
  // `matched=…  mismatched=…` 打出来。
  //
  // 规则来自 case 模型（设计者写的"这条必须恒成立"），**一份规则两个执行点** ——
  // 设计侧（SVA）与验证侧（这里）各写一份必然漂，而对不上时没人看得出来。
  //
  // 采样的两个条件与 `cg_dut` 一致：**时钟沿 + 不在复位周期**（复位期间的值无意义，
  // 拿它判会造出一堆假违规）。
  int unsigned chk_total = 0;
  int unsigned chk_matched = 0;
  int unsigned chk_mismatched = 0;
  // **求值为 X 的次数** —— 单列一个计数，因为"没验到"与"验了不过"是两件事。
  int unsigned chk_unknown = 0;
  string chk_first_fail = "";
  int unsigned chk_bad_queue_level_within_depth = 0;   // 这条规则违规次数
  // 逐条 SB 收口（`[SCB <id>]`）要按规则归并 —— 聚合行分不出是哪条 SB 的账，
  // 所以每条规则各记**求值次数**与**求值为 X 的次数**。
  int unsigned chk_n_queue_level_within_depth = 0;
  int unsigned chk_x_queue_level_within_depth = 0;
  int unsigned chk_bad_raw_never_issues = 0;   // 这条规则违规次数
  // 逐条 SB 收口（`[SCB <id>]`）要按规则归并 —— 聚合行分不出是哪条 SB 的账，
  // 所以每条规则各记**求值次数**与**求值为 X 的次数**。
  int unsigned chk_n_raw_never_issues = 0;
  int unsigned chk_x_raw_never_issues = 0;
  int unsigned chk_bad_barrier_flushes = 0;   // 这条规则违规次数
  // 逐条 SB 收口（`[SCB <id>]`）要按规则归并 —— 聚合行分不出是哪条 SB 的账，
  // 所以每条规则各记**求值次数**与**求值为 X 的次数**。
  int unsigned chk_n_barrier_flushes = 0;
  int unsigned chk_x_barrier_flushes = 0;
  int unsigned chk_bad_issued_needs_no_blocker = 0;   // 这条规则违规次数
  // 逐条 SB 收口（`[SCB <id>]`）要按规则归并 —— 聚合行分不出是哪条 SB 的账，
  // 所以每条规则各记**求值次数**与**求值为 X 的次数**。
  int unsigned chk_n_issued_needs_no_blocker = 0;
  int unsigned chk_x_issued_needs_no_blocker = 0;

  function void chk_dut_one();
    begin
      // **必须 `logic`（四态），不能用 `bit`** —— `bit` 是两态，X 赋进去会被
      // **静默转成 0**，于是下面那句 `$isunknown` 恒为假："求值为 X" 被读成
      // "值为 0"，再往下就成了"**违规**"。实测：误报 32 条 mismatched / 0 条
      // unverified，看着像设计违例，其实是 X 被压成了 0。
      logic _ok_1 = 1'b0;
      _ok_1 = ((cov_vif.queue_level <= 6'd32));
      // **X 不算命中。**
      //
      // 原来直接写 `if (!(expr))`：`expr` 为 X 时 `!(X)` 也是 X，`if (X)` 取
      // **false** → 落到 `else` → `chk_matched++`。于是"**不知道**"被记成"**通过**"。
      //
      // 这不是理论问题：DUT 的输入在复位竞态/悬空时会把它推成 X，而那种情况下
      // 检查的意义恰恰在于说"这里**没验到**"。实测踩过整条端到端：DUT 输入晚一拍
      // 被驱动，`queue_level` 锁成 X，而检查组件报了 `total=90 matched=90
      // mismatched=0` —— 看着全绿，其实一个 bit 都没验。
      if ($isunknown(_ok_1)) begin
        chk_unknown++;
        chk_x_queue_level_within_depth++;
        if (chk_first_fail == "")
          chk_first_fail = "queue_level_within_depth: 求值为 X（信号未知）—— 不是命中，是没验到";
      end else if (!_ok_1) begin
        chk_mismatched++;
        chk_bad_queue_level_within_depth++;
        if (chk_first_fail == "")
          chk_first_fail = "queue_level_within_depth: 队列水位超过深度 32（计数器越界）";
      end else begin
        chk_matched++;
      end
    end
    chk_total++;
    chk_n_queue_level_within_depth++;
    begin
      // **必须 `logic`（四态），不能用 `bit`** —— `bit` 是两态，X 赋进去会被
      // **静默转成 0**，于是下面那句 `$isunknown` 恒为假："求值为 X" 被读成
      // "值为 0"，再往下就成了"**违规**"。实测：误报 32 条 mismatched / 0 条
      // unverified，看着像设计违例，其实是 X 被压成了 0。
      logic _ok_2 = 1'b0;
      _ok_2 = (!(cov_vif.dep_type == 2'd1) || (cov_vif.issue_valid == 1'b0));
      // **X 不算命中。**
      //
      // 原来直接写 `if (!(expr))`：`expr` 为 X 时 `!(X)` 也是 X，`if (X)` 取
      // **false** → 落到 `else` → `chk_matched++`。于是"**不知道**"被记成"**通过**"。
      //
      // 这不是理论问题：DUT 的输入在复位竞态/悬空时会把它推成 X，而那种情况下
      // 检查的意义恰恰在于说"这里**没验到**"。实测踩过整条端到端：DUT 输入晚一拍
      // 被驱动，`queue_level` 锁成 X，而检查组件报了 `total=90 matched=90
      // mismatched=0` —— 看着全绿，其实一个 bit 都没验。
      if ($isunknown(_ok_2)) begin
        chk_unknown++;
        chk_x_raw_never_issues++;
        if (chk_first_fail == "")
          chk_first_fail = "raw_never_issues: 求值为 X（信号未知）—— 不是命中，是没验到";
      end else if (!_ok_2) begin
        chk_mismatched++;
        chk_bad_raw_never_issues++;
        if (chk_first_fail == "")
          chk_first_fail = "raw_never_issues: 存在 RAW 真依赖时不发射（dec_type==RAW 时 issue_valid 必须为 0）";
      end else begin
        chk_matched++;
      end
    end
    chk_total++;
    chk_n_raw_never_issues++;
    begin
      // **必须 `logic`（四态），不能用 `bit`** —— `bit` 是两态，X 赋进去会被
      // **静默转成 0**，于是下面那句 `$isunknown` 恒为假："求值为 X" 被读成
      // "值为 0"，再往下就成了"**违规**"。实测：误报 32 条 mismatched / 0 条
      // unverified，看着像设计违例，其实是 X 被压成了 0。
      logic _ok_3 = 1'b0;
      _ok_3 = (!(cov_vif.barrier_type != 2'd0) || (cov_vif.issue_decision == 2'd3));
      // **X 不算命中。**
      //
      // 原来直接写 `if (!(expr))`：`expr` 为 X 时 `!(X)` 也是 X，`if (X)` 取
      // **false** → 落到 `else` → `chk_matched++`。于是"**不知道**"被记成"**通过**"。
      //
      // 这不是理论问题：DUT 的输入在复位竞态/悬空时会把它推成 X，而那种情况下
      // 检查的意义恰恰在于说"这里**没验到**"。实测踩过整条端到端：DUT 输入晚一拍
      // 被驱动，`queue_level` 锁成 X，而检查组件报了 `total=90 matched=90
      // mismatched=0` —— 看着全绿，其实一个 bit 都没验。
      if ($isunknown(_ok_3)) begin
        chk_unknown++;
        chk_x_barrier_flushes++;
        if (chk_first_fail == "")
          chk_first_fail = "barrier_flushes: 求值为 X（信号未知）—— 不是命中，是没验到";
      end else if (!_ok_3) begin
        chk_mismatched++;
        chk_bad_barrier_flushes++;
        if (chk_first_fail == "")
          chk_first_fail = "barrier_flushes: 屏障命中时必须冲刷（barrier_type!=NONE → issue_decision==FLUSHED）";
      end else begin
        chk_matched++;
      end
    end
    chk_total++;
    chk_n_barrier_flushes++;
    begin
      // **必须 `logic`（四态），不能用 `bit`** —— `bit` 是两态，X 赋进去会被
      // **静默转成 0**，于是下面那句 `$isunknown` 恒为假："求值为 X" 被读成
      // "值为 0"，再往下就成了"**违规**"。实测：误报 32 条 mismatched / 0 条
      // unverified，看着像设计违例，其实是 X 被压成了 0。
      logic _ok_4 = 1'b0;
      _ok_4 = (!(cov_vif.issue_decision == 2'd0) || (cov_vif.queue_level != 6'd0 && cov_vif.barrier_type == 2'd0 && cov_vif.dep_type != 2'd1));
      // **X 不算命中。**
      //
      // 原来直接写 `if (!(expr))`：`expr` 为 X 时 `!(X)` 也是 X，`if (X)` 取
      // **false** → 落到 `else` → `chk_matched++`。于是"**不知道**"被记成"**通过**"。
      //
      // 这不是理论问题：DUT 的输入在复位竞态/悬空时会把它推成 X，而那种情况下
      // 检查的意义恰恰在于说"这里**没验到**"。实测踩过整条端到端：DUT 输入晚一拍
      // 被驱动，`queue_level` 锁成 X，而检查组件报了 `total=90 matched=90
      // mismatched=0` —— 看着全绿，其实一个 bit 都没验。
      if ($isunknown(_ok_4)) begin
        chk_unknown++;
        chk_x_issued_needs_no_blocker++;
        if (chk_first_fail == "")
          chk_first_fail = "issued_needs_no_blocker: 求值为 X（信号未知）—— 不是命中，是没验到";
      end else if (!_ok_4) begin
        chk_mismatched++;
        chk_bad_issued_needs_no_blocker++;
        if (chk_first_fail == "")
          chk_first_fail = "issued_needs_no_blocker: 发射的三个前提：队列非空、无屏障、无 RAW 真依赖";
      end else begin
        chk_matched++;
      end
    end
    chk_total++;
    chk_n_issued_needs_no_blocker++;
  endfunction
  // ── DUT 通道：取句柄 + 时钟沿采样 ──
  //
  // `get` 用的是**相对的** `this`/""（而不是 `null`/"*"）：tb_top 那边 `set(null,
  // "*", ...)` 广播，谁先建谁先取，两边不必知道对方的层次路径。
  //
  // 采样的两个条件，缺一不可：
  //   · **时钟沿** —— DUT 的信号是时序的，组合期间采到的是中间值；
  //   · **不在复位周期** —— 复位期间的水位/决策是无意义值，采进去只会把命中率
  //     弄脏（探针那边为同一个理由加了同样的屏蔽）。
  // 取句柄失败 = **接线错误**，不是"这次没覆盖率"：静默跑完只会给出一个恒 0%
  // 的数字，比停下来更难查（本仓库反复吃过"0% 与没有无从区分"的亏）。
  //
  // 消息先拼进一个 `string` 再交给宏，两个理由：
  //   · **跨行的字符串字面量在 SV 里不合法**（必须在同一行），拼接才写得下；
  //   · 宏实参里的逗号有预处理边界，塞进变量最省心。
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual npu_sched_cov_if)::get(this, "", "cov_vif", cov_vif)) begin
      string hint = {
        "DUT 覆盖率接口没挂进来（config_db 的 'cov_vif' 取不到）—— ",
        "接口是 verify 落在 coverage/npu_sched_cov_if.sv，",
        "由 tb_top 沿层次路径 <dut 实例>.u_npu_sched_cov_if 挂上。",
        "**这是接线错误，不是'这次没覆盖率'**：",
        "静默跑完只会给一个恒 0% 的数字，比停下来更难查"};
      `uvm_fatal("ENV_COV", hint)
    end
  endfunction

  task run_phase(uvm_phase phase);   // 只采样，不参与 objection（仿真由 sim_end 收口）
    forever begin
      @(posedge cov_vif.clk);
      if (cov_vif.rst_n) begin              // 复位周期不采、也不判
        cg_dut.sample();
        chk_dut_one();

      if (cov_vif.queue_level inside {0}) begin
        cov_vif.tp_seen[0] = 1'b1;
        if (!tp_hit_logged[0]) begin
          tp_hit_logged[0] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-0 cp=cp_queue_level bin=empty t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[1:7]}) begin
        cov_vif.tp_seen[1] = 1'b1;
        if (!tp_hit_logged[1]) begin
          tp_hit_logged[1] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-1 cp=cp_queue_level bin=low t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[1:7]}) begin
        cov_vif.tp_seen[2] = 1'b1;
        if (!tp_hit_logged[2]) begin
          tp_hit_logged[2] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-7 cp=cp_queue_level bin=low t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[8:15]}) begin
        cov_vif.tp_seen[3] = 1'b1;
        if (!tp_hit_logged[3]) begin
          tp_hit_logged[3] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-8 cp=cp_queue_level bin=mid t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[8:15]}) begin
        cov_vif.tp_seen[4] = 1'b1;
        if (!tp_hit_logged[4]) begin
          tp_hit_logged[4] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-15 cp=cp_queue_level bin=mid t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[16:24]}) begin
        cov_vif.tp_seen[5] = 1'b1;
        if (!tp_hit_logged[5]) begin
          tp_hit_logged[5] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-16 cp=cp_queue_level bin=high t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[16:24]}) begin
        cov_vif.tp_seen[6] = 1'b1;
        if (!tp_hit_logged[6]) begin
          tp_hit_logged[6] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-24 cp=cp_queue_level bin=high t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[25:31]}) begin
        cov_vif.tp_seen[7] = 1'b1;
        if (!tp_hit_logged[7]) begin
          tp_hit_logged[7] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-25 cp=cp_queue_level bin=near_full t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {[25:31]}) begin
        cov_vif.tp_seen[8] = 1'b1;
        if (!tp_hit_logged[8]) begin
          tp_hit_logged[8] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-31 cp=cp_queue_level bin=near_full t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.queue_level inside {32}) begin
        cov_vif.tp_seen[9] = 1'b1;
        if (!tp_hit_logged[9]) begin
          tp_hit_logged[9] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_QUEUE-32 cp=cp_queue_level bin=full t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_type inside {0}) begin
        cov_vif.tp_seen[10] = 1'b1;
        if (!tp_hit_logged[10]) begin
          tp_hit_logged[10] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_TYPE-MAC cp=cp_instr_type bin=mac t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_type inside {1}) begin
        cov_vif.tp_seen[11] = 1'b1;
        if (!tp_hit_logged[11]) begin
          tp_hit_logged[11] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_TYPE-VECTOR cp=cp_instr_type bin=vector t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_type inside {2}) begin
        cov_vif.tp_seen[12] = 1'b1;
        if (!tp_hit_logged[12]) begin
          tp_hit_logged[12] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_TYPE-SCALAR cp=cp_instr_type bin=scalar t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_type inside {3}) begin
        cov_vif.tp_seen[13] = 1'b1;
        if (!tp_hit_logged[13]) begin
          tp_hit_logged[13] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_TYPE-DMA cp=cp_instr_type bin=dma t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_dtype inside {0}) begin
        cov_vif.tp_seen[14] = 1'b1;
        if (!tp_hit_logged[14]) begin
          tp_hit_logged[14] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DTYPE-INT8 cp=cp_instr_dtype bin=int8 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_dtype inside {1}) begin
        cov_vif.tp_seen[15] = 1'b1;
        if (!tp_hit_logged[15]) begin
          tp_hit_logged[15] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DTYPE-FP16 cp=cp_instr_dtype bin=fp16 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_dtype inside {2}) begin
        cov_vif.tp_seen[16] = 1'b1;
        if (!tp_hit_logged[16]) begin
          tp_hit_logged[16] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DTYPE-BF16 cp=cp_instr_dtype bin=bf16 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_dtype inside {3}) begin
        cov_vif.tp_seen[17] = 1'b1;
        if (!tp_hit_logged[17]) begin
          tp_hit_logged[17] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DTYPE-FP32 cp=cp_instr_dtype bin=fp32 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.dep_type inside {0}) begin
        cov_vif.tp_seen[18] = 1'b1;
        if (!tp_hit_logged[18]) begin
          tp_hit_logged[18] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DEP-NONE cp=cp_dep_type bin=no_dep t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.dep_type inside {1}) begin
        cov_vif.tp_seen[19] = 1'b1;
        if (!tp_hit_logged[19]) begin
          tp_hit_logged[19] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DEP-RAW cp=cp_dep_type bin=raw t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.dep_type inside {2}) begin
        cov_vif.tp_seen[20] = 1'b1;
        if (!tp_hit_logged[20]) begin
          tp_hit_logged[20] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DEP-WAW cp=cp_dep_type bin=waw t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.dep_type inside {3}) begin
        cov_vif.tp_seen[21] = 1'b1;
        if (!tp_hit_logged[21]) begin
          tp_hit_logged[21] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DEP-WAR cp=cp_dep_type bin=war t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_unit inside {0}) begin
        cov_vif.tp_seen[22] = 1'b1;
        if (!tp_hit_logged[22]) begin
          tp_hit_logged[22] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_UNIT-MAC cp=cp_issue_unit bin=mac t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_unit inside {1}) begin
        cov_vif.tp_seen[23] = 1'b1;
        if (!tp_hit_logged[23]) begin
          tp_hit_logged[23] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_UNIT-VECTOR cp=cp_issue_unit bin=vector t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_unit inside {2}) begin
        cov_vif.tp_seen[24] = 1'b1;
        if (!tp_hit_logged[24]) begin
          tp_hit_logged[24] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_UNIT-SCALAR cp=cp_issue_unit bin=scalar t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_unit inside {3}) begin
        cov_vif.tp_seen[25] = 1'b1;
        if (!tp_hit_logged[25]) begin
          tp_hit_logged[25] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_UNIT-DMA cp=cp_issue_unit bin=dma t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_decision inside {0}) begin
        cov_vif.tp_seen[26] = 1'b1;
        if (!tp_hit_logged[26]) begin
          tp_hit_logged[26] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DECISION-ISSUED cp=cp_issue_decision bin=issued t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_decision inside {1}) begin
        cov_vif.tp_seen[27] = 1'b1;
        if (!tp_hit_logged[27]) begin
          tp_hit_logged[27] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DECISION-STALLED cp=cp_issue_decision bin=stalled t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_decision inside {2}) begin
        cov_vif.tp_seen[28] = 1'b1;
        if (!tp_hit_logged[28]) begin
          tp_hit_logged[28] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DECISION-BLOCKED cp=cp_issue_decision bin=blocked t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.issue_decision inside {3}) begin
        cov_vif.tp_seen[29] = 1'b1;
        if (!tp_hit_logged[29]) begin
          tp_hit_logged[29] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_DECISION-FLUSHED cp=cp_issue_decision bin=flushed t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.cluster_id inside {0}) begin
        cov_vif.tp_seen[30] = 1'b1;
        if (!tp_hit_logged[30]) begin
          tp_hit_logged[30] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_CLUSTER-0 cp=cp_cluster_id bin=c0 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.cluster_id inside {1}) begin
        cov_vif.tp_seen[31] = 1'b1;
        if (!tp_hit_logged[31]) begin
          tp_hit_logged[31] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_CLUSTER-1 cp=cp_cluster_id bin=c1 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.cluster_id inside {2}) begin
        cov_vif.tp_seen[32] = 1'b1;
        if (!tp_hit_logged[32]) begin
          tp_hit_logged[32] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_CLUSTER-2 cp=cp_cluster_id bin=c2 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.cluster_id inside {3}) begin
        cov_vif.tp_seen[33] = 1'b1;
        if (!tp_hit_logged[33]) begin
          tp_hit_logged[33] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_CLUSTER-3 cp=cp_cluster_id bin=c3 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {0}) begin
        cov_vif.tp_seen[34] = 1'b1;
        if (!tp_hit_logged[34]) begin
          tp_hit_logged[34] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-MAC_INT8 cp=cp_instr_opcode bin=mac_i8 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {1}) begin
        cov_vif.tp_seen[35] = 1'b1;
        if (!tp_hit_logged[35]) begin
          tp_hit_logged[35] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-MAC_FP16 cp=cp_instr_opcode bin=mac_fp16 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {2}) begin
        cov_vif.tp_seen[36] = 1'b1;
        if (!tp_hit_logged[36]) begin
          tp_hit_logged[36] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-MAC_BF16 cp=cp_instr_opcode bin=mac_bf16 t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {3}) begin
        cov_vif.tp_seen[37] = 1'b1;
        if (!tp_hit_logged[37]) begin
          tp_hit_logged[37] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-VEC_ADD cp=cp_instr_opcode bin=vec_add t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {4}) begin
        cov_vif.tp_seen[38] = 1'b1;
        if (!tp_hit_logged[38]) begin
          tp_hit_logged[38] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-VEC_MUL cp=cp_instr_opcode bin=vec_mul t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {5}) begin
        cov_vif.tp_seen[39] = 1'b1;
        if (!tp_hit_logged[39]) begin
          tp_hit_logged[39] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-VEC_RELU cp=cp_instr_opcode bin=vec_relu t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {6}) begin
        cov_vif.tp_seen[40] = 1'b1;
        if (!tp_hit_logged[40]) begin
          tp_hit_logged[40] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-LOAD cp=cp_instr_opcode bin=load t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {7}) begin
        cov_vif.tp_seen[41] = 1'b1;
        if (!tp_hit_logged[41]) begin
          tp_hit_logged[41] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-STORE cp=cp_instr_opcode bin=store t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {8}) begin
        cov_vif.tp_seen[42] = 1'b1;
        if (!tp_hit_logged[42]) begin
          tp_hit_logged[42] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-DMA_READ cp=cp_instr_opcode bin=dma_rd t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_opcode inside {9}) begin
        cov_vif.tp_seen[43] = 1'b1;
        if (!tp_hit_logged[43]) begin
          tp_hit_logged[43] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_OPCODE-DMA_WRITE cp=cp_instr_opcode bin=dma_wr t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_seq inside {0}) begin
        cov_vif.tp_seen[44] = 1'b1;
        if (!tp_hit_logged[44]) begin
          tp_hit_logged[44] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_SEQ-MAC_MAC cp=cp_instr_seq bin=mac_mac t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_seq inside {1}) begin
        cov_vif.tp_seen[45] = 1'b1;
        if (!tp_hit_logged[45]) begin
          tp_hit_logged[45] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_SEQ-LOAD_MAC cp=cp_instr_seq bin=load_mac t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_seq inside {2}) begin
        cov_vif.tp_seen[46] = 1'b1;
        if (!tp_hit_logged[46]) begin
          tp_hit_logged[46] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_SEQ-MAC_STORE cp=cp_instr_seq bin=mac_store t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_seq inside {3}) begin
        cov_vif.tp_seen[47] = 1'b1;
        if (!tp_hit_logged[47]) begin
          tp_hit_logged[47] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_SEQ-DMA_MAC cp=cp_instr_seq bin=dma_mac t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_seq inside {4}) begin
        cov_vif.tp_seen[48] = 1'b1;
        if (!tp_hit_logged[48]) begin
          tp_hit_logged[48] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_SEQ-VEC_MAC cp=cp_instr_seq bin=vec_mac t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.instr_seq inside {5}) begin
        cov_vif.tp_seen[49] = 1'b1;
        if (!tp_hit_logged[49]) begin
          tp_hit_logged[49] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_SEQ-SCALAR_MAC cp=cp_instr_seq bin=scalar_mac t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.pipeline_state inside {0}) begin
        cov_vif.tp_seen[50] = 1'b1;
        if (!tp_hit_logged[50]) begin
          tp_hit_logged[50] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PIPELINE-NONE cp=cp_pipeline_state bin=no_overlap t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.pipeline_state inside {1}) begin
        cov_vif.tp_seen[51] = 1'b1;
        if (!tp_hit_logged[51]) begin
          tp_hit_logged[51] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PIPELINE-MAC_MAC cp=cp_pipeline_state bin=mac_mac_overlap t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.pipeline_state inside {2}) begin
        cov_vif.tp_seen[52] = 1'b1;
        if (!tp_hit_logged[52]) begin
          tp_hit_logged[52] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PIPELINE-MAC_DMA cp=cp_pipeline_state bin=mac_dma_overlap t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.pipeline_state inside {3}) begin
        cov_vif.tp_seen[53] = 1'b1;
        if (!tp_hit_logged[53]) begin
          tp_hit_logged[53] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PIPELINE-VEC_MAC cp=cp_pipeline_state bin=vec_mac_overlap t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.pipeline_state inside {4}) begin
        cov_vif.tp_seen[54] = 1'b1;
        if (!tp_hit_logged[54]) begin
          tp_hit_logged[54] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PIPELINE-MULTI_OP cp=cp_pipeline_state bin=multi_op_overlap t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.op_priority inside {0}) begin
        cov_vif.tp_seen[55] = 1'b1;
        if (!tp_hit_logged[55]) begin
          tp_hit_logged[55] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PRIORITY-HIGH_FIRST cp=cp_op_priority bin=high_first t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.op_priority inside {1}) begin
        cov_vif.tp_seen[56] = 1'b1;
        if (!tp_hit_logged[56]) begin
          tp_hit_logged[56] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PRIORITY-LOW_FIRST cp=cp_op_priority bin=low_first t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.op_priority inside {2}) begin
        cov_vif.tp_seen[57] = 1'b1;
        if (!tp_hit_logged[57]) begin
          tp_hit_logged[57] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PRIORITY-SAME_PRIO cp=cp_op_priority bin=same_priority t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.op_priority inside {3}) begin
        cov_vif.tp_seen[58] = 1'b1;
        if (!tp_hit_logged[58]) begin
          tp_hit_logged[58] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_PRIORITY-ROUND_ROBIN cp=cp_op_priority bin=round_robin t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.barrier_type inside {0}) begin
        cov_vif.tp_seen[59] = 1'b1;
        if (!tp_hit_logged[59]) begin
          tp_hit_logged[59] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_BARRIER-NONE cp=cp_barrier_type bin=no_barrier t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.barrier_type inside {1}) begin
        cov_vif.tp_seen[60] = 1'b1;
        if (!tp_hit_logged[60]) begin
          tp_hit_logged[60] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_BARRIER-TILE_BARRIER cp=cp_barrier_type bin=tile_barrier t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.barrier_type inside {2}) begin
        cov_vif.tp_seen[61] = 1'b1;
        if (!tp_hit_logged[61]) begin
          tp_hit_logged[61] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_BARRIER-OP_BARRIER cp=cp_barrier_type bin=op_barrier t=%0t", $time), UVM_NONE)
        end
      end
      if (cov_vif.barrier_type inside {3}) begin
        cov_vif.tp_seen[62] = 1'b1;
        if (!tp_hit_logged[62]) begin
          tp_hit_logged[62] = 1'b1;
          `uvm_info("TP_HIT", $sformatf("tp=TP-NPUSCH-D_BARRIER-CLUSTER_BARRIER cp=cp_barrier_type bin=cluster_barrier t=%0t", $time), UVM_NONE)
        end
      end
      end
    end
  endtask

  // write 函数：每个 agent 的 monitor 采样触发**本 agent** 的 covergroup 采样
  function void write_npu_sched_in(npu_sched_in_master_seq_item t);
    npu_sched_in_item = t;
    cg_npu_sched_in.sample();
  endfunction
  function void write_npu_sched_out(npu_sched_out_master_seq_item t);
    npu_sched_out_item = t;
    cg_npu_sched_out.sample();
  endfunction

  // 报告功能覆盖率
  function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("ENV_COV", $sformatf("功能覆盖率[npu_sched_in]: %.1f%%", cg_npu_sched_in.get_inst_coverage()), UVM_NONE)
    `uvm_info("ENV_COV", $sformatf("功能覆盖率[npu_sched_out]: %.1f%%", cg_npu_sched_out.get_inst_coverage()), UVM_NONE)
    // DUT 通道也在这里报 —— 两条通道的数在**同一份报告**里，才不会各看各的
    `uvm_info("ENV_COV", $sformatf("功能覆盖率[dut]: %.1f%%", cg_dut.get_inst_coverage()), UVM_NONE)
    // ── 比对结论（**判据读的就是这一行**）──
    // 回归的判据要求出现 `mismatched=0`；没有这一行就没有比对结论，用例会判
    // `NO_CHECKER_EVIDENCE` 而不是"通过"（"没报错"不等于"验过了"）。
    if (chk_mismatched == 0 && chk_unknown == 0)
      `uvm_info("DUT_CHK", $sformatf(
        "[SCB_DUT] total=%0d matched=%0d mismatched=0", chk_total, chk_matched), UVM_NONE)
    else if (chk_mismatched == 0) begin
      // **有 X、没违规** —— 这一支**故意不打 `mismatched=0`**。
      //
      // 回归的判据就是 `grep -qE "mismatched=0"`（子串匹配）——只要这行里出现那个
      // 串，"**有拍求值为 X**"就会被判成"**验过了**"。所以这里换一个词
      //（`unverified`），让"没验到"和"验过且没过"都落在**同一个不通过**里。
      //
      // 同时报 `uvm_error`：判据的另一半是"日志里不许有 UVM_ERROR"。两条都亮，
      // 免得只看一处的读法把它读漏。
      `uvm_error("DUT_CHK", $sformatf(
        "有 %0d 拍求值为 X —— 那些拍**根本没验**（不是通过）：%s",
        chk_unknown, chk_first_fail))
      `uvm_info("DUT_CHK", $sformatf(
        "[SCB_DUT] total=%0d matched=%0d unverified=%0d（求值为 X 的拍）",
        chk_total, chk_matched, chk_unknown), UVM_NONE)
    end else begin
      if (chk_bad_queue_level_within_depth)
        `uvm_error("DUT_CHK", $sformatf("规则 %s 违规 %0d 次：队列水位超过深度 32（计数器越界）",
                   "queue_level_within_depth", chk_bad_queue_level_within_depth))
      if (chk_bad_raw_never_issues)
        `uvm_error("DUT_CHK", $sformatf("规则 %s 违规 %0d 次：存在 RAW 真依赖时不发射（dec_type==RAW 时 issue_valid 必须为 0）",
                   "raw_never_issues", chk_bad_raw_never_issues))
      if (chk_bad_barrier_flushes)
        `uvm_error("DUT_CHK", $sformatf("规则 %s 违规 %0d 次：屏障命中时必须冲刷（barrier_type!=NONE → issue_decision==FLUSHED）",
                   "barrier_flushes", chk_bad_barrier_flushes))
      if (chk_bad_issued_needs_no_blocker)
        `uvm_error("DUT_CHK", $sformatf("规则 %s 违规 %0d 次：发射的三个前提：队列非空、无屏障、无 RAW 真依赖",
                   "issued_needs_no_blocker", chk_bad_issued_needs_no_blocker))
      `uvm_info("DUT_CHK", $sformatf(
        "[SCB_DUT] total=%0d matched=%0d mismatched=%0d unverified=%0d  首条：%s",
        chk_total, chk_matched, chk_mismatched, chk_unknown, chk_first_fail), UVM_NONE)
    end
    // ── 逐条 SB 收口 ──
    //
    // 每行只数**这条 SB 自己那几条规则**（case 模型 `scoreboards[].rules`）：
    // 聚合行 `[SCB_DUT]` 说明"整轮比过了"，但签核问的是"**哪一条 SB** 比过"。
    // 规则归属来自声明，不靠猜 —— 没声明 `rules` 的 SB 就只有聚合证据。
    //
    // 与聚合行同一口径：有 X 的那支**不写 `mismatched=0`**（否则"没验到"
    // 会被 `grep` 当成"验过了"；回归判据已改为锚定 `[SCB_DUT]`/`Scoreboard:`）。
    begin
      int unsigned sb_n_1 = 0;
      int unsigned sb_bad_1 = 0;
      int unsigned sb_x_1 = 0;
      sb_n_1 += chk_n_queue_level_within_depth;
      sb_bad_1 += chk_bad_queue_level_within_depth;
      sb_x_1 += chk_x_queue_level_within_depth;
      sb_n_1 += chk_n_raw_never_issues;
      sb_bad_1 += chk_bad_raw_never_issues;
      sb_x_1 += chk_x_raw_never_issues;
      sb_n_1 += chk_n_barrier_flushes;
      sb_bad_1 += chk_bad_barrier_flushes;
      sb_x_1 += chk_x_barrier_flushes;
      sb_n_1 += chk_n_issued_needs_no_blocker;
      sb_bad_1 += chk_bad_issued_needs_no_blocker;
      sb_x_1 += chk_x_issued_needs_no_blocker;
      if (sb_x_1 == 0)
        `uvm_info("DUT_CHK", $sformatf(
          "[SCB SB-NPU-DUT] total=%0d matched=%0d mismatched=%0d",
          sb_n_1, (sb_n_1 - sb_bad_1), sb_bad_1), UVM_NONE)
      else
        `uvm_info("DUT_CHK", $sformatf(
          "[SCB SB-NPU-DUT] total=%0d matched=%0d unverified=%0d（求值为 X 的拍）",
          sb_n_1, (sb_n_1 - sb_bad_1 - sb_x_1),
          sb_x_1), UVM_NONE)
    end
  endfunction

endclass : npu_sched_env_coverage
