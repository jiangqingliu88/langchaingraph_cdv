// ════════════════════════════════════════════════════════════════
// multi_channel_logger.svh —— 多通道日志器（支持多个输入源）
// 职责: add_channel 注册通道 → 各自 analysis imp → [通道名] 前缀记录，
//   final_phase 输出每通道统计
// 依赖: stim_log_config.svh
// ════════════════════════════════════════════════════════════════

`ifndef MULTI_CHANNEL_LOGGER_SVH
`define MULTI_CHANNEL_LOGGER_SVH

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

        // 通道写入函数（analysis imp 回调：默认写入第一个通道）
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

`endif // MULTI_CHANNEL_LOGGER_SVH
