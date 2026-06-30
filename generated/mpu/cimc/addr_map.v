//==============================================================================
// addr_map — CIMM EXP Internal Address Mapping
// Maps XBAR[31:0] → CIMM {page[3:0], row[5:0]} based on CIME/CIMM + PATTERN
//
// EXP row internal address: 10-bit = {CIME[1:0], CIMM, 3'b010, 3'b000}
//   bit[9:8] = CIME index (0-3)
//   bit[7]   = CIMM index (0-1)
//   bit[6:4] = 3'b010 (EXP row indicator)
//   bit[3:0] = row offset
//
// XBAR address format for EXP access:
//   bit[19:17] = 3'b010 (EXP access flag, always)
//   bit[16:13] = PAGE offset (page[3:0] within CIMM)
//   bit[12:5]  = CIM offset (depends on PATTERN and CIME/CIMM)
//   bit[4:0]   = unused (byte offset within 256-bit row)
//
// PATTERN2 (2×2): CIME pairs
// PATTERN3 (1×4): CIME sequential
//==============================================================================
module addr_map #(
    parameter P_ADDR_WIDTH  = 32,
    parameter CIMM_ADDR_WD  = 10,
    parameter CIME_NUM      = 4,
    parameter CIMM_PER_CIME = 2
) (
    input  wire [P_ADDR_WIDTH-1:0]  xbar_addr_i,     // XBAR 32-bit address
    input  wire [2:0]                pattern_i,        // PATTERN2 / PATTERN3
    input  wire                      is_exp_access_i,  // addr[19:17]==3'b010

    //── Decoded outputs ──────────────────────────────────────────
    output wire [1:0]                cime_sel_o,       // which CIME (0-3)
    output wire                      cimm_sel_o,       // which CIMM within CIME (0-1)
    output wire [3:0]                page_o,           // page within CIMM (0-15)
    output wire [5:0]                row_o,            // row within page (0-32)
    output wire [7:0]                cim_offset_o,     // CIM offset XBAR[12:5]
    output wire                      is_exp_row_o      // 1 = EXP row access
);

    //── XBAR address fields ──────────────────────────────────────
    wire [2:0]  xbar_exp_flag  = xbar_addr_i[19:17];   // 3'b010=EXP
    wire [3:0]  xbar_page      = xbar_addr_i[16:13];   // PAGE offset
    wire [7:0]  xbar_cim_offset= xbar_addr_i[12:5];    // CIM offset

    assign is_exp_row_o = (xbar_exp_flag == 3'b010);

    //══════════════════════════════════════════════════════════════
    // PATTERN2 (2×2): CIME0+1 paired, CIME2+3 paired
    //
    // CIMM EXP internal addresses:
    //   000100000  CIME[0] CIMM[0]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0x00
    //   001100000  CIME[0] CIMM[1]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0x40
    //   010100000  CIME[1] CIMM[0]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0x80
    //   011100000  CIME[1] CIMM[1]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0xC0
    //   100100000  CIME[2] CIMM[0]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0x01
    //   101100000  CIME[2] CIMM[1]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0x41
    //   110100000  CIME[3] CIMM[0]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0x81
    //   111100000  CIME[3] CIMM[1]  PATTERN2  PAGE=XBAR[16:13]  CIM_OFFSET=0xC1
    //══════════════════════════════════════════════════════════════

    // PATTERN2 decode: CIME = {cim_offset[7], cim_offset[4]}
    //                  CIMM = cim_offset[6]
    wire [1:0] pt2_cime = {xbar_cim_offset[7], xbar_cim_offset[4]};
    wire       pt2_cimm = xbar_cim_offset[6];

    //══════════════════════════════════════════════════════════════
    // PATTERN3 (1×4): all 4 CIMEs sequential
    //
    //   000100000  CIME[0] CIMM[0]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x00
    //   001100000  CIME[0] CIMM[1]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x80
    //   010100000  CIME[1] CIMM[0]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x01
    //   011100000  CIME[1] CIMM[1]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x81
    //   100100000  CIME[2] CIMM[0]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x02
    //   101100000  CIME[2] CIMM[1]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x82
    //   110100000  CIME[3] CIMM[0]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x03
    //   111100000  CIME[3] CIMM[1]  PATTERN3  PAGE=XBAR[16:13]  CIM_OFFSET=0x83
    //══════════════════════════════════════════════════════════════

    // PATTERN3 decode: CIME = cim_offset[1:0] (sequentially 0,1,2,3)
    //                  CIMM = cim_offset[7] (bit 7 selects CIMM within CIME)
    wire [1:0] pt3_cime = xbar_cim_offset[1:0];
    wire       pt3_cimm = xbar_cim_offset[7];

    //── Mux based on pattern ─────────────────────────────────────
    wire       is_pt2  = (pattern_i == `PATTERN2);
    wire [1:0] cime_sel= is_pt2 ? pt2_cime  : pt3_cime;
    wire       cimm_sel= is_pt2 ? pt2_cimm  : pt3_cimm;

    assign cime_sel_o = cime_sel;
    assign cimm_sel_o = cimm_sel;
    assign page_o     = xbar_page;
    assign cim_offset_o = xbar_cim_offset;

    //── CIMM internal address: {CIME[1:0], CIMM, 3'b010, row_offset} ──
    // For EXP access: row = EXP row (32), else row = data row (0-31)
    wire [5:0] exp_row   = 6'd32;
    wire [5:0] data_row  = {1'b0, xbar_addr_i[4:0]};  // 0-31
    assign row_o = is_exp_row_o ? exp_row : data_row;

endmodule
