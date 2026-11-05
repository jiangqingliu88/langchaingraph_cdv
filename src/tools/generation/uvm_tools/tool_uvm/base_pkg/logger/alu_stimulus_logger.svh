// ════════════════════════════════════════════════════════════════
// alu_stimulus_logger.svh —— ALU 专用日志器（示例）
// 职责: 重载 hex/bin/dec/csv/vcd 字段提取，输出 a/b/op/result
// 依赖: generic_stimulus_logger.svh
// 注: 引用 alu_seq_item 类型——需外部（agent pkg）提供，
//   与 AXI 示例日志器同理；未提供对应类型时请勿编译本文件
// ════════════════════════════════════════════════════════════════

`ifndef ALU_STIMULUS_LOGGER_SVH
`define ALU_STIMULUS_LOGGER_SVH

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

`endif // ALU_STIMULUS_LOGGER_SVH
