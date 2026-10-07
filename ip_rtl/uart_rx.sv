module uart_rx (
    input  logic        pclk,
    input  logic        preset_n,
    input  logic        clk,
    input  logic        rst_n,
    input  logic        rx,
    output logic [7:0]  data,
    output logic        valid,
    input  logic [15:0] baud_div,
    output logic        frame_err
);

    localparam logic [1:0] IDLE  = 2'd0;
    localparam logic [1:0] START = 2'd1;
    localparam logic [1:0] DATA  = 2'd2;
    localparam logic [1:0] STOP  = 2'd3;

    logic [1:0]  state;
    logic [15:0] counter;
    logic [2:0]  bit_idx;
    logic        rx_sync1;
    logic        rx_sync2;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_sync1 <= 1'b1;
            rx_sync2 <= 1'b1;
        end else begin
            rx_sync1 <= rx;
            rx_sync2 <= rx_sync1;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= IDLE;
            counter   <= 16'd0;
            bit_idx   <= 3'd0;
            data      <= 8'd0;
            valid     <= 1'b0;
            frame_err <= 1'b0;
        end else begin
            valid     <= 1'b0;
            frame_err <= 1'b0;

            case (state)
                IDLE: begin
                    counter <= 16'd0;
                    bit_idx <= 3'd0;
                    if (!rx_sync2) begin
                        state   <= START;
                        counter <= (baud_div >> 1) - 1'b1;
                    end
                end

                START: begin
                    if (counter == 16'd0) begin
                        if (!rx_sync2) begin
                            state   <= DATA;
                            counter <= baud_div - 1'b1;
                            bit_idx <= 3'd0;
                        end else begin
                            state <= IDLE;
                        end
                    end else begin
                        counter <= counter - 1'b1;
                    end
                end

                DATA: begin
                    if (counter == 16'd0) begin
                        data[bit_idx] <= rx_sync2;
                        if (bit_idx == 3'd7) begin
                            state   <= STOP;
                            counter <= baud_div - 1'b1;
                        end else begin
                            bit_idx <= bit_idx + 1'b1;
                            counter <= baud_div - 1'b1;
                        end
                    end else begin
                        counter <= counter - 1'b1;
                    end
                end

                STOP: begin
                    if (counter == 16'd0) begin
                        frame_err <= ~rx_sync2;
                        valid     <= 1'b1;
                        state     <= IDLE;
                        counter   <= 16'd0;
                    end else begin
                        counter <= counter - 1'b1;
                    end
                end

                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end

endmodule