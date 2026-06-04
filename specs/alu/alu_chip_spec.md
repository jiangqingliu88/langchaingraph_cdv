# ALU IP 芯片级规格

## 概述
ALU (Arithmetic Logic Unit) IP 支持 16 种算术/逻辑运算，32bit 数据通路，APB 配置接口。
面向 RISC-V RV32I 指令集，可配置为单周期或多周期模式。

## 芯片级需求
- **REQ_ALU_CHIP_001**: ALU IP 完整验证，覆盖所有 16 种运算和标志位
- 时序: 单周期 (combinational) 或 2-cycle (pipelined)
- 工艺: 28nm, 目标频率 500MHz

## 关键指标
| 参数 | 规格 |
|------|------|
| 数据宽度 | 32 bit |
| 运算类型 | 16 种 (ALU_OP[3:0]) |
| 输入 | A[31:0], B[31:0], ALU_OP[3:0] |
| 输出 | RESULT[31:0], FLAGS[3:0] (N/Z/C/V) |
| 接口 | APB (配置) + Native (数据) |

## 子系统
1. 算术运算通路 (ADD/SUB/MUL/DIV)
2. 逻辑运算通路 (AND/OR/XOR/NOT)
3. 移位运算通路 (SLL/SRL/SRA)
4. 比较运算通路 (SLT/SLTU)
5. 标志位生成 (N/Z/C/V)
6. APB 寄存器接口
