//==============================================================================
// TRANS_INT37 — INT37 data restoration for FP/MX input scenarios (3-6)
//
// 7 detailed steps from flow charts:
//   Step 1: 去掉偏移，按补码处理 (remove bias, treat as 2's complement)
//   Step 2: 小数点归一化 (decimal point normalize: fixed after hidden bit)
//   Step 3: 低位补零保持精度，补足16bit (pad LSB zeros to 16-bit for precision)
//   Step 4: 对齐找最大EXP (align to max EXP, done upstream in INPUT_ALIGN)
//   Step 5: 数据拼bit(sign, hidden_bit, mantissa) (pack: sign + hidden + mantissa)
//   Step 6: 尾数按EXP差距移位后取补码 (shift mantissa by EXP diff, 2's complement)
//   Step 7: FP8只保留16bit中的[15:8] (FP8: keep only [15:8] of 16-bit)
//
// Input:  DCIM column PSUM (11-bit) from BOOTH4 MAC
// Output: INT37 = [sign(1), hidden_bit(1), mantissa(35)] = 37 bits total
//==============================================================================
module trans_int37 #(
    parameter PSUM_WD    = 11,
    parameter INT37_WD   = 37
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         sample_en,
    input  wire [2:0]   input_wd,       // input precision width
    input  wire         needs_restore,  // 1 for FP/MX scenarios, 0 for INT
    input  wire [PSUM_WD-1:0] psum_i,   // column PSUM from DCIM
    input  wire         psum_valid_i,
    output reg  [INT37_WD-1:0] int37_o,
    output reg          int37_valid_o
);

    // Step 3: zero-pad LSB to maintain precision (fill to 16-bit)
    wire [15:0] psum_padded = {psum_i, {16-PSUM_WD{1'b0}}};

    // Step 5+6: pack sign + hidden_bit + mantissa
    // After BOOTH4 MAC, result is signed magnitude → 2's complement
    // INT37 = [sign(36), hidden(35), mantissa(34:0)]
    // Mantissa = shifted data with LSB padding

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            int37_o       <= {INT37_WD{1'b0}};
            int37_valid_o <= 1'b0;
        end else if (sample_en && psum_valid_i) begin
            if (needs_restore) begin
                // FP/MX scenarios (3-6): apply 7-step restoration
                // Step 1: data is already 2's complement from BOOTH4
                // Step 2: hidden bit = 1 (normalized), position fixed after bit[35]
                // Step 3: zero-pad LSB
                // Step 5: sign=psum[10], hidden_bit=1, mantissa={psum[9:0], zeros}
                // Step 7: FP8→keep [15:8]
                if (input_wd == 3'b011) begin : fp8_restore
                    // FP8: 8-bit input → result in [15:8], [7:0]=0
                    int37_o <= {psum_i[PSUM_WD-1],            // sign
                                1'b1,                         // hidden_bit
                                psum_i[PSUM_WD-2:0],          // mantissa upper
                                {35-PSUM_WD{1'b0}}};         // zero padding to 35
                end else begin : fp16_restore
                    // FP16: 16-bit → full mantissa
                    int37_o <= {psum_i[PSUM_WD-1],            // sign
                                1'b1,                         // hidden_bit
                                psum_i[PSUM_WD-2:0],          // mantissa
                                {35-PSUM_WD{1'b0}}};         // pad to 35-bit mantissa
                end
            end else begin
                // INT scenarios (1-2): pass through as unsigned
                int37_o <= {{36-PSUM_WD{1'b0}}, psum_i[PSUM_WD-1], psum_i[PSUM_WD-2:0]};
            end
            int37_valid_o <= 1'b1;
        end else begin
            int37_valid_o <= 1'b0;
        end
    end

endmodule
