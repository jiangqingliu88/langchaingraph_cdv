module cmd_int_perf (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] creg_cmd_excep_en,
    output reg  [31:0] cmd_creg_int,
    input  wire [31:0] creg_cmd_mpu_inst0_masked_int,
    input  wire [31:0] creg_cmd_mpu_inst1_masked_int,
    input  wire [31:0] creg_cmd_vpu_inst0_masked_int,
    input  wire [31:0] creg_cmd_vpu_inst1_masked_int,
    input  wire [31:0] creg_cmd_glsu_inst0_masked_int,
    input  wire [31:0] creg_cmd_glsu_inst1_masked_int,
    input  wire [31:0] creg_cmd_llsu_inst0_masked_int,
    input  wire [31:0] creg_cmd_llsu_inst1_masked_int,
    input  wire [31:0] creg_cmd_niu_inst0_masked_int,
    input  wire [31:0] creg_cmd_niu_inst1_masked_int,
    output wire [31:0] cmd_creg_exce0,
    output wire [31:0] cmd_creg_exce1,
    output wire [31:0] cmd_creg_exce2,
    output wire [31:0] cmd_creg_mpu_exce0,
    output wire [31:0] cmd_creg_vpu_exce0,
    output wire [31:0] cmd_creg_glsu_exce0,
    output wire [31:0] cmd_creg_llsu_exce0,
    output wire [31:0] cmd_creg_niu_exce0,
    input  wire        creg_cmd_perf_en,
    input  wire        creg_cmd_perf_start,
    input  wire        creg_cmd_perf_pause,
    input  wire        creg_cmd_perf_conti,
    input  wire        creg_cmd_perf_end,
    output reg  [95:0] cmd_creg_perf_cnt
);

    wire [31:0] all_masked_int;
    wire [31:0] int_merged;
    wire [31:0] inst0_int;
    wire [31:0] inst1_int;

    assign all_masked_int =
        creg_cmd_mpu_inst0_masked_int |
        creg_cmd_mpu_inst1_masked_int |
        creg_cmd_vpu_inst0_masked_int |
        creg_cmd_vpu_inst1_masked_int |
        creg_cmd_glsu_inst0_masked_int |
        creg_cmd_glsu_inst1_masked_int |
        creg_cmd_llsu_inst0_masked_int |
        creg_cmd_llsu_inst1_masked_int |
        creg_cmd_niu_inst0_masked_int |
        creg_cmd_niu_inst1_masked_int;

    assign int_merged = all_masked_int & creg_cmd_excep_en;

    assign inst0_int =
        creg_cmd_mpu_inst0_masked_int |
        creg_cmd_vpu_inst0_masked_int |
        creg_cmd_glsu_inst0_masked_int |
        creg_cmd_llsu_inst0_masked_int |
        creg_cmd_niu_inst0_masked_int;

    assign inst1_int =
        creg_cmd_mpu_inst1_masked_int |
        creg_cmd_vpu_inst1_masked_int |
        creg_cmd_glsu_inst1_masked_int |
        creg_cmd_llsu_inst1_masked_int |
        creg_cmd_niu_inst1_masked_int;

    assign cmd_creg_exce0 = inst0_int;
    assign cmd_creg_exce1 = inst1_int;
    assign cmd_creg_exce2 = all_masked_int;

    assign cmd_creg_mpu_exce0  = creg_cmd_mpu_inst0_masked_int;
    assign cmd_creg_vpu_exce0  = creg_cmd_vpu_inst0_masked_int;
    assign cmd_creg_glsu_exce0 = creg_cmd_glsu_inst0_masked_int;
    assign cmd_creg_llsu_exce0 = creg_cmd_llsu_inst0_masked_int;
    assign cmd_creg_niu_exce0  = creg_cmd_niu_inst0_masked_int;

    reg [31:0] int_merged_d;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            int_merged_d <= 32'd0;
            cmd_creg_int <= 32'd0;
        end else begin
            int_merged_d <= int_merged;
            cmd_creg_int <= int_merged & ~int_merged_d;
        end
    end

    function automatic [5:0] popcount32(input [31:0] v);
        integer i;
        begin
            popcount32 = 6'd0;
            for (i = 0; i < 32; i = i + 1) begin
                popcount32 = popcount32 + v[i];
            end
        end
    endfunction

    wire [5:0] perf_event_sum;
    assign perf_event_sum = popcount32(int_merged);

    reg perf_active_r;
    reg perf_started_r;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            perf_active_r  <= 1'b0;
            perf_started_r <= 1'b0;
            cmd_creg_perf_cnt <= 96'd0;
        end else if (!creg_cmd_perf_en) begin
            perf_active_r  <= 1'b0;
            perf_started_r <= 1'b0;
            cmd_creg_perf_cnt <= 96'd0;
        end else if (creg_cmd_perf_end) begin
            perf_active_r  <= 1'b0;
            perf_started_r <= 1'b0;
        end else if (creg_cmd_perf_pause) begin
            perf_active_r <= 1'b0;
        end else if (creg_cmd_perf_conti) begin
            perf_active_r  <= 1'b1;
            perf_started_r <= 1'b1;
        end else if (creg_cmd_perf_start && !perf_started_r) begin
            perf_active_r  <= 1'b1;
            perf_started_r <= 1'b1;
            cmd_creg_perf_cnt <= 96'd0;
        end else if (perf_active_r) begin
            cmd_creg_perf_cnt <= cmd_creg_perf_cnt + 96'd1 + perf_event_sum;
        end
    end

endmodule