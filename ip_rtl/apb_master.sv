module apb_master (
  input  logic       pclk,
  input  logic       preset_n,
  output logic [7:0] paddr,
  output logic [7:0] pwdata,
  output logic       pwrite,
  output logic       psel,
  output logic       penable,
  input  logic [7:0] prdata
);

  typedef enum logic [1:0] {IDLE, SETUP, ACCESS} state_t;
  state_t state, next_state;

  logic [7:0] addr_reg;
  logic [7:0] data_reg;
  logic       write_reg;
  logic [7:0] rdata_reg;

  always_ff @(posedge pclk or negedge preset_n) begin
    if (!preset_n) begin
      state     <= IDLE;
      addr_reg  <= 8'h00;
      data_reg  <= 8'h00;
      write_reg <= 1'b1;
      rdata_reg <= 8'h00;
    end else begin
      state <= next_state;
      if (state == ACCESS) begin
        if (write_reg) begin
          data_reg  <= data_reg + 1'b1;
          write_reg <= 1'b0;
        end else begin
          rdata_reg <= prdata;
          addr_reg  <= addr_reg + 1'b1;
          write_reg <= 1'b1;
        end
      end
    end
  end

  always_comb begin
    next_state = state;
    case (state)
      IDLE:   next_state = SETUP;
      SETUP:  next_state = ACCESS;
      ACCESS: next_state = IDLE;
      default: next_state = IDLE;
    endcase
  end

  always_comb begin
    psel    = 1'b0;
    penable = 1'b0;
    paddr   = addr_reg;
    pwdata  = data_reg;
    pwrite  = write_reg;
    case (state)
      IDLE: begin
        psel    = 1'b0;
        penable = 1'b0;
      end
      SETUP: begin
        psel    = 1'b1;
        penable = 1'b0;
      end
      ACCESS: begin
        psel    = 1'b1;
        penable = 1'b1;
      end
      default: begin
        psel    = 1'b0;
        penable = 1'b0;
      end
    endcase
  end

endmodule