# APB UART 模块
<!--
  module: apb_uart
  level: BT
  data_width: 8
  baud_rates: [9600, 19200, 38400, 57600, 115200]
  fifo_depth: 16
  requirements: [REQ_APB_UART_001]
-->

## 1. 概述
APB 总线接口的 UART 收发模块，支持 8bit 数据位、可配波特率、16 字节 FIFO、中断输出。

## 2. 功能需求

### APB 寄存器读写
**级别**：P0
**描述**：通过 APB 总线读写 UART 配置寄存器（波特率、控制字、状态字）
**验收标准**：覆盖率 100%

### UART 发送
**级别**：P0
**描述**：将 FIFO 中的数据串行输出，支持起始位+数据位+停止位格式
**验收标准**：9600-115200 波特率下误差 ≤ 2%

### UART 接收
**级别**：P0
**描述**：从串行输入采样恢复字节数据，写入接收 FIFO
**验收标准**：所有标准波特率下 10000 次传输无误

### FIFO 管理
**级别**：P1
**描述**：16 字节收发 FIFO，支持溢出/空/满标志位
**验收标准**：满标志位触发时无数据丢失

### 中断输出
**级别**：P1
**描述**：接收完成、发送完成、FIFO 溢出时产生中断
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

## 3.5 寄存器映射

APB 从端寄存器文件。**地址按 `paddr[7:0]` 译码**（原文没写地址，这份表补上；
RTL 目前**尚未实现译码** —— `paddr` 全程不参与判断、`prdata` 被 `rx_data` 直接驱动，
见 `rtl/apb_uart.sv`。本表是**设计意图**，RTL 需照此实现地址译码）。

| 偏移 | 名称 | 读写 | 位宽 | 复位值 | 描述 |
|------|------|------|------|--------|------|
| 0x00 | RXDATA   | RO | 8 | 0x00 | 接收数据。读返回 RX FIFO 队首（空时 0） |
| 0x04 | TXDATA   | WO | 8 | 0x00 | 发送数据。写一字节进 TX FIFO（满时丢弃） |
| 0x08 | CTRL     | RW | 8 | 0x00 | bit0 收发使能；bit1 RX FIFO 复位；bit2 TX FIFO 复位 |
| 0x0C | BAUD     | RW | 8 | 0x00 | 波特率分频低 8 位（配合 BAUD_H） |
| 0x10 | BAUD_H   | RW | 8 | 0x00 | 波特率分频高 8 位。分频 = 时钟/波特率 |
| 0x14 | STATUS   | RO | 8 | 0x00 | bit0 TX 空；bit1 TX 满；bit2 RX 空；bit3 RX 满；bit4 帧错误 |
| 0x18 | IRQ_EN   | RW | 8 | 0x00 | bit0 RX 完成；bit1 TX 完成；bit2 RX 溢出；bit3 帧错误 |
| 0x1C | IRQ_STAT | RO | 8 | 0x00 | 与 IRQ_EN 同位的挂起状态，**读清除** |
| 0x20 | FIFO_LVL | RO | 8 | 0x00 | bit[3:0] RX 计数；bit[7:4] TX 计数 |

**写只读寄存器 / 读只写寄存器**：忽略，不回错误、不置 `pslverr`（本设计无 `pslverr`）。

## 4. 时序约束

| 路径 | 约束 | 说明 |
|------|------|------|
| paddr → prdata | ≤ 2 cycle | APB 读延迟 |
| tx 输出 | 波特率 16x 时钟 | 发送时序 |

## 5. 功耗约束

| 模式 | 功耗 | 说明 |
|------|------|------|
| Active | ≤ 2mW | 收发工作中 |
| Idle | ≤ 0.1mW | 无数据传输 |
