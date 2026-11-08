module decode (
  input  logic         clk,
  input  logic         rst_n,
  input  logic [73:0]  disp_cmd_inst,
  input  logic         disp_cmd_inst_flag,
  input  logic         disp_cmd_vld,
  output logic         cmd_disp_rdy,
  output logic [17:0]  cmd_xbr_ch0_req_waddr,
  output logic [511:0] cmd_xbr_ch0_req_wdata,
  output logic [1:0]   cmd_xbr_ch0_req_wstrb,
  output logic         cmd_xbr_ch0_req_wvld,
  input  logic         cmd_xbr_ch0_req_wrdy,
  input  logic         xbr_cmd_ch0_rsp_wvld,
  input  logic         xbr_cmd_ch0_rsp_wlast,
  output logic         cmd_xbr_ch0_rsp_wrdy,
  output logic [43:0]  cmd_xbr_ch1_req_raddr,
  output logic         cmd_xbr_ch1_req_rvld,
  input  logic         xbr_cmd_ch1_req_rrdy,
  input  logic [511:0] xbr_cmd_ch1_rsp_rdata,
  input  logic         xbr_cmd_ch1_rsp_rvld,
  output logic         cmd_xbr_ch1_rsp_rrdy,
  inout  wire          dsp_en,
  inout  wire          store_en,
  inout  wire          cfg_drv_buffer_not_full,
  inout  wire          ins_inst_info
);

  localparam [2:0] TYPE_CTRL    = 3'd0;
  localparam [2:0] TYPE_NOC     = 3'd1;
  localparam [2:0] TYPE_TLD_TST = 3'd2;
  localparam [2:0] TYPE_TMU     = 3'd3;
  localparam [2:0] TYPE_MPU     = 3'd4;
  localparam [2:0] TYPE_VPU     = 3'd5;

  localparam [3:0] OP_WR_LMEM  = 4'b0001;
  localparam [3:0] OP_RD_LMEM  = 4'b0010;
  localparam [3:0] OP_CFG_WR   = 4'b0011;
  localparam [3:0] OP_CFG_RD   = 4'b0100;
  localparam [3:0] OP_PRE_WR   = 4'b0101;
  localparam [3:0] OP_PRE_RD   = 4'b0110;

  logic [6:0]  dec_func7;
  logic [31:0] dec_rs1val;
  logic [31:0] dec_rs2val;
  logic        dec_xd;
  logic        dec_xs1;
  logic        dec_xs2;
  logic [2:0]  dec_type;
  logic [3:0]  dec_op;
  logic        dec_is_wr_lmem;
  logic        dec_is_rd_lmem;
  logic        dec_is_cfg;
  logic        dec_is_pre;

  logic [73:0] master_inst_q [0:5];
  logic        master_flag_q [0:5];
  logic [2:0]  master_type_q [0:5];
  logic        master_vld_q  [0:5];

  logic [73:0] buff_inst_q [0:1];
  logic        buff_flag_q [0:1];
  logic [2:0]  buff_type_q [0:1];
  logic        buff_vld_q  [0:1];
  logic [1:0]  buff_count_q;
  logic        buff_wr_ptr_q;
  logic        buff_rd_ptr_q;

  logic [73:0] cfg_info_q;
  logic [2:0]  cfg_type_q;
  logic        cfg_vld_q;
  logic [73:0] pre_info_q;
  logic [2:0]  pre_type_q;
  logic        pre_vld_q;
  logic [43:0] cfg_base_q;

  logic [73:0] lmem_cmd_q;
  logic        lmem_wr_pending_q;
  logic        lmem_rd_pending_q;
  logic        wr_wait_rsp_q;
  logic        rd_wait_rsp_q;
  logic [511:0] rd_data_q;

  wire        buff_not_empty;
  wire        buff_space;
  wire        direct_master_free;
  wire        direct_free;
  wire        push_ready;
  wire        default_ready;
  wire        accept_to_direct;
  wire        accept_to_buff;
  wire        disp_fire;
  wire [2:0]  buff_head_type;
  wire        buff_pop;

  always_comb begin
    dec_func7 = disp_cmd_inst[9:3];
    dec_rs1val = disp_cmd_inst[41:10];
    dec_rs2val = disp_cmd_inst[73:42];
    dec_xd     = disp_cmd_inst[0];
    dec_xs1    = disp_cmd_inst[1];
    dec_xs2    = disp_cmd_inst[2];
    dec_op     = dec_func7[3:0];

    case (dec_func7[6:4])
      3'd0: dec_type = TYPE_CTRL;
      3'd1: dec_type = TYPE_NOC;
      3'd2: dec_type = TYPE_TLD_TST;
      3'd3: dec_type = TYPE_TMU;
      3'd4: dec_type = TYPE_MPU;
      3'd5: dec_type = TYPE_VPU;
      default: dec_type = TYPE_CTRL;
    endcase

    dec_is_wr_lmem = (dec_op == OP_WR_LMEM);
    dec_is_rd_lmem = (dec_op == OP_RD_LMEM);
    dec_is_cfg     = (dec_op == OP_CFG_WR) || (dec_op == OP_CFG_RD);
    dec_is_pre     = (dec_op == OP_PRE_WR) || (dec_op == OP_PRE_RD);
  end

  assign buff_not_empty     = (buff_count_q != 2'd0);
  assign buff_head_type     = buff_type_q[buff_rd_ptr_q];
  assign buff_pop           = dsp_en && buff_not_empty && !master_vld_q[buff_head_type];
  assign buff_space         = (buff_count_q < 2'd2) || buff_pop;
  assign direct_master_free = !master_vld_q[dec_type];
  assign direct_free        = dsp_en && direct_master_free && !(buff_pop && (buff_head_type == dec_type));
  assign push_ready         = store_en && buff_space;
  assign default_ready      = (!dsp_en && !store_en) && buff_space;

  assign cmd_disp_rdy = direct_free || push_ready || default_ready;
  assign disp_fire    = disp_cmd_vld && cmd_disp_rdy;

  assign accept_to_direct = disp_cmd_vld && direct_free;
  assign accept_to_buff   = disp_cmd_vld && !accept_to_direct && (push_ready || default_ready);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < 6; i++) begin
        master_inst_q[i] <= 74'd0;
        master_flag_q[i] <= 1'b0;
        master_type_q[i] <= i;
        master_vld_q[i]  <= 1'b0;
      end
      for (int j = 0; j < 2; j++) begin
        buff_inst_q[j] <= 74'd0;
        buff_flag_q[j] <= 1'b0;
        buff_type_q[j] <= 3'd0;
        buff_vld_q[j]  <= 1'b0;
      end
      buff_count_q  <= 2'd0;
      buff_wr_ptr_q <= 1'b0;
      buff_rd_ptr_q <= 1'b0;
    end else begin
      if (buff_pop) begin
        master_inst_q[buff_head_type] <= buff_inst_q[buff_rd_ptr_q];
        master_flag_q[buff_head_type] <= buff_flag_q[buff_rd_ptr_q];
        master_type_q[buff_head_type] <= buff_head_type;
        master_vld_q[buff_head_type]  <= 1'b1;
        buff_vld_q[buff_rd_ptr_q]     <= 1'b0;
        buff_rd_ptr_q <= ~buff_rd_ptr_q;
      end

      if (accept_to_direct) begin
        master_inst_q[dec_type] <= disp_cmd_inst;
        master_flag_q[dec_type] <= disp_cmd_inst_flag;
        master_type_q[dec_type] <= dec_type;
        master_vld_q[dec_type]  <= 1'b1;
      end

      if (accept_to_buff) begin
        buff_inst_q[buff_wr_ptr_q] <= disp_cmd_inst;
        buff_flag_q[buff_wr_ptr_q] <= disp_cmd_inst_flag;
        buff_type_q[buff_wr_ptr_q] <= dec_type;
        buff_vld_q[buff_wr_ptr_q]  <= 1'b1;
        buff_wr_ptr_q <= ~buff_wr_ptr_q;
      end

      if (buff_pop && accept_to_buff)
        buff_count_q <= buff_count_q;
      else if (buff_pop)
        buff_count_q <= buff_count_q - 2'd1;
      else if (accept_to_buff)
        buff_count_q <= buff_count_q + 2'd1;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cfg_info_q  <= 74'd0;
      cfg_type_q  <= 3'd0;
      cfg_vld_q   <= 1'b0;
      pre_info_q  <= 74'd0;
      pre_type_q  <= 3'd0;
      pre_vld_q   <= 1'b0;
      cfg_base_q  <= 44'd0;
    end else begin
      if (disp_fire) begin
        if (dec_is_cfg) begin
          cfg_info_q <= disp_cmd_inst;
          cfg_type_q <= dec_type;
          cfg_vld_q  <= 1'b1;
          if (dec_op == OP_CFG_WR)
            cfg_base_q <= {dec_rs2val[11:0], dec_rs1val[31:0]};
        end
        if (dec_is_pre) begin
          pre_info_q <= disp_cmd_inst;
          pre_type_q <= dec_type;
          pre_vld_q  <= 1'b1;
        end
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lmem_cmd_q       <= 74'd0;
      lmem_wr_pending_q <= 1'b0;
      lmem_rd_pending_q <= 1'b0;
    end else begin
      if (disp_fire && dec_is_wr_lmem) begin
        lmem_cmd_q        <= disp_cmd_inst;
        lmem_wr_pending_q <= 1'b1;
      end else if (lmem_wr_pending_q && cmd_xbr_ch0_req_wrdy) begin
        lmem_wr_pending_q <= 1'b0;
      end

      if (disp_fire && dec_is_rd_lmem) begin
        lmem_cmd_q        <= disp_cmd_inst;
        lmem_rd_pending_q <= 1'b1;
      end else if (lmem_rd_pending_q && xbr_cmd_ch1_req_rrdy) begin
        lmem_rd_pending_q <= 1'b0;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_wait_rsp_q <= 1'b0;
      rd_wait_rsp_q <= 1'b0;
      rd_data_q     <= 512'd0;
    end else begin
      if (lmem_wr_pending_q && cmd_xbr_ch0_req_wrdy)
        wr_wait_rsp_q <= 1'b1;
      else if (xbr_cmd_ch0_rsp_wvld && cmd_xbr_ch0_rsp_wrdy && xbr_cmd_ch0_rsp_wlast)
        wr_wait_rsp_q <= 1'b0;

      if (lmem_rd_pending_q && xbr_cmd_ch1_req_rrdy)
        rd_wait_rsp_q <= 1'b1;
      else if (xbr_cmd_ch1_rsp_rvld && cmd_xbr_ch1_rsp_rrdy)
        rd_wait_rsp_q <= 1'b0;

      if (xbr_cmd_ch1_rsp_rvld && cmd_xbr_ch1_rsp_rrdy)
        rd_data_q <= xbr_cmd_ch1_rsp_rdata;
    end
  end

  assign cmd_xbr_ch0_req_waddr = cfg_base_q[17:0] + lmem_cmd_q[27:10];
  assign cmd_xbr_ch0_req_wdata = {lmem_cmd_q[73:42], lmem_cmd_q[41:10], 448'd0};
  assign cmd_xbr_ch0_req_wstrb = 2'b11;
  assign cmd_xbr_ch0_req_wvld  = lmem_wr_pending_q;
  assign cmd_xbr_ch0_rsp_wrdy  = wr_wait_rsp_q;

  assign cmd_xbr_ch1_req_raddr = cfg_base_q + {26'd0, lmem_cmd_q[27:10]};
  assign cmd_xbr_ch1_req_rvld  = lmem_rd_pending_q;
  assign cmd_xbr_ch1_rsp_rrdy  = rd_wait_rsp_q;

  assign cfg_drv_buffer_not_full = (buff_count_q != 2'd2);
  assign ins_inst_info           = (buff_count_q != 2'd0);

endmodule