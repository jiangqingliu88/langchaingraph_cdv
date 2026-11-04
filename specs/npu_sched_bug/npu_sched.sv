// ============================================================================
// NPU 指令调度器 —— 硬件指令调度器（DUT）
//
// 端口与内部信号**逐条对齐**《NPU 指令调度器功能覆盖率计划文档 v2.0》§2.2 的
// 接口表 —— 那份表就是这份 RTL 的契约，也是 `specs/npu_sched/casemodel.yaml`
// 里 12 个覆盖点的采样信号来源（`sample: dut` 走 bind 探针，按**名字**连）。
//
// ## 编码约定（**必须与 case 模型的 `values:` 顺序一致**）
//
// 模型把取值按**下标**投影成整型（`coverage.sv_value`）：`values: [A, B]` 意味着
// `A=0, B=1`。所以下面这些 localparam 的顺序不能随手改 —— 改了模型那边的 bin
// 含义就跟着变，而**编译不会报错**（只是覆盖率数字对不上实际行为）。
//
//   instr_type      MAC=0 VECTOR=1 SCALAR=2 DMA=3
//   instr_dtype     INT8=0 FP16=1 BF16=2 FP32=3
//   dep_type        NONE=0 RAW=1 WAW=2 WAR=3
//   issue_unit      MAC=0 VECTOR=1 SCALAR=2 DMA=3
//   issue_decision  ISSUED=0 STALLED=1 BLOCKED=2 FLUSHED=3
//   instr_opcode    MAC_INT8=0 … DMA_WRITE=9
//   instr_seq       由相邻两条 opcode 的**类型对**编码（见下）
//   pipeline_state  NONE=0 MAC_MAC=1 MAC_DMA=2 VEC_MAC=3 MULTI_OP=4
//   op_priority     HIGH_FIRST=0 LOW_FIRST=1 SAME_PRIO=2 ROUND_ROBIN=3
//   barrier_type    NONE=0 TILE=1 OP=2 CLUSTER=3
//
// ## 职责（§2.1 的 8 条，这里落实前 8 条里可测的那几条）
//
//   接收指令流 → 入队（管满/空）→ 查依赖 → 决定发射 → 分配执行单元
//   → 处理簇归属 → 响应屏障/冲刷 → 维护流水重叠
//
// **这是给验证流程用的模型化实现**，不是量产 RTL：它把 12 个被采样的信号都
// 产生出来、且行为可复现（同一个种子同样输入 → 同样轨迹），但时序细节（流水级数、
// 仲裁延迟）做了简化。真 RTL 替换掉它之后，覆盖点与种子管理**一行都不用改**。
// ============================================================================

`ifndef NPU_SCHED_SV
`define NPU_SCHED_SV

