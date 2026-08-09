---
document_id: SPEC-DOC-001
title: "设计需求规格书"
project: "ALU IP"
version: 1.0
date: 2026-08-09
author: SignOffAI
status: Draft
---

# 设计需求规格书

| 项目 | 内容 |
|------|------|
| **文档ID** | `SPEC-DOC-001` |
| **版本** | 1.0 |
| **日期** | 2026-08-09 |
| **作者** | SignOffAI |
| **状态** | Draft |
| **项目** | ALU IP — 32bit 算术逻辑单元 |

---

## 修订历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-08-09 | SignOffAI | 初始版本，由 SignOffAI 管道自动生成 |

---


## 1. 概述

**设计名称**: `apb_uart` | **版本**: 1.0

**概述**: APB 总线接口的 UART 收发模块，支持 8bit 数据位、可配波特率（9600-115200）、16 字节收发 FIFO、中断输出。通过 APB 总线配置寄存器，实现串行数据的发送与接收。

## 2. 功能特性

| 编号 | 特性名称 | 描述 | 优先级 |
|------|----------|------|--------|
| FEAT-001 | APB 寄存器读写 | 通过 APB 总线读写 UART 配置寄存器（波特率、控制字、状态字），支持 paddr[7:0] 地址空间，读写延迟 ≤2 时钟周期 | P0 |
| FEAT-002 | UART 发送 | 将发送 FIFO 中的数据串行输出，支持起始位+8bit数据位+停止位格式，支持 9600/19200/38400/57600/115200 波特率，波特率误差 ≤2% | P0 |
| FEAT-003 | UART 接收 | 从串行输入 rx 采样恢复字节数据，写入接收 FIFO，所有标准波特率下 10000 次传输无误 | P0 |
| FEAT-004 | FIFO 管理 | 16 字节收发 FIFO，支持溢出/空/满标志位，满标志位触发时无数据丢失 | P1 |
| FEAT-005 | 中断输出 | 接收完成、发送完成、FIFO 溢出时产生中断输出，中断延迟 ≤2 个时钟周期 | P1 |

## 3. 接口定义

| 编号 | 接口名称 | 类型 | 数据宽度 | 时钟域 | 信号数 |
|------|----------|------|----------|--------|--------|
| IF-001 | `apb_slave` | APB | 8 | pclk | 8 |
| IF-002 | `uart_serial` | UART | 1 | pclk | 2 |
| IF-003 | `interrupt` | Interrupt | 1 | pclk | 1 |

## 4. 寄存器映射

| 偏移 | 寄存器名称 | 位宽 | 访问 | 描述 |
|------|------------|------|------|------|
| 0x00 | `BAUD_RATE` | 8 | RW | 波特率配置寄存器，配置 9600/19200/38400/57600/115200 |
| 0x01 | `CTRL` | 8 | RW | 控制字寄存器，控制发送/接收使能、中断使能等 |
| 0x02 | `STATUS` | 8 | RO | 状态字寄存器，包含 FIFO 空/满/溢出标志、收发状态 |
| 0x03 | `TX_DATA` | 8 | WO | 发送数据寄存器，写入数据进入发送 FIFO |
| 0x04 | `RX_DATA` | 8 | RO | 接收数据寄存器，读取接收 FIFO 数据 |
| 0x05 | `INT_EN` | 8 | RW | 中断使能寄存器，控制接收完成/发送完成/FIFO溢出中断使能 |
| 0x06 | `INT_STATUS` | 8 | RO | 中断状态寄存器，指示中断源 |

## 5. 测试点概览

### 5.1 basic_function

| 编号 | 测试点 | 描述 |
|------|--------|------|
| TP-BASI-001 | test_apb_reg_rw | 验证 APB 总线对波特率、控制字、状态字寄存器的读写功能，覆盖所有寄存器地址，验证读写数据正确性 |
| TP-BASI-002 | test_uart_tx_basic | 验证 UART 发送功能，写入数据到发送 FIFO，检查串行输出波形符合起始位+8bit数据+停止位格式 |
| TP-BASI-003 | test_uart_rx_basic | 验证 UART 接收功能，通过 rx 输入串行数据，检查接收 FIFO 中恢复的数据正确 |
| TP-BASI-004 | test_uart_loopback | 验证回环模式，发送数据通过内部回环接收，检查收发数据一致性 |

### 5.2 baud_rate

