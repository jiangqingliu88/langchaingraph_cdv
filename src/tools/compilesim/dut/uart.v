// ============================================================
// UART Controller v2.1 — Simplified RTL DUT
// ============================================================
module uart_top (
    input  wire        pclk,       // APB clock 50MHz
    input  wire        presetn,    // async reset (active low)
    // AXI4-Lite
    input  wire [31:0] s_axi_awaddr,
    input  wire        s_axi_awvalid,
    output wire        s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire        s_axi_wvalid,
    output wire        s_axi_wready,
    output wire        s_axi_bvalid,
    input  wire        s_axi_bready,
    input  wire [31:0] s_axi_araddr,
    input  wire        s_axi_arvalid,
    output wire        s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire        s_axi_rvalid,
    input  wire        s_axi_rready,
    // UART
    output wire        tx,
    input  wire        rx,
    output wire        interrupt
);

    // ── Register map ──
    localparam ADDR_BAUD_RATE = 5'h00;
    localparam ADDR_CTRL      = 5'h04;
    localparam ADDR_STATUS    = 5'h08;
    localparam ADDR_TX_DATA   = 5'h0C;
    localparam ADDR_RX_DATA   = 5'h10;

    reg [15:0] baud_rate_reg;
    reg [7:0]  ctrl_reg;
    reg [7:0]  status_reg;
    reg [7:0]  tx_data_reg;
    reg [7:0]  rx_data_reg;

    // AXI read register
    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            baud_rate_reg <= 16'd0;
            ctrl_reg      <= 8'd0;
            status_reg    <= 8'd0;
            tx_data_reg   <= 8'd0;
            rx_data_reg   <= 8'd0;
        end else begin
            if (s_axi_awvalid && s_axi_awready && s_axi_wvalid && s_axi_wready) begin
                case (s_axi_awaddr[4:0])
                    ADDR_BAUD_RATE: baud_rate_reg <= s_axi_wdata[15:0];
                    ADDR_CTRL:      ctrl_reg      <= s_axi_wdata[7:0];
                    ADDR_TX_DATA:   tx_data_reg   <= s_axi_wdata[7:0];
                    default: ;
                endcase
            end
            if (s_axi_arvalid && s_axi_arready) begin
                rx_data_reg <= rx_data_reg; // hold
            end
        end
    end

    // ── AXI write channel (simple) ──
    reg aw_phase, w_phase;
    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            aw_phase <= 0; w_phase <= 0;
        end else begin
            if (s_axi_awvalid && s_axi_awready) aw_phase <= 1;
            if (s_axi_wvalid  && s_axi_wready)  w_phase  <= 1;
            if (aw_phase && w_phase) begin
                aw_phase <= 0; w_phase <= 0;
            end
        end
    end
    assign s_axi_awready = !aw_phase;
    assign s_axi_wready  = !w_phase;
    assign s_axi_bvalid  = aw_phase && w_phase;

    // ── AXI read channel (simple) ──
    reg ar_phase;
    always @(posedge pclk or negedge presetn) begin
        if (!presetn) ar_phase <= 0;
        else if (s_axi_arvalid && s_axi_arready) ar_phase <= 1;
        else if (s_axi_rvalid && s_axi_rready)   ar_phase <= 0;
    end
    assign s_axi_arready = !ar_phase;
    assign s_axi_rvalid  = ar_phase;
    assign s_axi_rdata   = (s_axi_araddr[4:0] == ADDR_RX_DATA) ? {24'd0, rx_data_reg}
                         : (s_axi_araddr[4:0] == ADDR_STATUS)   ? {24'd0, status_reg}
                         : 32'd0;

    // ── TX shifter ──
    reg [3:0] tx_bit_cnt;
    reg [9:0] tx_shift_reg; // start(0) + data[7:0] + stop(1)
    reg       tx_busy;

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            tx_bit_cnt   <= 0;
            tx_shift_reg <= 10'd0;
            tx_busy      <= 0;
            status_reg[0]<= 1; // TX_EMPTY
        end else begin
            if (ctrl_reg[0] && !tx_busy && !status_reg[0]) begin // TX_EN && TX_DATA written
                tx_shift_reg <= {1'b1, tx_data_reg, 1'b0}; // stop, data, start
                tx_bit_cnt   <= 10;
                tx_busy      <= 1;
                status_reg[0]<= 0;
            end
            if (tx_busy) begin
                tx_shift_reg <= tx_shift_reg >> 1;
                tx_bit_cnt   <= tx_bit_cnt - 1;
                if (tx_bit_cnt == 1) begin
                    tx_busy      <= 0;
                    status_reg[0]<= 1;
                end
            end
        end
    end
    assign tx = tx_busy ? tx_shift_reg[0] : 1'b1;

    // ── RX sampler ──
    reg [1:0] rx_sync;
    reg       rx_prev;
    reg [3:0] rx_bit_cnt;
    reg [7:0] rx_shift_reg;
    reg       rx_busy;
    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            rx_sync      <= 2'b11;
            rx_prev      <= 1;
            rx_bit_cnt   <= 0;
            rx_shift_reg <= 0;
            rx_busy      <= 0;
            status_reg[1]<= 0; // RX_FULL
        end else begin
            rx_sync <= {rx_sync[0], rx};
            rx_prev <= rx_sync[1];
            // start bit detect
            if (!rx_busy && rx_prev && !rx_sync[1] && ctrl_reg[1]) begin
                rx_busy    <= 1;
                rx_bit_cnt <= 8;
            end
            if (rx_busy) begin
                rx_shift_reg <= {rx_sync[1], rx_shift_reg[7:1]};
                rx_bit_cnt   <= rx_bit_cnt - 1;
                if (rx_bit_cnt == 1) begin
                    rx_busy      <= 0;
                    rx_data_reg  <= {rx_sync[1], rx_shift_reg[7:1]};
                    status_reg[1]<= 1;
                end
            end
        end
    end

    // ── Interrupt ──
    assign interrupt = status_reg[0]  // TX empty
                     | status_reg[1]; // RX full

endmodule
