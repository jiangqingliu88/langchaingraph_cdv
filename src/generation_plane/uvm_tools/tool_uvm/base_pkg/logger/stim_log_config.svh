// ════════════════════════════════════════════════════════════════
// stim_log_config.svh —— 日志格式枚举 + 全局日志配置类
// 职责: log_format_t 枚举、stim_log_config（文件名/格式/刷新策略，
//   +STIM_LOG_FORMAT / +STIM_LOG_FILE / +STIM_LOG_MAX 命令行配置）
// 依赖: 无（在 stimulus_logger_pkg 内 include）
// ════════════════════════════════════════════════════════════════

`ifndef STIM_LOG_CONFIG_SVH
`define STIM_LOG_CONFIG_SVH

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

`endif // STIM_LOG_CONFIG_SVH
