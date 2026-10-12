---
id: KB-DV-PROT
title: 协议与 VIP
type: 域索引
version: 0.1
status: 草稿
maintainer: 验证方法学组
created: 2026-10-12
updated: 2026-10-12
tags: [IC验证, 知识库, 域索引]
---

# 协议与 VIP

**位置**：`verify/` 验证翼

> **协议本身**：总线时序、字段语义、合法/非法组合，以及对应 VIP 怎么接。

## 子域

| 子目录 | 放什么 |
|---|---|
| `AMBA` | AXI / AHB / APB / ACE / CHI |
| `PCIe` | （待补） |
| `CXL` | （待补） |
| `USB` | （待补） |
| `DDR` | （待补） |
| `Ethernet` | （待补） |
| `MIPI` | （待补） |
| `UCIe` | （待补） |
| `低速接口` | SPI / I2C / UART / JTAG / CAN |


## 边界

**不放**：VIP 的**代码怎么写** → `verify/03_技术与组件/`；某个仿真器的编译选项 → `verify/04_工具与脚本/`。

这条比「放什么」更重要 —— 一个知识库烂掉，几乎总是从「什么都往里塞」开始的。

## 本域条目

| id | 标题 | 类型 | 状态 | 路径 |
|---|---|---|---|---|
| KB-DV-PROT-001 | AMBA 总线（AXI / AHB / APB）——握手时序、合法/非法组合与验证重点 | 协议卡 | 草稿 | [AMBA总线.md](AMBA/AMBA总线.md) |
| KB-DV-PROT-002 | 低速接口（SPI / I2C / UART / JTAG）——时序语义与验证重点 | 协议卡 | 草稿 | [低速接口.md](低速接口/低速接口.md) |
| KB-DV-PROT-003 | PCIe——分层结构、TLP 类型、流量控制与排序规则、验证重点 | 协议卡 | 草稿 | [PCIe.md](PCIe/PCIe.md) |
| KB-DV-PROT-004 | CXL——相对 PCIe 增加了什么（设备类型、一致性协议）与验证重点 | 协议卡 | 草稿 | [CXL.md](CXL/CXL.md) |
| KB-DV-PROT-005 | USB 验证要点 —— 端点与传输类型、枚举过程、以及该怎么写它的 coverpoint | 协议卡 | 草稿 | [USB.md](USB/USB.md) |
| KB-DV-PROT-006 | MIPI 验证要点 —— CSI-2 / DSI 的 Lane 与包结构、虚拟通道、低功耗模式怎么覆盖 | 协议卡 | 草稿 | [MIPI.md](MIPI/MIPI.md) |
| KB-DV-PROT-007 | UCIe 验证要点 —— Die-to-Die 的分层、链路训练、侧带通道该怎么验证 | 协议卡 | 草稿 | [UCIe.md](UCIe/UCIe.md) |
| KB-DV-PROT-008 | DDR 验证要点 —— 命令与寻址、时序参数的语义与相互关系、刷新该怎么覆盖 | 协议卡 | 草稿 | [DDR.md](DDR/DDR.md) |
| KB-DV-PROT-009 | Ethernet 验证要点 —— 帧结构、MAC 层、流控与背压该怎么覆盖 | 协议卡 | 草稿 | [Ethernet.md](Ethernet/Ethernet.md) |

## 加卡片

用 `04_治理运营/卡片模板.md` 的模板，落到本域下；然后
**同时**更新本文件的表格与 `01_术语与索引/索引.csv`（有测试/脚本核对两边是否一致）。
