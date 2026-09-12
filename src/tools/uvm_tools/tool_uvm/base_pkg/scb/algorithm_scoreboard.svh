// ════════════════════════════════════════════════════════════════
// algorithm_scoreboard.svh —— 算法计分板（内嵌参考模型）
// 职责: 请求进来即用参考模型 predict() 算期望，响应回来比对；
//       适合「请求 → 期望可即时计算」的流水/计算类 DUT
// 用法: 子类实现 predict()（必要时重载 compare()）
// ════════════════════════════════════════════════════════════════

`ifndef ALGORITHM_SCOREBOARD_SVH
`define ALGORITHM_SCOREBOARD_SVH

// 响应侧 imp 用命名宏（write_resp 回调），避免 REQ_T == RESP_T 时
// write(T) 重载重定义冲突
`uvm_analysis_imp_decl(_resp)

// virtual: 含 pure virtual predict()，按 LRM 8.21 须声明为虚类（不可直接例化）
virtual class algorithm_scoreboard #(
    type REQ_T  = uvm_sequence_item,
    type RESP_T = uvm_sequence_item
) extends uvm_scoreboard;

  `uvm_component_param_utils(algorithm_scoreboard#(REQ_T, RESP_T))

  // ── 请求/响应分析端口（回调 write / write_resp）──
  uvm_analysis_imp#(REQ_T,  algorithm_scoreboard#(REQ_T, RESP_T)) req_export;
  uvm_analysis_imp_resp#(RESP_T, algorithm_scoreboard#(REQ_T, RESP_T)) resp_export;

  // ── 挂起请求队列（FIFO：响应按请求顺序回）──
  protected REQ_T m_pending_reqs[$];

  // ── 统计 ──
  protected int m_num_reqs       = 0;
  protected int m_num_resps      = 0;
  protected int m_num_matches    = 0;
  protected int m_num_mismatches = 0;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    req_export  = new("req_export", this);
    resp_export = new("resp_export", this);
  endfunction

  //--------------------------------------------------------------------------
  // 参考模型：请求 → 期望响应（纯虚，子类实现）
  //--------------------------------------------------------------------------
  pure virtual function RESP_T predict(REQ_T req);

  //--------------------------------------------------------------------------
  // 比对（子类可重载，默认走事务 compare）
  //--------------------------------------------------------------------------
  protected virtual function bit compare(RESP_T expected, RESP_T actual);
    return expected.compare(actual);
  endfunction

  //--------------------------------------------------------------------------
  // 请求入口（DUT 输入侧 monitor → req_export）
  //--------------------------------------------------------------------------
  function void write(REQ_T req);
    m_pending_reqs.push_back(req);
    m_num_reqs++;
    `uvm_info(get_name(), $sformatf("req #%0d: %s",
               m_num_reqs, req.convert2string()), UVM_HIGH)
  endfunction

  //--------------------------------------------------------------------------
  // 响应入口（DUT 输出侧 monitor → resp_export → write_resp 回调）
  //--------------------------------------------------------------------------
  function void write_resp(RESP_T resp);
    RESP_T expected;

    m_num_resps++;

    if (m_pending_reqs.size() == 0) begin
      m_num_mismatches++;
      `uvm_error(get_name(), "response received without pending request")
      return;
    end

    // FIFO 取最早请求（顺序协议；乱序协议请用 out_of_order_scoreboard）
    REQ_T req = m_pending_reqs.pop_front();

    expected = predict(req);

    if (compare(expected, resp)) begin
      m_num_matches++;
      `uvm_info(get_name(), $sformatf("match #%0d", m_num_matches), UVM_HIGH)
    end else begin
      m_num_mismatches++;
      `uvm_error(get_name(), $sformatf("mismatch #%0d\n  req: %s\n  expected: %s\n  actual: %s",
                 m_num_mismatches,
                 req.convert2string(),
                 expected.convert2string(),
                 resp.convert2string()))
    end
  endfunction

  //--------------------------------------------------------------------------
  // 检查阶段：汇总并裁决
  //--------------------------------------------------------------------------
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);

    `uvm_info(get_name(), $sformatf(
        "\n=== algorithm scoreboard summary ===\n"
        "  requests : %0d\n  responses: %0d\n  matches  : %0d\n"
        "  mismatches: %0d\n  pending  : %0d",
        m_num_reqs, m_num_resps, m_num_matches,
        m_num_mismatches, m_pending_reqs.size()), UVM_NONE)

    if (m_num_mismatches > 0 || m_pending_reqs.size() > 0)
      `uvm_error(get_name(), "algorithm scoreboard FAILED")
    else
      `uvm_info(get_name(), "algorithm scoreboard PASSED", UVM_NONE)
  endfunction

endclass : algorithm_scoreboard

//------------------------------------------------------------------------------
// 使用示例（默认关闭，需先定义 alu_seq_item 再开宏）
//   class alu_algorithm_scoreboard extends algorithm_scoreboard#(alu_seq_item, alu_seq_item);
//     function alu_seq_item predict(alu_seq_item req);
//       alu_seq_item expected = alu_seq_item::type_id::create("expected");
//       expected.copy(req);
//       case (req.op)
//         ADD: expected.result = req.a + req.b;
//         SUB: expected.result = req.a - req.b;
//         default: expected.result = 0;
//       endcase
//       return expected;
//     endfunction
//   endclass
//------------------------------------------------------------------------------

`endif // ALGORITHM_SCOREBOARD_SVH
