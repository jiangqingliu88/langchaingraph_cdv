// ════════════════════════════════════════════════════════════════
// typed_scoreboard.svh —— 类型特化计分板
// 职责:
//   1. DEFINE_TYPED_SCOREBOARD 宏 —— 一行声明特化计分板（typedef + 子类注册）
//   2. typed_scoreboard 便捷类 —— 单类型参数（REQ_T = RSP_T = T）顺序计分板
// 依赖: in_order_scoreboard.svh
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
// 便捷类：单类型顺序计分板（REQ_T = RSP_T = T）
//------------------------------------------------------------------------------
class typed_scoreboard #(type T = uvm_sequence_item)
    extends in_order_scoreboard#(T, T);

  `uvm_component_param_utils(typed_scoreboard#(T))

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

endclass : typed_scoreboard

`endif // TYPED_SCOREBOARD_SVH
