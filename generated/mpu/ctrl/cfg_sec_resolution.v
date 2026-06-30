//==============================================================================
// cfg_sec_resolution — Configuration Secondary Resolution
// Parses raw config → MPU internal control signals:
//   - CIME activation count & mask
//   - Element width, elements per transfer
//   - ADDR_GEN pattern type
//   - Precision encoding for sub-modules
//==============================================================================
module cfg_sec_resolution (
    input  wire [13:0]  cfg_dim0_in_i,
    input  wire [13:0]  cfg_dim0_out_i,
    input  wire [12:0]  cfg_dim1_in_i,
    input  wire [12:0]  cfg_dim1_out_i,
    input  wire [12:0]  cfg_stride_in_i,
    input  wire [12:0]  cfg_stride_out_i,
    input  wire [2:0]   cfg_width_in_i,
    input  wire [2:0]   cfg_width_wt_i,
    input  wire [2:0]   cfg_width_out_i,
    input  wire         cfg_type_in_i,
    input  wire         cfg_type_wt_i,
    input  wire         cfg_type_out_i,
    input  wire         cfg_acc_en_i,
    input  wire         cfg_mx_in_i,
    input  wire [2:0]   cfg_pattern_i,
    input  wire [1:0]   cfg_task_i,

    //── Resolved outputs ─────────────────────────────────────────
    output reg  [5:0]   elem_width_o,        // element width in bits
    output reg  [5:0]   elems_per_xfer_o,    // elements per 512b transfer
    output reg  [15:0]  total_elems_o,       // total input elements
    output reg  [3:0]   active_cime_o,       // active CIME count (1-4)
    output reg  [3:0]   cime_mask_o,         // per-CIME enable mask
    output reg  [5:0]   elems_per_cime_o,    // elements per CIME
    output reg  [5:0]   rem_elems_o,          // remainder elements
    output reg  [2:0]   addr_pattern_o,      // ADDR_GEN type0/1/2
    output reg  [3:0]   precision_o,         // {type, width}
    output reg          mx_en_o,
    output reg          psum_en_o,
    // DIM in 32B units → converted to 64B transfer count
    output reg  [13:0]  dim0_xfer_o,          // DIM0 in 64B transfers (ceil(dim0_32b/2))
    output reg  [12:0]  dim1_xfer_o           // DIM1 in 64B transfers
);

    wire [5:0] elems_per_32b;  // elements per 32B (DIM unit granularity)
    wire [5:0] elems_per_64b;  // elements per 64B (512-bit HW transfer)

    assign elems_per_32b = (elem_width_o > 0) ? (6'd32 / (elem_width_o >> 3)) : 6'd32;
    assign elems_per_64b = elems_per_32b << 1;  // 2× per 512-bit xfer

    always @(*) begin
        //── Element width ────────────────────────────────────────
        case (cfg_width_in_i)
            3'b010: elem_width_o = 6'd4;
            3'b011: elem_width_o = 6'd8;
            3'b100: elem_width_o = 6'd16;
            3'b101: elem_width_o = 6'd32;
            default: elem_width_o = 6'd8;
        endcase

        //── Elements per 512-bit transfer (64B = 2×32B) ──────────
        // elem_w=4:  512/4=128   elem_w=8: 512/8=64
        // elem_w=16: 512/16=32  elem_w=32:512/32=16
        elems_per_xfer_o = elems_per_64b;

        //── Total elements = DIM0 × elements_per_32B ─────────────
        // DIM0 is in 32B units; each 32B = 256/elem_w elements
        total_elems_o = cfg_dim0_in_i * {10'd0, elems_per_32b};

        //── Active CIME count ────────────────────────────────────
        // CIME handles 32 channels per row
        // elem_w=4: 128/32=4→2 CIME(paired)   elem_w=8: 64→1 CIME
        if (elem_width_o <= 6'd4)
            active_cime_o = 4'd2;
        else
            active_cime_o = 4'd1;

        //── CIME mask ────────────────────────────────────────────
        case (active_cime_o)
            4'd1: cime_mask_o = 4'b0001;
            4'd2: cime_mask_o = 4'b0011;
            4'd3: cime_mask_o = 4'b0111;
            4'd4: cime_mask_o = 4'b1111;
            default: cime_mask_o = 4'b0001;
        endcase

        //── Elements per CIME ────────────────────────────────────
        elems_per_cime_o = elems_per_xfer_o / {1'b0, active_cime_o[2:0]};

        //── Remainder elements ───────────────────────────────────
        rem_elems_o = total_elems_o % elems_per_xfer_o;

        //── ADDR_GEN pattern ─────────────────────────────────────
        case (cfg_pattern_i)
            `PATTERN2: addr_pattern_o = `ADDR_TYPE2;   // DIM0 repeat 4×
            `PATTERN3: addr_pattern_o = `ADDR_TYPE1;   // DIM0 repeat 2×
            default:   addr_pattern_o = `ADDR_TYPE0;   // linear
        endcase

        //── Precision ────────────────────────────────────────────
        precision_o = {cfg_type_in_i, cfg_width_in_i};

        //── DIM conversion: 32B units → 64B transfer count ──────
        // DIM0/1 from config are in 32B units (256-bit granularity)
        // Each 512-bit HW transfer = 2×32B, so divide by 2
        dim0_xfer_o = cfg_dim0_in_i >> 1;    // ceil(dim0_32b / 2)
        dim1_xfer_o = cfg_dim1_in_i >> 1;

        //── Flags ────────────────────────────────────────────────
        mx_en_o   = cfg_mx_in_i;
        psum_en_o = cfg_acc_en_i;
    end

endmodule
