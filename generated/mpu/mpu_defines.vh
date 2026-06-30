//==============================================================================
// MPU Defines — Matrix Processing Unit from [HM056]-CDD-MPU v0.9
// Target: TSMC 22NM ULL, 500MHz
//==============================================================================
`ifndef MPU_DEFINES_VH
`define MPU_DEFINES_VH

//── Global Parameters ─────────────────────────────────────────────
`define  MPU_CIMM_NUM        8       // CIM Macro数量
`define  MPU_CIME_NUM        4       // CIM Engine数量（软件可调用最小单元）
`define  MPU_RD_CHL_NUM      2       // 读通道数量
`define  MPU_RD_CHL_WIDTH    512     // 读通道位宽
`define  MPU_WR_CHL_NUM      1       // 写通道数量
`define  MPU_WR_CHL_WIDTH    512     // 写通道位宽
`define  MPU_MEM_CHL_NUM     1       // 存储通道数量
`define  MPU_MEM_CHL_WIDTH   512     // 存储通道位宽

// Address space
`define  MPU_P_ADDR_WIDTH    32
`define  MPU_P_DIM0_WIDTH    14
`define  MPU_P_DIM1_WIDTH    13
`define  MPU_P_IO_DATA_WIDTH 512
`define  MPU_CIMC_ADDR_WIDTH 13

// RD Channel
`define  MPU_P_RD_CHL_NUM    64
`define  MPU_P_RD_CHL_WIDTH  16
`define  MPU_P_RD1_OUT_NUM   4
`define  MPU_P_FIFO_DEPTH    2

// CIM Interface
`define  MPU_P_CIMC_ADDR_WD  13
`define  MPU_P_RD_CIM_GRP_NUM 4
`define  MPU_P_CIME_IN_WIDTH  1024

// Post Process
`define  MPU_P_POST_IN1_W    2432
`define  MPU_P_POST_IN2_W    512
`define  MPU_P_POST_GRP_NUM  16

//── Task Select ──────────────────────────────────────────────────
`define  TASK_DEFAULT        2'b00
`define  TASK_SWITCH_PATTERN 2'b01
`define  TASK_GEMM           2'b11

//── Pattern ──────────────────────────────────────────────────────
`define  PATTERN2            3'b010       // 2×2 CIME
`define  PATTERN3            3'b100       // 1×4 CIME

//── Precision encoding (from 4.7 NPU数据精度编码) ────────────────
// Type: 0=INT 1=FP  |  Width: 010=4 011=8 100=16 101=32
`define  PREC_INT4    {1'b0, 3'b010}   // INT, 4-bit
`define  PREC_INT8    {1'b0, 3'b011}   // INT, 8-bit
`define  PREC_INT16   {1'b0, 3'b100}   // INT, 16-bit
`define  PREC_INT32   {1'b0, 3'b101}   // INT, 32-bit
`define  PREC_FP8E5M2 {1'b1, 3'b011}   // FP, 8-bit  E5M2
`define  PREC_FP8E4M3 {1'b1, 3'b011}   // FP, 8-bit  E4M3 (manti=1)
`define  PREC_FP16    {1'b1, 3'b100}   // FP, 16-bit
`define  PREC_BF16    {1'b1, 3'b100}   // BF, 16-bit (manti=1)
`define  PREC_FP32    {1'b1, 3'b101}   // FP, 32-bit

//── Compute combination encoding (5-bit: input_prec, weight_prec) ─
// config_format[10:0] = {mx_en, input[4:0], weight[4:0]}
// input_prec[4:0]: [4]=MX [3]=FP/INT [2:0]=width
// weight_prec[4:0]: [4]=MX [3]=FP/INT [2:0]=width
`define  CFG_COMB(n)   cfg_comb_``n

// Precision type flags
`define  IS_INT(prec)  (!prec[3])                    // INT type
`define  IS_FP(prec)   (prec[3] && !prec[4])         // FP type (non-MX)
`define  IS_MX(prec)   (prec[4])                     // MX type
`define  IS_MX_FP(prec) (prec[4] && prec[3])         // MX-FP type
`define  IS_MX_INT(prec) (prec[4] && !prec[3])       // MX-INT type

// Width extraction
`define  GET_WD(prec)  (prec[2:0])

//── 17 supported compute combinations ────────────────────────────
// Format: {input_prec[4:0], weight_prec[4:0]}
// input_prec: [4]=MX [3]=FP/INT [1:0]=width
localparam [9:0] COMB_INT8_INT4    = {5'b00001, 5'b00010};  // 组合一
localparam [9:0] COMB_INT8_INT8    = {5'b00001, 5'b00001};  // 组合二
localparam [9:0] COMB_FP16_FP16    = {5'b00100, 5'b00100};  // 组合三
localparam [9:0] COMB_BF16_BF16    = {5'b00101, 5'b00101};  // 组合四
localparam [9:0] COMB_FP8_FP8      = {5'b00111, 5'b00111};  // 组合五
localparam [9:0] COMB_BF16_FP16    = {5'b00101, 5'b00100};  // 组合六
localparam [9:0] COMB_FP16_BF16    = {5'b00100, 5'b00101};  // 组合七
localparam [9:0] COMB_FP16_INT4    = {5'b00100, 5'b00010};  // 组合八
localparam [9:0] COMB_BF16_INT4    = {5'b00101, 5'b00010};  // 组合九
localparam [9:0] COMB_FP16_INT8    = {5'b00100, 5'b00001};  // 组合十
localparam [9:0] COMB_BF16_INT8    = {5'b00101, 5'b00001};  // 组合十一
localparam [9:0] COMB_INT8_FP16    = {5'b00001, 5'b00100};  // 组合十二
localparam [9:0] COMB_INT8_BF16    = {5'b00001, 5'b00101};  // 组合十三
localparam [9:0] COMB_MXINT8_MXINT8 = {5'b10001, 5'b10001}; // 组合十四
localparam [9:0] COMB_FP16_MXINT8  = {5'b00100, 5'b10001};  // 组合十五
localparam [9:0] COMB_BF16_MXINT8  = {5'b00101, 5'b10001};  // 组合十六
localparam [9:0] COMB_FP8_MXINT8   = {5'b00111, 5'b10001};  // 组合十七

//── Address Generator Pattern ────────────────────────────────────
`define  ADDR_TYPE0         3'b001       // linear, no repeat
`define  ADDR_TYPE1         3'b010       // DIM0 repeat 2x
`define  ADDR_TYPE2         3'b100       // DIM0 repeat 4x

//── FRR Dispatcher mode ──────────────────────────────────────────
`define  DISP_MODE_1X       2'b00        // 1 per slave
`define  DISP_MODE_2X       2'b01        // 2 per slave
`define  DISP_MODE_4X       2'b10        // 4 per slave

//── Low Power ────────────────────────────────────────────────────
`define  LP_ACTIVE          1'b0
`define  LP_SLEEP           1'b1

//── State Machine ────────────────────────────────────────────────
`define  MPU_IDLE           3'd0
`define  MPU_CFG_CHK        3'd1
`define  MPU_CFG_PARSE      3'd2
`define  MPU_RUN            3'd3
`define  MPU_DONE           3'd4
`define  MPU_ERROR          3'd5

`endif
