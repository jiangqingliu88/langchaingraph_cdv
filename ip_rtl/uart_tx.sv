module uart_tx (
  input  logic        clk,
  input  logic        rst_n,
  output logic        tx,
  input  logic [7:0]  data,
  input  logic        valid,
  output logic        ready,
  input  logic [15:0] baud_div
);

  typedef enum logic [1:0] {
    IDLE  = 2'b00,
    START = 2'b01,
    DATA  = 2'b10,
    STOP  = 2'b11
  } state_t;

  state_t      state;
  logic [15:0] baud_cnt;
  logic [2:0]  bit_idx;
  logic [7:0]  shift_reg;

  assign ready = (state == IDLE);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state     <= IDLE;
      baud_cnt  <= 16'd0;
      bit_idx   <= 3'd0;
      shift_reg <= 8'd0;
      tx        <= 1'b1;
    end else begin
      case (state)
        IDLE: begin
          tx       <= 1'b1;
          baud_cnt <= 16'd0;
          bit_idx  <= 3'd0;
          if (valid) begin
            shift_reg <= data;
            state     <= START;
          end
        end

        START: begin
          tx <= 1'b0;
          if (baud_cnt == baud_div - 16'd1) begin
            baud_cnt <= 16'd0;
            state    <= DATA;
          end else begin
            baud_cnt <= baud_cnt + 16'd1;
          end
        end

        DATA: begin
          tx <= shift_reg[0];
          if (baud_cnt == baud_div - 16'd1) begin
            baud_cnt  <= 16'd0;
            shift_reg <= {1'b0, shift_reg[7:1]};
            if (bit_idx == 3'd7) begin
              state <= STOP;
            end else begin
              bit_idx <= bit_idx + 3'd1;
            end
          end else begin
            baud_cnt <= baud_cnt + 16'd1;
          end
        end

        STOP: begin
          tx <= 1'b1;
          if (baud_cnt == baud_div - 16'd1) begin
            baud_cnt <= 16'd0;
            state    <= IDLE;
          end else begin
            baud_cnt <= baud_cnt + 16'd1;
          end
        end

        default: begin
          state <= IDLE;
        end
      endcase
    end
  end

endmodule