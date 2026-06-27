// stimulus_logger_pkg.sv
// 完整的激励日志器包 - 支持多种格式的十六进制打印

package stimulus_logger_pkg;
    
    import uvm_pkg::*;
    `include "uvm_macros.svh"
    
    //==========================================================================
    // 日志格式枚举
    //==========================================================================
    typedef enum {
        HEX_FORMAT,      // 十六进制格式: time a=0xXX b=0xXX
        BIN_FORMAT,      // 二进制格式: time a=0bXXXXXXXX b=0bXXXXXXXX
        DEC_FORMAT,      // 十进制格式: time a=XXX b=XXX
        CSV_FORMAT,      // CSV 格式: time,hex_a,hex_b,hex_op,hex_result
        VERILOG_HEX,     // Verilog hex 格式: @time data
        VCD_FORMAT,      // VCD 兼容格式
        C_ARRAY,         // C 语言数组格式
        PYTHON_LIST,     // Python 列表格式
        MATLAB_FORMAT    // MATLAB 格式
    } log_format_t;
    
    //==========================================================================
    // 全局日志配置类
    //==========================================================================
    class stim_log_config extends uvm_object;
        `uvm_object_utils(stim_log_config)
        
        // 基本配置
        bit           enabled = 1;
        string        filename = "stimulus.hex";
        log_format_t  format = HEX_FORMAT;
        bit           include_time = 1;
        bit           include_header = 1;
        bit           auto_flush = 1;
        
        // 高级配置
        int           max_items = -1;           // 最大记录数量，-1表示无限制
        int           flush_interval = 1000;    // 每 N 条刷新一次
        string        separator = " ";          // 字段分隔符
        bit           append = 0;               // 是否追加模式
        bit           print_transaction_id = 0; // 是否打印事务ID
        
        function new(string name = "stim_log_config");
            super.new(name);
        endfunction
        
        // 从命令行参数配置
        function void from_cmdline();
            string format_str;
            if ($value$plusargs("STIM_LOG_FORMAT=%s", format_str)) begin
                case (format_str)
                    "HEX": format = HEX_FORMAT;
                    "BIN": format = BIN_FORMAT;
                    "DEC": format = DEC_FORMAT;
                    "CSV": format = CSV_FORMAT;
                    "VERILOG": format = VERILOG_HEX;
                    "VCD": format = VCD_FORMAT;
                endcase
            end
            $value$plusargs("STIM_LOG_FILE=%s", filename);
            $value$plusargs("STIM_LOG_MAX=%d", max_items);
        endfunction
        
    endclass
    
    //==========================================================================
    // 基础激励日志器（抽象类）
    //==========================================================================
    class stimulus_logger_base #(type T = uvm_sequence_item) extends uvm_component;
        `uvm_component_param_utils(stimulus_logger_base#(T))
        
        protected int         m_file_fd;
        protected stim_log_config m_cfg;
        protected int         m_item_count;
        protected int         m_flush_counter;
        protected string      m_file_open_mode;
        
        // 分析端口
        uvm_analysis_imp#(T, stimulus_logger_base#(T)) m_analysis_imp;
        
        function new(string name, uvm_component parent);
            super.new(name, parent);
            m_analysis_imp = new("m_analysis_imp", this);
            m_item_count = 0;
            m_flush_counter = 0;
        endfunction
        
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            
            // 获取配置
            if (!uvm_config_db#(stim_log_config)::get(this, "", "cfg", m_cfg)) begin
                m_cfg = stim_log_config::type_id::create("m_cfg");
                `uvm_info(get_name(), "Using default configuration", UVM_LOW)
            end
            
            // 从命令行更新配置
            m_cfg.from_cmdline();
            
            // 确定文件打开模式
            m_file_open_mode = m_cfg.append ? "a" : "w";
            
            // 打开文件
            if (m_cfg.enabled) begin
                open_file();
            end
        endfunction
        
        virtual function void open_file();
            m_file_fd = $fopen(m_cfg.filename, m_file_open_mode);
            if (!m_file_fd) begin
                `uvm_error(get_name(), $sformatf("Cannot open file: %s", m_cfg.filename))
                return;
            end
            
            if (m_cfg.include_header && !m_cfg.append) begin
                write_header();
            end
        endfunction
        
        virtual function void write_header();
            $fwrite(m_file_fd, "//============================================================\n");
            $fwrite(m_file_fd, "// Stimulus Logger: %s\n", get_name());
            $fwrite(m_file_fd, "// Component Path: %s\n", get_full_name());
            $fwrite(m_file_fd, "// Start Time: %0t\n", $time);
            $fwrite(m_file_fd, "// Format: %s\n", m_cfg.format.name());
            $fwrite(m_file_fd, "// Transaction Type: %s\n", $typename(T));
            $fwrite(m_file_fd, "//============================================================\n\n");
        endfunction
        
        // 写入事务（主入口）
        function void write(T t);
            if (!m_cfg.enabled || !m_file_fd) return;
            
            // 检查最大数量限制
            if (m_cfg.max_items > 0 && m_item_count >= m_cfg.max_items) begin
                return;
            end
            
            // 调用子类实现的格式化函数
            format_and_write(t);
            
            m_item_count++;
            m_flush_counter++;
            
            // 自动刷新
            if (m_cfg.auto_flush && m_flush_counter >= m_cfg.flush_interval) begin
                $fflush(m_file_fd);
                m_flush_counter = 0;
            end
        endfunction
        
        // 子类必须实现的格式化函数
        protected virtual function void format_and_write(T t);
            // 子类重载此函数
            $fwrite(m_file_fd, "%0t %s\n", $time, t.convert2string());
        endfunction
        
        // 分析接口实现
        function void write(T t);
            write(t);
        endfunction
        
        function void flush();
            if (m_file_fd) begin
                $fflush(m_file_fd);
                `uvm_info(get_name(), "File flushed", UVM_HIGH)
            end
        endfunction
        
        function void final_phase(uvm_phase phase);
            super.final_phase(phase);
            if (m_file_fd) begin
                write_footer();
                $fclose(m_file_fd);
                `uvm_info(get_name(), $sformatf("Logged %0d items to %s", 
                          m_item_count, m_cfg.filename), UVM_LOW)
            end
        endfunction
        
        virtual function void write_footer();
            $fwrite(m_file_fd, "\n//============================================================\n");
            $fwrite(m_file_fd, "// End Time: %0t\n", $time);
            $fwrite(m_file_fd, "// Total Items: %0d\n", m_item_count);
            $fwrite(m_file_fd, "//============================================================\n");
        endfunction
        
    endclass
    
    //==========================================================================
    // 通用序列项日志器（适用于任何有 pack() 方法的 item）
    //==========================================================================
    class generic_stimulus_logger #(type T = uvm_sequence_item) extends stimulus_logger_base#(T);
        `uvm_component_param_utils(generic_stimulus_logger#(T))
        
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        
        protected virtual function void format_and_write(T t);
            case (m_cfg.format)
                HEX_FORMAT: format_hex(t);
                BIN_FORMAT: format_bin(t);
                DEC_FORMAT: format_dec(t);
                CSV_FORMAT: format_csv(t);
                VERILOG_HEX: format_verilog_hex(t);
                VCD_FORMAT: format_vcd(t);
                C_ARRAY: format_c_array(t);
                PYTHON_LIST: format_python_list(t);
                MATLAB_FORMAT: format_matlab(t);
                default: format_hex(t);
            endcase
        endfunction
        
        //==========================================================================
        // 十六进制格式打印
        //==========================================================================
        protected virtual function void format_hex(T t);
            string line = "";
            
            if (m_cfg.include_time) begin
                line = {line, $sformatf("%0d%s", $time, m_cfg.separator)};
            end
            
            // 尝试获取字段值（通过反射或用户提供的回调）
            line = {line, get_hex_fields(t)};
            
            if (m_cfg.print_transaction_id && t.get_transaction_id() != -1) begin
                line = {line, $sformatf(" id=0x%0X", t.get_transaction_id())};
            end
            
            $fwrite(m_file_fd, "%s\n", line);
        endfunction
        
        // 获取十六进制字段（子类可重载）
        protected virtual function string get_hex_fields(T t);
            // 默认实现：尝试调用 pack()
            string hex_str;
            bit [8*$bits(T)-1:0] packed;
            
            if ($cast(packed, t)) begin
                hex_str = $sformatf("data=0x%0X", packed);
            end else begin
                hex_str = t.convert2string();
            end
            return hex_str;
        endfunction
        
        //==========================================================================
        // 二进制格式打印
        //==========================================================================
        protected virtual function void format_bin(T t);
            string line = "";
            
            if (m_cfg.include_time) begin
                line = {line, $sformatf("%0d%s", $time, m_cfg.separator)};
            end
            
            line = {line, get_bin_fields(t)};
            $fwrite(m_file_fd, "%s\n", line);
        endfunction
        
        protected virtual function string get_bin_fields(T t);
            return t.sprint();
        endfunction
        
        //==========================================================================
        // 十进制格式打印
        //==========================================================================
        protected virtual function void format_dec(T t);
            string line = "";
            
            if (m_cfg.include_time) begin
                line = {line, $sformatf("%0d%s", $time, m_cfg.separator)};
            end
            
            line = {line, get_dec_fields(t)};
            $fwrite(m_file_fd, "%s\n", line);
        endfunction
        
        protected virtual function string get_dec_fields(T t);
            return t.sprint();
        endfunction
        
        //==========================================================================
        // CSV 格式打印
        //==========================================================================
        protected virtual function void format_csv(T t);
            if (m_cfg.include_time) begin
                $fwrite(m_file_fd, "%0d,", $time);
            end
            write_csv_fields(t);
            $fwrite(m_file_fd, "\n");
        endfunction
        
        protected virtual function void write_csv_fields(T t);
            // 子类重载实现具体字段
            $fwrite(m_file_fd, "%s", t.convert2string());
        endfunction
        
        //==========================================================================
        // Verilog Hex 格式 (@time hex_data)
        //==========================================================================
        protected virtual function void format_verilog_hex(T t);
            bit [8*$bits(T)-1:0] packed;
            if ($cast(packed, t)) begin
                $fwrite(m_file_fd, "@%0h %h\n", $time, packed);
            end
        endfunction
        
        //==========================================================================
        // VCD 格式打印
        //==========================================================================
        protected virtual function void format_vcd(T t);
            $fwrite(m_file_fd, "#%0d\n", $time);
            write_vcd_signals(t);
        endfunction
        
        protected virtual function void write_vcd_signals(T t);
            // 子类重载
            $fwrite(m_file_fd, "$dumpvars\n");
        endfunction
        
        //==========================================================================
        // C 数组格式
        //==========================================================================
        protected virtual function void format_c_array(T t);
            bit [8*$bits(T)-1:0] packed;
            if ($cast(packed, t)) begin
                $fwrite(m_file_fd, "    {0x%08X, 0x%08X},  // %0d\n", 
                        packed[63:32], packed[31:0], $time);
            end
        endfunction
        
        //==========================================================================
        // Python 列表格式
        //==========================================================================
        protected virtual function void format_python_list(T t);
            bit [8*$bits(T)-1:0] packed;
            if ($cast(packed, t)) begin
                $fwrite(m_file_fd, "    (0x%0X, %0d),  # data, time\n", packed, $time);
            end
        endfunction
        
        //==========================================================================
        // MATLAB 格式
        //==========================================================================
        protected virtual function void format_matlab(T t);
            bit [8*$bits(T)-1:0] packed;
            if ($cast(packed, t)) begin
                $fwrite(m_file_fd, "%0d, 0x%0X\n", $time, packed);
            end
        endfunction
        
    endclass
    
    //==========================================================================
    // ALU 专用日志器（完整实现）
    //==========================================================================
    class alu_stimulus_logger extends generic_stimulus_logger#(alu_seq_item);
        `uvm_component_utils(alu_stimulus_logger)
        
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        
        // 重载十六进制字段提取
        protected virtual function string get_hex_fields(alu_seq_item t);
            if (m_cfg.include_time) begin
                return $sformatf("a=0x%02X b=0x%02X op=0x%01X result=0x%04X",
                                 t.a, t.b, t.op, t.result);
            end else begin
                return $sformatf("0x%02X,0x%02X,0x%01X,0x%04X",
                                 t.a, t.b, t.op, t.result);
            end
        endfunction
        
        // 重载二进制字段提取
        protected virtual function string get_bin_fields(alu_seq_item t);
            return $sformatf("a=0b%08b b=0b%08b op=0b%03b result=0b%016b",
                             t.a, t.b, t.op, t.result);
        endfunction
        
        // 重载十进制字段提取
        protected virtual function string get_dec_fields(alu_seq_item t);
            return $sformatf("a=%3d b=%3d op=%1d result=%5d",
                             t.a, t.b, t.op, t.result);
        endfunction
        
        // CSV 格式输出
        protected virtual function void write_csv_fields(alu_seq_item t);
            $fwrite(m_file_fd, "0x%02X,0x%02X,0x%01X,0x%04X",
                    t.a, t.b, t.op, t.result);
        endfunction
        
        // VCD 信号输出
        protected virtual function void write_vcd_signals(alu_seq_item t);
            $fwrite(m_file_fd, "b%08b a\n", t.a);
            $fwrite(m_file_fd, "b%08b b\n", t.b);
            $fwrite(m_file_fd, "b%03b op\n", t.op);
            $fwrite(m_file_fd, "b%016b result\n", t.result);
        endfunction
        
    endclass
    
    //==========================================================================
    // AXI 总线日志器示例
    //==========================================================================
    class axi_stimulus_logger extends generic_stimulus_logger#(axi_seq_item);
        `uvm_component_utils(axi_stimulus_logger)
        
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        
        protected virtual function string get_hex_fields(axi_seq_item t);
            return $sformatf("addr=0x%08X data=0x%016X id=0x%02X burst=%0d len=%0d",
                             t.addr, t.data, t.id, t.burst, t.len);
        endfunction
        
        protected virtual function void write_csv_fields(axi_seq_item t);
            $fwrite(m_file_fd, "0x%08X,0x%016X,0x%02X,%0d,%0d",
                    t.addr, t.data, t.id, t.burst, t.len);
        endfunction
        
    endclass
    
    //==========================================================================
    // 多通道日志器（支持多个输入源）
    //==========================================================================
    class multi_channel_logger #(type T = uvm_sequence_item) extends uvm_component;
        `uvm_component_param_utils(multi_channel_logger#(T))
        
        protected int m_file_fd;
        protected stim_log_config m_cfg;
        protected string m_channel_names[$];
        protected int m_channel_counts[$];
        
        // 通道分析端口
        uvm_analysis_imp#(T, multi_channel_logger#(T)) m_channel_imp[$];
        
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        
        function void add_channel(string channel_name);
            m_channel_names.push_back(channel_name);
            m_channel_counts.push_back(0);
            
            // 创建分析端口
            uvm_analysis_imp#(T, multi_channel_logger#(T)) imp;
            imp = new($sformatf("%s_imp", channel_name), this);
            m_channel_imp.push_back(imp);
        endfunction
        
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            
            if (!uvm_config_db#(stim_log_config)::get(this, "", "cfg", m_cfg)) begin
                m_cfg = stim_log_config::type_id::create("m_cfg");
            end
            
            m_file_fd = $fopen(m_cfg.filename, "w");
            if (m_file_fd) begin
                write_header();
            end
        endfunction
        
        function void write_header();
            $fwrite(m_file_fd, "// Multi-Channel Stimulus Logger\n");
            $fwrite(m_file_fd, "// Channels: ");
            foreach (m_channel_names[i]) begin
                $fwrite(m_file_fd, "%s ", m_channel_names[i]);
            end
            $fwrite(m_file_fd, "\n//====================================\n");
        endfunction
        
        function void write(T t, int channel_idx);
            if (!m_file_fd) return;
            
            m_channel_counts[channel_idx]++;
            $fwrite(m_file_fd, "[%s] %0t: %s\n", 
                    m_channel_names[channel_idx], $time, t.convert2string());
        endfunction
        
        // 通道写入函数
        function void write(T t);
            // 默认写入第一个通道
            write(t, 0);
        endfunction
        
        function void final_phase(uvm_phase phase);
            super.final_phase(phase);
            if (m_file_fd) begin
                $fwrite(m_file_fd, "\n// Channel Statistics:\n");
                foreach (m_channel_names[i]) begin
                    $fwrite(m_file_fd, "//   %s: %0d items\n", 
                            m_channel_names[i], m_channel_counts[i]);
                end
                $fclose(m_file_fd);
            end
        endfunction
        
    endclass
    
    //==========================================================================
    // 便利函数：快速创建日志器
    //==========================================================================
    function stimulus_logger_base#(T) create_stimulus_logger #(type T = uvm_sequence_item)
        (string name, uvm_component parent, string filename = "stimulus.hex");
        
        generic_stimulus_logger#(T) logger;
        stim_log_config cfg;
        
        cfg = stim_log_config::type_id::create("cfg");
        cfg.filename = filename;
        
        uvm_config_db#(stim_log_config)::set(parent, $sformatf("%s.cfg", name), "cfg", cfg);
        logger = generic_stimulus_logger#(T)::type_id::create(name, parent);
        
        return logger;
    endfunction
    
endpackage

// 在环境中使用日志器
// class alu_env extends uvm_env;
//     `uvm_component_utils(alu_env)
    
//     alu_agent m_agent;
//     alu_stimulus_logger m_logger;
    
//     function void build_phase(uvm_phase phase);
//         super.build_phase(phase);
        
//         m_agent = alu_agent::type_id::create("m_agent", this);
        
//         // 创建日志器
//         m_logger = alu_stimulus_logger::type_id::create("m_logger", this);
        
//         // 配置日志器
//         stim_log_config cfg = stim_log_config::type_id::create("cfg");
//         cfg.filename = "alu_stimulus.hex";
//         cfg.format = HEX_FORMAT;
//         cfg.include_time = 1;
//         cfg.auto_flush = 1;
//         uvm_config_db#(stim_log_config)::set(this, "m_logger", "cfg", cfg);
//     endfunction
    
//     function void connect_phase(uvm_phase phase);
//         super.connect_phase(phase);
//         // 连接监视器到日志器
//         m_agent.m_monitor.item_collected_port.connect(m_logger.m_analysis_imp);
//     endfunction
    
// endclass