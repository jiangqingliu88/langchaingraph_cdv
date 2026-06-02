// base_scoreboard.svh
// 参数化的基础计分板，支持事务类型重载

`ifndef BASE_SCOREBOARD_SVH
`define BASE_SCOREBOARD_SVH

//==============================================================================
// 基础比较器接口
//==============================================================================
virtual class comparator #(type T = uvm_sequence_item);
    // 纯虚函数：比较两个事务
    pure virtual function bit compare(T expected, T actual, 
                                       input uvm_comparer comparer = null);
    
    // 可选：提供转换字符串用于调试
    virtual function string convert2string(T t);
        return t.convert2string();
    endfunction
endclass

//==============================================================================
// 默认比较器：使用事务自带的 compare 方法
//==============================================================================
class default_comparator #(type T = uvm_sequence_item) 
    extends comparator#(T);
    
    function bit compare(T expected, T actual, 
                         input uvm_comparer comparer = null);
        if (comparer == null) begin
            comparer = new();
        end
        return expected.compare(actual, comparer);
    endfunction
endclass

//==============================================================================
// 参数化基础计分板
// 类型参数：
//   REQ_T  - 请求事务类型（通常来自 Monitor）
//   RSP_T  - 响应事务类型（可选，默认同 REQ_T）
//   CMP_T  - 比较器类型
//==============================================================================
class base_scoreboard #(
    type REQ_T = uvm_sequence_item,
    type RSP_T = REQ_T,
    type CMP_T = comparator#(REQ_T)
) extends uvm_scoreboard;
    
    // UVM 组件宏
    `uvm_component_param_utils(base_scoreboard#(REQ_T, RSP_T, CMP_T))
    
    //--------------------------------------------------------------------------
    // 公共成员变量
    //--------------------------------------------------------------------------
    protected int m_num_expected = 0;      // 预期事务计数
    protected int m_num_actual   = 0;      // 实际事务计数
    protected int m_num_matches  = 0;      // 匹配计数
    protected int m_num_mismatches = 0;    // 不匹配计数
    protected int m_num_extra    = 0;      // 额外事务计数
    protected int m_num_missing  = 0;      // 缺失事务计数
    
    // 分析端口（可连接多个）
    uvm_analysis_imp#(REQ_T, base_scoreboard#(REQ_T, RSP_T, CMP_T)) m_actual_export;
    uvm_analysis_imp#(RSP_T, base_scoreboard#(REQ_T, RSP_T, CMP_T)) m_expected_export;
    
    // 比较器句柄
    protected CMP_T m_comparator;
    
    // 配置参数
    protected bit m_enable_prediction = 1;   // 启用预测模式
    protected bit m_strict_ordering   = 1;   // 严格顺序比较
    protected bit m_auto_flush        = 0;   // 自动清空
    protected int  m_max_queue_depth  = 1024; // 最大队列深度
    
    // 保护队列
    protected REQ_T m_expected_queue[$];
    protected REQ_T m_actual_queue[$];
    
    // 统计互斥锁（多线程安全）
    protected semaphore m_stats_lock;
    
    //--------------------------------------------------------------------------
    // 构造函数
    //--------------------------------------------------------------------------
    function new(string name, uvm_component parent);
        super.new(name, parent);
        m_actual_export = new("m_actual_export", this);
        m_expected_export = new("m_expected_export", this);
        m_stats_lock = new(1);
        
        // 创建默认比较器（如果未提供）
        if (m_comparator == null) begin
            m_comparator = new();
        end
    endfunction
    
    //--------------------------------------------------------------------------
    // 构建阶段
    //--------------------------------------------------------------------------
    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        
        // 从配置数据库获取参数
        if (!uvm_config_db#(bit)::get(this, "", "enable_prediction", m_enable_prediction)) begin
            `uvm_info(get_name(), "Using default enable_prediction=1", UVM_HIGH)
        end
        
        if (!uvm_config_db#(bit)::get(this, "", "strict_ordering", m_strict_ordering)) begin
            `uvm_info(get_name(), "Using default strict_ordering=1", UVM_HIGH)
        end
        
        if (!uvm_config_db#(int)::get(this, "", "max_queue_depth", m_max_queue_depth)) begin
            `uvm_info(get_name(), $sformatf("Using default max_queue_depth=%0d", m_max_queue_depth), UVM_HIGH)
        end
    endfunction
    
    //--------------------------------------------------------------------------
    // 写入预期值（来自参考模型）
    //--------------------------------------------------------------------------
    virtual function void write_expected(RSP_T item);
        REQ_T expected;
        
        if (!m_enable_prediction) begin
            return;
        end
        
        // 转换类型（如果 RSP_T != REQ_T）
        if (!$cast(expected, item)) begin
            `uvm_error(get_name(), $sformatf("Cannot cast RSP_T to REQ_T: %s", 
                      item.convert2string()))
            return;
        end
        
        // 队列深度检查
        if (m_expected_queue.size() >= m_max_queue_depth) begin
            `uvm_warning(get_name(), $sformatf("Expected queue full (%0d), flushing oldest", 
                        m_max_queue_depth))
            void'(m_expected_queue.pop_front());
            m_num_missing++;
        end
        
        m_expected_queue.push_back(expected);
        m_num_expected++;
        
        `uvm_info(get_name(), $sformatf("Added expected item [%0d]: %s", 
                  m_expected_queue.size(), convert2string(expected)), UVM_HIGH)
        
        // 立即尝试比较
        if (!m_strict_ordering) begin
            try_compare();
        end
    endfunction
    
    //--------------------------------------------------------------------------
    // 写入实际值（来自 DUT Monitor）
    //--------------------------------------------------------------------------
    virtual function void write_actual(REQ_T item);
        // 队列深度检查
        if (m_actual_queue.size() >= m_max_queue_depth) begin
            `uvm_warning(get_name(), $sformatf("Actual queue full (%0d), flushing oldest", 
                        m_max_queue_depth))
            void'(m_actual_queue.pop_front());
            m_num_extra++;
        end
        
        m_actual_queue.push_back(item);
        m_num_actual++;
        
        `uvm_info(get_name(), $sformatf("Added actual item [%0d]: %s", 
                  m_actual_queue.size(), convert2string(item)), UVM_HIGH)
        
        // 尝试比较
        if (m_strict_ordering) begin
            compare_strict();
        end else begin
            try_compare();
        end
    endfunction
    
    //--------------------------------------------------------------------------
    // 分析出口实现（通过类型重载）
    //--------------------------------------------------------------------------
    function void write(REQ_T t);
        write_actual(t);
    endfunction
    
    // 重载：支持写入预期值
    function void write_expected(RSP_T t);
        write_expected(t);
    endfunction
    
    //--------------------------------------------------------------------------
    // 严格顺序比较
    //--------------------------------------------------------------------------
    protected function void compare_strict();
        REQ_T expected, actual;
        
        while (m_expected_queue.size() > 0 && m_actual_queue.size() > 0) begin
            expected = m_expected_queue[0];
            actual   = m_actual_queue[0];
            
            if (compare_items(expected, actual)) begin
                void'(m_expected_queue.pop_front());
                void'(m_actual_queue.pop_front());
                m_num_matches++;
                `uvm_info(get_name(), "Strict match found", UVM_HIGH)
            end else begin
                // 严格顺序模式下，如果不匹配则停止
                break;
            end
        end
    endfunction
    
    //--------------------------------------------------------------------------
    // 非严格顺序比较（尝试匹配任何未匹配的预期值）
    //--------------------------------------------------------------------------
    protected function void try_compare();
        REQ_T expected, actual;
        int expected_idx, actual_idx;
        
        // 遍历所有实际事务，尝试匹配预期事务
        for (actual_idx = 0; actual_idx < m_actual_queue.size(); actual_idx++) begin
            actual = m_actual_queue[actual_idx];
            
            // 查找匹配的预期事务
            for (expected_idx = 0; expected_idx < m_expected_queue.size(); expected_idx++) begin
                expected = m_expected_queue[expected_idx];
                
                if (compare_items(expected, actual)) begin
                    // 找到匹配，从队列中删除
                    m_expected_queue.delete(expected_idx);
                    m_actual_queue.delete(actual_idx);
                    m_num_matches++;
                    
                    `uvm_info(get_name(), $sformatf("Found match (expected_idx=%0d, actual_idx=%0d)", 
                              expected_idx, actual_idx), UVM_HIGH)
                    
                    // 重新开始扫描（因为队列已修改）
                    actual_idx = -1;
                    break;
                end
            end
        end
    endfunction
    
    //--------------------------------------------------------------------------
    // 比较两个事务（可重载）
    //--------------------------------------------------------------------------
    protected virtual function bit compare_items(REQ_T expected, REQ_T actual);
        return m_comparator.compare(expected, actual);
    endfunction
    
    //--------------------------------------------------------------------------
    // 转换字符串（可重载）
    //--------------------------------------------------------------------------
    protected virtual function string convert2string(REQ_T t);
        return m_comparator.convert2string(t);
    endfunction
    
    //--------------------------------------------------------------------------
    // 刷新队列：处理未匹配的事务
    //--------------------------------------------------------------------------
    virtual function void flush();
        m_num_missing  += m_expected_queue.size();
        m_num_extra    += m_actual_queue.size();
        
        if (m_expected_queue.size() > 0) begin
            `uvm_warning(get_name(), $sformatf("Flushing %0d unmatched expected items", 
                        m_expected_queue.size()))
            foreach (m_expected_queue[i]) begin
                `uvm_info(get_name(), $sformatf("Missing: %s", 
                          convert2string(m_expected_queue[i])), UVM_LOW)
            end
        end
        
        if (m_actual_queue.size() > 0) begin
            `uvm_warning(get_name(), $sformatf("Flushing %0d unmatched actual items", 
                        m_actual_queue.size()))
            foreach (m_actual_queue[i]) begin
                `uvm_info(get_name(), $sformatf("Extra: %s", 
                          convert2string(m_actual_queue[i])), UVM_LOW)
            end
        end
        
        m_expected_queue.delete();
        m_actual_queue.delete();
    endfunction
    
    //--------------------------------------------------------------------------
    // 检查阶段
    //--------------------------------------------------------------------------
    function void check_phase(uvm_phase phase);
        super.check_phase(phase);
        
        // 刷新剩余事务
        flush();
        
        // 打印统计信息
        `uvm_info(get_name(), "\n" + get_report_string(), UVM_LOW)
        
        // 如果有不匹配、缺失或额外事务，报告错误
        if (m_num_mismatches > 0 || m_num_missing > 0 || m_num_extra > 0) begin
            `uvm_error(get_name(), $sformatf("Scoreboard failed: mismatches=%0d, missing=%0d, extra=%0d",
                      m_num_mismatches, m_num_missing, m_num_extra))
        end else begin
            `uvm_info(get_name(), "Scoreboard PASSED", UVM_LOW)
        end
    endfunction
    
    //--------------------------------------------------------------------------
    // 生成报告字符串
    //--------------------------------------------------------------------------
    virtual function string get_report_string();
        string report;
        report = "===========================================================\n";
        report = {report, $sformatf("Scoreboard: %s\n", get_name())};
        report = {report, "===========================================================\n"};
        report = {report, $sformatf("  Expected items : %0d\n", m_num_expected)};
        report = {report, $sformatf("  Actual items   : %0d\n", m_num_actual)};
        report = {report, $sformatf("  Matches        : %0d\n", m_num_matches)};
        report = {report, $sformatf("  Mismatches     : %0d\n", m_num_mismatches)};
        report = {report, $sformatf("  Missing        : %0d\n", m_num_missing)};
        report = {report, $sformatf("  Extra          : %0d\n", m_num_extra)};
        report = {report, $sformatf("  Match Rate     : %0.2f%%\n", 
                  (m_num_matches + m_num_mismatches) > 0 ? 
                  100.0 * m_num_matches / (m_num_matches + m_num_mismatches) : 100.0)};
        report = {report, "===========================================================\n"};
        return report;
    endfunction
    
    //--------------------------------------------------------------------------
    // 清空统计
    //--------------------------------------------------------------------------
    virtual function void clear_stats();
        m_stats_lock.get(1);
        m_num_expected = 0;
        m_num_actual = 0;
        m_num_matches = 0;
        m_num_mismatches = 0;
        m_num_extra = 0;
        m_num_missing = 0;
        m_stats_lock.put(1);
    endfunction
    
    //--------------------------------------------------------------------------
    // 获取统计信息（线程安全）
    //--------------------------------------------------------------------------
    virtual function void get_stats(output int expected, output int actual,
                                     output int matches, output int mismatches,
                                     output int extra, output int missing);
        m_stats_lock.get(1);
        expected  = m_num_expected;
        actual    = m_num_actual;
        matches   = m_num_matches;
        mismatches = m_num_mismatches;
        extra     = m_num_extra;
        missing   = m_num_missing;
        m_stats_lock.put(1);
    endfunction
    
endclass

`endif