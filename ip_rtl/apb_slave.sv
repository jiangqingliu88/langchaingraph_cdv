module apb_slave (
    input  logic        pclk,
    input  logic        preset_n,
    input  logic [7:0]  paddr,
    input  logic [7:0]  pwdata,
    output logic [7:0]  prdata,
    input  logic        pwrite,
    input  logic        psel,
    input  logic        penable,
    output logic        pready,
    output logic        pslverr
);

    logic [7:0] r0;
    logic [7:0] r1;
    logic [7:0] r2;
    logic [7:0] r3;
    logic       addr_valid;
    logic [7:0] reg_read_data;

    always_ff @(posedge pclk or negedge preset_n) begin
        if (!preset_n) begin
            r0 <= 8'h00;
            r1 <= 8'h00;
            r2 <= 8'h00;
            r3 <= 8'h00;
        end else begin
            if (psel && penable && pwrite && addr_valid) begin
                case (paddr[1:0])
                    2'd0: r0 <= pwdata;
                    2'd1: r1 <= pwdata;
                    2'd2: r2 <= pwdata;
                    2'd3: r3 <= pwdata;
                    default: ;
                endcase
            end
        end
    end

    always_comb begin
        addr_valid = (paddr[7:2] == 6'h00);

        if (addr_valid) begin
            case (paddr[1:0])
                2'd0:    reg_read_data = r0;
                2'd1:    reg_read_data = r1;
                2'd2:    reg_read_data = r2;
                2'd3:    reg_read_data = r3;
                default: reg_read_data = 8'h00;
            endcase
        end else begin
            reg_read_data = 8'h00;
        end
    end

    assign prdata  = (psel && !pwrite) ? reg_read_data : 8'h00;
    assign pready  = 1'b1;
    assign pslverr = psel && penable && !addr_valid;

endmodule