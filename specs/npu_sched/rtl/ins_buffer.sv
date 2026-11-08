`timescale 1ns/1ps

module ins_buffer #(
  parameter int DEPTH  = 4,
  parameter int ID_W   = 2,
  parameter int INFO_W = 1,
  parameter int DSP_W  = 1
)(
  input  logic               clk,
  input  logic               rst_n,
  inout  wire                store_en,
  inout  wire                scoreboard_ren,
  inout  wire [ID_W-1:0]     ren_id,
  inout  wire [DEPTH-1:0]    ins_buff_xx_vld,
  inout  wire                cfg_drv_buffer_not_full,
  inout  wire [INFO_W-1:0]   ins_inst_info,
  inout  wire [DSP_W-1:0]    dsp_en
);

  localparam int PTR_W = ID_W;

  logic [DEPTH-1:0]    vld_q;
  logic [INFO_W-1:0]   info_mem [0:DEPTH-1];
  logic [DSP_W-1:0]    dsp_mem  [0:DEPTH-1];
  logic [PTR_W-1:0]    wr_ptr_q;

  wire read_hit;
  wire wr_slot_free;
  wire can_accept;
  wire store_fire;

  assign read_hit     = scoreboard_ren && vld_q[ren_id];
  assign wr_slot_free = ~vld_q[wr_ptr_q];
  assign can_accept   = wr_slot_free || (scoreboard_ren && (ren_id == wr_ptr_q));
  assign store_fire   = store_en && can_accept;

  assign ins_buff_xx_vld        = vld_q;
  assign cfg_drv_buffer_not_full = can_accept;

  assign ins_inst_info = (scoreboard_ren && !store_en && vld_q[ren_id])
                         ? info_mem[ren_id]
                         : {INFO_W{1'bz}};

  assign dsp_en = (scoreboard_ren && !store_en && vld_q[ren_id])
                  ? dsp_mem[ren_id]
                  : {DSP_W{1'bz}};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      vld_q    <= '0;
      wr_ptr_q <= '0;
      for (int i = 0; i < DEPTH; i++) begin
        info_mem[i] <= '0;
        dsp_mem[i]  <= '0;
      end
    end else begin
      if (read_hit) begin
        vld_q[ren_id] <= 1'b0;
      end

      if (store_fire) begin
        info_mem[wr_ptr_q] <= ins_inst_info;
        dsp_mem[wr_ptr_q]  <= dsp_en;
        vld_q[wr_ptr_q]    <= 1'b1;
        wr_ptr_q           <= wr_ptr_q + 1'b1;
      end
    end
  end

endmodule