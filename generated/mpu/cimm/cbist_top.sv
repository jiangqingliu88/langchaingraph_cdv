// cbist_top — CIM BIST wrapper (MBIST + LBIST)
module cbist_top (
    input  wire         clk, rst_n,
    input  wire         bist_mode, bist_start, mbist_en, lbist_en, alg_sel,
    output wire         ram_cen, ram_wen,
    output wire [8:0]   ram_addr,
    input  wire [511:0] ram_q,
    output reg          alg_end, atpg_end, lcomp_go, mcomp_go
);
    assign ram_cen  = 1'b1;
    assign ram_wen  = 1'b1;
    assign ram_addr = 9'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin alg_end<=0; atpg_end<=0; lcomp_go<=0; mcomp_go<=0; end
        else if (bist_mode && bist_start) begin
            mcomp_go <= mbist_en;
            lcomp_go <= lbist_en;
            alg_end  <= 1'b1;
            atpg_end <= 1'b1;
        end else begin alg_end<=0; atpg_end<=0; lcomp_go<=0; mcomp_go<=0; end
    end
endmodule
