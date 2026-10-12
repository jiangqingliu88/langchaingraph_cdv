---
id: KB-DV-TOOL
title: 工具与脚本
type: 域索引
version: 0.1
status: 草稿
maintainer: 验证方法学组
created: 2026-10-12
updated: 2026-10-12
tags: [IC验证, 知识库, 域索引]
---

# 工具与脚本

**位置**：`verify/` 验证翼

> **具体工具怎么用**：命令行、开关、常见报错、脚本与 CI。

## 子域

| 子目录 | 放什么 |
|---|---|
| `VCS` | Synopsys VCS |
| `Xcelium` | Cadence Xcelium |
| `Questa` | Siemens Questa / ModelSim |
| `Verdi` | 波形与调试（nWave / nTrace） |
| `JasperGold` | Cadence 形式验证 |
| `VC_Formal` | Synopsys 形式验证 |
| `SpyGlass` | Lint / CDC / RDC |
| `脚本与CI` | Tcl / Python / Makefile / 回归流水线 |


## 边界

**不放**：工具**无关**的方法 → `verify/02_验证方法学/`；协议本身的时序 → `verify/05_协议与VIP/`。

这条比「放什么」更重要 —— 一个知识库烂掉，几乎总是从「什么都往里塞」开始的。

## 本域条目

| id | 标题 | 类型 | 状态 | 路径 |
|---|---|---|---|---|
| KB-DV-TOOL-001 | VCS 编译、仿真与覆盖率命令速查（含常见报错对号入座） | 工具卡 | 草稿 | [VCS.md](VCS/VCS.md) |
| KB-DV-TOOL-002 | Questa / ModelSim 的 vlog / vsim / vcover 命令速查与报错对号入座 | 工具卡 | 草稿 | [Questa.md](Questa/Questa.md) |
| KB-DV-TOOL-003 | Verdi 打开 FSDB 做波形与源码调试（nWave / nTrace / nSchema） | 工具卡 | 草稿 | [Verdi.md](Verdi/Verdi.md) |
| KB-DV-TOOL-004 | 回归流水线：一次回归怎么组织才是可复现的 | 方法卡 | 草稿 | [回归流水线.md](脚本与CI/回归流水线.md) |
| KB-DV-TOOL-005 | Xcelium：仿真编译运行、覆盖率采集与常见报错 | 工具卡 | 草稿 | [Xcelium.md](Xcelium/Xcelium.md) |
| KB-DV-TOOL-006 | JasperGold：属性怎么组织、反例怎么看、三种结论各意味着什么 | 工具卡 | 草稿 | [JasperGold.md](JasperGold/JasperGold.md) |
| KB-DV-TOOL-007 | VC Formal：从仿真资产切入的形式验证，与 JasperGold 的分工 | 工具卡 | 草稿 | [VC_Formal.md](VC_Formal/VC_Formal.md) |
| KB-DV-TOOL-008 | SpyGlass：Lint / CDC / RDC 检查——什么该认真看、什么该 waiver、CDC 违例怎么判真伪 | 工具卡 | 草稿 | [SpyGlass.md](SpyGlass/SpyGlass.md) |

## 加卡片

用 `04_治理运营/卡片模板.md` 的模板，落到本域下；然后
**同时**更新本文件的表格与 `01_术语与索引/索引.csv`（有测试/脚本核对两边是否一致）。
