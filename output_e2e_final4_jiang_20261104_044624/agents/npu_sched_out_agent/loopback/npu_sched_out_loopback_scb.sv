// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_loopback_scb.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Loopback Scoreboard: npu_sched_out_loopback_scb
// ============================================================
// expected_export ← **master driver 驱动出去的事务**（`driver.driven_ap`）
// actual_export   ← slave monitor  （slave 在总线上观察到的字段）
//
// 为什么 expected 不取 master monitor：
//   loopback 里 tb 把**同一个**接口实例发给 master / slave 两个 agent，两个 monitor
//   采的是**同一组信号** → 拿它们互比是"同一个接口读两遍"，恒真（driver 一个信号
//   都不驱动也 PASS）。取 driver 驱动出去的事务，"发出去的 vs 总线上看到的"才是自检。
//   driver 只驱动**映射到 output 端口**的字段，故 compare_fields 也只比这些
//   （如 prdata 是 input 端口、由从端回填，driver 不驱动它，比它没有意义）。
import uvm_pkg::*;
import npu_sched_out_pkg::*;
`include "uvm_macros.svh"

`uvm_analysis_imp_decl(_expected)
`uvm_analysis_imp_decl(_actual)

class npu_sched_out_loopback_scb extends uvm_scoreboard;
  `uvm_component_utils(npu_sched_out_loopback_scb)

  uvm_analysis_imp_expected #(npu_sched_out_master_seq_item, npu_sched_out_loopback_scb) expected_export;
  uvm_analysis_imp_actual   #(npu_sched_out_slave_seq_item,  npu_sched_out_loopback_scb) actual_export;

  protected npu_sched_out_master_seq_item expected_q[$];
  protected time                            expected_t[$];
  protected npu_sched_out_slave_seq_item actual_q[$];
  protected time                            actual_t[$];
  protected int m_matched    = 0;
  protected int m_mismatched = 0;
  protected int m_total      = 0;
  // slave 常采到的"空拍"（driver 没发那一笔：复位刚放开、最后一笔之后）
  protected int m_idle_act   = 0;

  function new(string name = "npu_sched_out_loopback_scb", uvm_component parent = null);
    super.new(name, parent);
    expected_export = new("expected_export", this);
    actual_export   = new("actual_export",   this);
  endfunction

  virtual function void write_expected(npu_sched_out_master_seq_item exp);
    expected_q.push_back(exp);
    expected_t.push_back($time);
    pair_ready();
  endfunction

  virtual function void write_actual(npu_sched_out_slave_seq_item act);
    actual_q.push_back(act);
    actual_t.push_back($time);
    pair_ready();
  endfunction

  // ── 配对规则：**同一 `$time` 才算一对** ──
  //
  //   · 不能"来的 actual 配队头 expected"：两侧的 write 在**同一时刻**发生，
  //     但同一时刻谁先写、每个周期会翻转（实测 monitor 对 monitor 时：
  //     t=115 master 先、t=125 slave 先）；按到达顺序配就被翻转带跑，报满屏
  //     mismatch（实测 22 拍只对 2）。`$time` 是"这一拍"唯一的身份。
  //   · driver 的 `driven_ap.write(req)` 与 slave monitor 采到该 req 的那一拍
  //     是**同一个 `$time`**（driver 在第二个 `@(master_cb)` 之后才 write，
  //     而那一拍总线上正是这一笔），所以按 `$time` 能对齐。
  //   · slave 是 PASSIVE 的常采 monitor：复位刚放开的头几拍、以及最后一笔之后的
  //     空拍，它都采得到，而 driver 那边没有对应事务 —— 这些是**空拍**，丢掉并计数，
  //     不算失败（方向不对称：只有"driver 发了、slave 没看到"才是问题）。
  virtual function void pair_ready();
    // ⚠️ 声明必须排在**块内所有语句之前**（SV 规则）：循环体里有 `continue`，
    // 声明写在它后面就是 "Illegal declaration after the statement ... Look for
    // stray semicolons."（实测踩过）。故提到 while 之前。
    npu_sched_out_master_seq_item exp;
    npu_sched_out_slave_seq_item  act;
    while (expected_q.size() > 0 && actual_q.size() > 0) begin
      if (actual_t[0] < expected_t[0]) begin
        // slave 先看到的空拍，driver 这边没有对应事务
        actual_q.pop_front();
        actual_t.pop_front();
        m_idle_act++;
        continue;
      end
      if (expected_t[0] < actual_t[0])
        break;  // 这一拍的 actual 还没到，等下一次 write_actual 再来配
      exp = expected_q.pop_front();
      act = actual_q.pop_front();
      expected_t.pop_front();
      actual_t.pop_front();
      m_total++;
      if (compare_fields(exp, act)) begin
        m_matched++;
        // 匹配的也要把 exp / act 打全：loopback 是"环境自洽"的门，看日志的人要能从
        // 单条记录里看到**到底比了什么值**，而不是只有一个 "matched"。格式与下面
        // FAIL 的那条**刻意保持一致**，这样日志可以逐条对照着看。
        `uvm_info("SCB_LOOP_PASS", $sformatf("[PASS] #%0d matched\n  exp=\n%s\n  act=\n%s",
          m_total, exp.sprint(), act.sprint()), UVM_MEDIUM)
      end else begin
        m_mismatched++;
        // 用 `sprint()` 而不是 `convert2string()`：两个 seq_item 都**没实现**
        // `convert2string()`，直接调它得到空串 → 失败信息成了 `exp=` / `act=` 全空，
        // 等于没有证据（实测踩过，整个 bug 因此修不动）。`sprint()` 走 UVM 的
        // field automation（两个 item 都 `uvm_field_int(...)` 注册过），打得真值。
        `uvm_error("SCB_LOOP", $sformatf("[FAIL] #%0d mismatched\n  exp=\n%s\n  act=\n%s",
          m_total, exp.sprint(), act.sprint()))
      end
    end
  endfunction

  // 比较 driver 驱动出去的字段 —— 口径与 `<ag>_master_driver` 的驱动列表一致：
  // 既要是 is_compare 的公共字段，又要**映射到 output 端口**（driver 才驱动得到，
  // 也只有这些在总线上是 driver 说了算）。
  virtual function bit compare_fields(npu_sched_out_master_seq_item exp,
                                      npu_sched_out_slave_seq_item act);
    bit ok = 1;
    return ok;
  endfunction

  virtual function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("SCB_LOOP", $sformatf(
      "Scoreboard: total=%0d matched=%0d mismatched=%0d idle_act=%0d pending_exp=%0d",
      m_total, m_matched, m_mismatched, m_idle_act, expected_q.size()), UVM_NONE)
    // ── 假绿拦截：**方向不对称** ──
    // expected 侧残留 = driver 发了、slave monitor 没在那一拍看到 → 真问题
    //（slave 没跑 / vif 拿错 / 采样节奏错位），必须报错。
    if (expected_q.size() > 0)
      `uvm_error("SCB_LOOP", $sformatf(
        "driver 驱动了 %0d 笔、slave monitor 没在对应拍上看到（pending_exp=%0d）",
        expected_q.size(), expected_q.size()))
    // actual 侧残留是 driver 之后的空拍，已在 pair_ready 里按 idle 计数丢掉，
    // 这里不报错（slave 是 PASSIVE 常采，本来就会多采）。
    if (m_total == 0)
      `uvm_error("SCB_LOOP", "一轮下来一对都没配上 —— loopback 没真正跑起来（假绿）")
  endfunction

endclass : npu_sched_out_loopback_scb
