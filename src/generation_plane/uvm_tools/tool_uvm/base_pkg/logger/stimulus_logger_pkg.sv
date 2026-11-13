// ════════════════════════════════════════════════════════════════
// stimulus_logger_pkg.sv —— 激励日志器包（顶层组装文件）
// 职责: 按依赖顺序 include 各分片（.svh），对外仅暴露本 package
// 分片:
//   stim_log_config.svh         日志格式枚举 + 配置类
//   stimulus_logger_base.svh    抽象基类（文件生命周期 + analysis imp）
//   generic_stimulus_logger.svh 通用日志器（9 种格式）
//   alu_stimulus_logger.svh     ALU 示例日志器（依赖外部 alu_seq_item）
//   axi_stimulus_logger.svh     AXI 示例日志器（依赖外部 axi_seq_item）
//   multi_channel_logger.svh    多通道日志器
//   stim_log_utils.svh          create_stimulus_logger 便利函数
// 注: alu/axi 示例引用外部 seq_item 类型；如无对应类型，
//   可在 package 内注释掉对应 include（其余分片不受影响）
// ════════════════════════════════════════════════════════════════

package stimulus_logger_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    // 依赖顺序: config → base → generic → 示例 → multi_channel → utils
    `include "stim_log_config.svh"
    `include "stimulus_logger_base.svh"
    `include "generic_stimulus_logger.svh"
    `include "alu_stimulus_logger.svh"
    `include "axi_stimulus_logger.svh"
    `include "multi_channel_logger.svh"
    `include "stim_log_utils.svh"

endpackage

// ════════════════════════════════════════════════════════════════
// 在环境中使用日志器（示例）
// ════════════════════════════════════════════════════════════════
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
