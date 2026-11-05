// Multi-channel testbench: demonstrates 64b, 128b, 256b, 512b simultaneous comparison.

`timescale 1ns/1ps

module tb_multi_channel;

    import uvm_pkg::*;
    import uvmc_pkg::*;
    import rtl_sc_pkg::*;
    `include "uvm_macros.svh"

    logic clk, rst_n;

    initial begin clk = 0; forever #5 clk = ~clk; end
    initial begin rst_n = 0; #50; rst_n = 1; end

    // 4 interfaces with different widths
    rtl_data_if #(64)  if_64(clk, rst_n);
    rtl_data_if #(128) if_128(clk, rst_n);
    rtl_data_if #(256) if_256(clk, rst_n);
    rtl_data_if #(512) if_512(clk, rst_n);

    // Stimulus for 64-bit channel
    initial begin
        if_64.valid = 0; if_64.addr = 0; if_64.data = 0; if_64.byte_len = 0;
        wait(rst_n); repeat(20) @(posedge clk);
        for (int i = 0; i < 10; i++) begin
            @(posedge clk);
            if_64.valid    = 1;
            if_64.addr     = 64'h2000 + i * 8;
            if_64.byte_len = 8;
            for (int b = 0; b < 8; b++)
                if_64.data[b*8 +: 8] = (i * 8 + b) & 8'hFF;
            @(posedge clk);
            if_64.valid = 0;
        end
    end

    // Stimulus for 128-bit channel
    initial begin
        if_128.valid = 0; if_128.addr = 0; if_128.data = 0; if_128.byte_len = 0;
        wait(rst_n); repeat(25) @(posedge clk);
        for (int i = 0; i < 10; i++) begin
            @(posedge clk);
            if_128.valid    = 1;
            if_128.addr     = 64'h3000 + i * 16;
            if_128.byte_len = 16;
            for (int b = 0; b < 16; b++)
                if_128.data[b*8 +: 8] = (i * 16 + b) & 8'hFF;
            @(posedge clk);
            if_128.valid = 0;
        end
    end

    // Stimulus for 256-bit channel
    initial begin
        if_256.valid = 0; if_256.addr = 0; if_256.data = 0; if_256.byte_len = 0;
        wait(rst_n); repeat(30) @(posedge clk);
        for (int i = 0; i < 10; i++) begin
            @(posedge clk);
            if_256.valid    = 1;
            if_256.addr     = 64'h4000 + i * 32;
            if_256.byte_len = 32;
            for (int b = 0; b < 32; b++)
                if_256.data[b*8 +: 8] = (i * 32 + b) & 8'hFF;
            @(posedge clk);
            if_256.valid = 0;
        end
    end

    // Stimulus for 512-bit channel
    initial begin
        if_512.valid = 0; if_512.addr = 0; if_512.data = 0; if_512.byte_len = 0;
        wait(rst_n); repeat(35) @(posedge clk);
        for (int i = 0; i < 10; i++) begin
            @(posedge clk);
            if_512.valid    = 1;
            if_512.addr     = 64'h5000 + i * 64;
            if_512.byte_len = 64;
            for (int b = 0; b < 64; b++)
                if_512.data[b*8 +: 8] = (i * 64 + b) & 8'hFF;
            @(posedge clk);
            if_512.valid = 0;
        end
    end

    // -------------------------------------------------------
    class multi_test extends uvm_test;
        `uvm_component_utils(multi_test)

        typedef rtl_sc_registry #(64)  reg64_t;
        typedef rtl_sc_registry #(128) reg128_t;
        typedef rtl_sc_registry #(256) reg256_t;
        typedef rtl_sc_registry #(512) reg512_t;

        rtl_monitor_ex #(64)  mon_64;
        rtl_monitor_ex #(128) mon_128;
        rtl_monitor_ex #(256) mon_256;
        rtl_monitor_ex #(512) mon_512;

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        function void build_phase(uvm_phase phase);
            rtl_sc_cfg cfg;
            super.build_phase(phase);

            cfg = new("cfg");
            cfg.timeout_cycles = 5000;

            // Initialize each width registry
            reg64_t::init(this, cfg);
            reg128_t::init(this, cfg);
            reg256_t::init(this, cfg);
            reg512_t::init(this, cfg);

            // Register SC channels (one line each)
            reg64_t::register_sc("pcie_64");
            reg128_t::register_sc("dma_128");
            reg256_t::register_sc("noc_256");
            reg512_t::register_sc("hbm_512");

            // Register config (only once — shared)
            reg256_t::register_cfg();

            // Create monitors
            mon_64  = rtl_monitor_ex #(64)::type_id::create("mon_64", this);
            mon_128 = rtl_monitor_ex #(128)::type_id::create("mon_128", this);
            mon_256 = rtl_monitor_ex #(256)::type_id::create("mon_256", this);
            mon_512 = rtl_monitor_ex #(512)::type_id::create("mon_512", this);

            mon_64.channel_id  = "pcie_64";
            mon_128.channel_id = "dma_128";
            mon_256.channel_id = "noc_256";
            mon_512.channel_id = "hbm_512";

            uvm_config_db #(virtual rtl_data_if #(64))::set(this, "mon_64", "vif", if_64);
            uvm_config_db #(virtual rtl_data_if #(128))::set(this, "mon_128", "vif", if_128);
            uvm_config_db #(virtual rtl_data_if #(256))::set(this, "mon_256", "vif", if_256);
            uvm_config_db #(virtual rtl_data_if #(512))::set(this, "mon_512", "vif", if_512);
        endfunction

        function void connect_phase(uvm_phase phase);
            super.connect_phase(phase);

            // Register RTL (one line each)
            reg64_t::register_rtl("pcie_64", mon_64.ap);
            reg128_t::register_rtl("dma_128", mon_128.ap);
            reg256_t::register_rtl("noc_256", mon_256.ap);
            reg512_t::register_rtl("hbm_512", mon_512.ap);

            // Connect all
            reg64_t::connect_all();
            reg128_t::connect_all();
            reg256_t::connect_all();
            reg512_t::connect_all();
        endfunction

        task run_phase(uvm_phase phase);
            phase.raise_objection(this);

            // Send base addresses to SC
            reg256_t::write_reg(64'h0000, 64'h2000);  // 64b base
            reg256_t::write_reg(64'h0008, 64'h3000);  // 128b base
            reg256_t::write_reg(64'h0010, 64'h4000);  // 256b base
            reg256_t::write_reg(64'h0018, 64'h5000);  // 512b base

            `uvm_info("TEST", "Multi-channel comparison running...", UVM_LOW)
            #300000;

            reg64_t::report();
            reg128_t::report();
            reg256_t::report();
            reg512_t::report();

            phase.drop_objection(this);
        endtask
    endclass

    initial begin
        run_test("multi_test");
    end

endmodule
