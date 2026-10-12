`ifndef CG_NPU_SCHED_DUT_SV
`define CG_NPU_SCHED_DUT_SV

// DUT 信号的功能覆盖率 —— 由 case 模型生成（casemodel_tools.coverage）
// 用 `bind` 挂到 `npu_sched` 上：该模块的**每个实例**都会带一份探针。
//
// 为什么走 bind 而不是从 monitor 采：monitor 只看得到**激励侧**，而
// 队列水位 / 依赖类型 / 发射决策这些是内部状态与输出端口 —— 只有从 DUT
// 内部才看得见。端口连接表达式在**目标模块作用域**里求值，所以内部名
// 直接连过来即可。

module cg_npu_sched_dut_probe (
  input logic clk,
  input logic rst_n,
  input logic [5:0] queue_level,  // queue_level
  input logic [2:0] instr_type,  // instr_type
  input logic [2:0] instr_dtype,  // instr_dtype
  input logic [1:0] dep_type,  // dep_type
  input logic [2:0] issue_unit,  // issue_unit
  input logic [1:0] issue_decision,  // issue_decision
  input logic [1:0] cluster_id,  // cluster_id
  input logic [3:0] instr_opcode,  // instr_opcode
  input logic [7:0] instr_seq,  // instr_seq
  input logic [2:0] pipeline_state,  // pipeline_state
  input logic [1:0] op_priority,  // op_priority
  input logic [1:0] barrier_type  // barrier_type
);

  covergroup cg_npu_sched_dut;
    option.per_instance = 1;
    cp_queue_level: coverpoint queue_level {
        bins empty = {0};  // 0
        bins low = {[1:7]};  // 1:7
        bins mid = {[8:15]};  // 8:15
        bins high = {[16:24]};  // 16:24
        bins near_full = {[25:31]};  // 25:31
        bins full = {32};  // 32
        illegal_bins illegal_over = {[33:$]};  // 33:$
    }
    cp_instr_type: coverpoint instr_type {
        bins mac = {0};  // MAC
        bins vector = {1};  // VECTOR
        bins scalar = {2};  // SCALAR
        bins dma = {3};  // DMA
    }
    cp_instr_dtype: coverpoint instr_dtype {
        bins int8 = {0};  // INT8
        bins fp16 = {1};  // FP16
        bins bf16 = {2};  // BF16
        bins fp32 = {3};  // FP32
    }
    cp_dep_type: coverpoint dep_type {
        bins no_dep = {0};  // NONE
        bins raw = {1};  // RAW
        bins waw = {2};  // WAW
        bins war = {3};  // WAR
    }
    cp_issue_unit: coverpoint issue_unit {
        bins mac = {0};  // MAC
        bins vector = {1};  // VECTOR
        bins scalar = {2};  // SCALAR
        bins dma = {3};  // DMA
    }
    cp_issue_decision: coverpoint issue_decision {
        bins issued = {0};  // ISSUED
        bins stalled = {1};  // STALLED
        bins blocked = {2};  // BLOCKED
        bins flushed = {3};  // FLUSHED
    }
    cp_cluster_id: coverpoint cluster_id {
        bins c0 = {0};  // 0
        bins c1 = {1};  // 1
        bins c2 = {2};  // 2
        bins c3 = {3};  // 3
        illegal_bins illegal_cluster = {[4:$]};  // 4:$
    }
    cp_instr_opcode: coverpoint instr_opcode {
        bins mac_i8 = {0};  // MAC_INT8
        bins mac_fp16 = {1};  // MAC_FP16
        bins mac_bf16 = {2};  // MAC_BF16
        bins vec_add = {3};  // VEC_ADD
        bins vec_mul = {4};  // VEC_MUL
        bins vec_relu = {5};  // VEC_RELU
        bins load = {6};  // LOAD
        bins store = {7};  // STORE
        bins dma_rd = {8};  // DMA_READ
        bins dma_wr = {9};  // DMA_WRITE
    }
    cp_instr_seq: coverpoint instr_seq {
        bins mac_mac = {0};  // MAC_MAC
        bins load_mac = {1};  // LOAD_MAC
        bins mac_store = {2};  // MAC_STORE
        bins dma_mac = {3};  // DMA_MAC
        bins vec_mac = {4};  // VEC_MAC
        bins scalar_mac = {5};  // SCALAR_MAC
    }
    cp_pipeline_state: coverpoint pipeline_state {
        bins no_overlap = {0};  // NONE
        bins mac_mac_overlap = {1};  // MAC_MAC
        bins mac_dma_overlap = {2};  // MAC_DMA
        bins vec_mac_overlap = {3};  // VEC_MAC
        bins multi_op_overlap = {4};  // MULTI_OP
    }
    cp_op_priority: coverpoint op_priority {
        bins high_first = {0};  // HIGH_FIRST
        bins low_first = {1};  // LOW_FIRST
        bins same_priority = {2};  // SAME_PRIO
        bins round_robin = {3};  // ROUND_ROBIN
    }
    cp_barrier_type: coverpoint barrier_type {
        bins no_barrier = {0};  // NONE
        bins tile_barrier = {1};  // TILE_BARRIER
        bins op_barrier = {2};  // OP_BARRIER
        bins cluster_barrier = {3};  // CLUSTER_BARRIER
    }
    cx_instr_type_issue_unit: cross cp_instr_type, cp_issue_unit {
        bins mac_to_mac = binsof(cp_instr_type.mac) && binsof(cp_issue_unit.mac);
        bins vec_to_vec = binsof(cp_instr_type.vector) && binsof(cp_issue_unit.vector);
        bins scalar_to_scalar = binsof(cp_instr_type.scalar) && binsof(cp_issue_unit.scalar);
        bins dma_to_dma = binsof(cp_instr_type.dma) && binsof(cp_issue_unit.dma);
        illegal_bins mac_to_dma = binsof(cp_instr_type.mac) && binsof(cp_issue_unit.dma);
    }
    cx_instr_dtype_issue_unit: cross cp_instr_dtype, cp_issue_unit {
        bins int8_mac = binsof(cp_instr_dtype.int8) && binsof(cp_issue_unit.mac);
        bins fp16_mac = binsof(cp_instr_dtype.fp16) && binsof(cp_issue_unit.mac);
        bins bf16_mac = binsof(cp_instr_dtype.bf16) && binsof(cp_issue_unit.mac);
        bins fp32_vector = binsof(cp_instr_dtype.fp32) && binsof(cp_issue_unit.vector);
        illegal_bins int8_vector = binsof(cp_instr_dtype.int8) && binsof(cp_issue_unit.vector);
    }
    cx_dep_type_issue_decision: cross cp_dep_type, cp_issue_decision {
        bins raw_stalled = binsof(cp_dep_type.raw) && binsof(cp_issue_decision.stalled);
        bins raw_issued = binsof(cp_dep_type.raw) && binsof(cp_issue_decision.issued);
        bins waw_stalled = binsof(cp_dep_type.waw) && binsof(cp_issue_decision.stalled);
        bins war_stalled = binsof(cp_dep_type.war) && binsof(cp_issue_decision.stalled);
        bins no_dep_issued = binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.issued);
        bins no_dep_blocked = binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.blocked);
    }
    cx_queue_level_issue_decision: cross cp_queue_level, cp_issue_decision {
        bins full_blocked = binsof(cp_queue_level.full) && binsof(cp_issue_decision.blocked);
        bins near_full_stalled = binsof(cp_queue_level.near_full) && binsof(cp_issue_decision.stalled);
        bins empty_issued = binsof(cp_queue_level.empty) && binsof(cp_issue_decision.issued);
        bins low_issued = binsof(cp_queue_level.low) && binsof(cp_issue_decision.issued);
    }
    cx_cluster_id_issue_unit: cross cp_cluster_id, cp_issue_unit;
    cx_instr_opcode_issue_unit: cross cp_instr_opcode, cp_issue_unit {
        bins mac_i8_mac = binsof(cp_instr_opcode.mac_i8) && binsof(cp_issue_unit.mac);
        bins mac_fp16_mac = binsof(cp_instr_opcode.mac_fp16) && binsof(cp_issue_unit.mac);
        bins vec_add_vec = binsof(cp_instr_opcode.vec_add) && binsof(cp_issue_unit.vector);
        bins load_scalar = binsof(cp_instr_opcode.load) && binsof(cp_issue_unit.scalar);
        bins dma_rd_dma = binsof(cp_instr_opcode.dma_rd) && binsof(cp_issue_unit.dma);
        illegal_bins mac_vec = binsof(cp_instr_opcode.mac_i8) && binsof(cp_issue_unit.vector);
    }
    cx_instr_seq_issue_decision: cross cp_instr_seq, cp_issue_decision {
        bins mac_mac_stalled = binsof(cp_instr_seq.mac_mac) && binsof(cp_issue_decision.stalled);
        bins load_mac_issued = binsof(cp_instr_seq.load_mac) && binsof(cp_issue_decision.issued);
        bins mac_store_issued = binsof(cp_instr_seq.mac_store) && binsof(cp_issue_decision.issued);
        bins dma_mac_blocked = binsof(cp_instr_seq.dma_mac) && binsof(cp_issue_decision.blocked);
        bins vec_mac_issued = binsof(cp_instr_seq.vec_mac) && binsof(cp_issue_decision.issued);
        bins scalar_mac_stalled = binsof(cp_instr_seq.scalar_mac) && binsof(cp_issue_decision.stalled);
    }
  endgroup

  cg_npu_sched_dut cg = new();

  // 采样：时钟沿，且**不在复位周期**（复位期间的水位/决策是无意义值）
  always @(posedge clk) if (rst_n) cg.sample();
endmodule

bind npu_sched cg_npu_sched_dut_probe u_cg_probe(
  .clk(clk),
  .rst_n(rst_n),
  .queue_level(queue_level),
  .instr_type(instr_type),
  .instr_dtype(instr_dtype),
  .dep_type(dep_type),
  .issue_unit(issue_unit),
  .issue_decision(issue_decision),
  .cluster_id(cluster_id),
  .instr_opcode(instr_opcode),
  .instr_seq(instr_seq),
  .pipeline_state(pipeline_state),
  .op_priority(op_priority),
  .barrier_type(barrier_type)
);

`endif  // CG_NPU_SCHED_DUT_SV
