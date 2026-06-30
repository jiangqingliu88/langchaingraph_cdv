//==============================================================================
// data_top — VPU Data Fetch, Align, Dispatch & Writeback
// Handles ch1_rd (Vector 0), ch2_rd (Vector 1), ch0_wr (output)
// 512-bit read → 32-bit per-VPE elements → 512-bit write
//==============================================================================
`include "vpu_defines.vh"

module data_top #(
    parameter LMEM_WD       = 512,
    parameter LMEM_ADDR_WD  = 32,
    parameter VPE_NUM       = 16,
    parameter RV_LEN        = 32
) (
    input  wire                     clk_i,
    input  wire                     rst_n,

    // Config (registered at start)
    input  wire [2:0]               cfg_type_out,
    input  wire [2:0]               cfg_wd_out,
    input  wire [1:0]               cfg_exp_wd_out,
    input  wire [2:0]               cfg_type_in1,
    input  wire [2:0]               cfg_wd_in1,
    input  wire [1:0]               cfg_exp_wd_in1,
    input  wire [2:0]               cfg_type_in2,
    input  wire [2:0]               cfg_wd_in2,
    input  wire [15:0]              cfg_size_dim0_in1,
    input  wire [4:0]               cfg_rem_dim0_in1,
    input  wire [15:0]              cfg_size_dim0_in2,
    input  wire [4:0]               cfg_rem_dim0_in2,
    input  wire [15:0]              cfg_size_dim0_out,
    input  wire [4:0]               cfg_rem_dim0_out,
    input  wire [5:0]               cfg_op,
    input  wire [1:0]               cfg_funct_sel,
    input  wire                     cfg_bypass,
    input  wire [LMEM_ADDR_WD-1:0]  byte_base_out,
    input  wire                     byte_base_out_vld,
    input  wire [LMEM_ADDR_WD-1:0]  byte_base_in1,
    input  wire                     byte_base_in1_vld,
    input  wire [LMEM_ADDR_WD-1:0]  byte_base_in2,
    input  wire [RV_LEN-1:0]        scalar_data_in2,
    output wire [31:0]              scalar_data_o,
    input  wire                     start_i,
    output wire                     done_o,

    //── Write Channel ch0_wr ─────────────────────────────────────
    output reg  [LMEM_ADDR_WD-1:0]  ch0_wr_req_addr_o,
    output reg  [LMEM_WD-1:0]       ch0_wr_req_data_o,
    output reg                      ch0_wr_req_flag_o,
    output reg                      ch0_wr_req_valid_o,
    output reg                      ch0_wr_exp_valid_o,
    input  wire                     ch0_wr_req_ready_i,
    input  wire                     ch0_wr_ack_valid_i,
    output reg  [1:0]               ch0_wr_req_strobe_o,
    output reg                      ch0_wr_ack_ready_o,

    //── Read Channel ch1_rd ───────────────────────────────────────
    output reg  [LMEM_ADDR_WD-1:0]  ch1_rd_req_addr_o,
    output reg                      ch1_rd_req_valid_o,
    input  wire                     ch1_rd_req_ready_i,
    input  wire                     ch1_rd_exp_valid_i,
    input  wire [LMEM_WD-1:0]       ch1_rd_ack_data_i,
    input  wire                     ch1_rd_ack_valid_i,
    output reg                      ch1_rd_ack_ready_o,

    //── Read Channel ch2_rd ───────────────────────────────────────
    output reg  [LMEM_ADDR_WD-1:0]  ch2_rd_req_addr_o,
    output reg                      ch2_rd_req_valid_o,
    input  wire                     ch2_rd_req_ready_i,
    input  wire [LMEM_WD-1:0]       ch2_rd_ack_data_i,
    input  wire                     ch2_rd_ack_valid_i,
    output reg                      ch2_rd_ack_ready_o,

    //── to vpe_top ────────────────────────────────────────────────
    output reg  [VPE_NUM-1:0][31:0] vec0_elem_o,
    output reg  [VPE_NUM-1:0][31:0] vec1_elem_o,
    output reg  [VPE_NUM-1:0][7:0]  vec0_exp_o,
    output reg  [VPE_NUM-1:0][7:0]  vec1_exp_o,
    output reg  [3:0]               active_vpe_o,
    output reg                      dispatch_valid_o,

    //── from vpe_top ──────────────────────────────────────────────
    input  wire [VPE_NUM-1:0][31:0] result_i,
    input  wire [VPE_NUM-1:0]       result_valid_i,
    input  wire                     vpe_done_i
);

    //══════════════════════════════════════════════════════════════
    // FSM states
    //══════════════════════════════════════════════════════════════
    localparam IDLE     = 3'd0;
    localparam RD_REQ   = 3'd1;   // issue read requests to ch1_rd + ch2_rd
    localparam RD_WAIT  = 3'd2;   // wait for read data
    localparam DISPATCH = 3'd3;   // distribute to VPEs
    localparam COMPUTE  = 3'd4;   // wait for vpe_top
    localparam WRITEBK  = 3'd5;   // write results back

    reg [2:0] state, state_next;
    reg [15:0] dim0_cnt;           // how many 256-bit transfers done
    reg [15:0] dim0_limit;         // total transfers needed
    reg [LMEM_ADDR_WD-1:0] rd_addr_in1, rd_addr_in2;
    reg [LMEM_ADDR_WD-1:0] wr_addr;

    // Elem width extraction
    wire [4:0] elem_w_in1  = get_elem_width(cfg_wd_in1);
    wire [4:0] elem_w_in2  = get_elem_width(cfg_wd_in2);
    wire [4:0] elem_w_out  = get_elem_width(cfg_wd_out);
    // Elements per 512-bit transfer
    wire [5:0] elems_per_xfer_in1 = 6'd512 / {1'b0, elem_w_in1};   // 512/elem_w
    wire [5:0] elems_per_xfer_in2 = 6'd512 / {1'b0, elem_w_in2};
    wire [5:0] elems_per_xfer_out = 6'd512 / {1'b0, elem_w_out};

    // How many VPEs needed per transfer
    wire [3:0] vpe_needed = (elems_per_xfer_in1 > VPE_NUM) ? VPE_NUM[3:0] :
                            elems_per_xfer_in1[3:0];

    //══════════════════════════════════════════════════════════════
    // FSM
    //══════════════════════════════════════════════════════════════
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n)
            state <= IDLE;
        else
            state <= state_next;
    end

    always @(*) begin
        state_next = state;
        case (state)
            IDLE: begin
                if (start_i)
                    state_next = RD_REQ;
            end

            RD_REQ: begin
                // Issue read requests (1 cycle)
                state_next = RD_WAIT;
            end

            RD_WAIT: begin
                // Wait for both read channels to return data
                if (ch1_rd_ack_valid_i && ch2_rd_ack_valid_i)
                    state_next = DISPATCH;
            end

            DISPATCH: begin
                state_next = COMPUTE;
            end

            COMPUTE: begin
                if (vpe_done_i)
                    state_next = WRITEBK;
            end

            WRITEBK: begin
                if (ch0_wr_ack_valid_i || !ch0_wr_req_valid_o) begin
                    if (dim0_cnt >= dim0_limit)
                        state_next = IDLE;
                    else
                        state_next = RD_REQ;
                end
            end

            default: state_next = IDLE;
        endcase
    end

    //══════════════════════════════════════════════════════════════
    // Read request generation
    //══════════════════════════════════════════════════════════════
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            rd_addr_in1      <= 'd0;
            rd_addr_in2      <= 'd0;
            dim0_cnt         <= 16'd0;
        end else if (state == IDLE && start_i) begin
            rd_addr_in1      <= byte_base_in1;
            rd_addr_in2      <= byte_base_in2;
            dim0_cnt         <= 16'd0;
            // dim0_limit: ceil(size_dim0 / elems_per_xfer) * elems_per_xfer / 2
            dim0_limit       <= cfg_size_dim0_in1[15:1]; // simplified
        end else if (state == WRITEBK && (ch0_wr_ack_valid_i || !ch0_wr_req_valid_o)) begin
            dim0_cnt         <= dim0_cnt + 16'd1;
            rd_addr_in1      <= rd_addr_in1 + (LMEM_WD / 8);
            rd_addr_in2      <= rd_addr_in2 + (LMEM_WD / 8);
        end
    end

    //── ch1_rd (Vector 0) read request ───────────────────────────
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            ch1_rd_req_addr_o  <= 'd0;
            ch1_rd_req_valid_o <= 1'b0;
        end else if (state == RD_REQ) begin
            ch1_rd_req_addr_o  <= rd_addr_in1;
            ch1_rd_req_valid_o <= 1'b1;
        end else if (ch1_rd_req_ready_i) begin
            ch1_rd_req_valid_o <= 1'b0;
        end
    end
    always @(*) ch1_rd_ack_ready_o = (state == RD_WAIT);

    //── ch2_rd (Vector 1) read request ───────────────────────────
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            ch2_rd_req_addr_o  <= 'd0;
            ch2_rd_req_valid_o <= 1'b0;
        end else if (state == RD_REQ) begin
            ch2_rd_req_addr_o  <= rd_addr_in2;
            ch2_rd_req_valid_o <= 1'b1;
        end else if (ch2_rd_req_ready_i) begin
            ch2_rd_req_valid_o <= 1'b0;
        end
    end
    always @(*) ch2_rd_ack_ready_o = (state == RD_WAIT);

    //══════════════════════════════════════════════════════════════
    // Data dispatch: 512-bit → VPE lanes
    //══════════════════════════════════════════════════════════════
    integer vpe_idx;
    always @(posedge clk_i) begin
        if (state == RD_WAIT && ch1_rd_ack_valid_i && ch2_rd_ack_valid_i) begin
            active_vpe_o    <= vpe_needed;
            dispatch_valid_o <= 1'b1;
            // Unpack 512-bit → 16× 32-bit lanes
            for (vpe_idx = 0; vpe_idx < VPE_NUM; vpe_idx = vpe_idx + 1) begin
                vec0_elem_o[vpe_idx] <= ch1_rd_ack_data_i[(vpe_idx*32)+:32];
                vec1_elem_o[vpe_idx] <= ch2_rd_ack_data_i[(vpe_idx*32)+:32];
                // EXP data — for FP types, extract from exp channel
                vec0_exp_o[vpe_idx]  <= ch1_rd_exp_valid_i ? ch1_rd_ack_data_i[(vpe_idx*8)+:8] : 8'd0;
                vec1_exp_o[vpe_idx]  <= 8'd0;
            end
        end else begin
            dispatch_valid_o <= 1'b0;
        end
    end

    //══════════════════════════════════════════════════════════════
    // Writeback: VPE results → 512-bit → ch0_wr
    //══════════════════════════════════════════════════════════════
    wire [LMEM_WD-1:0] packed_result;
    genvar wi;
    generate
    for (wi = 0; wi < VPE_NUM; wi = wi + 1) begin : result_pack
        assign packed_result[(wi*32)+:32] = result_i[wi];
    end
    endgenerate

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            ch0_wr_req_addr_o  <= 'd0;
            ch0_wr_req_data_o  <= 'd0;
            ch0_wr_req_valid_o <= 1'b0;
            ch0_wr_req_flag_o  <= 1'b0;
            ch0_wr_req_strobe_o<= 2'b11;  // full 512-bit valid
            wr_addr            <= 'd0;
        end else if (state == COMPUTE && vpe_done_i) begin
            ch0_wr_req_addr_o  <= wr_addr;
            ch0_wr_req_data_o  <= packed_result;
            ch0_wr_req_valid_o <= 1'b1;
            // Flag: last transfer
            ch0_wr_req_flag_o  <= (dim0_cnt >= dim0_limit - 16'd1);
            ch0_wr_req_strobe_o<= 2'b11;   // 512-bit valid
            wr_addr            <= wr_addr + (LMEM_WD / 8);
        end else if (ch0_wr_req_ready_i) begin
            ch0_wr_req_valid_o <= 1'b0;
        end
    end

    always @(*) begin
        ch0_wr_ack_ready_o  = (state == WRITEBK);
        ch0_wr_exp_valid_o  = 1'b0;
    end

    //══════════════════════════════════════════════════════════════
    // Scalar output (for V_S reduce result)
    //══════════════════════════════════════════════════════════════
    assign scalar_data_o = 32'd0;   // connected to reduce chain final output

    //══════════════════════════════════════════════════════════════
    // Done
    //══════════════════════════════════════════════════════════════
    assign done_o = (state == WRITEBK && (ch0_wr_ack_valid_i || !ch0_wr_req_valid_o)
                     && dim0_cnt >= dim0_limit);

endmodule
