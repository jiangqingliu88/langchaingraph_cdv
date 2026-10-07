module interrupt_controller (
    input  logic        pclk,
    input  logic        preset_n,
    input  logic        clk,
    input  logic        rst_n,
    input  logic [31:0] irq_in,
    input  logic [31:0] irq_en,
    output logic        irq_out,
    output logic [4:0]  irq_id
);

    logic [31:0] irq_masked;
    logic        next_irq_out;
    logic [4:0]  next_irq_id;

    assign irq_masked = irq_in & irq_en;

    always_comb begin
        next_irq_out = 1'b0;
        next_irq_id  = 5'd0;
        for (int i = 0; i < 32; i++) begin
            if (irq_masked[i] && !next_irq_out) begin
                next_irq_id  = i[4:0];
                next_irq_out = 1'b1;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            irq_out <= 1'b0;
            irq_id  <= 5'd0;
        end else begin
            irq_out <= next_irq_out;
            irq_id  <= next_irq_id;
        end
    end

endmodule