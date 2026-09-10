// ════════════════════════════════════════════════════════════════
// axi_stimulus_logger.svh —— AXI 总线日志器（示例）
// 职责: 重载 hex/csv 字段提取，输出 addr/data/id/burst/len
// 依赖: generic_stimulus_logger.svh
// 注: 引用 axi_seq_item 类型——需外部（agent pkg）提供，
//   与 ALU 示例日志器同理；未提供对应类型时请勿编译本文件
// ════════════════════════════════════════════════════════════════

`ifndef AXI_STIMULUS_LOGGER_SVH
`define AXI_STIMULUS_LOGGER_SVH

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

`endif // AXI_STIMULUS_LOGGER_SVH
