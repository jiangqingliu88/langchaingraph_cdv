---
document_id: RTL-DOC-005
title: "RTL 签核报告"
project: "ALU IP"
version: 1.0
date: 2026-08-08
author: SignOffAI
status: Review
---

# RTL 签核报告

| 项目 | 内容 |
|------|------|
| **文档ID** | `RTL-DOC-005` |
| **版本** | 1.0 |
| **日期** | 2026-08-08 |
| **作者** | SignOffAI |
| **状态** | Review |
| **项目** | ALU IP — 32bit 算术逻辑单元 |

---

## 修订历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-08-08 | SignOffAI | 初始版本，由 SignOffAI 管道自动生成 |

---


## 1. RTL 质量检查

| 检查项 | 工具 | 状态 | 结果 |
|--------|------|------|------|
| Lint (设计规则检查) | SpyGlass / Verilator | ⏳ | 待运行 |
| CDC (跨时钟域检查) | SpyGlass CDC | ⏳ | 待运行 |
| RDC (复位域检查) | SpyGlass RDC | ⏳ | 待运行 |
| Synthesis (综合) | Design Compiler | ⏳ | 待运行 |
| Formal Equiv (形式验证) | Formality | ⏳ | 待运行 |
| STA (静态时序分析) | PrimeTime | ⏳ | 待运行 |

## 2. 设计参数

- **模块名称**: `-`
- **设计名称**: `-`
- **功能特性**: 0 项
- **寄存器数量**: 0 个

## 4. 交付物

| 文件 | 类型 | 状态 |
|------|------|------|
| `rtl/alu_core.v`      | RTL (Verilog)  | ⏳ |
| `rtl/alu_apb_if.v`    | RTL (Verilog)  | ⏳ |
| `rtl/alu_top.v`       | RTL (Verilog)  | ⏳ |
| `constraints/alu.sdc` | SDC Constraints| ⏳ |



---

*文档ID: RTL-DOC-005 | 自动生成于 2026-08-08 18:02:02 | SignOffAI Pipeline Documentation System*
