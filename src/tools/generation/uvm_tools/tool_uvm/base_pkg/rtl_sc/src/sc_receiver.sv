class sc_receiver #(int DW = 256) extends uvm_component;

    typedef rtl_sc_txn #(DW) txn_t;

    uvm_tlm_b_target_socket #(sc_receiver #(DW)) target_socket;
    uvm_analysis_port #(txn_t) ap;

    string channel_id;

    `uvm_component_param_utils(sc_receiver #(DW))

    function new(string name, uvm_component parent);
        super.new(name, parent);
        target_socket = new("target_socket", this);
        ap = new("ap", this);
    endfunction

    task b_transport(uvm_tlm_gp gp, uvm_tlm_time delay);
        txn_t t;
        byte unsigned gp_data[];
        int unsigned len, sw;

        t = txn_t::type_id::create("sc_txn");

        t.addr = gp.get_address();
        sw = gp.get_streaming_width();
        t.seq_num = sw;

        gp.get_data(gp_data);
        len = gp.get_data_length();
        if (len > DW/8) len = DW/8;
        t.byte_len = len;
        t.data = '0;
        for (int i = 0; i < len; i++)
            t.data[i*8 +: 8] = gp_data[i];

        gp.set_response_status(UVM_TLM_OK_RESPONSE);
        ap.write(t);
    endtask

endclass
