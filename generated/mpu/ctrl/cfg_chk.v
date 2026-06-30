//==============================================================================
// cfg_chk — Complete Configuration Check (mpu_creg_int[31:0])
//
// SPAD: 0 ~ 32'h1_FFFF (128KB), 8 SPADs × 16KB each
//   SPAD0: 0x00000 ~ 0x03FFF   SPAD1: 0x04000 ~ 0x07FFF
//   SPAD2: 0x08000 ~ 0x0BFFF   SPAD3: 0x0C000 ~ 0x0FFFF
//   SPAD4: 0x10000 ~ 0x13FFF   SPAD5: 0x14000 ~ 0x17FFF
//   SPAD6: 0x18000 ~ 0x1BFFF   SPAD7: 0x1C000 ~ 0x1FFFF
//
// CIM: 128KB visible (0x0004_0000 ~ 0x0005_FFFF) + 4KB hidden
//   Each CIMM: 16p × 33r × 256b = 16,896 bytes → 8 CIMM = 135,168 bytes
//==============================================================================
module cfg_chk (
    input  wire [31:0]  cfg_base_out_i,     // base addr of Vector O (output)
    input  wire [31:0]  cfg_base_in_i,      // base addr of Vector 0 (activation)
    input  wire [31:0]  cfg_base_orig_i,    // base addr of PSUM (orig vector)
    input  wire [31:0]  cfg_base_wt_i,      // base addr of weight (CIM)
    input  wire [31:0]  cfg_base_mx_i,      // base addr of MX shared EXP
    input  wire         cfg_type_in_i,      // 0:INT 1:FP
    input  wire         cfg_type_wt_i,
    input  wire         cfg_type_out_i,
    input  wire         cfg_type_orig_i,
    input  wire [2:0]   cfg_width_in_i,     // 010:4 011:8 100:16 101:32
    input  wire [2:0]   cfg_width_wt_i,
    input  wire [2:0]   cfg_width_out_i,
    input  wire [2:0]   cfg_width_orig_i,
    input  wire         cfg_mx_in_i,
    input  wire         cfg_mx_wt_i,
    input  wire [13:0]  cfg_dim0_in_i,      // DIM0 in 32B units
    input  wire [13:0]  cfg_dim0_out_i,
    input  wire [13:0]  cfg_dim0_orig_i,
    input  wire [12:0]  cfg_dim1_in_i,
    input  wire [12:0]  cfg_dim1_out_i,
    input  wire [5:0]   cfg_rem_dim0_in_i,
    input  wire [5:0]   cfg_rem_dim0_out_i,
    input  wire [31:0]  cfg_mx_size_i,      // MX shared exp channels: 1/2/3
    input  wire [1:0]   cfg_task_i,
    input  wire [2:0]   cfg_pattern_i,
    input  wire [3:0]   active_cime_i,

    output wire         chk_pass_o,
    output reg  [31:0]  int_o               // mpu_creg_int[31:0]
);

    //══════════════════════════════════════════════════════════════
    // SPAD address space: 0 ~ 32'h1_FFFF, 8×16KB SPADs
    //══════════════════════════════════════════════════════════════
    localparam SPAD_BASE      = 32'h00000;
    localparam SPAD_END       = 32'h1FFFF;
    localparam SPAD_SIZE      = 32'd16384;     // 16KB per SPAD
    localparam SPAD_END_ADDR  = 32'h20000;     // exclusive bound

    //── Check: address within SPAD range ─────────────────────────
    function addr_in_spad(input [31:0] addr);
        addr_in_spad = (addr >= SPAD_BASE) && (addr < SPAD_END_ADDR);
    endfunction

    //── Check: 512-bit (64B) alignment ───────────────────────────
    function addr_512b_aligned(input [31:0] addr);
        addr_512b_aligned = (addr[5:0] == 6'd0);
    endfunction

    //── Check: CIM address range ─────────────────────────────────
    localparam CIM_BASE = 32'h0004_0000;
    localparam CIM_END  = 32'h0005_FFFF;
    function addr_in_cim(input [31:0] addr);
        addr_in_cim = (addr >= CIM_BASE) && (addr <= CIM_END);
    endfunction

    //── Width validity: 010=4, 011=8, 100=16, 101=32 ─────────────
    function width_valid(input [2:0] w);
        width_valid = (w == 3'b010) || (w == 3'b011) || (w == 3'b100) || (w == 3'b101);
    endfunction

    //── SPAD usage computation ──────────────────────────────────
    // Bytes per activation transfer = DIM0 × DIM1 × 32B (each DIM unit = 32B)
    wire [31:0] bytes_in    = cfg_dim0_in_i  * cfg_dim1_in_i  * 32'd32;
    wire [31:0] bytes_out   = cfg_dim0_out_i * cfg_dim1_out_i * 32'd32;
    wire [31:0] bytes_orig  = cfg_dim0_orig_i>0 ? (cfg_dim0_orig_i * cfg_dim1_in_i * 32'd32) : 32'd0;
    wire [31:0] bytes_mx    = cfg_mx_in_i ? (cfg_dim0_in_i * 32'd32 / cfg_mx_size_i) : 32'd0;

    wire [3:0] spads_in    = (bytes_in  + SPAD_SIZE-1) / SPAD_SIZE;
    wire [3:0] spads_out   = (bytes_out + SPAD_SIZE-1) / SPAD_SIZE;
    wire [3:0] spads_orig  = (bytes_orig>0) ? ((bytes_orig + SPAD_SIZE-1) / SPAD_SIZE) : 4'd0;
    wire [3:0] spads_mx    = cfg_mx_in_i ? ((bytes_mx + SPAD_SIZE-1) / SPAD_SIZE) : 4'd0;

    //── Address overlap detection (simplified: same SPAD region) ─
    wire [2:0] spad_in   = cfg_base_in_i[16:14];
    wire [2:0] spad_out  = cfg_base_out_i[16:14];
    wire [2:0] spad_orig = cfg_base_orig_i[16:14];
    wire [2:0] spad_mx   = cfg_base_mx_i[16:14];

    // Overlap: two regions overlap if they start in same SPAD or
    // their range spans into the same SPAD
    wire overlap_out_orig = (spad_out == spad_orig) && cfg_base_orig_i > 0;
    wire overlap_out_mx   = (spad_out == spad_mx)   && cfg_mx_in_i;
    wire overlap_orig_mx  = (spad_orig == spad_mx)  && cfg_mx_in_i && cfg_base_orig_i>0;
    wire overlap_in_orig  = (spad_in  == spad_orig) && cfg_base_orig_i > 0;
    wire overlap_in_mx    = (spad_in  == spad_mx)   && cfg_mx_in_i;
    wire overlap_in_out   = (spad_in  == spad_out);

    //══════════════════════════════════════════════════════════════
    // Check logic
    //══════════════════════════════════════════════════════════════
    reg [31:0] int_r;

    always @(*) begin
        int_r = 32'd0;

        //── [31] MX通道数配置异常 ─────────────────────────────────
        if (cfg_mx_in_i && (cfg_mx_size_i != 32'd1 && cfg_mx_size_i != 32'd2 && cfg_mx_size_i != 32'd3))
            int_r[31] = 1'b1;
        else if (cfg_mx_in_i) begin
            // MX shared exp channels vs matrix shape conflict
            // 32CH/64CH/128CH per MX EXP → must match active CIME × 32
            if ((cfg_mx_size_i == 32'd1 && active_cime_i > 4'd1) ||
                (cfg_mx_size_i == 32'd2 && active_cime_i > 4'd2))
                int_r[31] = 1'b1;
        end

        //── [30] PSUM数据格式异常 ────────────────────────────────
        if (cfg_base_orig_i > 0 && !width_valid(cfg_width_orig_i))
            int_r[30] = 1'b1;

        //── [29] 权重数据格式异常 ──────────────────────────────────
        if (!width_valid(cfg_width_wt_i))
            int_r[29] = 1'b1;

        //── [28] 输出数据格式异常 ──────────────────────────────────
        if (!width_valid(cfg_width_out_i))
            int_r[28] = 1'b1;

        //── [27] 输入数据格式异常 ──────────────────────────────────
        if (!width_valid(cfg_width_in_i))
            int_r[27] = 1'b1;

        //── [26] 输入/输出DIM1不匹配 ──────────────────────────────
        if (cfg_dim1_in_i != cfg_dim1_out_i)
            int_r[26] = 1'b1;

        //── [25] REM配置异常 ──────────────────────────────────────
        if (cfg_rem_dim0_in_i > 0 || cfg_rem_dim0_out_i > 0)
            int_r[25] = 1'b1;

        //── [24] SIZE配置异常 (输入/输出DIM0矩阵形状不匹配) ──────
        if (cfg_pattern_i == `PATTERN2) begin
            // PATTERN2: 2×2 grid, DIM must align to 2-CIME width
            if ((cfg_dim0_in_i % 2) != 0 || (cfg_dim0_out_i % 2) != 0)
                int_r[24] = 1'b1;
        end

        //── [23] 所有数据超过6个SPAD ──────────────────────────────
        if ((spads_in + spads_out + spads_orig + spads_mx) > 4'd6)
            int_r[23] = 1'b1;

        //── [22] MX EXP超过1个SPAD ────────────────────────────────
        if (cfg_mx_in_i && spads_mx > 4'd1)
            int_r[22] = 1'b1;

        //── [21] PSUM超过2个SPAD ──────────────────────────────────
        if (cfg_base_orig_i > 0 && spads_orig > 4'd2)
            int_r[21] = 1'b1;

        //── [20] 输出超过2个SPAD ──────────────────────────────────
        if (spads_out > 4'd2)
            int_r[20] = 1'b1;

        //── [19] 输入超过1个SPAD ──────────────────────────────────
        if (spads_in > 4'd1)
            int_r[19] = 1'b1;

        //── [18] MX EXP未512b对齐 ─────────────────────────────────
        if (cfg_mx_in_i && !addr_512b_aligned(cfg_base_mx_i))
            int_r[18] = 1'b1;

        //── [17] PSUM未512b对齐 ───────────────────────────────────
        if (cfg_base_orig_i > 0 && !addr_512b_aligned(cfg_base_orig_i))
            int_r[17] = 1'b1;

        //── [16] 输出未512b对齐 ───────────────────────────────────
        if (!addr_512b_aligned(cfg_base_out_i))
            int_r[16] = 1'b1;

        //── [15] 输入未512b对齐 ───────────────────────────────────
        if (!addr_512b_aligned(cfg_base_in_i))
            int_r[15] = 1'b1;

        //── [14] 输出/PSUM地址重叠 ───────────────────────────────
        if (overlap_out_orig)
            int_r[14] = 1'b1;

        //── [13] 输出/MX EXP地址重叠 ──────────────────────────────
        if (overlap_out_mx)
            int_r[13] = 1'b1;

        //── [12] PSUM/MX EXP地址重叠 ──────────────────────────────
        if (overlap_orig_mx)
            int_r[12] = 1'b1;

        //── [11] 输入/PSUM地址重叠 ────────────────────────────────
        if (overlap_in_orig)
            int_r[11] = 1'b1;

        //── [10] 输入/MX EXP地址重叠 ──────────────────────────────
        if (overlap_in_mx)
            int_r[10] = 1'b1;

        //── [9] 输入/输出地址重叠 ─────────────────────────────────
        if (overlap_in_out)
            int_r[9] = 1'b1;

        //── [8] MX EXP地址超界 ────────────────────────────────────
        if (cfg_mx_in_i && !addr_in_spad(cfg_base_mx_i))
            int_r[8] = 1'b1;

        //── [7] 权重地址超界(CIM) ─────────────────────────────────
        if (!addr_in_cim(cfg_base_wt_i))
            int_r[7] = 1'b1;

        //── [6] 输出地址超界 ──────────────────────────────────────
        if (!addr_in_spad(cfg_base_out_i))
            int_r[6] = 1'b1;

        //── [5] PSUM地址超界 ──────────────────────────────────────
        if (cfg_base_orig_i > 0 && !addr_in_spad(cfg_base_orig_i))
            int_r[5] = 1'b1;

        //── [4] 输入地址超界 ──────────────────────────────────────
        if (!addr_in_spad(cfg_base_in_i))
            int_r[4] = 1'b1;
    end

    //── Compute errors ([3:0]) set by pipeline, not config check ─
    // These are wired from compute modules (NaN/Inf/overflow/underflow)

    assign int_o    = int_r;
    assign chk_pass_o = (int_r[31:4] == 28'd0);  // fatal config errors all clear

endmodule
