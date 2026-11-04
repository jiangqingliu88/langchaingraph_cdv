`ifndef NPU_SCHED_COV_IF_SV
`define NPU_SCHED_COV_IF_SV

// 覆盖率采样接口 —— 由 case/覆盖率模型生成（casemodel_tools.coverage）
// `bind` 到 `npu_sched`：端口连接表达式在该模块作用域里求值，
// 所以输入端口 / 输出端口 / **内部寄存器** 一视同仁地连得进来。
//
// 它只**引信号**，不采样 —— 采样由 env 的覆盖率组件做（`coverpoint vif.<信号>`，
// 时钟沿 + 复位屏蔽），这样覆盖率跟着 UVM 的报告走。
//
// bind 出来的实例是 `u_npu_sched_cov_if`，它在 DUT 的作用域里 —— 所以
// tb_top 用层次路径挂给组件：`config_db::set(..., <dut 实例>.
// u_npu_sched_cov_if)`。两边的名字都来自同一份 meta（`cov_interface_meta`）。

interface npu_sched_cov_if (
  input logic clk,
  input logic rst_n,
  input logic [5:0] queue_level,
  input logic [2:0] instr_type,
  input logic [2:0] instr_dtype,
  input logic [1:0] dep_type,
  input logic [2:0] issue_unit,
  input logic [1:0] issue_decision,
  input logic [1:0] cluster_id,
  input logic [7:0] instr_opcode,
  input logic [7:0] instr_seq,
  input logic [2:0] pipeline_state,
  input logic [1:0] op_priority,
  input logic [1:0] barrier_type,
  input logic issue_valid
);

  // 测试点位图（位序 = coverage/tp_bitmap.json 的 entries[].bit）
  logic [69:0] tp_seen;
endinterface : npu_sched_cov_if

bind npu_sched npu_sched_cov_if u_npu_sched_cov_if(
  .clk(clk),
  .rst_n(rst_n),
  .queue_level(queue_level),
  .instr_type(instr_type),
  .instr_dtype(instr_dtype),
  .dep_type(dep_type),
  .issue_unit(issue_unit),
  .issue_decision(issue_decision),
  .cluster_id(cluster_id),
  .instr_opcode(instr_opcode),
  .instr_seq(instr_seq),
  .pipeline_state(pipeline_state),
  .op_priority(op_priority),
  .barrier_type(barrier_type),
  .issue_valid(issue_valid)
);

`endif  // NPU_SCHED_COV_IF_SV
