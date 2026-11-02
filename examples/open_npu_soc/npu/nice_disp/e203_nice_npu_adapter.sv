// E203 NICE → Open NPU 适配器（M1）
//
// 替换 E203 自带示例 `e203_subsys_nice_core`，端口逐一对齐
// `e203_cpu.v` 里的 NICE 实例化。CPU 通过 custom3 指令提交 GEMM 命令：
//
//   START : .insn r 0x7b, 2, 1, rd, desc_addr, x0
//           desc = {a_addr, b_addr, c_addr, M, N, K}（6 x 32bit）
//   STATUS: .insn r 0x7b, 4, 1, rd, x0, x0   -> bit0=done, bit1=irq
//   ACK   : .insn r 0x7b, 0, 1, rd, x0, x0   -> 清 irq
//
// **func3 不是随便选的**：E203 的 NICE 解码把 `instr[13]` 当 rs1en、
// `instr[14]` 当 rdwen（`e203_exu_decode.v: nice_need_rs1/rd`）。func3 的
// bit1/bit2 就是这两位：
//   - START 要读 rs1（desc 地址） -> func3=010（bit13=1）
//   - STATUS 要写 rd（状态值）    -> func3=100（bit14=1）
//   - ACK 两个都不用              -> func3=000
// 不按这个编码，IFU 不会更新 rs1idx（会沿用上一条指令的索引，实测把
// desc 地址采成 DTCM 基址），STATUS 也不会写回 rd。
//
// 数据搬运走 NICE 的 ICB 主口（E203 DTCM），所以 CPU 看到的是普通内存：
//   A/B 各 64B（8x8 INT8，按 4 字节打包），C 64x32bit。
// 这是**阻塞式**命令（CPU 轮询 STATUS）；把 irq 接到 E203 PLIC 是下一步。
`include "e203_defines.v"

module e203_nice_npu_adapter (
    input  logic                         nice_clk,
    input  logic                         nice_rst_n,
    output logic                         nice_active,
    output logic                         nice_mem_holdup,

    input  logic                         nice_req_valid,
    output logic                         nice_req_ready,
    input  logic [`E203_XLEN-1:0]        nice_req_inst,
    input  logic [`E203_XLEN-1:0]        nice_req_rs1,
    input  logic [`E203_XLEN-1:0]        nice_req_rs2,

    output logic                         nice_rsp_valid,
    input  logic                         nice_rsp_ready,
    output logic [`E203_XLEN-1:0]        nice_rsp_rdat,
    output logic                         nice_rsp_err,

    output logic                         nice_icb_cmd_valid,
    input  logic                         nice_icb_cmd_ready,
    output logic [`E203_ADDR_SIZE-1:0]   nice_icb_cmd_addr,
    output logic                         nice_icb_cmd_read,
    output logic [`E203_XLEN-1:0]        nice_icb_cmd_wdata,
    output logic [1:0]                   nice_icb_cmd_size,

    input  logic                         nice_icb_rsp_valid,
    output logic                         nice_icb_rsp_ready,
    input  logic [`E203_XLEN-1:0]        nice_icb_rsp_rdata,
    input  logic                         nice_icb_rsp_err
);

    localparam int M = 8, N = 8, K = 8;
    localparam logic [6:0] OPCODE_CUSTOM3 = 7'b1111011;
    localparam logic [6:0] FUNC7_CMD     = 7'b0000001;

    wire [6:0] opcode = nice_req_inst[6:0];
    wire [2:0] func3  = nice_req_inst[14:12];
    wire [6:0] func7  = nice_req_inst[31:25];
    wire is_custom = (opcode == OPCODE_CUSTOM3) && (func7 == FUNC7_CMD);
    // func3 的 bit1/bit2 同时是 E203 的 rs1en/rdwen 控制位，见文件头。
    wire is_start  = is_custom && (func3 == 3'b010);
    wire is_status = is_custom && (func3 == 3'b100);
    wire is_ack    = is_custom && (func3 == 3'b000);

    typedef enum logic [3:0] {
        IDLE, RD_DESC, RD_A, RD_B, GEMM_WAIT, WR_C, DONE
    } state_t;

    state_t state, next_state;
    logic [2:0]  req_func3;
    logic [`E203_XLEN-1:0] desc_addr;
    logic [`E203_XLEN-1:0] desc [0:5];
    logic [`E203_XLEN-1:0] a_words [0:15];
    logic [`E203_XLEN-1:0] b_words [0:15];
    logic [`E203_XLEN-1:0] c_words [0:63];

    logic signed [7:0]  a_buf [0:M-1][0:K-1];
    logic signed [7:0]  b_buf [0:K-1][0:N-1];
    logic signed [31:0] c_buf [0:M-1][0:N-1];

    logic        gemm_start, gemm_done;
    logic        done, irq, busy, err;
    logic        rsp_pending;
    logic [`E203_XLEN-1:0] rsp_data;

    logic        mem_cmd_sent;
    logic [5:0]  mem_count;
    logic [`E203_XLEN-1:0] mem_addr;

    // ── 请求握手 / 响应 ──
    // **响应未取走前不再接收下一条请求**：与 Nuclei 参考 core 的
    // `nice_req_ready = state_is_idle & ...` 同一握手纪律；否则 CPU 可能
    // 看不到已经挂起的 status response，表现为无限轮询。
    assign nice_req_ready = !rsp_pending && ((state == IDLE) || is_status || is_ack);
    // STATUS / ACK 是单拍操作：请求同拍回 rsp，避免 CPU 在
    // “发出请求 → 等响应”之间看不到一拍 pending 而反复轮询。
    assign nice_rsp_valid = rsp_pending || is_status;
    assign nice_rsp_rdat  = is_status ? {30'b0, irq, done} : rsp_data;
    assign nice_rsp_err   = err;
    assign nice_active    = busy || nice_req_valid;
    assign nice_mem_holdup = 1'b0;
    assign nice_icb_rsp_ready = 1'b1;
    assign nice_icb_cmd_size = 2'b10;   // word

    always_ff @(posedge nice_clk or negedge nice_rst_n) begin
        if (!nice_rst_n) begin
            rsp_pending <= 1'b0;
            rsp_data    <= '0;
            err         <= 1'b0;
            done        <= 1'b0;
            irq         <= 1'b0;
            busy        <= 1'b0;
            req_func3   <= '0;
            desc_addr   <= '0;
        end else begin
            if (rsp_pending && nice_rsp_ready) rsp_pending <= 1'b0;

            if (nice_req_valid && nice_req_ready) begin
                rsp_pending <= 1'b1;
                err         <= 1'b0;
                req_func3   <= func3;
                if (is_start) begin
                    desc_addr <= nice_req_rs1;
                    done      <= 1'b0;
                    irq       <= 1'b0;
                    busy      <= 1'b1;
                    rsp_data  <= '0;
                end else if (is_status) begin
                    rsp_data <= {30'b0, irq, done};
                end else if (is_ack) begin
                    irq      <= 1'b0;
                    rsp_data <= 32'b0;
                end else begin
                    err      <= 1'b1;
                    rsp_data <= '0;
                end
            end
        end
    end

    // ── 内存 FSM：读 desc/A/B，跑 GEMM，写 C ──
    always_ff @(posedge nice_clk or negedge nice_rst_n) begin
        if (!nice_rst_n) begin
            state         <= IDLE;
            mem_cmd_sent  <= 1'b0;
            mem_count     <= '0;
            mem_addr      <= '0;
            gemm_start    <= 1'b0;
            c_words       <= '{default: '0};
        end else begin
            gemm_start <= 1'b0;

            case (state)
                IDLE: begin
                    if (nice_req_valid && nice_req_ready && is_start) begin
                        mem_addr     <= nice_req_rs1;
                        mem_count    <= '0;
                        mem_cmd_sent <= 1'b0;
                        state        <= RD_DESC;
                    end
                end

                RD_DESC: begin
                    if (!mem_cmd_sent) begin
                        if (nice_icb_cmd_ready) begin
                            mem_cmd_sent <= 1'b1;
                        end
                    end else if (nice_icb_rsp_valid) begin
                        desc[mem_count] <= nice_icb_rsp_rdata;
                        mem_cmd_sent <= 1'b0;
                        mem_addr     <= mem_addr + 4;
                        if (mem_count == 5) begin
                            mem_count <= '0;
                            mem_addr  <= desc[0];   // A 地址
                            state     <= RD_A;
                        end else begin
                            mem_count <= mem_count + 1'b1;
                        end
                    end
                end

                RD_A: begin
                    if (!mem_cmd_sent) begin
                        if (nice_icb_cmd_ready) mem_cmd_sent <= 1'b1;
                    end else if (nice_icb_rsp_valid) begin
                        a_words[mem_count] <= nice_icb_rsp_rdata;
                        mem_cmd_sent <= 1'b0;
                        mem_addr     <= mem_addr + 4;
                        if (mem_count == 15) begin
                            mem_count <= '0;
                            mem_addr  <= desc[1];
                            state     <= RD_B;
                        end else begin
                            mem_count <= mem_count + 1'b1;
                        end
                    end
                end

                RD_B: begin
                    if (!mem_cmd_sent) begin
                        if (nice_icb_cmd_ready) mem_cmd_sent <= 1'b1;
                    end else if (nice_icb_rsp_valid) begin
                        b_words[mem_count] <= nice_icb_rsp_rdata;
                        mem_cmd_sent <= 1'b0;
                        mem_addr     <= mem_addr + 4;
                        if (mem_count == 15) begin
                            mem_count <= '0;
                            mem_addr  <= desc[2];
                            state     <= GEMM_WAIT;
                            gemm_start <= 1'b1;
                        end else begin
                            mem_count <= mem_count + 1'b1;
                        end
                    end
                end

                GEMM_WAIT: begin
                    if (gemm_done) begin
                        mem_count <= '0;
                        state     <= WR_C;
                    end
                end

                WR_C: begin
                    if (!mem_cmd_sent) begin
                        if (nice_icb_cmd_ready) mem_cmd_sent <= 1'b1;
                    end else if (nice_icb_rsp_valid) begin
                        mem_cmd_sent <= 1'b0;
                        mem_addr     <= mem_addr + 4;
                        if (mem_count == 63) begin
                            done  <= 1'b1;
                            irq   <= 1'b1;
                            busy  <= 1'b0;
                            state <= IDLE;
                        end else begin
                            mem_count <= mem_count + 1'b1;
                        end
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

    // ICB 命令：读写都由 state 决定；地址在 mem_addr
    assign nice_icb_cmd_valid = ((state == RD_DESC) || (state == RD_A) ||
                                 (state == RD_B) || (state == WR_C)) && !mem_cmd_sent;
    assign nice_icb_cmd_read  = (state != WR_C);
    assign nice_icb_cmd_addr  = mem_addr[`E203_ADDR_SIZE-1:0];
    assign nice_icb_cmd_wdata = c_words[mem_count];

    // A/B 解包（每 word 4 个 INT8）与 C 打包（每 word 1 个 INT32）
    always_ff @(posedge nice_clk) begin
        if (state == RD_A && mem_cmd_sent && nice_icb_rsp_valid) begin
            for (int i = 0; i < M; i++)
                for (int k = 0; k < K; k++)
                    if ((i*K + k) / 4 == mem_count)
                        a_buf[i][k] <= nice_icb_rsp_rdata[((i*K + k) % 4)*8 +: 8];
        end
        if (state == RD_B && mem_cmd_sent && nice_icb_rsp_valid) begin
            for (int k = 0; k < K; k++)
                for (int j = 0; j < N; j++)
                    if ((k*N + j) / 4 == mem_count)
                        b_buf[k][j] <= nice_icb_rsp_rdata[((k*N + j) % 4)*8 +: 8];
        end
        for (int i = 0; i < M*N; i++)
            c_words[i] <= c_buf[i / N][i % N];
    end

    int8_gemm #(.M(M), .N(N), .K(K)) u_gemm (
        .clk(nice_clk), .rst_n(nice_rst_n), .start(gemm_start),
        .a(a_buf), .b(b_buf), .c(c_buf), .done(gemm_done)
    );

endmodule
