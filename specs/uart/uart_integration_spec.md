# UART 集成级规格
<!--
  module: UART
  level: IT
  parent: SOC
  connected_modules: [DMA, Interrupt_Controller, AXI_Bus]
  requirements: [REQ_UART_INT_001, REQ_UART_INT_002, REQ_UART_INT_003]
-->

## 1. 概述
UART 与 DMA、中断控制器等模块的集成验证，确保子系统级交互正确。

## 2. 功能需求

### UART + DMA 联合传输
**级别**：P0
**类型**：FUNCTIONAL
**描述**：DMA 控制 UART TX/RX 数据传输
**验收标准**：DMA 传输完成中断触发，数据无丢失

### 多 UART 通道仲裁
**级别**：P1
**类型**：CONTROL
**描述**：多个 UART 实例共享 DMA 时的仲裁
**验收标准**：各通道公平调度，无饥饿

### 中断控制器联动
**级别**：P0
**类型**：CONTROL
**描述**：UART 中断到中断控制器的路由
**验收标准**：所有中断源（TX/RX/Error）正确路由

### 功耗模式切换
**级别**：P1
**类型**：POWER
**描述**：Active → Idle → Sleep 模式切换的子系统协调
**验收标准**：状态切换无死锁，唤醒时间 ≤ 10μs

### AXI 总线压力测试
**级别**：P1
**类型**：FUNCTIONAL
**描述**：高带宽 AXI 访问与 UART 低带宽操作的共存
**验收标准**：无总线死锁，UART 数据无丢失

## 3. 接口规范

| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| dma_req | 1 | OUTPUT | — | DMA 请求 |
| dma_ack | 1 | INPUT | — | DMA 应答 |
| dma_done | 1 | INPUT | — | DMA 完成 |
| irq_lines[2:0] | 3 | OUTPUT | — | 中断输出 |
| power_mode[1:0] | 2 | INPUT | — | 功耗模式 |

## 4. 时序约束

| 路径 | 约束 | 说明 |
|------|------|------|
| dma_req → dma_ack | ≤ 4 cycles | DMA 握手 |
| power_mode → 实际切换 | ≤ 10μs | 功耗模式切换 |

## 5. 功耗约束

| 模式 | 功耗 | 说明 |
|------|------|------|
| Full Active | ≤ 8mW | 全部模块运行 |
| Partial Active | ≤ 4mW | 仅 UART 活跃 |
| System Idle | ≤ 1mW | 子系统空闲 |
