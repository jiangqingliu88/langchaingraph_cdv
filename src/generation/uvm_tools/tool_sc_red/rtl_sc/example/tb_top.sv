// Testbench demonstrating one-line registration for RTL-SC comparison.
// Supports 64b, 128b, 256b, 512b — this example uses 256b.

`timescale 1ns/1ps

module tb_top;

    import uvm_pkg::*;
    import uvmc_pkg::*;
    import rtl_sc_pkg::*;
    `include "uvm_macros.svh"

    // -------------------------------------------------------
    // Clock and reset
    // -------------------------------------------------------
    logic clk;
    logic rst_n;

    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end

    initial begin
        rst_n = 0;
        #50;
        rst_n = 1;
    end

    // -------------------------------------------------------
    // RTL interface
    // -------------------------------------------------------
    rtl_data_if #(256) dut_if(clk, rst_n);

    // -------------------------------------------------------
    // Simulated DUT output (generates 20 transactions)
    // -------------------------------------------------------
    initial begin
        dut_if.valid    = 0;
        dut_if.addr     = 0;
        dut_if.data     = 0;
        dut_if.byte_len = 0;

        wait(rst_n);
        repeat(20) @(posedge clk);

        for (int i = 0; i < 20; i++) begin
            @(posedge clk);
            dut_if.valid    = 1;
            dut_if.addr     = 64'h1000 + i * 32;
            dut_if.byte_len = 32;
            for (int b = 0; b < 32; b++)
                dut_if.data[b*8 +: 8] = (i * 32 + b) & 8'hFF;
            @(posedge clk);
            dut_if.valid = 0;
        end

        repeat(100) @(posedge clk);
    end

    // -------------------------------------------------------
    // UVM Test
    // -------------------------------------------------------
    class basic_test extends uvm_test;
        `uvm_component_utils(basic_test)

        typedef rtl_sc_registry #(256) reg_t;
        rtl_monitor_ex #(256) mon;

        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction

        function void build_phase(uvm_phase phase);
            rtl_sc_cfg cfg;
            super.build_phase(phase);

            cfg = new("cfg");
            cfg.timeout_cycles = 5000;
            cfg.max_errors     = 10;

            // Initialize platform
            reg_t::init(this, cfg);

            // One-line registrations
            reg_t::register_sc("data0");
            reg_t::register_cfg("cfg0");

            // Create monitor
            mon = rtl_monitor_ex #(256)::type_id::create("mon", this);
            mon.channel_id = "data0";

            uvm_config_db #(virtual rtl_data_if #(256))::set(
                this, "mon", "vif", dut_if);
        endfunction

        function void connect_phase(uvm_phase phase);
            super.connect_phase(phase);

            // One-line RTL registration
            reg_t::register_rtl("data0", mon.ap);

            // Connect everything
            reg_t::connect_all();
        endfunction

        task run_phase(uvm_phase phase);
            typedef struct packed {
                bit [63:0] base_addr;
                bit [31:0] beat_size;
                bit [31:0] num_beats;
            } simple_cfg_t;

            simple_cfg_t s_cfg;
            byte unsigned cfg_bytes[];

            phase.raise_objection(this);

            // Pack config struct and send
            s_cfg.base_addr = 64'h1000;
            s_cfg.beat_size = 32;
            s_cfg.num_beats = 20;
            cfg_bytes = new[$bits(simple_cfg_t)/8];
            { >> {cfg_bytes}} = s_cfg;
            reg_t::send_cfg("cfg0", cfg_bytes);

            `uvm_info("TEST", "Struct config sent, waiting for comparison...", UVM_LOW)
            #200000;

            reg_t::report();
            phase.drop_objection(this);
        endtask
    endclass

    // -------------------------------------------------------
    initial begin
        run_test("basic_test");
    end

endmodule
