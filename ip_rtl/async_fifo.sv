module async_fifo (
    input  logic       pclk,
    input  logic       preset_n,
    input  logic       wr_clk,
    input  logic       rd_clk,
    input  logic       wr_en,
    input  logic       rd_en,
    input  logic [7:0] wr_data,
    output logic [7:0] rd_data,
    output logic       full,
    output logic       empty
);

    localparam int ADDR_WIDTH = 4;
    localparam int DEPTH      = (1 << ADDR_WIDTH);

    logic [7:0] mem [0:DEPTH-1];

    logic [ADDR_WIDTH:0] wbin, wbin_next;
    logic [ADDR_WIDTH:0] wgray, wgray_next;
    logic [ADDR_WIDTH:0] rbin, rbin_next;
    logic [ADDR_WIDTH:0] rgray, rgray_next;

    logic [ADDR_WIDTH:0] rq1_wgray, rq2_wgray;
    logic [ADDR_WIDTH:0] wq1_rgray, wq2_rgray;

    logic full_val, empty_val;

    function automatic logic [ADDR_WIDTH:0] bin2gray(input logic [ADDR_WIDTH:0] b);
        return (b >> 1) ^ b;
    endfunction

    assign wbin_next  = wbin + (wr_en && !full);
    assign wgray_next = bin2gray(wbin_next);
    assign full_val   = (wgray_next == {~wq2_rgray[ADDR_WIDTH:ADDR_WIDTH-1], wq2_rgray[ADDR_WIDTH-2:0]});

    assign rbin_next  = rbin + (rd_en && !empty);
    assign rgray_next = bin2gray(rbin_next);
    assign empty_val  = (rgray_next == rq2_wgray);

    always_ff @(posedge wr_clk or negedge preset_n) begin
        if (!preset_n) begin
            wbin  <= '0;
            wgray <= '0;
            full  <= 1'b0;
        end else begin
            wbin  <= wbin_next;
            wgray <= wgray_next;
            full  <= full_val;
            if (wr_en && !full) begin
                mem[wbin[ADDR_WIDTH-1:0]] <= wr_data;
            end
        end
    end

    always_ff @(posedge rd_clk or negedge preset_n) begin
        if (!preset_n) begin
            rbin    <= '0;
            rgray   <= '0;
            empty   <= 1'b1;
            rd_data <= '0;
        end else begin
            rbin  <= rbin_next;
            rgray <= rgray_next;
            empty <= empty_val;
            if (rd_en && !empty) begin
                rd_data <= mem[rbin[ADDR_WIDTH-1:0]];
            end
        end
    end

    always_ff @(posedge rd_clk or negedge preset_n) begin
        if (!preset_n) begin
            rq1_wgray <= '0;
            rq2_wgray <= '0;
        end else begin
            rq1_wgray <= wgray;
            rq2_wgray <= rq1_wgray;
        end
    end

    always_ff @(posedge wr_clk or negedge preset_n) begin
        if (!preset_n) begin
            wq1_rgray <= '0;
            wq2_rgray <= '0;
        end else begin
            wq1_rgray <= rgray;
            wq2_rgray <= wq1_rgray;
        end
    end

endmodule