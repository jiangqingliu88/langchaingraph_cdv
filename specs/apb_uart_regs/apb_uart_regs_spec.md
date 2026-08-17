# APB UART 模块（带寄存器表）

<!--
  module: apb_uart_regs
  level: BT
  data_width: 8
  baud_rates: [9600, 115200]
  fifo_depth: 16
-->

## 1. 概述
APB 总线接口的 UART 收发模块，8bit 数据位、可配波特率、16 字节 FIFO、中断输出。
本规格带完整寄存器表，用于验证"复合参考模型"（APB 寄存器 + UART TX/RX 接线）路径。

## 2. 功能需求

### APB 寄存器读写
**级别**：P0
**描述**：通过 APB 总线读写 UART 配置寄存器（波特率、控制字、状态字）
**验收标准**：覆盖率 100%

### UART 发送
**级别**：P0
**描述**：写 TX_DATA 寄存器触发串行发送（起始位+8数据位+停止位）
**验收标准**：9600/115200 波特率下误差 ≤ 2%

### UART 接收
**级别**：P0
**描述**：从串行输入采样恢复字节数据，写入 RX_DATA 寄存器
**验收标准**：所有标准波特率下 10000 次传输无误

### 中断输出
**级别**：P1
**描述**：接收完成、发送完成时产生中断（IRQ_EN 寄存器门控）
**验收标准**：中断延迟 ≤ 2 个时钟周期

## 3. 接口规范

| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| pclk | 1 | INPUT | Clock | APB 时钟 |
| preset_n | 1 | INPUT | Reset | 异步复位低有效 |
| paddr[7:0] | 8 | INPUT | APB | 寄存器地址 |
| pwdata[7:0] | 8 | INPUT | APB | 写数据 |
| prdata[7:0] | 8 | OUTPUT | APB | 读数据 |
| pwrite | 1 | INPUT | APB | 写使能 |
| psel | 1 | INPUT | APB | 片选 |
| penable | 1 | INPUT | APB | 使能 |
| tx | 1 | OUTPUT | UART | 串行发送 |
| rx | 1 | INPUT | UART | 串行接收 |
| irq | 1 | OUTPUT | Intr | 中断输出 |

## 4. 寄存器表

| 偏移 | 名称 | 位宽 | 属性 | 描述 |
|------|------|------|------|------|
| 0x00 | TX_DATA | 8 | RW | 写触发 UART 发送（数据位） |
| 0x01 | RX_DATA | 8 | RO | 接收数据（UART RX 写入） |
| 0x02 | STATUS | 8 | RO | 状态字（bit0 tx_busy, bit1 rx_valid） |
| 0x03 | BAUD_DIV | 16 | RW | 波特率分频（低 8 位） |
| 0x04 | IRQ_EN | 8 | RW | 中断使能（bit0 发送完成, bit1 接收完成） |

## 5. 时序约束

| 路径 | 约束 | 说明 |
|------|------|------|
| paddr → prdata | ≤ 2 cycle | APB 读延迟 |
| tx 输出 | 波特率 16x 时钟 | 发送时序 |
