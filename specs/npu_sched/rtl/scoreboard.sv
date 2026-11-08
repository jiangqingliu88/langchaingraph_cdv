module scoreboard #(
  parameter int NUM_INS     = 16,
  parameter int ID_W        = 4,
  parameter int INST_INFO_W = 64,
  parameter int RT_IDX_W    = 3,
  parameter int WT_IDX_W    = 3,
  parameter int PG_IDX_W    = 4,
  parameter int DR_IDX_W    = 3,
  parameter int AGE_W       = 8
)(
  input  logic                   clk,
  input  logic                   rst_n,

  input  logic [INST_INFO_W-1:0] ins_inst_info,
  output logic                   dsp_en,
  output logic                   store_en,
  input  logic [NUM_INS-1:0]     ins_done,

  input  logic                   rtile_rls_vld,
  input  logic [RT_IDX_W-1:0]    rtile_rls_idx,
  input  logic                   wtile_rls_vld,
  input  logic [WT_IDX_W-1:0]    wtile_rls_idx,
  input  logic                   page_rls_vld,
  input  logic [PG_IDX_W-1:0]    page_rls_idx,
  input  logic                   rdram_rls_vld,
  input  logic [DR_IDX_W-1:0]    rdram_rls_idx,

  output logic [NUM_INS-1:0]     ins_buff_xx_vld,
  output logic                   ren,
  output logic [ID_W-1:0]        ren_id,
  output logic [4*NUM_INS-1:0]   ins_status
);

  // ------------------------------------------------------------------
  // Local parameters
  // ------------------------------------------------------------------
  localparam int RT_NUM = 1 << RT_IDX_W;
  localparam int WT_NUM = 1 << WT_IDX_W;
  localparam int PG_NUM = 1 << PG_IDX_W;
  localparam int DR_NUM = 1 << DR_IDX_W;

  localparam int OFF_VALID = 0;
  localparam int OFF_ID    = 1;
  localparam int OFF_SRC0  = OFF_ID + ID_W;
  localparam int OFF_SRC1  = OFF_SRC0 + ID_W;
  localparam int OFF_DST   = OFF_SRC1 + ID_W;
  localparam int OFF_RTILE = OFF_DST + ID_W;
  localparam int OFF_WTILE = OFF_RTILE + RT_IDX_W;
  localparam int OFF_PAGE  = OFF_WTILE + WT_IDX_W;
  localparam int OFF_RDRAM = OFF_PAGE + PG_IDX_W;
  localparam int OFF_FLAGS = OFF_RDRAM + DR_IDX_W;

  // ------------------------------------------------------------------
  // Instruction info decode
  // ------------------------------------------------------------------
  wire                dec_valid   = ins_inst_info[OFF_VALID];
  wire [ID_W-1:0]     dec_id      = ins_inst_info[OFF_ID    +: ID_W];
  wire [ID_W-1:0]     dec_src0    = ins_inst_info[OFF_SRC0  +: ID_W];
  wire [ID_W-1:0]     dec_src1    = ins_inst_info[OFF_SRC1  +: ID_W];
  wire [ID_W-1:0]     dec_dst     = ins_inst_info[OFF_DST   +: ID_W];
  wire [RT_IDX_W-1:0] dec_rtile   = ins_inst_info[OFF_RTILE +: RT_IDX_W];
  wire [WT_IDX_W-1:0] dec_wtile   = ins_inst_info[OFF_WTILE +: WT_IDX_W];
  wire [PG_IDX_W-1:0] dec_page    = ins_inst_info[OFF_PAGE  +: PG_IDX_W];
  wire [DR_IDX_W-1:0] dec_rdram   = ins_inst_info[OFF_RDRAM +: DR_IDX_W];
  wire [6:0]          dec_need    = ins_inst_info[OFF_FLAGS +: 7];

  wire                dec_need_rtile = dec_need[0];
  wire                dec_need_wtile = dec_need[1];
  wire                dec_need_page  = dec_need[2];
  wire                dec_need_rdram = dec_need[3];
  wire                dec_is_store   = dec_need[4];
  wire                dec_is_dsp     = dec_need[5];
  wire                dec_is_glsu    = dec_need[6];

  // ------------------------------------------------------------------
  // Age comparison helper
  // ------------------------------------------------------------------
  function automatic logic is_older (input logic [AGE_W-1:0] a_j,
                                     input logic [AGE_W-1:0] a_i);
    logic [AGE_W-1:0] d;
    d = a_i - a_j;
    is_older = (d != '0) && (d[AGE_W-1] == 1'b0);
  endfunction

  // ------------------------------------------------------------------
  // Instruction status table registers
  // ------------------------------------------------------------------
  logic [NUM_INS-1:0]   valid_q;
  logic [NUM_INS-1:0]   master_q;

  logic [ID_W-1:0]      id_q    [NUM_INS];
  logic [ID_W-1:0]      src0_q  [NUM_INS];
  logic [ID_W-1:0]      src1_q  [NUM_INS];
  logic [ID_W-1:0]      dst_q   [NUM_INS];
  logic [RT_IDX_W-1:0]  rtile_q [NUM_INS];
  logic [WT_IDX_W-1:0]  wtile_q [NUM_INS];
  logic [PG_IDX_W-1:0]  page_q  [NUM_INS];
  logic [DR_IDX_W-1:0]  rdram_q [NUM_INS];
  logic [6:0]           need_q  [NUM_INS];
  logic [AGE_W-1:0]     age_q   [NUM_INS];

  logic [AGE_W-1:0]     age_cnt_q;

  logic [NUM_INS-1:0]   haz_raw_q;
  logic [NUM_INS-1:0]   haz_waw_q;
  logic [NUM_INS-1:0]   haz_war_q;
  logic [NUM_INS-1:0]   haz_st_q;

  logic [RT_NUM-1:0]    rtile_busy_q;
  logic [WT_NUM-1:0]    wtile_busy_q;
  logic [PG_NUM-1:0]    page_busy_q;
  logic [DR_NUM-1:0]    rdram_busy_q;

  // ------------------------------------------------------------------
  // Release one-hot expansion
  // ------------------------------------------------------------------
  logic [RT_NUM-1:0] rtile_rls_oh;
  logic [WT_NUM-1:0] wtile_rls_oh;
  logic [PG_NUM-1:0] page_rls_oh;
  logic [DR_NUM-1:0] rdram_rls_oh;

  always_comb begin
    rtile_rls_oh = '0;
    wtile_rls_oh = '0;
    page_rls_oh  = '0;
    rdram_rls_oh = '0;
    if (rtile_rls_vld) rtile_rls_oh[rtile_rls_idx] = 1'b1;
    if (wtile_rls_vld) wtile_rls_oh[wtile_rls_idx] = 1'b1;
    if (page_rls_vld)  page_rls_oh [page_rls_idx ] = 1'b1;
    if (rdram_rls_vld) rdram_rls_oh[rdram_rls_idx] = 1'b1;
  end

  wire [RT_NUM-1:0] rtile_busy_eff = rtile_busy_q & ~rtile_rls_oh;
  wire [WT_NUM-1:0] wtile_busy_eff = wtile_busy_q & ~wtile_rls_oh;
  wire [PG_NUM-1:0] page_busy_eff  = page_busy_q  & ~page_rls_oh;
  wire [DR_NUM-1:0] rdram_busy_eff = rdram_busy_q & ~rdram_rls_oh;

  // ------------------------------------------------------------------
  // Allocation slot selection
  // ------------------------------------------------------------------
  wire [NUM_INS-1:0] entry_free = ~valid_q;
  wire [NUM_INS-1:0] alloc_oh   = entry_free & (~entry_free + 1'b1);
  wire               alloc_vld  = dec_valid & (|entry_free);

  // ------------------------------------------------------------------
  // Packed per-entry attribute views
  // ------------------------------------------------------------------
  logic [NUM_INS-1:0] is_store_v;
  logic [NUM_INS-1:0] is_dsp_v;
  logic [NUM_INS-1:0] is_glsu_v;
  logic [NUM_INS-1:0] wr_v;

  always_comb begin
    for (int i = 0; i < NUM_INS; i++) begin
      is_store_v[i] = need_q[i][4];
      is_dsp_v[i]   = need_q[i][5];
      is_glsu_v[i]  = need_q[i][6];
      wr_v[i]       = ~need_q[i][4];
    end
  end

  wire tmu_busy = |(valid_q & master_q & is_dsp_v);

  // ------------------------------------------------------------------
  // New instruction hazard evaluation (parallel comparison vs whole table)
  // ------------------------------------------------------------------
  logic new_raw;
  logic new_waw;
  logic new_war;
  logic new_st;

  always_comb begin
    new_raw = 1'b0;
    new_waw = 1'b0;
    new_war = 1'b0;
    new_st  = 1'b0;

    for (int j = 0; j < NUM_INS; j++) begin
      if (valid_q[j]) begin
        if (wr_v[j] && ((dst_q[j] == dec_src0) || (dst_q[j] == dec_src1)))
          new_raw = 1'b1;
        if (wr_v[j] && !dec_is_store && (dst_q[j] == dec_dst))
          new_waw = 1'b1;
        if (!dec_is_store && ((src0_q[j] == dec_dst) || (src1_q[j] == dec_dst)))
          new_war = 1'b1;
      end
    end

    new_st = (dec_need_rtile & rtile_busy_eff[dec_rtile])
           | (dec_need_wtile & wtile_busy_eff[dec_wtile])
           | (dec_need_page  & page_busy_eff [dec_page ])
           | (dec_need_rdram & rdram_busy_eff[dec_rdram])
           | (dec_is_dsp & tmu_busy & ~dec_is_glsu);
  end

  wire new_any_hazard = new_raw | new_waw | new_war | new_st;

  wire direct_disp = alloc_vld & ~new_any_hazard;
  wire store_disp  = alloc_vld &  new_any_hazard;

  assign dsp_en   = direct_disp;
  assign store_en = store_disp;

  // ------------------------------------------------------------------
  // Resource acquisition one-hot for the freshly decoded instruction
  // ------------------------------------------------------------------
  logic [RT_NUM-1:0] rtile_new_oh;
  logic [WT_NUM-1:0] wtile_new_oh;
  logic [PG_NUM-1:0] page_new_oh;
  logic [DR_NUM-1:0] rdram_new_oh;

  always_comb begin
    rtile_new_oh = '0;
    wtile_new_oh = '0;
    page_new_oh  = '0;
    rdram_new_oh = '0;
    if (direct_disp) begin
      if (dec_need_rtile) rtile_new_oh[dec_rtile] = 1'b1;
      if (dec_need_wtile) wtile_new_oh[dec_wtile] = 1'b1;
      if (dec_need_page)  page_new_oh [dec_page ] = 1'b1;
      if (dec_need_rdram) rdram_new_oh[dec_rdram] = 1'b1;
    end
  end

  wire [RT_NUM-1:0] rtile_use_eff = rtile_busy_eff | rtile_new_oh;
  wire [WT_NUM-1:0] wtile_use_eff = wtile_busy_eff | wtile_new_oh;
  wire [PG_NUM-1:0] page_use_eff  = page_busy_eff  | page_new_oh;
  wire [DR_NUM-1:0] rdram_use_eff = rdram_busy_eff | rdram_new_oh;

  // ------------------------------------------------------------------
  // Per-entry hazard re-evaluation (status table parallel compare)
  // ------------------------------------------------------------------
  logic [NUM_INS-1:0] raw_c;
  logic [NUM_INS-1:0] waw_c;
  logic [NUM_INS-1:0] war_c;
  logic [NUM_INS-1:0] st_c;

  always_comb begin
    raw_c = '0;
    waw_c = '0;
    war_c = '0;
    st_c  = '0;

    for (int i = 0; i < NUM_INS; i++) begin
      if (valid_q[i] && !master_q[i]) begin
        for (int j = 0; j < NUM_INS; j++) begin
          if (valid_q[j] && (j != i) && is_older(age_q[j], age_q[i])) begin
            if (wr_v[j] && ((dst_q[j] == src0_q[i]) || (dst_q[j] == src1_q[i])))
              raw_c[i] = 1'b1;
            if (wr_v[j] && !is_store_v[i] && (dst_q[j] == dst_q[i]))
              waw_c[i] = 1'b1;
            if (!is_store_v[i] && ((src0_q[j] == dst_q[i]) || (src1_q[j] == dst_q[i])))
              war_c[i] = 1'b1;
          end
        end

        st_c[i] = (need_q[i][0] & rtile_busy_eff[rtile_q[i]])
                | (need_q[i][1] & wtile_busy_eff[wtile_q[i]])
                | (need_q[i][2] & page_busy_eff [page_q[i]])
                | (need_q[i][3] & rdram_busy_eff[rdram_q[i]])
                | (is_dsp_v[i] & tmu_busy & ~is_glsu_v[i]);
      end
    end
  end

  // ------------------------------------------------------------------
  // Out-of-order issue selection from ins_buffer (GLSU / TMU priority first)
  // ------------------------------------------------------------------
  logic [NUM_INS-1:0] struct_ok_v;

  always_comb begin
    for (int i = 0; i < NUM_INS; i++) begin
      struct_ok_v[i] = 1'b1;
      if (valid_q[i] && !master_q[i]) begin
        if (need_q[i][0] && rtile_use_eff[rtile_q[i]]) struct_ok_v[i] = 1'b0;
        if (need_q[i][1] && wtile_use_eff[wtile_q[i]]) struct_ok_v[i] = 1'b0;
        if (need_q[i][2] && page_use_eff [page_q[i]])  struct_ok_v[i] = 1'b0;
        if (need_q[i][3] && rdram_use_eff[rdram_q[i]]) struct_ok_v[i] = 1'b0;
        if (is_dsp_v[i] && tmu_busy && !is_glsu_v[i])  struct_ok_v[i] = 1'b0;
      end
    end
  end

  wire [NUM_INS-1:0] buf_vec     = valid_q & ~master_q;
  wire [NUM_INS-1:0] ready_glsu  = buf_vec & ~haz_raw_q & ~haz_waw_q & ~haz_war_q
                                 & struct_ok_v &  is_glsu_v;
  wire [NUM_INS-1:0] ready_other = buf_vec & ~haz_raw_q & ~haz_waw_q & ~haz_war_q
                                 & struct_ok_v & ~is_glsu_v;

  wire [NUM_INS-1:0] issue_oh =
        (|ready_glsu)  ? (ready_glsu  & (~ready_glsu  + 1'b1)) :
        (|ready_other) ? (ready_other & (~ready_other + 1'b1)) : '0;

  assign ins_buff_xx_vld = buf_vec;

  // ------------------------------------------------------------------
  // Resource set one-hot generation
  // ------------------------------------------------------------------
  wire [NUM_INS-1:0] acq_vec = issue_oh | (alloc_oh & {NUM_INS{direct_disp}});

  logic [RT_NUM-1:0] rtile_set_oh;
  logic [WT_NUM-1:0] wtile_set_oh;
  logic [PG_NUM-1:0] page_set_oh;
  logic [DR_NUM-1:0] rdram_set_oh;

  always_comb begin
    rtile_set_oh = '0;
    wtile_set_oh = '0;
    page_set_oh  = '0;
    rdram_set_oh = '0;

    for (int i = 0; i < NUM_INS; i++) begin
      if (acq_vec[i]) begin
        if (alloc_oh[i]) begin
          if (dec_need_rtile) rtile_set_oh[dec_rtile] = 1'b1;
          if (dec_need_wtile) wtile_set_oh[dec_wtile] = 1'b1;
          if (dec_need_page)  page_set_oh [dec_page ] = 1'b1;
          if (dec_need_rdram) rdram_set_oh[dec_rdram] = 1'b1;
        end else begin
          if (need_q[i][0]) rtile_set_oh[rtile_q[i]] = 1'b1;
          if (need_q[i][1]) wtile_set_oh[wtile_q[i]] = 1'b1;
          if (need_q[i][2]) page_set_oh [page_q[i]]  = 1'b1;
          if (need_q[i][3]) rdram_set_oh[rdram_q[i]] = 1'b1;
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // Instruction status table (sequential)
  // ------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      valid_q   <= '0;
      master_q  <= '0;
      age_cnt_q <= '0;
      for (int i = 0; i < NUM_INS; i++) begin
        id_q[i]    <= '0;
        src0_q[i]  <= '0;
        src1_q[i]  <= '0;
        dst_q[i]   <= '0;
        rtile_q[i] <= '0;
        wtile_q[i] <= '0;
        page_q[i]  <= '0;
        rdram_q[i] <= '0;
        need_q[i]  <= '0;
        age_q[i]   <= '0;
      end
    end else begin
      age_cnt_q <= age_cnt_q + AGE_W'(alloc_vld);
      for (int i = 0; i < NUM_INS; i++) begin
        if (valid_q[i] && ins_done[i]) begin
          valid_q[i]  <= 1'b0;
          master_q[i] <= 1'b0;
        end else if (valid_q[i] && !master_q[i] && issue_oh[i]) begin
          master_q[i] <= 1'b1;
        end else if (alloc_vld && alloc_oh[i]) begin
          valid_q[i]  <= 1'b1;
          master_q[i] <= direct_disp;
          id_q[i]     <= dec_id;
          src0_q[i]   <= dec_src0;
          src1_q[i]   <= dec_src1;
          dst_q[i]    <= dec_dst;
          rtile_q[i]  <= dec_rtile;
          wtile_q[i]  <= dec_wtile;
          page_q[i]   <= dec_page;
          rdram_q[i]  <= dec_rdram;
          need_q[i]   <= dec_need;
          age_q[i]    <= age_cnt_q;
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // Hazard bit registers (status0~status3)
  // ------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      haz_raw_q <= '0;
      haz_waw_q <= '0;
      haz_war_q <= '0;
      haz_st_q  <= '0;
    end else begin
      for (int i = 0; i < NUM_INS; i++) begin
        if (alloc_vld && alloc_oh[i]) begin
          haz_raw_q[i] <= new_raw;
          haz_waw_q[i] <= new_waw;
          haz_war_q[i] <= new_war;
          haz_st_q[i]  <= new_st;
        end else if (valid_q[i] && !master_q[i]) begin
          haz_raw_q[i] <= raw_c[i];
          haz_waw_q[i] <= waw_c[i];
          haz_war_q[i] <= war_c[i];
          haz_st_q[i]  <= st_c[i];
        end else begin
          haz_raw_q[i] <= 1'b0;
          haz_waw_q[i] <= 1'b0;
          haz_war_q[i] <= 1'b0;
          haz_st_q[i]  <= 1'b0;
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // Resource occupancy tables (sequential)
  // ------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rtile_busy_q <= '0;
      wtile_busy_q <= '0;
      page_busy_q  <= '0;
      rdram_busy_q <= '0;
    end else begin
      rtile_busy_q <= (rtile_busy_q & ~rtile_rls_oh) | rtile_set_oh;
      wtile_busy_q <= (wtile_busy_q & ~wtile_rls_oh) | wtile_set_oh;
      page_busy_q  <= (page_busy_q  & ~page_rls_oh ) | page_set_oh;
      rdram_busy_q <= (rdram_busy_q & ~rdram_rls_oh) | rdram_set_oh;
    end
  end

  // ------------------------------------------------------------------
  // ins_buffer replay request (ren / ren_id)
  // ------------------------------------------------------------------
  logic [ID_W-1:0] issue_id_c;

  always_comb begin
    issue_id_c = '0;
    for (int i = 0; i < NUM_INS; i++) begin
      if (issue_oh[i]) issue_id_c = id_q[i];
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ren    <= 1'b0;
      ren_id <= '0;
    end else begin
      ren    <= |issue_oh;
      ren_id <= issue_id_c;
    end
  end

  // ------------------------------------------------------------------
  // Status output packing
  // ------------------------------------------------------------------
  always_comb begin
    for (int i = 0; i < NUM_INS; i++) begin
      ins_status[4*i + 0] = haz_raw_q[i];
      ins_status[4*i + 1] = haz_waw_q[i];
      ins_status[4*i + 2] = haz_war_q[i];
      ins_status[4*i + 3] = haz_st_q[i];
    end
  end

endmodule