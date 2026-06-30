//==============================================================================
// VPU Defines & Parameters — from vpu.md spec v2.2
//==============================================================================

`ifndef VPU_DEFINES_VH
`define VPU_DEFINES_VH

//── RV32/RV64 config ──────────────────────────────────────────────
`define  RV_LEN          32

//── SPAD / Local Memory ───────────────────────────────────────────
`define  SPAD_NUM        6
`define  SPAD_BANK_NUM   1
`define  SPAD_WD         512
`define  SPAD_DEPTH      512
`define  SPAD_BANK_DP    (32*1024)
`define  LMEM_WD         512
`define  LMEM_ADDR_WD    32

//── VPU ────────────────────────────────────────────────────────────
`define  VPE_NUM         16

//── Data types ─────────────────────────────────────────────────────
`define  DT_INT          3'b000
`define  DT_FP           3'b001          // F152
`define  DT_BF           3'b010
`define  DT_BFF          3'b011          // F143
`define  DT_MX_INT       3'b100
`define  DT_MX_FP        3'b101          // FP152
`define  DT_MX_FP8       3'b111          // FP143
`define  DT_MX_BF        3'b110

//── Width codes ────────────────────────────────────────────────────
`define  WD_4            3'b010
`define  WD_8            3'b011
`define  WD_16           3'b100
`define  WD_32           3'b101

//── Function selection ─────────────────────────────────────────────
`define  FUNC_VV_V       2'b00
`define  FUNC_VS_V       2'b01
`define  FUNC_V_S        2'b10
`define  FUNC_V_V        2'b11

//── Opcodes ────────────────────────────────────────────────────────
`define  OP_ADD          6'b000_000
`define  OP_SUB          6'b000_001
`define  OP_RSUB         6'b000_010
`define  OP_MIN          6'b001_000
`define  OP_MAX          6'b001_001
`define  OP_EQUAL        6'b010_000
`define  OP_NOT_EQUAL    6'b010_001
`define  OP_GREATER      6'b010_010
`define  OP_GREATER_EQ   6'b010_011
`define  OP_LESS         6'b010_100
`define  OP_LESS_EQ      6'b010_101
`define  OP_SHIFT_L      6'b011_000
`define  OP_SHIFT_R      6'b011_001
`define  OP_AND          6'b100_000
`define  OP_OR           6'b100_001
`define  OP_XOR          6'b100_010
`define  OP_MUL          6'b101_000
`define  OP_MAC          6'b101_001
// Type-convert pseudo-ops (for V_V instructions)
`define  OP_I2F          6'b110_000
`define  OP_F2I          6'b110_001
`define  OP_F2F          6'b110_010
`define  OP_M2F          6'b110_011
`define  OP_F2M          6'b110_100
`define  OP_M2I          6'b110_101
`define  OP_I2M          6'b110_110
// Reduce pseudo-ops (for V_S instructions)
`define  OP_SUM          6'b111_000

//── Rounding modes ─────────────────────────────────────────────────
`define  RM_FLOOR        3'b000
`define  RM_CEILING      3'b001
`define  RM_ZERO         3'b010
`define  RM_AWAY_ZERO    3'b011
`define  RM_NEAREST_ZERO 3'b100
`define  RM_NEAREST_EVEN 3'b101

//── GPR width per type ─────────────────────────────────────────────
function automatic int get_elem_width(input [2:0] wd_code);
    case (wd_code)
        `WD_4:  get_elem_width = 4;
        `WD_8:  get_elem_width = 8;
        `WD_16: get_elem_width = 16;
        `WD_32: get_elem_width = 32;
        default: get_elem_width = 32;
    endcase
endfunction

// Expansion: short exp → w8 exp
function automatic [7:0] expand_exp_fp8(input [4:0] e5);
    expand_exp_fp8 = {e5[4], e5[4], e5[4], e5};   // sign-extend E5M2
endfunction

function automatic [7:0] expand_exp_bf8(input [7:0] e8);
    expand_exp_bf8 = e8;   // BF16 exp already 8-bit
endfunction

`endif
