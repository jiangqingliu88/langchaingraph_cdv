class rtl_monitor_ex #(int DW = 256) extends rtl_sc_monitor_base #(DW);

    virtual rtl_data_if #(DW) vif;

    `uvm_component_param_utils(rtl_monitor_ex #(DW))

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if (!uvm_config_db #(virtual rtl_data_if #(DW))::get(this, "", "vif", vif))
            `uvm_fatal(get_name(), "Failed to get vif from config_db")
    endfunction

    task capture();
        forever begin
            @(posedge vif.clk);
            if (vif.rst_n && vif.valid) begin
                send_txn(vif.addr, vif.data, vif.byte_len);
            end
        end
    endtask

endclass
