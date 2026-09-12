virtual class rtl_sc_monitor_base #(int DW = 256) extends uvm_monitor;

    typedef rtl_sc_txn #(DW) txn_t;

    uvm_analysis_port #(txn_t) ap;
    string channel_id;
    protected int unsigned seq_counter;

    function new(string name, uvm_component parent);
        super.new(name, parent);
        ap = new("ap", this);
        seq_counter = 0;
    endfunction

    protected function void send_txn(bit [63:0] addr,
                                     bit [DW-1:0] data,
                                     int unsigned byte_len);
        txn_t t = txn_t::type_id::create("txn");
        t.addr     = addr;
        t.data     = data;
        t.byte_len = byte_len;
        t.seq_num  = seq_counter++;
        ap.write(t);
    endfunction

    pure virtual task capture();

    task run_phase(uvm_phase phase);
        capture();
    endtask

endclass
