//==============================================================================
// cfg_ctrl — Configuration Control & Distribution
// Core FSM: IDLE→CFG_CHK→CFG_PARSE→RUN→DONE/ERROR
// Distributes control signals to RD_IO, WR_IO, CIMC_IO, POST_IO
//==============================================================================
module cfg_ctrl (
    input  wire         clk_i,
    input  wire         rst_n,
    input  wire         start_i,
    input  wire         chk_pass_i,
    input  wire [31:0]  chk_errors_i,

    //── Config inputs (latched on start) ─────────────────────────
    input  wire [31:0]  base_out_i, base_in_i, base_orig_i, base_wt_i, base_mx_i,
    input  wire [13:0]  dim0_out_i, dim0_in_i,   // 64B transfer count
    input  wire [12:0]  dim1_out_i, dim1_in_i,    // 64B transfer count
    input  wire [12:0]  stride_out_i, stride_in_i,
    input  wire [3:0]   precision_i,
    input  wire [1:0]   task_i,
    input  wire [3:0]   active_cime_i,

    //── Shape info ───────────────────────────────────────────────
    input  wire [5:0]   elem_width_i, elems_per_xfer_i, elems_per_cime_i, rem_elems_i,
    input  wire [15:0]  total_elems_i,
    input  wire [3:0]   cime_mask_i,
    input  wire [2:0]   addr_pattern_i,

    //── Control outputs to sub-modules ───────────────────────────
    output reg           rd0_start_o, rd1_start_o,
    output reg  [31:0]   rd0_base_o,  rd1_base_o,
    output reg  [13:0]   rd0_dim0_o,  rd1_dim0_o,   // in 64B transfer count
    output reg  [12:0]   rd1_dim1_o,  rd0_dim1_o,
    output reg  [12:0]   rd0_stride_o,rd1_stride_o,
    output reg  [3:0]    precision_o,
    output reg           mx_en_o, psum_en_o,
    output reg  [3:0]    active_cime_o,
    output reg  [3:0]    cime_mask_o,
    output reg  [2:0]    addr_pattern_o,
    output reg  [5:0]    elems_per_xfer_o, elems_per_cime_o, rem_elems_o,
    output reg  [15:0]   total_elems_o,

    //── State ────────────────────────────────────────────────────
    output reg  [2:0]    state_o,
    output reg           done_o, error_o
);

    localparam IDLE=0, CFG_CHK=1, CFG_PARSE=2, RUN=3, DONE=4, ERROR=5;
    reg [2:0] state, state_next;

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) state <= IDLE; else state <= state_next;
    end

    always @(*) begin
        state_next = state;
        case (state)
            IDLE:   if (start_i) state_next = CFG_CHK;
            CFG_CHK: state_next = chk_pass_i ? CFG_PARSE : ERROR;
            CFG_PARSE: state_next = RUN;
            RUN:    if (done_o) state_next = DONE;
            DONE:   state_next = IDLE;
            ERROR:  if (!start_i) state_next = IDLE;
            default: state_next = IDLE;
        endcase
    end

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            rd0_start_o<=0; rd1_start_o<=0;
            rd0_base_o <=0; rd1_base_o <=0;
            rd0_dim0_o <=0; rd1_dim0_o <=0;
            rd0_dim1_o <=0; rd1_dim1_o <=0;
            rd0_stride_o<=0;rd1_stride_o<=0;
            precision_o<=0; mx_en_o<=0; psum_en_o<=0;
            active_cime_o<=0; cime_mask_o<=0; addr_pattern_o<=0;
            elems_per_xfer_o<=0; elems_per_cime_o<=0; rem_elems_o<=0; total_elems_o<=0;
            done_o<=0; error_o<=0;
        end else begin
            case (state)
                CFG_PARSE: begin
                    rd0_base_o <= base_in_i;
                    rd1_base_o <= base_orig_i;
                    rd0_dim0_o <= dim0_in_i;   rd1_dim0_o <= dim0_out_i;
                    rd0_dim1_o <= dim1_in_i;   rd1_dim1_o <= dim1_out_i;
                    rd0_stride_o<=stride_in_i; rd1_stride_o<=stride_out_i;
                    precision_o<=precision_i;
                    mx_en_o    <=1'b0;  // from combined config
                    psum_en_o  <=1'b0;
                    active_cime_o <=active_cime_i;
                    cime_mask_o   <=cime_mask_i;
                    addr_pattern_o<=addr_pattern_i;
                    elems_per_xfer_o<=elems_per_xfer_i;
                    elems_per_cime_o<=elems_per_cime_i;
                    rem_elems_o <=rem_elems_i;
                    total_elems_o<=total_elems_i;
                end
                RUN: begin
                    rd0_start_o<=1'b1;
                    rd1_start_o<=psum_en_o;
                end
                DONE: begin rd0_start_o<=0; rd1_start_o<=0; done_o<=1; end
                ERROR: error_o<=1;
                default: begin done_o<=0; error_o<=0; end
            endcase
        end
    end

    assign state_o = state;

endmodule
