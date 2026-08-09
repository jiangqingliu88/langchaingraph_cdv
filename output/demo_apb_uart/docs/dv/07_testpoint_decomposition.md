---
document_id: TPOINT-DOC-007
title: "测试点分解文档"
project: "ALU IP"
version: 1.0
date: 2026-08-09
author: SignOffAI
status: Review
---

# 测试点分解文档

| 项目 | 内容 |
|------|------|
| **文档ID** | `TPOINT-DOC-007` |
| **版本** | 1.0 |
| **日期** | 2026-08-09 |
| **作者** | SignOffAI |
| **状态** | Review |
| **项目** | ALU IP — 32bit 算术逻辑单元 |

---

## 修订历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-08-09 | SignOffAI | 初始版本，由 SignOffAI 管道自动生成 |

---


## 1. 概述

本文档将 apb_uart 模块的验证需求分解为可执行的测试点。

- **测试点总计**: 27
- **测试分类**: 6 个类别
- **功能特性**: 5 个

## 2. 功能覆盖率交叉矩阵

将测试点与功能特性、接口进行交叉映射，确保全覆盖。

| 测试类别 | 特性覆盖 | 接口覆盖 | 优先级 |
|----------|----------|----------|--------|
| basic_function | APB 寄存器读写, UART 发送 | - | P0 |
| baud_rate | APB 寄存器读写, UART 发送 | - | P1 |
| fifo_management | APB 寄存器读写, UART 发送 | - | P2 |
| interrupt | APB 寄存器读写, UART 发送 | - | P1 |
| reset | APB 寄存器读写, UART 发送 | - | P1 |
| stress | APB 寄存器读写, UART 发送 | - | P1 |

## 3. 测试点详细分解

### 3.1 basic_function

**类别描述**: basic_function 相关功能验证

| TP编号 | 测试点名称 | 描述 | 激励类型 | 检查类型 | 优先级 |
|--------|------------|------|----------|----------|--------|
| TP-0001 | test_apb_reg_rw | 验证 APB 总线对波特率、控制字、状态字寄存器的读写功能，覆盖所有寄存器地址，验证读写数据正确性 | Directed | Scoreboard | P0 |
| TP-0002 | test_uart_tx_basic | 验证 UART 发送功能，写入数据到发送 FIFO，检查串行输出波形符合起始位+8bit数据+停止位格式 | Directed | Scoreboard | P0 |
| TP-0003 | test_uart_rx_basic | 验证 UART 接收功能，通过 rx 输入串行数据，检查接收 FIFO 中恢复的数据正确 | Directed | Scoreboard | P0 |
| TP-0004 | test_uart_loopback | 验证回环模式，发送数据通过内部回环接收，检查收发数据一致性 | Directed | Scoreboard | P0 |

### 3.2 baud_rate

**类别描述**: baud_rate 相关功能验证

| TP编号 | 测试点名称 | 描述 | 激励类型 | 检查类型 | 优先级 |
|--------|------------|------|----------|----------|--------|
| TP-0005 | test_baud_9600 | 验证 9600 波特率下发送和接收功能，检查波特率误差 ≤2% | Directed | Scoreboard | P0 |
| TP-0006 | test_baud_19200 | 验证 19200 波特率下发送和接收功能，检查波特率误差 ≤2% | Directed | Scoreboard | P0 |
| TP-0007 | test_baud_38400 | 验证 38400 波特率下发送和接收功能，检查波特率误差 ≤2% | Directed | Scoreboard | P0 |
| TP-0008 | test_baud_57600 | 验证 57600 波特率下发送和接收功能，检查波特率误差 ≤2% | Directed | Scoreboard | P0 |
| TP-0009 | test_baud_115200 | 验证 115200 波特率下发送和接收功能，检查波特率误差 ≤2% | Directed | Scoreboard | P0 |
| TP-0010 | test_baud_accuracy | 验证所有标准波特率下发送时序精度，测量实际波特率与配置波特率误差 ≤2% | Directed | Scoreboard | P0 |

### 3.3 fifo_management

**类别描述**: fifo_management 相关功能验证