module npu_sched (
  input  logic        clk,
  input  logic        rst_n,            // 异步复位，低有效

  // ── 指令流（来自主控）──
  input  logic        instr_valid,
  input  logic [7:0]  instr_opcode,
  input  logic [2:0]  instr_type,
  input  logic [2:0]  instr_dtype,
  input  logic [7:0]  instr_tile_id,
  input  logic [31:0] instr_src_addr,
  input  logic [31:0] instr_dst_addr,

  // ── 同步屏障与优先级策略（外部可配）──
  input  logic [1:0]  barrier_type,     // NONE / TILE / OP / CLUSTER
  input  logic [1:0]  op_priority,      // HIGH_FIRST / LOW_FIRST / SAME_PRIO / ROUND_ROBIN（4 个取值 → 2 位）

  // ── 发射（到执行单元）──
  output logic        issue_valid,
  output logic [2:0]  issue_unit,
  output logic [1:0]  issue_decision
);

  // ── 编码常量（与 case 模型 values 的顺序一一对应，见文件头）──
  localparam int TYPE_MAC = 0, TYPE_VEC = 1, TYPE_SCL = 2, TYPE_DMA = 3;
  localparam int DEC_ISSUED = 0, DEC_STALLED = 1, DEC_BLOCKED = 2, DEC_FLUSHED = 3;
  localparam int DEP_NONE = 0, DEP_RAW = 1, DEP_WAW = 2, DEP_WAR = 3;
  localparam int PIPE_NONE = 0, PIPE_MAC_MAC = 1, PIPE_MAC_DMA = 2,
                PIPE_VEC_MAC = 3, PIPE_MULTI = 4;

  localparam int QUEUE_DEPTH = 32;      // §3.2 CP_NPU_QUEUE_001：0-32

  // ── 内部信号：**case 模型 `sample: dut` 采的就是这几个**，名字不能改 ──
  logic [5:0] queue_level;              // 队列水位 0..32（6 位够到 63，33+ 走 illegal_bins）
  logic [1:0] dep_type;                 // 队头那条指令的依赖类型
  logic [1:0] cluster_id;               // 指令归属的簇（由 tile_id 低位来）
  logic [7:0] instr_seq;                // 相邻两条指令的 opcode 组合
  logic [2:0] pipeline_state;           // 当前流水重叠状态

  // ── 队列（存最近的指令摘要，供依赖判定）──
  logic [31:0] q_src [0:QUEUE_DEPTH-1];
  logic [31:0] q_dst [0:QUEUE_DEPTH-1];
  logic [2:0]  q_typ [0:QUEUE_DEPTH-1];
  logic [7:0]  q_opc [0:QUEUE_DEPTH-1];

  logic [5:0]  rd_ptr, wr_ptr;
  logic [7:0]  prev_opcode;             // 上一条入队的 opcode（算 instr_seq 用）
  logic [2:0]  last_issued_type;        // 上一条发射出去的类型（算 pipeline_state 用）

  wire full  = (queue_level >= 6'd63);  // BUG-C：永远不满，水位可越界
  wire empty = (queue_level == 6'd0);

  // ── 组合：依赖判定（拿队头的地址比已入队的所有项）──
  //   RAW —— 队头的**源**被它**前面**的指令写过（真依赖，必须等）
  //   WAW —— 队头的**目的**与前面某条的目的相同（输出依赖）
  //   WAR —— 队头的**目的**命中前面某条的**源**（反依赖）
  // 取最先命中的那一条（真依赖优先于其余两种）。
  logic has_raw, has_waw, has_war;
  always_comb begin
    has_raw = 1'b0; has_waw = 1'b0; has_war = 1'b0;
    if (!empty) begin
      for (int i = 0; i < QUEUE_DEPTH; i++) begin
        if (q_dst[i] == q_src[rd_ptr]) has_raw = 1'b1;
        if (q_dst[i] == q_dst[rd_ptr]) has_waw = 1'b1;
        if (q_src[i] == q_dst[rd_ptr]) has_war = 1'b1;
      end
    end
  end

  // ── 组合：发射决策 ──
  //   屏障命中        → FLUSHED（冲刷，这一拍不发）
  //   队列空          → STALLED（没东西可发）
  //   队列满且入队请求 → BLOCKED（压力来自入口，不是依赖）
  //   有真依赖        → STALLED（等依赖消解）
  //   其余            → ISSUED
  always_comb begin
    if (1'b0)                               issue_decision = 2'(DEC_FLUSHED);  // BUG-A
    else if (empty)                          issue_decision = 2'(DEC_STALLED);
    else if (full && instr_valid)            issue_decision = 2'(DEC_BLOCKED);
    else if (1'b0)                          issue_decision = 2'(DEC_STALLED);  // BUG-B
    else                                     issue_decision = 2'(DEC_ISSUED);
  end

  always_comb begin
    logic [1:0] d;
    if      (has_raw) d = 2'(DEP_RAW);
    else if (has_waw) d = 2'(DEP_WAW);
    else if (has_war) d = 2'(DEP_WAR);
    else              d = 2'(DEP_NONE);
    dep_type = d;
  end

  // 执行单元跟随指令类型（`MAC→MAC / VECTOR→VECTOR / SCALAR→SCALAR / DMA→DMA`）
  assign issue_unit = empty ? 3'd0 : 3'(q_typ[rd_ptr]);
  assign issue_valid = (issue_decision == 2'(DEC_ISSUED));
  assign cluster_id  = 2'(instr_tile_id[1:0]);

  // ── 组合：流水重叠状态（看**上一条**与**刚发射这条**的类型对）──
  always_comb begin
    if (last_issued_type == 3'(TYPE_MAC) && issue_unit == 3'(TYPE_MAC))
      pipeline_state = 3'(PIPE_MAC_MAC);
    else if (last_issued_type == 3'(TYPE_MAC) && issue_unit == 3'(TYPE_DMA))
      pipeline_state = 3'(PIPE_MAC_DMA);
    else if (last_issued_type == 3'(TYPE_VEC) && issue_unit == 3'(TYPE_MAC))
      pipeline_state = 3'(PIPE_VEC_MAC);
    else if (last_issued_type != 3'(TYPE_MAC) && last_issued_type != 3'(TYPE_VEC))
      pipeline_state = 3'(PIPE_NONE);
    else
      pipeline_state = 3'(PIPE_MULTI);      // 其余组合：两条不同类型的指令并行
  end

  // ── 时序：入队 / 出队 / 流水状态 ──
  integer k;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rd_ptr <= 6'd0; wr_ptr <= 6'd0; queue_level <= 6'd0;
      prev_opcode <= 8'd0; instr_seq <= 8'd0; last_issued_type <= 3'd0;
      for (k = 0; k < QUEUE_DEPTH; k++) begin
        q_src[k] <= 32'd0; q_dst[k] <= 32'd0;
        q_typ[k] <= 3'd0;  q_opc[k] <= 8'd0;
      end
    end else begin
      // 入队：有效且没满
      if (instr_valid && !full) begin
        q_src[wr_ptr] <= instr_src_addr;
        q_dst[wr_ptr] <= instr_dst_addr;
        q_typ[wr_ptr] <= instr_type;
        q_opc[wr_ptr] <= instr_opcode;
        wr_ptr <= (wr_ptr == QUEUE_DEPTH[5:0] - 6'd1) ? 6'd0 : wr_ptr + 6'd1;

        // `instr_seq`：**相邻两条 opcode 的组合作成一个码**。
        // 组合空间按文档 §3.2 只留 6 种名义 bin（mac_mac / load_mac / …），
        // 这里用 `{上一条的低 4 位, 当前的低 4 位}` 做机器通道 —— 名义 bin 与
        // 具体编码的对应由覆盖率的 bin 划分承担（`cover_bins` 那 6 个）。
        instr_seq <= {prev_opcode[3:0], instr_opcode[3:0]};
        prev_opcode <= instr_opcode;
      end

      // 出队：这一拍真发射了
      if (issue_valid && !empty) begin
        rd_ptr <= (rd_ptr == QUEUE_DEPTH[5:0] - 6'd1) ? 6'd0 : rd_ptr + 6'd1;
        last_issued_type <= q_typ[rd_ptr];
      end

      // 水位：入队 +1、出队 -1，两件事都可能在同一拍发生
      queue_level <= queue_level
                   + ((instr_valid && !full)   ? 6'd1 : 6'd0)
                   - ((issue_valid && !empty)  ? 6'd1 : 6'd0);
    end
  end

endmodule

`endif  // NPU_SCHED_SV
