---
document_id: ICD-DOC-004
title: "接口控制文档 (ICD)"
project: "ALU IP"
version: 1.0
date: 2026-08-09
author: SignOffAI
status: Review
---

# 接口控制文档 (ICD)

| 项目 | 内容 |
|------|------|
| **文档ID** | `ICD-DOC-004` |
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

本文档定义 **apb_uart** 的所有外部接口，供前端设计(DE)和功能验证(DV)共同使用。

## 2. 接口清单

| 接口名 | 类型 | 数据宽度 | 时钟 | 方向 | 描述 |
|--------|------|----------|------|------|------|
| `apb_slave` | APB | 8 | pclk | In/Out | 8 signals |
| `uart_serial` | UART | 1 | pclk | In/Out | 2 signals |
| `interrupt` | Interrupt | 1 | pclk | In/Out | 1 signals |

## 3. 接口时序

```
         ┌───┐   ┌───┐   ┌───┐
  clk    │   │   │   │   │   │
       ──┘   └───┘   └───┘   └──
         ┌───────────┐
  valid  │           │
       ──┘           └──────────
         ┌───────────┐
  data   │XXXXXXXXXXX│
       ──┘           └──────────
                 ┌───┐
  ready          │   │
       ──────────┘   └──────────
```

## 4. 信号映射 (DE ↔ DV)

| 信号名 | DE 端口 | DV Interface | 位宽 | 方向(DE) | 方向(DV) |
|--------|---------|-------------|------|----------|----------|
| pclk | pclk | vif.pclk | 8 | output | input |
| preset_n | preset_n | vif.preset_n | 8 | output | input |
| paddr | paddr | vif.paddr | 8 | output | input |
| pwdata | pwdata | vif.pwdata | 8 | output | input |
| prdata | prdata | vif.prdata | 8 | output | input |
| pwrite | pwrite | vif.pwrite | 8 | output | input |
| psel | psel | vif.psel | 8 | output | input |
| penable | penable | vif.penable | 8 | output | input |
| tx | tx | vif.tx | 1 | output | input |
| rx | rx | vif.rx | 1 | output | input |
| irq | irq | vif.irq | 1 | output | input |



---

*文档ID: ICD-DOC-004 | 自动生成于 2026-08-09 08:16:36 | SignOffAI Pipeline Documentation System*
