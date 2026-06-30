//==============================================================================
// controller — CIMM pipeline FSM: Input→DCIM→Post→Format sample phases
//==============================================================================
module controller (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         cen,
    input  wire [3:0]   num_iterations,
    output reg          input_sample_o,
    output reg          dcim_sample_o,
    output reg          post_sample_o,
    output reg          format_sample_o,
    output reg  [2:0]   iter_o
);
    localparam IDLE=0, INPUT_S=1, DCIM_S=2, POST_S=3, FORMAT_S=4;
    reg [2:0] state, state_next;
    reg [3:0] iter_cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin state <= IDLE; iter_cnt <= 4'd0; end
        else begin state <= state_next; if (state == DCIM_S) iter_cnt <= iter_cnt + 4'd1; else if (state != DCIM_S) iter_cnt <= 4'd0; end
    end

    always @(*) begin
        state_next = state;
        case (state)
            IDLE:    if (cen) state_next = INPUT_S;
            INPUT_S: state_next = DCIM_S;
            DCIM_S:  if (iter_cnt >= num_iterations - 1) state_next = POST_S;
            POST_S:  state_next = FORMAT_S;
            FORMAT_S: state_next = IDLE;
            default: state_next = IDLE;
        endcase
    end

    always @(*) begin
        input_sample_o  = (state == INPUT_S);
        dcim_sample_o   = (state == DCIM_S);
        post_sample_o   = (state == POST_S);
        format_sample_o = (state == FORMAT_S);
        iter_o          = iter_cnt[2:0];
    end
endmodule
