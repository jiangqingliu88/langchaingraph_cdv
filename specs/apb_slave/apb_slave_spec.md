# APB Slave 模块
<!--
  module: apb_slave
  level: BT
  data_width: 8
-->

## 1. 概述
APB 从端寄存器文件：4 个 8 bit 寄存器 `r0`-`r3`，按 `paddr[1:0]` 译码。
写事务存入，读事务送回 `prdata`；地址越界时写忽略、读回 0 并拉 `pslverr`。

> **下面的接口表与寄存器表是从 RTL 逐行读出来的**（`ip_rtl/apb_slave.sv`，
> 来自 `.signoffai/ip_registry.db` 的 v4，状态 `reused`）。
> 第一版我按「常规 APB 从端」想当然写了 16 个寄存器和 8 个端口 —— **全错**。
> 规格必须照实现读，不能照印象写。

## 2. 功能需求

### 寄存器读写
**级别**：P0
**描述**：`psel && penable && pwrite && addr_valid` 时 `r{paddr[1:0]} <= pwdata`；
读事务 `prdata = (psel && !pwrite) ? reg_read_data : 8'h00`
**验收标准**：写后读回同值；`paddr[7:2] != 0` 时读写都不作用于寄存器

### 地址越界错误
**级别**：P1
**描述**：`pslverr = psel && penable && !addr_valid`
**验收标准**：访问 0x04 及以上地址时 `pslverr` 拉起

### 复位
**级别**：P0
**描述**：`preset_n` 低有效异步复位，复位后 `r0`-`r3` 全部清零
**验收标准**：复位释放后读 0x00-0x03 均为 0

## 3. 接口规范

| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| pclk | 1 | INPUT | Clock | APB 时钟 |
| preset_n | 1 | INPUT | Reset | 异步复位低有效 |
| paddr | 8 | INPUT | APB | 地址（仅 `[1:0]` 参与译码） |
| pwdata | 8 | INPUT | APB | 写数据 |
| prdata | 8 | OUTPUT | APB | 读数据 |
| pwrite | 1 | INPUT | APB | 写使能 |
| psel | 1 | INPUT | APB | 片选 |
| penable | 1 | INPUT | APB | 使能 |
| pready | 1 | OUTPUT | APB | 恒为 1（无等待态） |
| pslverr | 1 | OUTPUT | APB | 地址越界错误（访问阶段） |

## 4. 寄存器映射

| 偏移 | 名称 | 读写 | 位宽 | 复位值 | 描述 |
|------|------|------|------|--------|------|
| 0x00 | r0 | RW | 8 | 0x00 | 通用寄存器 0 |
| 0x01 | r1 | RW | 8 | 0x00 | 通用寄存器 1 |
| 0x02 | r2 | RW | 8 | 0x00 | 通用寄存器 2 |
| 0x03 | r3 | RW | 8 | 0x00 | 通用寄存器 3 |
| 0x04+ | — | — | — | — | **越界**：写忽略、读回 0、`pslverr` 拉起 |
