// ════════════════════════════════════════════════════════════════
// stimulus_logger_base.svh —— 基础激励日志器（抽象类）
// 职责: 文件生命周期（open/header/footer/close）、配置获取、
//   分析 imp 回调（write(T) 即主入口）、自动刷新
// 依赖: stim_log_config.svh
// 注: write(T t) 同时是 uvm_analysis_imp 回调与直接调用入口
//   （原单文件版曾重复定义两个同名 write 造成重定义+自递归，已合并）
// ════════════════════════════════════════════════════════════════

`ifndef STIMULUS_LOGGER_BASE_SVH
`define STIMULUS_LOGGER_BASE_SVH

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

        // 分析端口（write 回调 = 下方主入口 write(T)）
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

        // 写入事务（主入口；同时是 uvm_analysis_imp 的 write 回调）
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

`endif // STIMULUS_LOGGER_BASE_SVH
