// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_master_sequence.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Master Sequence: npu_sched_out_master_sequence
// ============================================================
class npu_sched_out_master_sequence extends uvm_sequence #(npu_sched_out_master_seq_item);
  `uvm_object_utils(npu_sched_out_master_sequence)
  `uvm_declare_p_sequencer(npu_sched_out_master_sequencer)

  // 本序列驱动多少笔事务。环境级 virtual sequence 会覆写它
  //（`<env>_virtual_base_seq::send_<agent>_random(count)`）。
  // 少了这个字段，virtual_base_seq 里那行 `_rs.num_transactions = count;`
  // 在 vopt 阶段就报 "Failed to find 'num_transactions'" —— **整个设计加载不了**。
  rand int unsigned num_transactions = 10;

  // ── 属性 test 的激励通道（模型 `stimulus.field` 那一半）──
  //
  // 属性 test 在 build_phase 里 `set("<字段>_int", <取值>)`；这里逐字段读回来，
  // 读到了就把它**钉死**在事务上。没设的（`has_* = 0`）保持自由随机 ——
  // 所以普通 test / 批次 test 的行为一字不变。
  //
  // 为什么放在序列里而不是 test 里：事务对象是序列创建的，只有这里能对它
  // `randomize() with {...}`；test 那层根本碰不到 req。
  //
  // 只列**事务上真实存在**的 rand 字段（模板从 agent 的事务定义生成）：
  // 模型里的 `queue_level` / `issue_unit` 这类 DUT 内部量没有对应字段，
  // 永远不会出现在这里 —— 它们由覆盖仓（bind 探针）采，不靠激励。
  bit has_issue_valid = 1'b0;
  int attr_issue_valid = 0;
  // sequence 场景通道：test 写 <field>_seq_len / <field>_seq_<i>，这里逐笔取值。
  // 上限 8 笔是**显式边界**：超过就截断并在日志里说明，不静默丢。
  int attr_issue_valid_seq[8];
  int attr_issue_valid_seq_len = 0;
  bit has_issue_unit = 1'b0;
  int attr_issue_unit = 0;
  // sequence 场景通道：test 写 <field>_seq_len / <field>_seq_<i>，这里逐笔取值。
  // 上限 8 笔是**显式边界**：超过就截断并在日志里说明，不静默丢。
  int attr_issue_unit_seq[8];
  int attr_issue_unit_seq_len = 0;
  bit has_issue_decision = 1'b0;
  int attr_issue_decision = 0;
  // sequence 场景通道：test 写 <field>_seq_len / <field>_seq_<i>，这里逐笔取值。
  // 上限 8 笔是**显式边界**：超过就截断并在日志里说明，不静默丢。
  int attr_issue_decision_seq[8];
  int attr_issue_decision_seq_len = 0;

  function new(string name = "npu_sched_out_master_sequence");
    super.new(name);
  endfunction
  virtual task pre_body();
    // 用 sequencer 作上下文：属性 test 是 `set(this, "*", ...)` 设的，
    // 从这里沿父作用域向上找得到（标准 config_db 作用域解析）。
    has_issue_valid = uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_int", attr_issue_valid);
    // sequence 场景：读逐笔取值。没有这个键时 len=0，行为与普通属性 test 一致。
    void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_len",
                                  attr_issue_valid_seq_len));
    if (attr_issue_valid_seq_len > 0) begin
      if (attr_issue_valid_seq_len > 8) begin
        `uvm_warning("SEQ", "issue_valid_seq_len 超过 8，截断为 8 笔")
        attr_issue_valid_seq_len = 8;
      end
      has_issue_valid = 1'b1;
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_0", attr_issue_valid_seq[0]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_1", attr_issue_valid_seq[1]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_2", attr_issue_valid_seq[2]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_3", attr_issue_valid_seq[3]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_4", attr_issue_valid_seq[4]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_5", attr_issue_valid_seq[5]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_6", attr_issue_valid_seq[6]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_valid_seq_7", attr_issue_valid_seq[7]));
    end
    has_issue_unit = uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_int", attr_issue_unit);
    // sequence 场景：读逐笔取值。没有这个键时 len=0，行为与普通属性 test 一致。
    void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_len",
                                  attr_issue_unit_seq_len));
    if (attr_issue_unit_seq_len > 0) begin
      if (attr_issue_unit_seq_len > 8) begin
        `uvm_warning("SEQ", "issue_unit_seq_len 超过 8，截断为 8 笔")
        attr_issue_unit_seq_len = 8;
      end
      has_issue_unit = 1'b1;
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_0", attr_issue_unit_seq[0]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_1", attr_issue_unit_seq[1]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_2", attr_issue_unit_seq[2]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_3", attr_issue_unit_seq[3]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_4", attr_issue_unit_seq[4]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_5", attr_issue_unit_seq[5]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_6", attr_issue_unit_seq[6]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_unit_seq_7", attr_issue_unit_seq[7]));
    end
    has_issue_decision = uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_int", attr_issue_decision);
    // sequence 场景：读逐笔取值。没有这个键时 len=0，行为与普通属性 test 一致。
    void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_len",
                                  attr_issue_decision_seq_len));
    if (attr_issue_decision_seq_len > 0) begin
      if (attr_issue_decision_seq_len > 8) begin
        `uvm_warning("SEQ", "issue_decision_seq_len 超过 8，截断为 8 笔")
        attr_issue_decision_seq_len = 8;
      end
      has_issue_decision = 1'b1;
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_0", attr_issue_decision_seq[0]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_1", attr_issue_decision_seq[1]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_2", attr_issue_decision_seq[2]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_3", attr_issue_decision_seq[3]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_4", attr_issue_decision_seq[4]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_5", attr_issue_decision_seq[5]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_6", attr_issue_decision_seq[6]));
      void'(uvm_config_db#(int)::get(get_sequencer(), "", "issue_decision_seq_7", attr_issue_decision_seq[7]));
    end
  endtask

  virtual task body();
    npu_sched_out_port_config cfg;
    // 1. 向 p_sequencer 请求配置，存入 cfg
    p_sequencer.get_cfg(cfg);
    if (cfg == null)
      `uvm_error(get_type_name(), "Sequencer cfg is null (agent build 未传入 config_db)")
    // 2. 交替发读写，共 num_transactions 笔
    //
    // sequence 场景（`*_seq_len > 0`）下改成**逐笔按序取值**：第 i 笔把字段
    // 钉成 `attr_<field>_seq[i % len]`。这就是"相邻指令组合"能被确定驱动的
    // 唯一位置 —— test 那层碰不到事务对象。
    if (attr_issue_valid_seq_len > 0)
      num_transactions = attr_issue_valid_seq_len;
    for (int i = 0; i < int'(num_transactions); i++) begin
      if (attr_issue_valid_seq_len > 0)
        attr_issue_valid =
            attr_issue_valid_seq[i % attr_issue_valid_seq_len];
      if ($urandom_range(0, 1)) do_write();
      else                     do_read();
    end
  endtask
  virtual task post_body();
  endtask

  // **不要在这里调 `get_response()`**：本环境约定 driver 用 `item_done()`（无参）
  // 结束事务、**不产生响应**，读回的 prdata/pslverr 由 driver **就地写回同一条
  // req 对象**（见 reg_adapter 的 provides_responses=0）。
  // `get_response()` 会等响应队列，而队列永远是空的 → 序列永久阻塞。
  task do_write();
    npu_sched_out_master_seq_item req = npu_sched_out_master_seq_item::type_id::create("req");
    start_item(req);
    // `has_<字段> -> 字段 == 取值`：只有属性 test 设过这个字段时才加约束，
    // 否则前件为假、约束恒真 —— 普通 test 的随机分布不受影响。
    assert(req.randomize() with {
      xact_type == WRITE;
      has_issue_valid -> issue_valid == attr_issue_valid;
      has_issue_unit -> issue_unit == attr_issue_unit;
      has_issue_decision -> issue_decision == attr_issue_decision;
    });
    finish_item(req);
  endtask

  task do_read();
    npu_sched_out_master_seq_item req = npu_sched_out_master_seq_item::type_id::create("req");
    start_item(req);
    assert(req.randomize() with {
      xact_type == READ;
      has_issue_valid -> issue_valid == attr_issue_valid;
      has_issue_unit -> issue_unit == attr_issue_unit;
      has_issue_decision -> issue_decision == attr_issue_decision;
    });
    finish_item(req);
  endtask

  // pragma custom seq_body begin
  // pragma custom seq_body end
endclass : npu_sched_out_master_sequence
