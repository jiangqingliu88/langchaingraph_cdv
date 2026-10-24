class cfg_sender extends uvm_component;

    uvm_tlm_b_initiator_socket #() init_socket;
    string channel_id;

    `uvm_component_utils(cfg_sender)

    function new(string name, uvm_component parent);
        super.new(name, parent);
        init_socket = new("init_socket", this);
    endfunction

    // Send a packed struct as raw bytes via GP.
    // User packs their struct into byte array, this sends it.
    task send_cfg(byte unsigned data[], int unsigned len);
        uvm_tlm_gp gp = new("cfg_gp");
        uvm_tlm_time delay = new("delay", 1e-9);

        gp.set_write();
        gp.set_address(0);
        gp.set_data(data);
        gp.set_data_length(len);
        gp.set_streaming_width(len);
        gp.set_byte_enable_length(0);
        gp.set_response_status(UVM_TLM_INCOMPLETE_RESPONSE);

        init_socket.b_transport(gp, delay);
    endtask

endclass
