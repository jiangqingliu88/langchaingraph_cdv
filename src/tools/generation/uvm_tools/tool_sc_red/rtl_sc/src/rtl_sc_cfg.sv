class rtl_sc_cfg extends uvm_object;
    `uvm_object_utils(rtl_sc_cfg)

    int unsigned timeout_cycles   = 10000;
    int unsigned max_errors       = 0;      // 0 = unlimited
    bit          stop_on_first    = 0;
    int unsigned max_queue_depth  = 256;

    function new(string name = "rtl_sc_cfg");
        super.new(name);
    endfunction
endclass
