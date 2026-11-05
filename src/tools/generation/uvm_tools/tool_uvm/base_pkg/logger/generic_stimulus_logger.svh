// ════════════════════════════════════════════════════════════════
// generic_stimulus_logger.svh —— 通用序列项日志器
// 职责: 按 m_cfg.format 分发到 9 种格式打印
//   （hex/bin/dec/csv/verilog_hex/vcd/c_array/python_list/matlab）
// 依赖: stimulus_logger_base.svh
// ════════════════════════════════════════════════════════════════

`ifndef GENERIC_STIMULUS_LOGGER_SVH
`define GENERIC_STIMULUS_LOGGER_SVH

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

`endif // GENERIC_STIMULUS_LOGGER_SVH