| TP编号 | 测试点名称 | 描述 | 激励类型 | 检查类型 | 优先级 |
|--------|------------|------|----------|----------|--------|
| TP-0011 | test_fifo_full_flag | 验证发送/接收 FIFO 满标志位正确触发，满标志触发时无数据丢失 | Directed | Assertion | P1 |
| TP-0012 | test_fifo_empty_flag | 验证发送/接收 FIFO 空标志位正确触发 | Directed | Assertion | P1 |
| TP-0013 | test_fifo_overflow | 验证 FIFO 溢出标志位正确触发，溢出时数据不丢失 | Directed | Scoreboard | P1 |
| TP-0014 | test_fifo_depth_16 | 验证 16 字节 FIFO 深度，写入 16 字节后满标志触发，第 17 字节触发溢出 | Directed | Scoreboard | P1 |
| TP-0015 | test_fifo_concurrent_rw | 验证 FIFO 同时读写场景，确保数据完整性和标志位正确性 | Directed | Scoreboard | P1 |

### 3.4 interrupt

**类别描述**: interrupt 相关功能验证

| TP编号 | 测试点名称 | 描述 | 激励类型 | 检查类型 | 优先级 |
|--------|------------|------|----------|----------|--------|
| TP-0016 | test_int_rx_done | 验证接收完成中断产生，中断延迟 ≤2 时钟周期 | Directed | Scoreboard | P1 |
| TP-0017 | test_int_tx_done | 验证发送完成中断产生，中断延迟 ≤2 时钟周期 | Directed | Scoreboard | P1 |
| TP-0018 | test_int_fifo_overflow | 验证 FIFO 溢出中断产生，中断延迟 ≤2 时钟周期 | Directed | Scoreboard | P1 |
| TP-0019 | test_int_enable_disable | 验证中断使能/禁止功能，禁止时中断不产生 | Directed | Scoreboard | P1 |
| TP-0020 | test_int_clear | 验证中断状态清除功能，清除后中断信号释放 | Directed | Scoreboard | P1 |

### 3.5 reset

**类别描述**: reset 相关功能验证

| TP编号 | 测试点名称 | 描述 | 激励类型 | 检查类型 | 优先级 |
|--------|------------|------|----------|----------|--------|
| TP-0021 | test_reset_initial | 验证异步复位后所有寄存器复位到默认值，FIFO 清空，中断释放 | Directed | Scoreboard | P2 |
| TP-0022 | test_reset_during_tx | 验证发送过程中复位，发送状态正确终止，FIFO 清空 | Directed | Scoreboard | P2 |
| TP-0023 | test_reset_during_rx | 验证接收过程中复位，接收状态正确终止，FIFO 清空 | Directed | Scoreboard | P2 |

### 3.6 stress

**类别描述**: stress 相关功能验证

| TP编号 | 测试点名称 | 描述 | 激励类型 | 检查类型 | 优先级 |
|--------|------------|------|----------|----------|--------|
| TP-0024 | test_rx_10000_transfers | 验证所有标准波特率下 10000 次传输无误，覆盖随机数据模式 | Directed | Scoreboard | P2 |
| TP-0025 | test_tx_rx_concurrent | 验证发送和接收同时进行，全双工模式下数据正确性 | Directed | Scoreboard | P2 |
| TP-0026 | test_random_data_pattern | 使用随机数据模式验证收发功能，覆盖边界值 0x00 和 0xFF | Random | Scoreboard | P2 |
| TP-0027 | test_apb_back_to_back | 验证 APB 连续读写操作，确保读写延迟满足 ≤2 时钟周期约束 | Directed | Scoreboard | P2 |

## 4. 测试点→验证目标映射

| 验证目标 | 覆盖测试点 | 覆盖状态 |
|----------|------------|----------|
| VGOAL-001 功能正确性 | TP-0001 ~ TP-0027 | 待验证 |
| VGOAL-002 接口协议合规 | APB/Native 接口测试点 | 待验证 |
| VGOAL-003 寄存器访问 | 寄存器读写测试点 | 待验证 |
| VGOAL-004 代码覆盖率 | 全部 directed + random | 待收集 |
| VGOAL-005 功能覆盖率 | Cross-coverage 检查 | 待收集 |



---

*文档ID: TPOINT-DOC-007 | 自动生成于 2026-08-09 08:16:36 | SignOffAI Pipeline Documentation System*