| 编号 | 测试点 | 描述 |
|------|--------|------|
| TP-BAUD-001 | test_baud_9600 | 验证 9600 波特率下发送和接收功能，检查波特率误差 ≤2% |
| TP-BAUD-002 | test_baud_19200 | 验证 19200 波特率下发送和接收功能，检查波特率误差 ≤2% |
| TP-BAUD-003 | test_baud_38400 | 验证 38400 波特率下发送和接收功能，检查波特率误差 ≤2% |
| TP-BAUD-004 | test_baud_57600 | 验证 57600 波特率下发送和接收功能，检查波特率误差 ≤2% |
| TP-BAUD-005 | test_baud_115200 | 验证 115200 波特率下发送和接收功能，检查波特率误差 ≤2% |
| TP-BAUD-006 | test_baud_accuracy | 验证所有标准波特率下发送时序精度，测量实际波特率与配置波特率误差 ≤2% |

### 5.3 fifo_management

| 编号 | 测试点 | 描述 |
|------|--------|------|
| TP-FIFO-001 | test_fifo_full_flag | 验证发送/接收 FIFO 满标志位正确触发，满标志触发时无数据丢失 |
| TP-FIFO-002 | test_fifo_empty_flag | 验证发送/接收 FIFO 空标志位正确触发 |
| TP-FIFO-003 | test_fifo_overflow | 验证 FIFO 溢出标志位正确触发，溢出时数据不丢失 |
| TP-FIFO-004 | test_fifo_depth_16 | 验证 16 字节 FIFO 深度，写入 16 字节后满标志触发，第 17 字节触发溢出 |
| TP-FIFO-005 | test_fifo_concurrent_rw | 验证 FIFO 同时读写场景，确保数据完整性和标志位正确性 |

### 5.4 interrupt

| 编号 | 测试点 | 描述 |
|------|--------|------|
| TP-INTE-001 | test_int_rx_done | 验证接收完成中断产生，中断延迟 ≤2 时钟周期 |
| TP-INTE-002 | test_int_tx_done | 验证发送完成中断产生，中断延迟 ≤2 时钟周期 |
| TP-INTE-003 | test_int_fifo_overflow | 验证 FIFO 溢出中断产生，中断延迟 ≤2 时钟周期 |
| TP-INTE-004 | test_int_enable_disable | 验证中断使能/禁止功能，禁止时中断不产生 |
| TP-INTE-005 | test_int_clear | 验证中断状态清除功能，清除后中断信号释放 |

### 5.5 reset

| 编号 | 测试点 | 描述 |
|------|--------|------|
| TP-RESE-001 | test_reset_initial | 验证异步复位后所有寄存器复位到默认值，FIFO 清空，中断释放 |
| TP-RESE-002 | test_reset_during_tx | 验证发送过程中复位，发送状态正确终止，FIFO 清空 |
| TP-RESE-003 | test_reset_during_rx | 验证接收过程中复位，接收状态正确终止，FIFO 清空 |

### 5.6 stress

| 编号 | 测试点 | 描述 |
|------|--------|------|
| TP-STRE-001 | test_rx_10000_transfers | 验证所有标准波特率下 10000 次传输无误，覆盖随机数据模式 |
| TP-STRE-002 | test_tx_rx_concurrent | 验证发送和接收同时进行，全双工模式下数据正确性 |
| TP-STRE-003 | test_random_data_pattern | 使用随机数据模式验证收发功能，覆盖边界值 0x00 和 0xFF |
| TP-STRE-004 | test_apb_back_to_back | 验证 APB 连续读写操作，确保读写延迟满足 ≤2 时钟周期约束 |

**测试点总计**: 27

## 6. 覆盖率目标

- **code_coverage**: {'line': 95, 'branch': 90, 'toggle': 85, 'fsm': 100}
- **functional_coverage**: {'reg_access': 100, 'baud_rate': 100, 'fifo_states': 100, 'interrupt_sources': 100, 'tx_frame_format': 100, 'rx_frame_format': 100}

## 7. 验证架构概览

- **Agent 数量**: 3
- **Scoreboard**: [{'name': 'uart_scoreboard', 'description': '比较发送数据与接收数据，验证收发一致性', 'type': 'in_order'}, {'name': 'apb_scoreboard', 'description': '验证 APB 寄存器读写数据正确性', 'type': 'in_order'}]
- **Virtual Sequencer**: {'enabled': True, 'description': '协调 APB 配置序列与 UART 收发序列的时序关系'}



---

*文档ID: SPEC-DOC-001 | 自动生成于 2026-08-09 08:14:26 | SignOffAI Pipeline Documentation System*
