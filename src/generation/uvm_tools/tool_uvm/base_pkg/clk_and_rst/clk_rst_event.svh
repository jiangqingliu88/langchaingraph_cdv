// ════════════════════════════════════════════════════════════════
// clk_rst_event.svh —— 时钟复位事件（monitor 分析端口载荷）
// 职责: clk_rst_event_type 枚举 + clk_rst_event 事务
//   （CLK_POSEDGE/CLK_NEGEDGE/RST_ASSERT/RST_DEASSERT + idx/ev_time/period）
// 依赖: 无
// ════════════════════════════════════════════════════════════════

`ifndef CLK_RST_EVENT_SVH
`define CLK_RST_EVENT_SVH

// ── 3. Event (Monitor 引用，放前面) ──
typedef enum { CLK_POSEDGE, CLK_NEGEDGE, RST_ASSERT, RST_DEASSERT } clk_rst_event_type;

class clk_rst_event extends uvm_sequence_item;
  `uvm_object_utils(clk_rst_event)
  clk_rst_event_type ev_type;
  int                idx;
  realtime           ev_time;
  realtime           period;
  function new(string name = "clk_rst_event");
    super.new(name);
  endfunction
endclass

`endif // CLK_RST_EVENT_SVH
