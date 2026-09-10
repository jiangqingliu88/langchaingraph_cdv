// ════════════════════════════════════════════════════════════════
// multich_out_of_order_scoreboard.svh —— 多通道乱序计分板
// 职责: multi_channel_out_of_order_scoreboard
//   （通道 0 = 预期，通道 1..N-1 = 实际，按事务 ID 关联匹配）
//   各通道独立 ID 挂起表；通道 0 与任一实际通道同 ID 齐备即比对
// 注: 与顺序版同限制——write() 无法区分来源 imp，多源精确分发
//   请用子类重载 write_channel() 或独立 imp 声明
// 依赖: out_of_order_scoreboard.svh
// ════════════════════════════════════════════════════════════════

`ifndef MULTICH_OUT_OF_ORDER_SCOREBOARD_SVH
`define MULTICH_OUT_OF_ORDER_SCOREBOARD_SVH

`include "out_of_order_scoreboard.svh"

//------------------------------------------------------------------------------
// 多通道乱序计分板
//   通道 0 = 预期；通道 1..NUM_CHANNELS-1 = 实际（多源汇聚）
//   按 ID 关联匹配，乱序到达也成立；比较逻辑子类可重载 compare_channels()
//------------------------------------------------------------------------------
class multi_channel_out_of_order_scoreboard #(
    type T = uvm_sequence_item,
    type ID_T = int,
    type CMP_T = default_comparator#(T),
    int NUM_CHANNELS = 2
) extends out_of_order_scoreboard#(T, ID_T, CMP_T);

  `uvm_component_param_utils(
      multi_channel_out_of_order_scoreboard#(T, ID_T, CMP_T, NUM_CHANNELS))

  // ── 通道分析端口与按 ID 挂起表 ──
  uvm_analysis_imp#(
      T, multi_channel_out_of_order_scoreboard#(T, ID_T, CMP_T, NUM_CHANNELS))
      channel_export[NUM_CHANNELS];
  protected T m_channel_pending[NUM_CHANNELS][ID_T];

  function new(string name, uvm_component parent);
    super.new(name, parent);
    foreach (channel_export[i])
      channel_export[i] = new($sformatf("channel_%0d_export", i), this);
  endfunction

  //--------------------------------------------------------------------------
  // 统一 write 入口：按「最早空通道」入队（与多通道顺序版同策略）
  //--------------------------------------------------------------------------
  function void write(T item);
    for (int i = 0; i < NUM_CHANNELS; i++) begin
      if (m_channel_pending[i].size() == 0) begin
        write_channel(i, item);
        return;
      end
    end
    write_channel(0, item);   // 全忙时兜底进通道 0
  endfunction

  //--------------------------------------------------------------------------
  // 写入指定通道（按 ID 挂起，同通道重 ID 报错）
  //--------------------------------------------------------------------------
  function void write_channel(int channel, T item);
    ID_T id;

    if (channel >= NUM_CHANNELS) begin
      `uvm_error(get_name(), $sformatf("invalid channel %0d", channel))
      return;
    end

    id = get_id(item);
    if (m_channel_pending[channel].exists(id)) begin
      `uvm_error(get_name(), $sformatf("duplicate ID %0s on channel %0d",
                 convert2string_id(id), channel))
      return;
    end

    m_channel_pending[channel][id] = item;
    if (channel == 0)
      m_num_expected++;
    else
      m_num_actual++;
    `uvm_info(get_name(), $sformatf("channel %0d pending [id=%0s]: %s",
               channel, convert2string_id(id), convert2string(item)), UVM_HIGH)

    compare_channels(id);
  endfunction

  //--------------------------------------------------------------------------
  // 跨通道比较（子类可重载）：通道 0 与各实际通道按 ID 匹配，
  // 不匹配报错并摘除该 ID
  //--------------------------------------------------------------------------
  protected virtual function void compare_channels(ID_T id);
    if (NUM_CHANNELS < 2 || !m_channel_pending[0].exists(id))
      return;

    for (int c = 1; c < NUM_CHANNELS; c++) begin
      if (!m_channel_pending[c].exists(id))
        continue;

      if (compare_items(m_channel_pending[0][id], m_channel_pending[c][id])) begin
        m_num_matches++;
        `uvm_info(get_name(), $sformatf("match [id=%0s] channel 0 vs %0d",
                   convert2string_id(id), c), UVM_HIGH)
      end else begin
        m_num_mismatches++;
        `uvm_error(get_name(), $sformatf(
            "channel mismatch [id=%0s] channel 0 vs %0d\n  expected: %s\n  actual: %s",
            convert2string_id(id), c,
            convert2string(m_channel_pending[0][id]),
            convert2string(m_channel_pending[c][id])))
      end

      m_channel_pending[0].delete(id);
      m_channel_pending[c].delete(id);
      return;
    end
  endfunction

  //--------------------------------------------------------------------------
  // 刷新：通道 0 剩余 → missing（预期）；其余通道剩余 → extra（实际）
  //--------------------------------------------------------------------------
  virtual function void flush();
    for (int i = 0; i < NUM_CHANNELS; i++) begin
      if (i == 0) begin
        foreach (m_channel_pending[i][id]) begin
          m_num_missing++;
          `uvm_info(get_name(), $sformatf("missing [id=%0s]: %s",
                     convert2string_id(id),
                     convert2string(m_channel_pending[i][id])), UVM_LOW)
        end
      end else begin
        foreach (m_channel_pending[i][id]) begin
          m_num_extra++;
          `uvm_info(get_name(), $sformatf("extra [id=%0s]: %s",
                     convert2string_id(id),
                     convert2string(m_channel_pending[i][id])), UVM_LOW)
        end
      end
      m_channel_pending[i].delete();
    end
  endfunction

endclass : multi_channel_out_of_order_scoreboard

`endif // MULTICH_OUT_OF_ORDER_SCOREBOARD_SVH
