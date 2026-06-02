// out_of_order_scoreboard.svh
// 支持乱序匹配的计分板

`ifndef OUT_OF_ORDER_SCOREBOARD_SVH
`define OUT_OF_ORDER_SCOREBOARD_SVH

//==============================================================================
// 乱序计分板 - 使用 ID/标签进行匹配
//==============================================================================
class out_of_order_scoreboard #(
    type T = uvm_sequence_item,
    type ID_T = int,
    type CMP_T = comparator#(T)
) extends base_scoreboard#(T, T, CMP_T);
    
    `uvm_component_param_utils(out_of_order_scoreboard#(T, ID_T, CMP_T))
    
    // 用于乱序匹配的关联数组
    protected T m_pending_expected[ID_T];
    protected T m_pending_actual[ID_T];
    
    // 获取事务 ID 的虚函数（需要子类重载）
    protected virtual function ID_T get_id(T item);
        // 默认实现：假设 item 有 get_id 方法
        // 子类应该重载此函数
        return item.get_id();
    endfunction
    
    // 重载写入预期值
    function void write_expected(T item);
        ID_T id = get_id(item);
        
        if (m_pending_expected.exists(id)) begin
            `uvm_error(get_name(), $sformatf("Duplicate expected ID %0d", id))
            return;
        end
        
        m_pending_expected[id] = item;
        m_num_expected++;
        
        // 尝试匹配
        try_match_id(id);
    endfunction
    
    // 重载写入实际值
    function void write_actual(T item);
        ID_T id = get_id(item);
        
        if (m_pending_actual.exists(id)) begin
            `uvm_error(get_name(), $sformatf("Duplicate actual ID %0d", id))
            return;
        end
        
        m_pending_actual[id] = item;
        m_num_actual++;
        
        // 尝试匹配
        try_match_id(id);
    endfunction
    
    // 尝试匹配特定 ID
    protected function void try_match_id(ID_T id);
        if (m_pending_expected.exists(id) && m_pending_actual.exists(id)) begin
            if (compare_items(m_pending_expected[id], m_pending_actual[id])) begin
                m_num_matches++;
                `uvm_info(get_name(), $sformatf("Matched ID %0d", id), UVM_HIGH)
                
                m_pending_expected.delete(id);
                m_pending_actual.delete(id);
            end else begin
                m_num_mismatches++;
                `uvm_error(get_name(), $sformatf("Mismatch for ID %0d\n  Expected: %s\n  Actual: %s",
                          id, convert2string(m_pending_expected[id]), 
                          convert2string(m_pending_actual[id])))
                
                m_pending_expected.delete(id);
                m_pending_actual.delete(id);
            end
        end
    endfunction
    
    // 刷新未匹配的事务
    function void flush();
        ID_T id;
        
        foreach (m_pending_expected[id]) begin
            m_num_missing++;
            `uvm_info(get_name(), $sformatf("Missing ID %0d: %s", 
                      id, convert2string(m_pending_expected[id])), UVM_LOW)
        end
        
        foreach (m_pending_actual[id]) begin
            m_num_extra++;
            `uvm_info(get_name(), $sformatf("Extra ID %0d: %s", 
                      id, convert2string(m_pending_actual[id])), UVM_LOW)
        end
        
        m_pending_expected.delete();
        m_pending_actual.delete();
    endfunction
    
endclass

`endif