# UART TX 发送模块
<!--
  module: uart_tx
  parent: UART
  level: BT
  data_bits: [5, 6, 7, 8]
  parity: [N, E, O]
  stop_bits: [1, 1.5, 2]
  requirements: [REQ_UART_TX_001]
-->

## 1. 概述
UART 发送模块负责将并行数据转换为串行数据输出，包括起始位/数据位/校验位/停止位的帧组装。

## 2. 功能需求

### 帧组装
**级别**：P0
**类型**：FUNCTIONAL
**描述**：按配置组装起始位+数据位+校验位+停止位
**验收标准**：所有帧格式组合正确

### 移位寄存器
**级别**：P0
**类型**：FUNCTIONAL
**描述**：并行数据加载到移位寄存器，按波特率逐位输出
**验收标准**：移位顺序和时序正确

### TX FIFO
**级别**：P1
**类型**：CONTROL
**描述**：FIFO 读写指针管理和空标志
**验收标准**：FIFO empty 时停止发送，写入后自动恢复

### 发送状态机
**级别**：P0
**类型**：CONTROL
**描述**：IDLE → START → DATA → PARITY → STOP 状态转移
**验收标准**：所有状态转移正确，无死锁

### 中断生成
**级别**：P1
**类型**：CONTROL
**描述**：TX FIFO empty 时产生中断
**验收标准**：中断及时触发，软件可清除

## 3. 接口规范

| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| clk | 1 | INPUT | — | 时钟 |
| rst_n | 1 | INPUT | — | 复位 |
| tx_data[7:0] | 8 | INPUT | — | 发送数据 |
| tx_valid | 1 | INPUT | — | 数据有效 |
| tx_ready | 1 | OUTPUT | — | 可接收数据 |
| tx | 1 | OUTPUT | UART | 串行输出 |
| tx_busy | 1 | OUTPUT | — | 发送忙 |
| baud_tick | 1 | INPUT | — | 波特率时钟 |

## 4. 时序约束

| 路径 | 约束 | 说明 |
|------|------|------|
| tx_data → tx | ≤ 1 波特率周期 | 加载到输出 |
| tx_valid → tx_ready | ≤ 1 cycle | 握手响应 |

## 5. 功耗约束

| 模式 | 功耗 | 说明 |
|------|------|------|
| Active (发送中) | ≤ 2mW | 移位寄存器工作 |
| Idle | ≤ 0.2mW | 等待数据 |
