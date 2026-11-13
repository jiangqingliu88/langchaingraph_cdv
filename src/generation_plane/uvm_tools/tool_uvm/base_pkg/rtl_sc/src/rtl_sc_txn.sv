class rtl_sc_txn #(int DW = 256) extends uvm_sequence_item;

    bit [63:0]   addr;
    bit [DW-1:0] data;
    int unsigned  byte_len;
    int unsigned  seq_num;
    time          ts;

    `uvm_object_param_utils_begin(rtl_sc_txn #(DW))
        `uvm_field_int(addr,     UVM_ALL_ON)
        `uvm_field_int(data,     UVM_ALL_ON)
        `uvm_field_int(byte_len, UVM_ALL_ON)
        `uvm_field_int(seq_num,  UVM_ALL_ON)
    `uvm_object_param_utils_end

    function new(string name = "rtl_sc_txn");
        super.new(name);
    endfunction

    virtual function void do_pack(uvm_packer packer);
        super.do_pack(packer);
        packer.pack_field_int(addr, 64);
        packer.pack_field_int(seq_num, 32);
        packer.pack_field_int(byte_len, 32);
        for (int i = 0; i < DW/8; i++)
            packer.pack_field_int(data[i*8 +: 8], 8);
    endfunction

    virtual function void do_unpack(uvm_packer packer);
        super.do_unpack(packer);
        addr     = packer.unpack_field_int(64);
        seq_num  = packer.unpack_field_int(32);
        byte_len = packer.unpack_field_int(32);
        data = '0;
        for (int i = 0; i < DW/8; i++)
            data[i*8 +: 8] = packer.unpack_field_int(8);
    endfunction

endclass
