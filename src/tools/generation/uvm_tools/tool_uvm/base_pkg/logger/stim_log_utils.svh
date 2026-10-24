// ════════════════════════════════════════════════════════════════
// stim_log_utils.svh —— 便利函数：快速创建日志器
// 职责: create_stimulus_logger 一步完成 config_db set + 类型化创建
// 依赖: generic_stimulus_logger.svh
// ════════════════════════════════════════════════════════════════

`ifndef STIM_LOG_UTILS_SVH
`define STIM_LOG_UTILS_SVH

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

`endif // STIM_LOG_UTILS_SVH
