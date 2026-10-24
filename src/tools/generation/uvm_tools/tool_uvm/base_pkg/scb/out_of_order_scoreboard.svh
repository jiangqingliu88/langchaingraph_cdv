// ════════════════════════════════════════════════════════════════
// out_of_order_scoreboard.svh —— 乱序计分板（ID 关联匹配）
// 职责: 扩展顺序计分板，按事务 ID 做 pending 关联匹配，
//       乱序到达的 expected/actual 只要 ID 相同即可比对
// 用法: 子类重载 get_id() 返回事务 ID；ID_T 缺省 int
// ════════════════════════════════════════════════════════════════

`ifndef OUT_OF_ORDER_SCOREBOARD_SVH
`define OUT_OF_ORDER_SCOREBOARD_SVH

`include "in_order_scoreboard.svh"

class out_of_order_scoreboard #(
    type T     = uvm_sequence_item,
    type ID_T  = int,
    type CMP_T = default_comparator#(T)
) extends in_order_scoreboard#(T, T, CMP_T);

  `uvm_component_param_utils(out_of_order_scoreboard#(T, ID_T, CMP_T))

  // ── 按 ID 挂起的预期/实际事务 ──
  protected T m_pending_expected[ID_T];
  protected T m_pending_actual[ID_T];

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  //--------------------------------------------------------------------------
  // 事务 ID（子类重载；默认假设事务带 get_id()）
  //--------------------------------------------------------------------------
  protected virtual function ID_T get_id(T item);
    return item.get_id();
  endfunction

  //--------------------------------------------------------------------------
  // 预期入口：按 ID 挂起，两表同 ID 齐备即比对
  //--------------------------------------------------------------------------
  virtual function void write_expected(T item);
    ID_T id = get_id(item);

    if (m_pending_expected.exists(id)) begin
      `uvm_error(get_name(), $sformatf("duplicate expected ID %0s",
                 convert2string_id(id)))
      return;
    end

    m_pending_expected[id] = item;
    m_num_expected++;
    `uvm_info(get_name(), $sformatf("expected pending [id=%0s]",
               convert2string_id(id)), UVM_HIGH)

    try_match_id(id);
  endfunction

  //--------------------------------------------------------------------------
  // 实际入口：按 ID 挂起，两表同 ID 齐备即比对
  //--------------------------------------------------------------------------
  virtual function void write_actual(T item);
    ID_T id = get_id(item);

    if (m_pending_actual.exists(id)) begin
      `uvm_error(get_name(), $sformatf("duplicate actual ID %0s",
                 convert2string_id(id)))
      return;
    end

    m_pending_actual[id] = item;
    m_num_actual++;
    `uvm_info(get_name(), $sformatf("actual pending [id=%0s]",
               convert2string_id(id)), UVM_HIGH)

    try_match_id(id);
  endfunction

  //--------------------------------------------------------------------------
  // 尝试匹配指定 ID（两侧齐备才比对；不匹配立即报错并摘除）
  //--------------------------------------------------------------------------
  protected function void try_match_id(ID_T id);
    if (!(m_pending_expected.exists(id) && m_pending_actual.exists(id)))
      return;

    if (compare_items(m_pending_expected[id], m_pending_actual[id])) begin
      m_num_matches++;
      `uvm_info(get_name(), $sformatf("match [id=%0s]",
                 convert2string_id(id)), UVM_HIGH)
    end else begin
      m_num_mismatches++;
      `uvm_error(get_name(), $sformatf("mismatch [id=%0s]\n  expected: %s\n  actual: %s",
                 convert2string_id(id),
                 convert2string(m_pending_expected[id]),
                 convert2string(m_pending_actual[id])))
    end

    m_pending_expected.delete(id);
    m_pending_actual.delete(id);
  endfunction

  //--------------------------------------------------------------------------
  // 刷新：挂起表剩余 → missing（预期）/ extra（实际）
  //--------------------------------------------------------------------------
  virtual function void flush();
    foreach (m_pending_expected[id]) begin
      m_num_missing++;
      `uvm_info(get_name(), $sformatf("missing [id=%0s]: %s",
                 convert2string_id(id),
                 convert2string(m_pending_expected[id])), UVM_LOW)
    end
    foreach (m_pending_actual[id]) begin
      m_num_extra++;
      `uvm_info(get_name(), $sformatf("extra [id=%0s]: %s",
                 convert2string_id(id),
                 convert2string(m_pending_actual[id])), UVM_LOW)
    end

    m_pending_expected.delete();
    m_pending_actual.delete();
  endfunction

  // ID 打印（子类可重载，默认 $sformatf）
  protected virtual function string convert2string_id(ID_T id);
    return $sformatf("%0d", id);
  endfunction

endclass : out_of_order_scoreboard

`endif // OUT_OF_ORDER_SCOREBOARD_SVH
