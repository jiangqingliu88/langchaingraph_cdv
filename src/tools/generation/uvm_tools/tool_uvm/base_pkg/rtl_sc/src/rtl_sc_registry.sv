class rtl_sc_registry #(int DW = 256);

    typedef rtl_sc_txn #(DW) txn_t;
    typedef rtl_sc_channel #(DW) channel_t;
    typedef sc_receiver #(DW) receiver_t;

    // Internal storage
    static protected channel_t   m_channels[string];
    static protected receiver_t  m_receivers[string];
    static protected cfg_sender  m_cfgs[string];
    static protected rtl_sc_cfg  m_cfg_obj;
    static protected uvm_component m_parent;
    static protected bit m_inited;

    // Pending RTL port connections (from build_phase, connected in connect_all)
    typedef struct {
        string id;
        uvm_analysis_port #(txn_t) port;
    } rtl_entry_t;
    static protected rtl_entry_t m_rtl_pending[$];

    // -------------------------------------------------------
    // init: call once before any registration
    // -------------------------------------------------------
    static function void init(uvm_component parent, rtl_sc_cfg cfg = null);
        m_parent = parent;
        if (cfg == null) begin
            m_cfg_obj = new("rtl_sc_cfg");
        end else begin
            m_cfg_obj = cfg;
        end
        m_inited = 1;
    endfunction

    // -------------------------------------------------------
    // register_rtl: one line, registers RTL analysis port
    //   rtl_sc_registry#(256)::register_rtl("dma_0", mon.ap);
    // -------------------------------------------------------
    static function void register_rtl(string id, uvm_analysis_port #(txn_t) port);
        rtl_entry_t e;
        assert(m_inited) else $fatal(1, "rtl_sc_registry: call init() first");
        ensure_channel(id);
        e.id = id;
        e.port = port;
        m_rtl_pending.push_back(e);
    endfunction

    // -------------------------------------------------------
    // register_sc: one line, registers SC-side UVMC receiver
    //   rtl_sc_registry#(256)::register_sc("dma_0");
    // -------------------------------------------------------
    static function void register_sc(string id);
        receiver_t recv;
        assert(m_inited) else $fatal(1, "rtl_sc_registry: call init() first");
        ensure_channel(id);
        if (!m_receivers.exists(id)) begin
            recv = receiver_t::type_id::create({"sc_recv_", id}, m_parent);
            recv.channel_id = id;
            m_receivers[id] = recv;
        end
    endfunction

    // -------------------------------------------------------
    // register_cfg: one line, creates a named config sender
    //   rtl_sc_registry#(256)::register_cfg("dma_cfg");
    // -------------------------------------------------------
    static function void register_cfg(string id);
        assert(m_inited) else $fatal(1, "rtl_sc_registry: call init() first");
        if (!m_cfgs.exists(id)) begin
            m_cfgs[id] = cfg_sender::type_id::create({"cfg_", id}, m_parent);
            m_cfgs[id].channel_id = id;
        end
    endfunction

    // -------------------------------------------------------
    // connect_all: call in connect_phase
    // -------------------------------------------------------
    static function void connect_all();
        string id;

        // Connect RTL ports to channel rtl_imp
        foreach (m_rtl_pending[i]) begin
            id = m_rtl_pending[i].id;
            m_rtl_pending[i].port.connect(m_channels[id].rtl_imp);
        end

        // Connect SC receivers to channel sc_imp + UVMC
        if (m_receivers.first(id)) begin
            do begin
                m_receivers[id].ap.connect(m_channels[id].sc_imp);
                uvmc_tlm #()::connect(m_receivers[id].target_socket,
                                      {"rtl_sc_", id});
            end while (m_receivers.next(id));
        end

        // Connect config senders to UVMC
        if (m_cfgs.first(id)) begin
            do begin
                uvmc_tlm #()::connect(m_cfgs[id].init_socket,
                                      {"rtl_sc_cfg_", id});
            end while (m_cfgs.next(id));
        end
    endfunction

    // -------------------------------------------------------
    // send_cfg: send a packed struct to named config channel
    //   byte unsigned bytes[];
    //   // pack struct into bytes...
    //   rtl_sc_registry#(256)::send_cfg("dma_cfg", bytes);
    // -------------------------------------------------------
    static task send_cfg(string id, byte unsigned data[]);
        assert(m_cfgs.exists(id)) else
            $fatal(1, {"rtl_sc_registry: cfg '", id, "' not registered"});
        m_cfgs[id].send_cfg(data, data.size());
    endtask

    // -------------------------------------------------------
    // report: print all channel results
    // -------------------------------------------------------
    static function void report();
        string id;
        if (m_channels.first(id)) begin
            do begin
                `uvm_info("RTL_SC", $sformatf(
                    "[%s] match=%0d mismatch=%0d timeout=%0d",
                    id, m_channels[id].match_cnt,
                    m_channels[id].mismatch_cnt,
                    m_channels[id].timeout_cnt), UVM_LOW)
            end while (m_channels.next(id));
        end
    endfunction

    // -------------------------------------------------------
    // Internal: ensure channel exists
    // -------------------------------------------------------
    static protected function void ensure_channel(string id);
        channel_t ch;
        if (!m_channels.exists(id)) begin
            ch = channel_t::type_id::create({"ch_", id}, m_parent);
            ch.channel_id = id;
            ch.set_cfg(m_cfg_obj);
            m_channels[id] = ch;
        end
    endfunction

endclass
