// typed_scoreboard.svh
// 通过 typedef 进行类型重载的特化计分板

`ifndef TYPED_SCOREBOARD_SVH
`define TYPED_SCOREBOARD_SVH

//==============================================================================
// 类型重载宏 - 简化特化计分板的定义
//==============================================================================
`define DEFINE_TYPED_SCOREBOARD(NAME, REQ_T, RSP_T, CMP_T) \
    typedef base_scoreboard#(REQ_T, RSP_T, CMP_T) NAME``_base_t; \
    class NAME extends NAME``_base_t; \
        `uvm_component_utils(NAME) \
        function new(string name, uvm_component parent); \
            super.new(name, parent); \
        endfunction \
    endclass

//==============================================================================
// 针对 ALU 事务的特化计分板
//==============================================================================
// 先定义 ALU 事务类型
typedef class alu_seq_item;
typedef class alu_result_item;

// ALU 专用比较器
class alu_comparator extends comparator#(alu_seq_item);
    typedef enum {
        STRICT,      // 严格匹配所有字段
        IGNORE_RESULT,  // 忽略计算结果（用于功能验证）
        APPROXIMATE     // 近似匹配（例如浮点误差）
    } compare_mode_t;
    
    protected compare_mode_t m_mode = STRICT;
    
    function new(compare_mode_t mode = STRICT);
        m_mode = mode;
    endfunction
    
    function bit compare(alu_seq_item expected, alu_seq_item actual, 
                         input uvm_comparer comparer = null);
        bit match = 1;
        
        // 比较操作数
        match &= (expected.a == actual.a);
        match &= (expected.b == actual.b);
        match &= (expected.op == actual.op);
        
        // 根据模式比较结果
        case (m_mode)
            STRICT: begin
                match &= (expected.result == actual.result);
            end
            IGNORE_RESULT: begin
                // 不比较结果字段
            end
            APPROXIMATE: begin
                // 允许一定误差
                match &= (expected.result inside {[actual.result-1 : actual.result+1]});
            end
        endcase
        
        return match;
    endfunction
endclass

// 定义 ALU 特化计分板
`DEFINE_TYPED_SCOREBOARD(alu_scoreboard, alu_seq_item, alu_seq_item, alu_comparator)

//==============================================================================
// 针对 AXI 事务的特化计分板（支持乱序和 ID）
//==============================================================================
typedef class axi_seq_item;

class axi_comparator extends comparator#(axi_seq_item);
    function bit compare(axi_seq_item expected, axi_seq_item actual,
                         input uvm_comparer comparer = null);
        // AXI 比较规则：
        // 1. 必须匹配 ID
        // 2. 必须匹配地址
        // 3. 数据可以乱序，通过 ID 匹配
        return (expected.id == actual.id) &&
               (expected.addr == actual.addr) &&
               (expected.data == actual.data);
    endfunction
endclass

`DEFINE_TYPED_SCOREBOARD(axi_scoreboard, axi_seq_item, axi_seq_item, axi_comparator)

//==============================================================================
// 多通道计分板（支持多个输入源）
//==============================================================================
class multi_channel_scoreboard #(
    type T = uvm_sequence_item,
    type CMP_T = comparator#(T),
    int NUM_CHANNELS = 2
) extends base_scoreboard#(T, T, CMP_T);
    
    `uvm_component_param_utils(multi_channel_scoreboard#(T, CMP_T, NUM_CHANNELS))
    
    // 多通道分析端口
    uvm_analysis_imp#(T, multi_channel_scoreboard#(T, CMP_T, NUM_CHANNELS)) 
        m_channel_exports[NUM_CHANNELS];
    
    // 通道队列
    protected T m_channel_queues[NUM_CHANNELS][$];
    
    function new(string name, uvm_component parent);
        super.new(name, parent);
        foreach (m_channel_exports[i]) begin
            m_channel_exports[i] = new($sformatf("channel_%0d_export", i), this);
        end
    endfunction
    
    // 写入指定通道
    function void write_channel(int channel, T item);
        if (channel >= NUM_CHANNELS) begin
            `uvm_error(get_name(), $sformatf("Invalid channel %0d", channel))
            return;
        end
        
        m_channel_queues[channel].push_back(item);
        `uvm_info(get_name(), $sformatf("Channel %0d received: %s", 
                  channel, convert2string(item)), UVM_HIGH)
        
        // 跨通道比较逻辑
        compare_channels();
    endfunction
    
    // 跨通道比较（例如：通道0是预期，通道1是实际）
    protected virtual function void compare_channels();
        if (NUM_CHANNELS >= 2) begin
            while (m_channel_queues[0].size() > 0 && 
                   m_channel_queues[1].size() > 0) begin
                if (compare_items(m_channel_queues[0][0], m_channel_queues[1][0])) begin
                    void'(m_channel_queues[0].pop_front());
                    void'(m_channel_queues[1].pop_front());
                    m_num_matches++;
                end else begin
                    break;
                end
            end
        end
    endfunction
    
endclass

`endif

//// 你定义了一个 sequencer，带有特殊的方法和变量
// class my_sequencer extends uvm_sequencer #(my_transaction);
//     int my_special_counter;
//     function void my_special_method();
//         $display("Special method called");
//     endfunction
// endclass

// // 在 sequence 中
// class my_sequence extends uvm_sequence #(my_transaction);
    
//     task body();
//         // 问题：m_sequencer 的类型是 uvm_sequencer_base
//         // 无法直接访问 my_special_counter 和 my_special_method()
        
//         // ❌ 编译错误：uvm_sequencer_base 没有 my_special_counter
//         m_sequencer.my_special_counter = 10;
        
//         // ✅ 解决方案：使用 p_sequencer
//         p_sequencer.my_special_counter = 10;
//         p_sequencer.my_special_method();
//     endtask
    
// endclass
// m_sequencer 是基类句柄，功能有限
// • p_sequencer 是具体类型句柄，功能完整
// • 使用 
// ￼
// uvm_declare_p_sequencer` 宏定义 p_sequencer
// • 虚拟 sequencer 场景必须用 p_sequencer
// • 简单场景不需要 p_sequencer