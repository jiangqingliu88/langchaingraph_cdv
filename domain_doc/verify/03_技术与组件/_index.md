---
id: KB-DV-TECH
title: 技术与组件
type: 域索引
version: 0.1
status: 草稿
maintainer: 验证方法学组
created: 2026-10-12
updated: 2026-10-12
tags: [IC验证, 知识库, 域索引]
---

# 技术与组件

**位置**：`verify/` 验证翼

> **手里敲的东西**：SystemVerilog 语言、UVM 组件（driver/monitor/scoreboard…）、断言与覆盖率语法、RAL。

## 子域

| 子目录 | 放什么 |
|---|---|
| `SystemVerilog` | 语言特性：类、随机约束、接口、时钟块 |
| `UVM组件` | driver / monitor / agent / env / test / sequence / scoreboard |
| `断言与覆盖率` | SVA 断言、covergroup / coverpoint / cross |
| `RAL` | 寄存器抽象层：adapter / predictor / 镜像 |


## 边界

**不放**：**为什么这么分** → `verify/02_验证方法学/`；某个仿真器的编译选项 → `verify/04_工具与脚本/`。

这条比「放什么」更重要 —— 一个知识库烂掉，几乎总是从「什么都往里塞」开始的。

## 本域条目

| id | 标题 | 类型 | 状态 | 路径 |
|---|---|---|---|---|
| KB-DV-TECH-001 | 随机约束怎么写才是可控的 —— 分布、求解、冲突排查 | 方法卡 | 草稿 | [随机约束.md](SystemVerilog/随机约束.md) |
| KB-DV-TECH-002 | UVM 组件职责与边界 —— 这段逻辑该放谁那 | 组件卡 | 草稿 | [UVM组件职责与边界.md](UVM组件/UVM组件职责与边界.md) |
| KB-DV-TECH-003 | 写一条有价值的断言 —— 蕴含、采样语义与假信心 | 方法卡 | 草稿 | [SVA断言.md](断言与覆盖率/SVA断言.md) |
| KB-DV-TECH-004 | RAL 寄存器抽象层 —— adapter / predictor / mirror 的职责与失同步 | 组件卡 | 草稿 | [RAL寄存器抽象层.md](RAL/RAL寄存器抽象层.md) |
| KB-DV-TECH-005 | UVM 代码风格 —— 每条规范防的是什么 | 方法卡 | 草稿 | [UVM代码风格.md](SystemVerilog/UVM代码风格.md) |
| KB-DV-TECH-006 | 环境配置的两层校验 —— 语法层与语义层为什么必须分开 | 方法卡 | 草稿 | [环境配置的两层校验.md](UVM组件/环境配置的两层校验.md) |

## 加卡片

用 `04_治理运营/卡片模板.md` 的模板，落到本域下；然后
**同时**更新本文件的表格与 `01_术语与索引/索引.csv`（有测试/脚本核对两边是否一致）。
