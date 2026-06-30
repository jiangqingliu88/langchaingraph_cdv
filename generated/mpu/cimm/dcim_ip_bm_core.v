//==============================================================================
// DCIM_IP_BM_CORE — DCIM IP Core (Bit-Match, V3)
// SRAM: 16 pages × 33 rows × 256 bits
// 32 channels BOOTH4 MAC + 64 channels MASK/PSUM
//==============================================================================
module dcim_ip_bm_core #(
    parameter TOTAL_PAGES   = 16,
    parameter TOTAL_ROWS    = 33,       // 32 mantissa + 1 exp
    parameter ROW_WD        = 256,
    parameter NUM_CH        = 32,       // BOOTH4 channels
    parameter PSUM_CH       = 64        // PSUM channels (2×BOOTH4)
) (
    input  wire                STORAGE_CLK,
    input  wire                MIX_CLK,
    input  wire                WEN,
    input  wire                REN_GLOBAL,
    input  wire                REN_LOCAL,
    input  wire [9:0]          ADDR,
    input  wire [8:0]          I_EXP,
    output wire [287:0]        O_EXP,          // 9*32 = 288-bit
    input  wire [63:0]         MASK,
    input  wire [255:0]        D,
    output wire [255:0]        Q,
    input  wire [3:0]          SIGN,
    input  wire [31:0]         NEG,
    input  wire [31:0]         TWO,
    input  wire [31:0]         ZERO,
    //── Buffered outputs (drive to next stage) ───────────────────
    output wire [8:0]          I_EXPDRV,
    output wire [3:0]          SIGNDRV,
    output wire [31:0]         NEGDRV,
    output wire [31:0]         TWODRV,
    output wire [31:0]         ZERODRV,
    //── PSUM output (registered) ─────────────────────────────────
    output reg  [703:0]        DATA_PSUM       // 11*64 = 704-bit
);

    //══════════════════════════════════════════════════════════════
    // SRAM Array: 16 pages × 33 rows × 256 bits
    // row[0:31] = weight mantissa (per-page)
    // row[32]   = shared exponent (weight alignment max EXP)
    //══════════════════════════════════════════════════════════════
    reg [ROW_WD-1:0] sram [0:TOTAL_PAGES-1][0:TOTAL_ROWS-1];

    //── Storage write port ───────────────────────────────────────
    wire [3:0] wr_page = ADDR[9:6];
    wire [5:0] wr_row  = ADDR[5:0];

    always @(posedge STORAGE_CLK) begin
        if (WEN && wr_row < TOTAL_ROWS && wr_page < TOTAL_PAGES)
            sram[wr_page][wr_row] <= D;
    end

    //── Storage read port ────────────────────────────────────────
    wire [3:0] rd_page = ADDR[9:6];
    wire [5:0] rd_row  = ADDR[5:0];
    reg [ROW_WD-1:0] rd_data;

    always @(posedge STORAGE_CLK) begin
        if (REN_GLOBAL && rd_row < TOTAL_ROWS && rd_page < TOTAL_PAGES)
            rd_data <= sram[rd_page][rd_row];
    end
    assign Q = rd_data;

    //── Compute read port (REN_LOCAL sets active page) ───────────
    reg [3:0] active_page;
    wire [5:0] comp_row;

    always @(posedge MIX_CLK or negedge REN_LOCAL) begin
        if (!REN_LOCAL)
            active_page <= 4'd0;
        else
            active_page <= ADDR[9:6];  // Latch page on REN_LOCAL
    end

    // Compute row counter — incremented per BOOTH4 iteration
    reg [5:0] comp_row_reg;
    always @(posedge MIX_CLK or negedge REN_LOCAL) begin
        if (!REN_LOCAL)
            comp_row_reg <= 6'd0;
        else if (|NEG || |TWO || !|ZERO)  // Any active compute
            comp_row_reg <= comp_row_reg + 6'd1;
    end
    assign comp_row = comp_row_reg;

    // Read weight from SRAM at compute port
    wire [ROW_WD-1:0] weight_row;
    assign weight_row = (comp_row < TOTAL_ROWS && active_page < TOTAL_PAGES) ?
                         sram[active_page][comp_row] : {ROW_WD{1'b0}};

    // Read EXP row for active page
    wire [ROW_WD-1:0] exp_row;
    assign exp_row = sram[active_page][TOTAL_ROWS-1];  // row 32

    //══════════════════════════════════════════════════════════════
    // Weight extraction: 256-bit → 32 channels × 8-bit
    //══════════════════════════════════════════════════════════════
    wire [NUM_CH-1:0][7:0] ch_weight;
    genvar ch;
    generate
    for (ch = 0; ch < NUM_CH; ch = ch + 1) begin : w_extract
        assign ch_weight[ch] = weight_row[ch*8 +: 8];
    end
    endgenerate

    //══════════════════════════════════════════════════════════════
    // BOOTH4 MAC: 32 channels × weight × encoded_activation
    // PSUM = ZERO ? 0 : (TWO ? 2*W : W) * (NEG ? -1 : 1)
    // Result: 6-bit signed per channel → 11-bit per column pair
    //══════════════════════════════════════════════════════════════
    wire [PSUM_CH-1:0][10:0] col_psum;

    genvar ci;
    generate
    for (ci = 0; ci < PSUM_CH; ci = ci + 1) begin : mac_col
        // Each PSUM column pairs two BOOTH4 channels (odd/even)
        wire [4:0] ch_lo = ci * 2;
        wire [4:0] ch_hi = ci * 2 + 1;

        // Channel LO
        wire [6:0] lo_mul = ZERO[ch_lo] ? 7'sd0 :
                            TWO[ch_lo]  ? (NEG[ch_lo] ? -{1'b0, ch_weight[ch_lo][5:0], 1'b0} :
                                                         {1'b0, ch_weight[ch_lo][5:0], 1'b0}) :
                                          (NEG[ch_lo] ? -{1'b0, ch_weight[ch_lo][5:0]} :
                                                         {1'b0, ch_weight[ch_lo][5:0]});
        // Channel HI
        wire [6:0] hi_mul = ZERO[ch_hi] ? 7'sd0 :
                            TWO[ch_hi]  ? (NEG[ch_hi] ? -{1'b0, ch_weight[ch_hi][5:0], 1'b0} :
                                                         {1'b0, ch_weight[ch_hi][5:0], 1'b0}) :
                                          (NEG[ch_hi] ? -{1'b0, ch_weight[ch_hi][5:0]} :
                                                         {1'b0, ch_weight[ch_hi][5:0]});

        assign col_psum[ci] = {4'd0, lo_mul[5:0]} + {4'd0, hi_mul[5:0]};
    end
    endgenerate

    //══════════════════════════════════════════════════════════════
    // PSUM output register: 64 columns × 11-bit = 704-bit
    //══════════════════════════════════════════════════════════════
    integer pcol;
    always @(posedge MIX_CLK) begin
        for (pcol = 0; pcol < PSUM_CH; pcol = pcol + 1)
            DATA_PSUM[pcol*11 +: 11] <= col_psum[pcol];
    end

    //══════════════════════════════════════════════════════════════
    // Buffered pass-through outputs (drive to next pipeline stage)
    //══════════════════════════════════════════════════════════════
    assign I_EXPDRV = I_EXP;
    assign SIGNDRV  = SIGN;
    assign NEGDRV   = NEG;
    assign TWODRV   = TWO;
    assign ZERODRV  = ZERO;

    //── O_EXP: per-channel exponent output, 32 channels × 9-bit ──
    genvar ex;
    generate
    for (ex = 0; ex < NUM_CH; ex = ex + 1) begin : exp_out
        assign O_EXP[ex*9 +: 9] = I_EXP;
    end
    endgenerate

endmodule
