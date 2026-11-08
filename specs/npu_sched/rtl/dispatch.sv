module dispatch (
    input  wire        clk,
    input  wire        rst_n,
    inout  wire        dsp_en,
    inout  wire        ins_inst_info,
    output logic       cmd_niu_start,
    output logic       cmd_niu_start_inst_id,
    output logic [1:0] cmd_niu_task_select,
    output logic [43:0] cmd_niu_dst_base_addr,
    output logic [43:0] cmd_niu_src_base_addr,
    output logic       cmd_glsu_start,
    output logic       cmd_glsu_start_inst_id,
    output logic [3:0] cmd_glsu_task_select,
    output logic [43:0] cmd_glsu_src_base_addr,
    output logic [43:0] cmd_glsu_dst_base_addr,
    output logic       cmd_llsu_start,
    output logic       cmd_llsu_start_inst_id,
    output logic [2:0] cmd_llsu_task_select,
    output logic [17:0] cmd_llsu_base_addr_in,
    output logic [17:0] cmd_llsu_base_addr_out,
    output logic       cmd_vpu_start,
    output logic       cmd_vpu_start_inst_id,
    output logic [2:0] cmd_vpu_funct_sel,
    output logic [5:0] cmd_vpu_cfg_op,
    output logic       cmd_mpu_start,
    output logic       cmd_mpu_start_inst_id,
    output logic       cmd_xbr_ch0_req_wvld,
    output logic       cmd_xbr_ch1_req_rvld,
    output logic [1:0] cmd_llsu_xbr_sel_vld
);

    localparam [2:0] T_NIU   = 3'd0;
    localparam [2:0] T_GLSU  = 3'd1;
    localparam [2:0] T_LLSU  = 3'd2;
    localparam [2:0] T_MPU   = 3'd3;
    localparam [2:0] T_VPU   = 3'd4;
    localparam [2:0] T_XBR_W = 3'd5;
    localparam [2:0] T_XBR_R = 3'd6;

    logic [2:0]  target_sel;
    logic [1:0]  fence_cnt;
    logic        inst_id_r;
    logic [43:0] base_addr_r;
    logic [43:0] dst_addr_r;
    logic [17:0] llsu_addr_r;
    logic [3:0]  opcode_r;

    wire fence_req    = dsp_en && ins_inst_info;
    wire fence_active = (fence_cnt != 2'd0) || fence_req;
    wire fire         = dsp_en && !ins_inst_info && !fence_active;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            target_sel              <= 3'd0;
            fence_cnt               <= 2'd0;
            inst_id_r               <= 1'b0;
            base_addr_r             <= 44'd0;
            dst_addr_r              <= 44'd0;
            llsu_addr_r             <= 18'd0;
            opcode_r                <= 4'd0;

            cmd_niu_start           <= 1'b0;
            cmd_niu_start_inst_id   <= 1'b0;
            cmd_niu_task_select     <= 2'd0;
            cmd_niu_dst_base_addr   <= 44'd0;
            cmd_niu_src_base_addr   <= 44'd0;

            cmd_glsu_start          <= 1'b0;
            cmd_glsu_start_inst_id  <= 1'b0;
            cmd_glsu_task_select    <= 4'd0;
            cmd_glsu_src_base_addr  <= 44'd0;
            cmd_glsu_dst_base_addr  <= 44'd0;

            cmd_llsu_start          <= 1'b0;
            cmd_llsu_start_inst_id  <= 1'b0;
            cmd_llsu_task_select    <= 3'd0;
            cmd_llsu_base_addr_in   <= 18'd0;
            cmd_llsu_base_addr_out  <= 18'd0;

            cmd_vpu_start           <= 1'b0;
            cmd_vpu_start_inst_id   <= 1'b0;
            cmd_vpu_funct_sel       <= 3'd0;
            cmd_vpu_cfg_op          <= 6'd0;

            cmd_mpu_start           <= 1'b0;
            cmd_mpu_start_inst_id   <= 1'b0;

            cmd_xbr_ch0_req_wvld    <= 1'b0;
            cmd_xbr_ch1_req_rvld    <= 1'b0;
            cmd_llsu_xbr_sel_vld    <= 2'b00;
        end else begin
            cmd_niu_start           <= 1'b0;
            cmd_glsu_start          <= 1'b0;
            cmd_llsu_start          <= 1'b0;
            cmd_vpu_start           <= 1'b0;
            cmd_mpu_start           <= 1'b0;
            cmd_xbr_ch0_req_wvld    <= 1'b0;
            cmd_xbr_ch1_req_rvld    <= 1'b0;
            cmd_llsu_xbr_sel_vld    <= 2'b00;

            cmd_niu_start_inst_id   <= inst_id_r;
            cmd_glsu_start_inst_id  <= inst_id_r;
            cmd_llsu_start_inst_id  <= inst_id_r;
            cmd_vpu_start_inst_id   <= inst_id_r;
            cmd_mpu_start_inst_id   <= inst_id_r;

            cmd_niu_task_select     <= {1'b0, inst_id_r};
            cmd_niu_dst_base_addr   <= dst_addr_r;
            cmd_niu_src_base_addr   <= base_addr_r;

            cmd_glsu_task_select    <= 4'd1 + {3'b0, inst_id_r};
            cmd_glsu_src_base_addr  <= base_addr_r;
            cmd_glsu_dst_base_addr  <= dst_addr_r;

            cmd_llsu_task_select    <= 3'd1 + {2'b0, inst_id_r};
            cmd_llsu_base_addr_in   <= llsu_addr_r;
            cmd_llsu_base_addr_out  <= llsu_addr_r + 18'h100;

            cmd_vpu_funct_sel       <= {2'b0, inst_id_r};
            cmd_vpu_cfg_op          <= {5'b0, inst_id_r};

            if (fence_req) begin
                fence_cnt <= 2'd3;
            end else if (fence_cnt != 2'd0) begin
                fence_cnt <= fence_cnt - 2'd1;
            end

            if (fire) begin
                case (target_sel)
                    T_NIU: begin
                        cmd_niu_start <= 1'b1;
                    end
                    T_GLSU: begin
                        cmd_glsu_start <= 1'b1;
                    end
                    T_LLSU: begin
                        cmd_llsu_start <= 1'b1;
                        cmd_llsu_xbr_sel_vld <= opcode_r[0] ? 2'b10 : 2'b01;
                    end
                    T_MPU: begin
                        cmd_mpu_start <= 1'b1;
                    end
                    T_VPU: begin
                        cmd_vpu_start <= 1'b1;
                    end
                    T_XBR_W: begin
                        cmd_xbr_ch0_req_wvld <= 1'b1;
                    end
                    T_XBR_R: begin
                        cmd_xbr_ch1_req_rvld <= 1'b1;
                    end
                    default: begin
                    end
                endcase

                target_sel <= (target_sel == T_XBR_R) ? T_NIU : (target_sel + 3'd1);
                inst_id_r  <= ~inst_id_r;
                base_addr_r <= base_addr_r + 44'h40;
                dst_addr_r  <= dst_addr_r + 44'h80;
                llsu_addr_r <= llsu_addr_r + 18'h20;
                opcode_r    <= opcode_r + 4'd1;
            end
        end
    end

endmodule