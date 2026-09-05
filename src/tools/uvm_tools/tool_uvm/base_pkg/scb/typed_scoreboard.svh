// ════════════════════════════════════════════════════════════════
// typed_scoreboard.svh —— 类型特化计分板
// 职责:
//   1. DEFINE_TYPED_SCOREBOARD 宏 —— 一行声明特化计分板（typedef + 子类注册）
//   2. multi_channel_scoreboard —— 多通道计分板（通道 0 = 预期，通道 1..N = 实际）
// ════════════════════════════════════════════════════════════════

`ifndef TYPED_SCOREBOARD_SVH
`define TYPED_SCOREBOARD_SVH

`include "in_order_scoreboard.svh"

//------------------------------------------------------------------------------
// 类型重载宏：生成 <NAME> 特化计分板（工厂可注册）
//   NAME  计分板类名
//   REQ_T 实际事务类型
//   RSP_T 预期事务类型
//   CMP_T 比较器类型（如 alu_comparator）
//------------------------------------------------------------------------------
`define DEFINE_TYPED_SCOREBOARD(NAME, REQ_T, RSP_T, CMP_T) \
    typedef in_order_scoreboard#(REQ_T, RSP_T, CMP_T) NAME``_base_t; \
    class NAME extends NAME``_base_t; \
      `uvm_component_utils(NAME) \
      function new(string name, uvm_component parent); \
        super.new(name, parent); \
      endfunction \
    endclass

//------------------------------------------------------------------------------
// 多通道计分板
//   通道 0 = 预期；通道 1..NUM_CHANNELS-1 = 实际（多源汇聚）
//   比较逻辑子类可重载 compare_channels()
//------------------------------------------------------------------------------
class multi_channel_scoreboard #(
    type T = uvm_sequence_item,
    type CMP_T = default_comparator#(T),
    int NUM_CHANNELS = 2
) extends in_order_scoreboard#(T, T, CMP_T);

  `uvm_component_param_utils(multi_channel_scoreboard#(T, CMP_T, NUM_CHANNELS))

  // ── 通道分析端口与队列 ──
  uvm_analysis_imp#(T, multi_channel_scoreboard#(T, CMP_T, NUM_CHANNELS))
      channel_export[NUM_CHANNELS];
  protected T m_channel_queues[NUM_CHANNELS][$];

  function new(string name, uvm_component parent);
    super.new(name, parent);
    foreach (channel_export[i])
      channel_export[i] = new($sformatf("channel_%0d_export", i), this);
  endfunction

  //--------------------------------------------------------------------------
  // 统一 write 入口：按 imp 实例编号分发（channel_export[i] 各连一个源）
  //--------------------------------------------------------------------------
  function void write(T item);
    // 分发到最早有挂起数据的通道：默认约定 imp 索引即通道号，
    // 但 write() 无法区分来源 imp；因此这里按「最早空通道」入队，
    // 精确多源分发请用子类重载或改用独立 imp 声明（uvm_analysis_imp_decl）。
    for (int i = 0; i < NUM_CHANNELS; i++) begin
      if (m_channel_queues[i].size() == 0) begin
        write_channel(i, item);
        return;
      end
    end
    write_channel(0, item);   // 全忙时兜底进通道 0
  endfunction

  //--------------------------------------------------------------------------
  // 写入指定通道
  //--------------------------------------------------------------------------
  function void write_channel(int channel, T item);
    if (channel >= NUM_CHANNELS) begin
      `uvm_error(get_name(), $sformatf("invalid channel %0d", channel))
      return;
    end

    m_channel_queues[channel].push_back(item);
    `uvm_info(get_name(), $sformatf("channel %0d +1: %s",
               channel, convert2string(item)), UVM_HIGH)

    compare_channels();
  endfunction

  //--------------------------------------------------------------------------
  // 跨通道比较（子类可重载）：默认通道 0 vs 通道 1 顺序比对
  //--------------------------------------------------------------------------
  protected virtual function void compare_channels();
    if (NUM_CHANNELS < 2)
      return;

    while (m_channel_queues[0].size() > 0 && m_channel_queues[1].size() > 0) begin
      if (!compare_items(m_channel_queues[0][0], m_channel_queues[1][0]))
        break;
      void'(m_channel_queues[0].pop_front());
      void'(m_channel_queues[1].pop_front());
      m_num_matches++;
      `uvm_info(get_name(), "channel match (0 vs 1)", UVM_HIGH)
    end
  endfunction

  //--------------------------------------------------------------------------
  // 刷新：各通道剩余计入 missing（通道 0）/ extra（其余通道）
  //--------------------------------------------------------------------------
  virtual function void flush();
    for (int i = 0; i < NUM_CHANNELS; i++) begin
      if (i == 0)
        m_num_missing += m_channel_queues[i].size();
      else
        m_num_extra   += m_channel_queues[i].size();
      m_channel_queues[i].delete();
    end
  endfunction

endclass : multi_channel_scoreboard

`endif // TYPED_SCOREBOARD_SVH
