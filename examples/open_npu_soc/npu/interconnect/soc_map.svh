// Open NPU SoC v0.1 地址映射 —— 软件和 RTL 共用的唯一一份。
// v0.1 的数据面是直接连线；AXI/E203 原生总线适配在 M2 替换这一层。
`ifndef SOC_MAP_SVH
`define SOC_MAP_SVH

`define SOC_SRAM_A_BASE   32'h0000_A000
`define SOC_SRAM_B_BASE   32'h0000_B000
`define SOC_SRAM_C_BASE   32'h0000_C000
`define SOC_NICE_CMD      32'h0000_2000
`define SOC_NICE_IRQ      32'h0000_2004

`endif
