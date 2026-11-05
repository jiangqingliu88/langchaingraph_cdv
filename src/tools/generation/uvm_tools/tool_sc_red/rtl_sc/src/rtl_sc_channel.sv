`uvm_analysis_imp_decl(_rtl)
`uvm_analysis_imp_decl(_sc)

class rtl_sc_channel #(int DW = 256) extends uvm_component;

    typedef rtl_sc_txn #(DW) txn_t;

    uvm_analysis_imp_rtl #(txn_t, rtl_sc_channel #(DW)) rtl_imp;
    uvm_analysis_imp_sc  #(txn_t, rtl_sc_channel #(DW)) sc_imp;

    string channel_id;

    protected txn_t rtl_q[$];
    protected txn_t sc_q[$];
    protected rtl_sc_cfg cfg;

    int unsigned match_cnt;
    int unsigned mismatch_cnt;
    int unsigned timeout_cnt;
    int unsigned error_total;

    `uvm_component_param_utils(rtl_sc_channel #(DW))

    function new(string name, uvm_component parent);
        super.new(name, parent);
        rtl_imp = new("rtl_imp", this);
        sc_imp  = new("sc_imp", this);
        match_cnt    = 0;
        mismatch_cnt = 0;
        timeout_cnt  = 0;
        error_total  = 0;
    endfunction

    function void set_cfg(rtl_sc_cfg c);
        cfg = c;
    endfunction

    function void write_rtl(txn_t t);
        txn_t clone;
        if (cfg.max_queue_depth > 0 && rtl_q.size() >= cfg.max_queue_depth) begin
            `uvm_error(channel_id, $sformatf("RTL queue overflow (depth=%0d)", rtl_q.size()))
            return;
        end
        $cast(clone, t.clone());
        clone.ts = $time;
        rtl_q.push_back(clone);
    endfunction

    function void write_sc(txn_t t);
        txn_t clone;
        if (cfg.max_queue_depth > 0 && sc_q.size() >= cfg.max_queue_depth) begin
            `uvm_error(channel_id, $sformatf("SC queue overflow (depth=%0d)", sc_q.size()))
            return;
        end
        $cast(clone, t.clone());
        clone.ts = $time;
        sc_q.push_back(clone);
    endfunction

    task run_phase(uvm_phase phase);
        fork
            compare_loop();
            timeout_watch();
        join_none
    endtask

    protected task compare_loop();
        txn_t r, s;
        forever begin
            wait(rtl_q.size() > 0 && sc_q.size() > 0);
            r = rtl_q.pop_front();
            s = sc_q.pop_front();
            do_compare(r, s);
        end
    endtask

    protected function void do_compare(txn_t r, txn_t s);
        bit pass = 1;
        int unsigned len;

        if (r.addr !== s.addr) begin
            `uvm_error(channel_id, $sformatf(
                "ADDR mismatch seq=%0d: RTL=0x%016h SC=0x%016h",
                r.seq_num, r.addr, s.addr))
            pass = 0;
        end

        len = (r.byte_len < s.byte_len) ? r.byte_len : s.byte_len;
        for (int i = 0; i < len; i++) begin
            if (r.data[i*8 +: 8] !== s.data[i*8 +: 8]) begin
                `uvm_error(channel_id, $sformatf(
                    "DATA mismatch seq=%0d byte[%0d]: RTL=0x%02h SC=0x%02h",
                    r.seq_num, i, r.data[i*8 +: 8], s.data[i*8 +: 8]))
                pass = 0;
                break;
            end
        end

        if (pass) begin
            match_cnt++;
            `uvm_info(channel_id, $sformatf("MATCH seq=%0d addr=0x%016h", r.seq_num, r.addr), UVM_HIGH)
        end else begin
            mismatch_cnt++;
            error_total++;
            if (cfg.stop_on_first) begin
                `uvm_fatal(channel_id, "Stop on first error triggered")
            end
            if (cfg.max_errors > 0 && error_total >= cfg.max_errors) begin
                `uvm_fatal(channel_id, $sformatf("Max errors (%0d) reached", cfg.max_errors))
            end
        end
    endfunction

    protected task timeout_watch();
        if (!cfg.enable_timeout_check) return;
        forever begin
            #(cfg.timeout_cycles * 1ns);
            while (rtl_q.size() > 0 && ($time - rtl_q[0].ts) > cfg.timeout_cycles * 1ns) begin
                `uvm_error(channel_id, $sformatf(
                    "TIMEOUT: RTL seq=%0d waited too long", rtl_q[0].seq_num))
                void'(rtl_q.pop_front());
                timeout_cnt++;
                error_total++;
            end
            while (sc_q.size() > 0 && ($time - sc_q[0].ts) > cfg.timeout_cycles * 1ns) begin
                `uvm_error(channel_id, $sformatf(
                    "TIMEOUT: SC seq=%0d waited too long", sc_q[0].seq_num))
                void'(sc_q.pop_front());
                timeout_cnt++;
                error_total++;
            end
        end
    endtask

    function void report_phase(uvm_phase phase);
        `uvm_info(channel_id, $sformatf(
            "Results: match=%0d mismatch=%0d timeout=%0d",
            match_cnt, mismatch_cnt, timeout_cnt), UVM_LOW)
    endfunction

    bit enable_timeout_check = 1;
endclass
