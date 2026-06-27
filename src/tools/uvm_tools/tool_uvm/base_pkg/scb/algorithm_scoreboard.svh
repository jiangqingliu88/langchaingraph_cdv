// algorithm_scoreboard.svh
// 包含参考模型算法的计分板

`ifndef ALGORITHM_SCOREBOARD_SVH
`define ALGORITHM_SCOREBOARD_SVH

//==============================================================================
// 算法计分板 - 内嵌参考模型
//==============================================================================
class algorithm_scoreboard #(
    type REQ_T = uvm_sequence_item,
    type RESP_T = uvm_sequence_item
) extends uvm_scoreboard;
    
    `uvm_component_param_utils(algorithm_scoreboard#(REQ_T, RESP_T))
    
    // 分析端口
    uvm_analysis_imp#(REQ_T, algorithm_scoreboard#(REQ_T, RESP_T)) m_req_export;
    uvm_analysis_imp#(RESP_T, algorithm_scoreboard#(REQ_T, RESP_T)) m_resp_export;
    
    // 待处理请求队列
    protected REQ_T m_pending_reqs[$];
    
    // 统计
    protected int m_num_reqs = 0;
    protected int m_num_resps = 0;
    protected int m_num_matches = 0;
    protected int m_num_mismatches = 0;
    
    function new(string name, uvm_component parent);
        super.new(name, parent);
        m_req_export = new("m_req_export", this);
        m_resp_export = new("m_resp_export", this);
    endfunction
    
    // 虚函数：参考模型计算预期结果
    protected virtual function RESP_T predict(REQ_T req);
        // 子类必须重载此函数
        `uvm_fatal(get_name(), "predict() not implemented")
        return null;
    endfunction
    
    // 虚函数：比较实际结果与预期结果
    protected virtual function bit compare(RESP_T expected, RESP_T actual);
        return expected.compare(actual);
    endfunction
    
    // 处理请求
    function void write_req(REQ_T req);
        m_pending_reqs.push_back(req);
        m_num_reqs++;
        `uvm_info(get_name(), $sformatf("Received request #%0d: %s", 
                  m_num_reqs, req.convert2string()), UVM_HIGH)
        
        // 尝试匹配任何等待的响应
        try_match();
    endfunction
    
    // 处理响应
    function void write_resp(RESP_T resp);
        RESP_T expected;
        
        m_num_resps++;
        
        // 如果没有待处理请求，报告错误
        if (m_pending_reqs.size() == 0) begin
            `uvm_error(get_name(), "Received response without pending request")
            return;
        end
        
        // 取出最早的请求（FIFO 顺序）
        REQ_T req = m_pending_reqs.pop_front();
        
        // 计算预期结果
        expected = predict(req);
        
        // 比较
        if (compare(expected, resp)) begin
            m_num_matches++;
            `uvm_info(get_name(), $sformatf("Match #%0d: Request=%s, Response=%s", 
                      m_num_matches, req.convert2string(), resp.convert2string()), 
                      UVM_HIGH)
        end else begin
            m_num_mismatches++;
            `uvm_error(get_name(), $sformatf("Mismatch #%0d\n  Request: %s\n  Expected: %s\n  Actual: %s",
                      m_num_mismatches, req.convert2string(), 
                      expected.convert2string(), resp.convert2string()))
        end
    endfunction
    
    // 统一写入接口
    function void write(REQ_T t);
        write_req(t);
    endfunction
    
    // 尝试匹配
    protected function void try_match();
        // 默认不做额外匹配
    endfunction
    
    // 检查阶段
    function void check_phase(uvm_phase phase);
        super.check_phase(phase);
        
        `uvm_info(get_name(), $sformatf("\n=== Algorithm Scoreboard Summary ===\n  Requests: %0d\n  Responses: %0d\n  Matches: %0d\n  Mismatches: %0d\n  Pending: %0d",
                  m_num_reqs, m_num_resps, m_num_matches, m_num_mismatches, 
                  m_pending_reqs.size()), UVM_LOW)
        
        if (m_num_mismatches > 0 || m_pending_reqs.size() > 0) begin
            `uvm_error(get_name(), "Scoreboard failed")
        end
    endfunction
    
endclass

//==============================================================================
// ALU 算法计分板示例
//==============================================================================
class alu_algorithm_scoreboard extends algorithm_scoreboard#(alu_seq_item, alu_seq_item);
    `uvm_component_utils(alu_algorithm_scoreboard)
    
    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction
    
    // 实现 ALU 参考模型
    function alu_seq_item predict(alu_seq_item req);
        alu_seq_item expected;
        expected = alu_seq_item::type_id::create("expected");
        expected.copy(req);
        
        // 计算预期结果
        case (req.op)
            ADD: expected.result = req.a + req.b;
            SUB: expected.result = req.a - req.b;
            MUL: expected.result = req.a * req.b;
            default: expected.result = 0;
        endcase
        
        return expected;
    endfunction
    
endclass

`endif