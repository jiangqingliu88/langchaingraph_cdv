// ════════════════════════════════════════════════════════════════
// in_order_scoreboard.svh —— 顺序计分板（scb 组件族基座）
// 职责: 比较器接口 + 默认比较器 + 参数化顺序计分板
//   REQ_T 实际事务类型（来自 monitor）
//   RSP_T 预期事务类型（来自参考模型/predictor，缺省 = REQ_T）
//   CMP_T 比较器类型（缺省 default_comparator，可注入自定义比较器）
// 代码风格: 2 空格缩进 · 小写蛇形命名 · 中文注释
// ════════════════════════════════════════════════════════════════

`ifndef IN_ORDER_SCOREBOARD_SVH
`define IN_ORDER_SCOREBOARD_SVH

// 预期侧 imp 用命名宏（write_expected 回调），避免 REQ_T == RSP_T 时
// write(T) 重载重定义冲突
`uvm_analysis_imp_decl(_expected)

//------------------------------------------------------------------------------
// 比较器接口（纯虚 compare，支持注入 uvm_comparer）
//------------------------------------------------------------------------------
virtual class comparator #(type T = uvm_sequence_item);

  pure virtual function bit compare(T expected, T actual,
                                    input uvm_comparer comparer = null);

  // 调试打印（默认走事务自身 convert2string）
  virtual function string convert2string(T t);
    return t.convert2string();
  endfunction
endclass : comparator

//------------------------------------------------------------------------------
// 默认比较器：使用事务自带 compare（uvm_object 语义）
//------------------------------------------------------------------------------
class default_comparator #(type T = uvm_sequence_item) extends comparator#(T);

  virtual function bit compare(T expected, T actual,
                               input uvm_comparer comparer = null);
    if (comparer == null)
      comparer = new();
    return expected.compare(actual, comparer);
  endfunction
endclass : default_comparator

//------------------------------------------------------------------------------
// 顺序计分板
//   write_expected(RSP_T) ← 参考模型/predictor（预期）
//   write(REQ_T)          ← DUT monitor（实际）
//   严格模式: 队列首元素一一比对；非严格: 任意位置匹配
//------------------------------------------------------------------------------
class in_order_scoreboard #(
    type REQ_T = uvm_sequence_item,
    type RSP_T = REQ_T,
    type CMP_T = default_comparator#(REQ_T)
) extends uvm_scoreboard;

  `uvm_component_param_utils(in_order_scoreboard#(REQ_T, RSP_T, CMP_T))

  // ── 统计 ──
  protected int m_num_expected   = 0;
  protected int m_num_actual     = 0;
  protected int m_num_matches    = 0;
  protected int m_num_mismatches = 0;
  protected int m_num_missing    = 0;
  protected int m_num_extra      = 0;

  // ── 分析端口（expected 与 actual 两个 imp，回调 write_expected / write）──
  uvm_analysis_imp#(REQ_T, in_order_scoreboard#(REQ_T, RSP_T, CMP_T)) actual_export;
  uvm_analysis_imp_expected#(RSP_T, in_order_scoreboard#(REQ_T, RSP_T, CMP_T)) expected_export;

  // ── 比较器 ──
  protected CMP_T m_comparator;

  // ── 配置 ──
  protected bit m_enable_prediction = 1;
  protected bit m_strict_ordering   = 1;
  protected int m_max_queue_depth   = 1024;

  // ── 队列 ──
  protected REQ_T m_expected_queue[$];
  protected REQ_T m_actual_queue[$];

  function new(string name, uvm_component parent);
    super.new(name, parent);
    actual_export   = new("actual_export", this);
    expected_export = new("expected_export", this);
    m_comparator    = new();   // CMP_T 缺省构造（注入自定义比较器用 set_comparator）
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 配置可用 config_db 覆盖: enable_prediction / strict_ordering / max_queue_depth
    if (!uvm_config_db#(bit)::get(this, "", "enable_prediction", m_enable_prediction))
      `uvm_info(get_name(), "using default enable_prediction=1", UVM_HIGH)
    if (!uvm_config_db#(bit)::get(this, "", "strict_ordering", m_strict_ordering))
      `uvm_info(get_name(), "using default strict_ordering=1", UVM_HIGH)
    if (!uvm_config_db#(int)::get(this, "", "max_queue_depth", m_max_queue_depth))
      `uvm_info(get_name(), $sformatf("using default max_queue_depth=%0d",
                 m_max_queue_depth), UVM_HIGH)
  endfunction

  //--------------------------------------------------------------------------
  // 注入自定义比较器（需要在 build 之前调用）
  //--------------------------------------------------------------------------
  function void set_comparator(CMP_T cmp);
    m_comparator = cmp;
  endfunction

  //--------------------------------------------------------------------------
  // 实际事务入口（DUT monitor → actual_export → write(REQ_T)）
  // 预期事务入口（参考模型 → expected_export → write_expected(RSP_T)，见宏声明）
  //--------------------------------------------------------------------------
  function void write(REQ_T item);
    write_actual(item);
  endfunction

  //--------------------------------------------------------------------------
  // 写入预期值（来自参考模型/predictor）
  //--------------------------------------------------------------------------
  virtual function void write_expected(RSP_T item);
    REQ_T expected;

    if (!m_enable_prediction)
      return;

    if (!$cast(expected, item)) begin
      `uvm_error(get_name(), $sformatf("cannot cast RSP_T to REQ_T: %s",
                 item.convert2string()))
      return;
    end

    if (m_expected_queue.size() >= m_max_queue_depth) begin
      `uvm_warning(get_name(), $sformatf("expected queue full (%0d), flushing oldest",
                   m_max_queue_depth))
      void'(m_expected_queue.pop_front());
      m_num_missing++;
    end

    m_expected_queue.push_back(expected);
    m_num_expected++;
    `uvm_info(get_name(), $sformatf("expected +1 [%0d] %s",
               m_expected_queue.size(), req2string(expected)), UVM_HIGH)

    if (!m_strict_ordering)
      try_compare();
  endfunction

  //--------------------------------------------------------------------------
  // 写入实际值（来自 DUT monitor）
  //--------------------------------------------------------------------------
  virtual function void write_actual(REQ_T item);
    if (m_actual_queue.size() >= m_max_queue_depth) begin
      `uvm_warning(get_name(), $sformatf("actual queue full (%0d), flushing oldest",
                   m_max_queue_depth))
      void'(m_actual_queue.pop_front());
      m_num_extra++;
    end

    m_actual_queue.push_back(item);
    m_num_actual++;
    `uvm_info(get_name(), $sformatf("actual +1 [%0d] %s",
               m_actual_queue.size(), req2string(item)), UVM_HIGH)

    if (m_strict_ordering)
      compare_strict();
    else
      try_compare();
  endfunction

  //--------------------------------------------------------------------------
  // 严格顺序比较：队首一对一，不匹配报错并消费该对
  //--------------------------------------------------------------------------
  protected function void compare_strict();
    REQ_T expected, actual;

    while (m_expected_queue.size() > 0 && m_actual_queue.size() > 0) begin
      expected = m_expected_queue[0];
      actual   = m_actual_queue[0];
      if (!compare_items(expected, actual)) begin
        m_num_mismatches++;
        `uvm_error(get_name(), $sformatf("mismatch\n  expected: %s\n  actual: %s",
                   req2string(expected), req2string(actual)))
        void'(m_expected_queue.pop_front());
        void'(m_actual_queue.pop_front());
        continue;
      end

      void'(m_expected_queue.pop_front());
      void'(m_actual_queue.pop_front());
      m_num_matches++;
      `uvm_info(get_name(), "strict match", UVM_HIGH)
    end
  endfunction

  //--------------------------------------------------------------------------
  // 非严格比较：任意位置匹配（乱序容忍）
  //--------------------------------------------------------------------------
  protected function void try_compare();
    for (int a = 0; a < m_actual_queue.size(); a++) begin
      for (int e = 0; e < m_expected_queue.size(); e++) begin
        if (compare_items(m_expected_queue[e], m_actual_queue[a])) begin
          m_expected_queue.delete(e);
          m_actual_queue.delete(a);
          m_num_matches++;
          `uvm_info(get_name(), $sformatf("match at e=%0d a=%0d", e, a), UVM_HIGH)
          a = -1;   // 队列已变更，从头重扫
          break;
        end
      end
    end
  endfunction

  //--------------------------------------------------------------------------
  // 比较两个事务（子类可重载）
  //--------------------------------------------------------------------------
  protected virtual function bit compare_items(REQ_T expected, REQ_T actual);
    return m_comparator.compare(expected, actual);
  endfunction

  protected virtual function string req2string(REQ_T t);
    return m_comparator.convert2string(t);
  endfunction

  //--------------------------------------------------------------------------
  // 刷新：未匹配项计入 missing/extra
  //--------------------------------------------------------------------------
  virtual function void flush();
    m_num_missing += m_expected_queue.size();
    m_num_extra   += m_actual_queue.size();

    foreach (m_expected_queue[i])
      `uvm_info(get_name(), $sformatf("missing: %s",
                 req2string(m_expected_queue[i])), UVM_LOW)
    foreach (m_actual_queue[i])
      `uvm_info(get_name(), $sformatf("extra: %s",
                 req2string(m_actual_queue[i])), UVM_LOW)

    m_expected_queue.delete();
    m_actual_queue.delete();
  endfunction

  //--------------------------------------------------------------------------
  // 检查阶段：汇总并裁决
  //--------------------------------------------------------------------------
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    flush();

    // 注：这里原来是 `"\n" + get_report_string()` —— Questa 判
    // 「Illegal operation on unpacked type」（`+` 作用在它眼里的非标量上）。
    // 换成 `$sformatf` 的写法，与下面那句 `` `uvm_error `` 一个形状。
    `uvm_info(get_name(), $sformatf("\n%s", get_report_string()), UVM_NONE)

    if (m_num_mismatches > 0 || m_num_missing > 0 || m_num_extra > 0)
      `uvm_error(get_name(), $sformatf("scoreboard FAILED: mismatches=%0d missing=%0d extra=%0d",
                 m_num_mismatches, m_num_missing, m_num_extra))
    else
      `uvm_info(get_name(), "scoreboard PASSED", UVM_NONE)
  endfunction

  virtual function string get_report_string();
    string r;
    r = "===========================================================\n";
    r = {r, $sformatf("Scoreboard: %s\n", get_name())};
    r = {r, "===========================================================\n"};
    r = {r, $sformatf("  Expected items : %0d\n", m_num_expected)};
    r = {r, $sformatf("  Actual items   : %0d\n", m_num_actual)};
    r = {r, $sformatf("  Matches        : %0d\n", m_num_matches)};
    r = {r, $sformatf("  Mismatches     : %0d\n", m_num_mismatches)};
    r = {r, $sformatf("  Missing        : %0d\n", m_num_missing)};
    r = {r, $sformatf("  Extra          : %0d\n", m_num_extra)};
    r = {r, $sformatf("  Match Rate     : %0.2f%%\n",
         ((m_num_matches + m_num_mismatches) > 0)
         ? (100.0 * m_num_matches / (m_num_matches + m_num_mismatches)) : 100.0)};
    r = {r, "===========================================================\n"};
    return r;
  endfunction

  //--------------------------------------------------------------------------
  // 统计读取（线程安全快照）
  //--------------------------------------------------------------------------
  // 注：这个出参原来叫 `matches` —— 那是 **SystemVerilog 关键字**（`matches`
  // 运算符，IEEE 1800-2012），vlog 直接判语法错：
  //     in_order_scoreboard.svh(279): near "matches": syntax error,
  //     unexpected SystemVerilog keyword 'matches'
  // 而这个文件在 `scb_pkg` 里，是**每个** UVM 环境都要编的公共包 ——
  // 一处端口名就把整条编译链挡死。改名 `match_count`（形参名不进接口契约，
  // 调用方用的都是位置参数）。
  virtual function void get_stats(output int expected, output int actual,
                                  output int match_count, output int mismatches,
                                  output int extra, output int missing);
    expected    = m_num_expected;
    actual      = m_num_actual;
    match_count = m_num_matches;
    mismatches  = m_num_mismatches;
    extra      = m_num_extra;
    missing    = m_num_missing;
  endfunction

  virtual function void clear_stats();
    m_num_expected   = 0;
    m_num_actual     = 0;
    m_num_matches    = 0;
    m_num_mismatches = 0;
    m_num_extra      = 0;
    m_num_missing    = 0;
  endfunction

endclass : in_order_scoreboard

`endif // IN_ORDER_SCOREBOARD_SVH
