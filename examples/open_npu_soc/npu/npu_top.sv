// Open NPU 子系统顶层 —— 挂在 E203 SoC 的 `e203_subsys_top` 层级，
// 与 `u_e203_subsys_main` 同级。
//
// 层级（波形里也能看到）：
//
//   e203_subsys_top
//    ├─ u_e203_subsys_main   # E203 CPU 子系统；NICE 请求/响应/ICB 引到边界
//    └─ u_npu_top            # 本模块：NICE 从口 → nice_disp → INT8 GEMM
//         └─ u_nice_disp     # e203_nice_npu_adapter（e203/nice_disp）
//              └─ u_gemm     # INT8 GEMM（npu/int8_gemm.sv）
//
// NICE 的 ICB 主口回到 CPU 的 LSU（地址落在 DTCM），所以 CPU 看到的仍是
// 普通内存：A/B/C/desc 都在 DTCM。DMA/SRAM 仍由参考 TB 路径使用，本层
// 暂不实例化（E203 路径的数据搬运由 NICE ICB 完成）。
`include "e203_defines.v"

module npu_top (
    input  logic                         clk,
    input  logic                         rst_n,

    // NICE request channel（来自 CPU）
    input  logic                         nice_req_valid,
    output logic                         nice_req_ready,
    input  logic [`E203_XLEN-1:0]        nice_req_inst,
    input  logic [`E203_XLEN-1:0]        nice_req_rs1,
    input  logic [`E203_XLEN-1:0]        nice_req_rs2,

    // NICE response channel（回 CPU）
    output logic                         nice_rsp_valid,
    input  logic                         nice_rsp_ready,
    output logic [`E203_XLEN-1:0]        nice_rsp_rdat,
    output logic                         nice_rsp_err,
    output logic                         nice_active,
    output logic                         nice_mem_holdup,

    // NICE ICB master（回到 CPU LSU → DTCM）
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

    e203_nice_npu_adapter u_nice_disp (
        .nice_clk             (clk),
        .nice_rst_n           (rst_n),
        .nice_active          (nice_active),
        .nice_mem_holdup      (nice_mem_holdup),

        .nice_req_valid       (nice_req_valid),
        .nice_req_ready       (nice_req_ready),
        .nice_req_inst        (nice_req_inst),
        .nice_req_rs1         (nice_req_rs1),
        .nice_req_rs2         (nice_req_rs2),

        .nice_rsp_valid       (nice_rsp_valid),
        .nice_rsp_ready       (nice_rsp_ready),
        .nice_rsp_rdat        (nice_rsp_rdat),
        .nice_rsp_err         (nice_rsp_err),

        .nice_icb_cmd_valid   (nice_icb_cmd_valid),
        .nice_icb_cmd_ready   (nice_icb_cmd_ready),
        .nice_icb_cmd_addr    (nice_icb_cmd_addr),
        .nice_icb_cmd_read    (nice_icb_cmd_read),
        .nice_icb_cmd_wdata   (nice_icb_cmd_wdata),
        .nice_icb_cmd_size    (nice_icb_cmd_size),

        .nice_icb_rsp_valid   (nice_icb_rsp_valid),
        .nice_icb_rsp_ready   (nice_icb_rsp_ready),
        .nice_icb_rsp_rdata   (nice_icb_rsp_rdata),
        .nice_icb_rsp_err     (nice_icb_rsp_err)
    );

endmodule
