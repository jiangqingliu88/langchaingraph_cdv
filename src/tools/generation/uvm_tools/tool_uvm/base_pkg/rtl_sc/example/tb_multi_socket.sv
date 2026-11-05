// Multi-socket example with struct-based config.
// - 3 DMA channels (256b) with "dma_cfg" struct
// - 2 PCIe channels (128b) with "pcie_cfg" struct
// - 1 HBM channel (512b) with "hbm_cfg" struct

`timescale 1ns/1ps

module tb_multi_socket;

    import uvm_pkg::*;
    import uvmc_pkg::*;
    import rtl_sc_pkg::*;
    `include "uvm_macros.svh"

    logic clk, rst_n;
    initial begin clk = 0; forever #5 clk = ~clk; end
    initial begin rst_n = 0; #50; rst_n = 1; end

    // -------------------------------------------------------
    // Config structs (shared between SV and SC via packed bytes)
    // -------------------------------------------------------
    typedef struct packed {
        bit [63:0] base_addr_0;
        bit [63:0] base_addr_1;
        bit [63:0] base_addr_2;
        bit [31:0] burst_size;
        bit [31:0] num_beats;
    } dma_cfg_t;   // 28 bytes

    typedef struct packed {
        bit [63:0] base_addr_0;
        bit [63:0] base_addr_1;
        bit [31:0] max_payload;
        bit [7:0]  enable_mask;
        bit [7:0]  reserved;
    } pcie_cfg_t;  // 22 bytes (with padding would be different, using packed)

    typedef struct packed {
        bit [63:0] base_addr;
        bit [31:0] burst_len;
        bit [31:0] channel_mode;
    } hbm_cfg_t;   // 16 bytes

    // -------------------------------------------------------
    // Interfaces
    // -------------------------------------------------------
    rtl_data_if #(256) dma_if[3](clk, rst_n);
    rtl_data_if #(128) pcie_if[2](clk, rst_n);
    rtl_data_if #(512) hbm_if(clk, rst_n);

    // -------------------------------------------------------
    // DMA stimulus
    // -------------------------------------------------------
    genvar gi;
    generate
        for (gi = 0; gi < 3; gi++) begin : dma_stim
            initial begin
                dma_if[gi].valid = 0; dma_if[gi].addr = 0;
                dma_if[gi].data = 0; dma_if[gi].byte_len = 0;
                wait(rst_n); repeat(20 + gi * 5) @(posedge clk);
                for (int i = 0; i < 15; i++) begin
                    @(posedge clk);
                    dma_if[gi].valid    = 1;
                    dma_if[gi].addr     = 64'hA000 + gi * 64'h1000 + i * 32;
                    dma_if[gi].byte_len = 32;
                    for (int b = 0; b < 32; b++)
                        dma_if[gi].data[b*8 +: 8] = (gi * 64 + i * 32 + b) & 8'hFF;
                    @(posedge clk);
                    dma_if[gi].valid = 0;
                    repeat(2) @(posedge clk);
                end
            end
        end
    endgenerate

    // -------------------------------------------------------
    // PCIe stimulus
    // -------------------------------------------------------
    generate
        for (gi = 0; gi < 2; gi++) begin : pcie_stim
            initial begin
                pcie_if[gi].valid = 0; pcie_if[gi].addr = 0;
                pcie_if[gi].data = 0; pcie_if[gi].byte_len = 0;
                wait(rst_n); repeat(30 + gi * 3) @(posedge clk);
                for (int i = 0; i < 12; i++) begin
                    @(posedge clk);
                    pcie_if[gi].valid    = 1;
                    pcie_if[gi].addr     = 64'hD000 + gi * 64'h800 + i * 16;
                    pcie_if[gi].byte_len = 16;
                    for (int b = 0; b < 16; b++)
                        pcie_if[gi].data[b*8 +: 8] = (gi * 32 + i * 16 + b) & 8'hFF;
                    @(posedge clk);
                    pcie_if[gi].valid = 0;
                end
            end
        end
    endgenerate

    // -------------------------------------------------------
    // HBM stimulus
    // -------------------------------------------------------
    initial begin
        hbm_if.valid = 0; hbm_if.addr = 0;
        hbm_if.data = 0; hbm_if.byte_len = 0;
        wait(rst_n); repeat(40) @(posedge clk);
        for (int i = 0; i < 8; i++) begin
            @(posedge clk);
            hbm_if.valid    = 1;
            hbm_if.addr     = 64'hF000 + i * 64;
            hbm_if.byte_len = 64;
            for (int b = 0; b < 64; b++)
                hbm_if.data[b*8 +: 8] = (i * 64 + b) & 8'hFF;
            @(posedge clk);
            hbm_if.valid = 0;
            repeat(3) @(posedge clk);
        end
    end

    // -------------------------------------------------------
    // UVM Test
    // -------------------------------------------------------
    class multi_socket_test extends uvm_test;
        `uvm_component_utils(multi_socket_test)

        typedef rtl_sc_registry #(256) reg256_t;
        typedef rtl_sc_registry #(128) reg128_t;
        typedef rtl_sc_registry #(512) reg512_t;

        rtl_monitor_ex #(256) dma_mon[3];
        rtl_monitor_ex #(128) pcie_mon[2];
        rtl_monitor_ex #(512) hbm_mon;

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        function void build_phase(uvm_phase phase);
            rtl_sc_cfg cfg;
            super.build_phase(phase);

            cfg = new("cfg");
            cfg.timeout_cycles = 8000;
            cfg.max_errors     = 50;

            reg256_t::init(this, cfg);
            reg128_t::init(this, cfg);
            reg512_t::init(this, cfg);

            // Data channels
            reg256_t::register_sc("dma_0");
            reg256_t::register_sc("dma_1");
            reg256_t::register_sc("dma_2");
            reg128_t::register_sc("pcie_0");
            reg128_t::register_sc("pcie_1");
            reg512_t::register_sc("hbm_0");

            // Config channels (struct-based)
            reg256_t::register_cfg("dma_cfg");
            reg128_t::register_cfg("pcie_cfg");
            reg512_t::register_cfg("hbm_cfg");

            // Monitors
            for (int i = 0; i < 3; i++) begin
                dma_mon[i] = rtl_monitor_ex #(256)::type_id::create(
                    $sformatf("dma_mon_%0d", i), this);
                dma_mon[i].channel_id = $sformatf("dma_%0d", i);
                uvm_config_db #(virtual rtl_data_if #(256))::set(
                    this, $sformatf("dma_mon_%0d", i), "vif", dma_if[i]);
            end

            for (int i = 0; i < 2; i++) begin
                pcie_mon[i] = rtl_monitor_ex #(128)::type_id::create(
                    $sformatf("pcie_mon_%0d", i), this);
                pcie_mon[i].channel_id = $sformatf("pcie_%0d", i);
                uvm_config_db #(virtual rtl_data_if #(128))::set(
                    this, $sformatf("pcie_mon_%0d", i), "vif", pcie_if[i]);
            end

            hbm_mon = rtl_monitor_ex #(512)::type_id::create("hbm_mon", this);
            hbm_mon.channel_id = "hbm_0";
            uvm_config_db #(virtual rtl_data_if #(512))::set(
                this, "hbm_mon", "vif", hbm_if);
        endfunction

        function void connect_phase(uvm_phase phase);
            super.connect_phase(phase);

            reg256_t::register_rtl("dma_0",  dma_mon[0].ap);
            reg256_t::register_rtl("dma_1",  dma_mon[1].ap);
            reg256_t::register_rtl("dma_2",  dma_mon[2].ap);
            reg128_t::register_rtl("pcie_0", pcie_mon[0].ap);
            reg128_t::register_rtl("pcie_1", pcie_mon[1].ap);
            reg512_t::register_rtl("hbm_0",  hbm_mon.ap);

            reg256_t::connect_all();
            reg128_t::connect_all();
            reg512_t::connect_all();
        endfunction

        task run_phase(uvm_phase phase);
            dma_cfg_t  dma_cfg_s;
            pcie_cfg_t pcie_cfg_s;
            hbm_cfg_t  hbm_cfg_s;

            byte unsigned dma_bytes[];
            byte unsigned pcie_bytes[];
            byte unsigned hbm_bytes[];

            phase.raise_objection(this);

            // --- Pack DMA config struct ---
            dma_cfg_s.base_addr_0 = 64'hA000;
            dma_cfg_s.base_addr_1 = 64'hB000;
            dma_cfg_s.base_addr_2 = 64'hC000;
            dma_cfg_s.burst_size  = 32;
            dma_cfg_s.num_beats   = 15;
            dma_bytes = new[$bits(dma_cfg_t)/8];
            { >> {dma_bytes}} = dma_cfg_s;
            reg256_t::send_cfg("dma_cfg", dma_bytes);

            // --- Pack PCIe config struct ---
            pcie_cfg_s.base_addr_0 = 64'hD000;
            pcie_cfg_s.base_addr_1 = 64'hD800;
            pcie_cfg_s.max_payload = 256;
            pcie_cfg_s.enable_mask = 8'hFF;
            pcie_cfg_s.reserved    = 0;
            pcie_bytes = new[$bits(pcie_cfg_t)/8];
            { >> {pcie_bytes}} = pcie_cfg_s;
            reg128_t::send_cfg("pcie_cfg", pcie_bytes);

            // --- Pack HBM config struct ---
            hbm_cfg_s.base_addr    = 64'hF000;
            hbm_cfg_s.burst_len    = 64;
            hbm_cfg_s.channel_mode = 1;
            hbm_bytes = new[$bits(hbm_cfg_t)/8];
            { >> {hbm_bytes}} = hbm_cfg_s;
            reg512_t::send_cfg("hbm_cfg", hbm_bytes);

            `uvm_info("TEST", "Struct configs sent (DMA/PCIe/HBM)", UVM_LOW)
            #500000;

            `uvm_info("TEST", "=== Final Report ===", UVM_LOW)
            reg256_t::report();
            reg128_t::report();
            reg512_t::report();

            phase.drop_objection(this);
        endtask
    endclass

    initial begin
        run_test("multi_socket_test");
    end

endmodule
