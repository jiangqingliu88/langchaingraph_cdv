---
id: KB-DV-PROT-001
title: AMBA 总线（AXI / AHB / APB）——握手时序、合法/非法组合与验证重点
type: 协议卡
domain: 协议与VIP
subdomain: AMBA
tags: [AXI, AHB, APB]
roles: [DV工程师, 设计工程师, 架构师]
stages: [计划, TB架构, 编码, 调试, 覆盖率]
summary: >
  AMBA 三代总线（APB / AHB / AXI）的共性是「用握手代替时钟约定」，差异在通道数量、
  流水线深度与乱序能力。本卡按「握手时序 → 合法/非法组合 → 检查点 → VIP 怎么接」，
  给出每一代该验什么，以及能直接落成 coverpoint 的覆盖维度。
applicable: |
  设计或验证一个 AMBA 接口（主/从/互连/桥），要判断「这个接口的协议检查点该怎么列」；
  要给 AXI/AHB/APB 写覆盖模型、写断言、写 VIP 的 scoreboard 检查表。
not_applicable: |
  要验的是片外高速串行协议（PCIe / CXL / USB / DDR）—— 那些是分组化、分层、带链路训练的
  完全不同模型，去 `verify/05_协议与VIP/PCIe/` 等；
  要验 CHI / ACE 一致性协议 —— 那是 cache 一致性协议，握手之外还有 coherency 状态机，
  本卡只覆盖 AXI/AHB/APB 这一层；
  要查某厂商 VIP 的 API 怎么写 —— 去 `verify/03_技术与组件/`，本卡只讲协议本身的检查点。
prerequisites: [接口时序与协议基础]
references: []
related: [KB-DV-PROT-002, KB-DV-COV-001]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# AMBA 总线（AXI / AHB / APB）

> **一句话**：三代总线都在回答「一个主怎么把一个传输交给一个从」，但 APB 是一次一个、
> AHB 是一拍地址多拍数据、AXI 是五条独立通道全流水。**握手时序的差异，直接决定
> 「哪些组合是合法的」—— 而合法/非法组合的边界，就是你要验的东西。**

## 一、信号与时序：三代对照

AMBA 的握手只有一条核心规则：**VALID 不能等 READY，READY 可以等 VALID。**

| 通道 / 信号 | APB | AHB | AXI |
|---|---|---|---|
| 请求表达 | `PSEL` + `PENABLE`（两拍） | `HSEL` + `HTRANS` + 地址 | `AW`/`AR` 独立地址通道 |
| 数据 | `PWDATA`/`PRDATA` 单拍 | `HWDATA`/`HRDATA` 多拍 | `W`/`R` 独立数据通道，带 `WSTRB` |
| 握手 | `PREADY` 拉长访问 | `HREADY` 拉长传输 | `AWVALID/AWREADY`、`WVALID/WREADY`、`BVALID/BREADY`… |
| 流水线 | 无（一拍地址一拍数据） | 地址相位 / 数据相位（2 拍流水） | 地址与数据完全解耦，可乱序 |
| 乱序 | 不支持 | 不支持（保序） | 支持，靠 ID 区分 |
| 突发 | 不支持（一次一笔） | `HBURST`（INCR/WRAP） | `AxLEN` / `AxSIZE` / `AxBURST` |

### AXI 的五通道与两条依赖

| 通道 | 方向 | 携带 | 谁依赖谁 |
|---|---|---|---|
| 写地址 `AW` | 主→从 | `AWID/AWADDR/AWLEN/AWSIZE/AWBURST` + 属性 | — |
| 写数据 `W` | 主→从 | `WDATA/WSTRB/WLAST` | 与 `AW` 无顺序要求（可先数据后地址） |
| 写响应 `B` | 从→主 | `BID/BRESP` | 必须等 `AW` 与 `W` 都完成 |
| 读地址 `AR` | 主→从 | `ARID/ARADDR/ARLEN/ARSIZE/ARBURST` | — |
| 读数据 `R` | 从→主 | `RID/RDATA/RRESP/RLAST` | 必须等 `AR` 完成 |

**看时序抓这一条就够**：`VALID` 一旦拉高，**在该次握手完成前不得撤销，且载荷必须保持稳定**；
`READY` 可以在 `VALID` 之前任意拉高，也允许中途撤销。违反这一条的所有行为都归入「非法组合」。

## 二、合法 / 非法组合

### 2.1 握手层（三代通用）

| 组合 | 合法性 | 该不该验 |
|---|---|---|
| VALID 先高，READY 后到 | 合法 | 必验（最常见的背压路径） |
| READY 先高，VALID 后到 | 合法 | 必验（零等待路径） |
| 两者同拍高 | 合法 | 必验 |
| VALID 高后撤销 | **非法** | 写断言，仿真会报、硬件可能不保证 |
| VALID 高时数据跳变 | **非法** | 写断言——这一条最常在「地址对齐/字节选通」上翻车 |

### 2.2 AXI 传输层

| 组合 | 合法性 | 该不该验 |
|---|---|---|
| 写数据早于写地址到达 | 合法 | 必验（从机不能假定先见地址） |
| `AWLEN` 与 `WLAST` 不匹配 | **非法** | 长度、`WLAST` 必须自洽 |
| `AxSIZE` 与 `AxADDR` 对齐冲突 | **非法** | 非对齐首拍行为要按规范判定 |
| 跨 4KB 边界的突发 | **非法** | AXI 铁律：一个突发不得跨 4KB 边界 |
| 写响应 `BID` 与任一未完成 `AWID` 对不上 | **非法** | 检查响应的归属 |
| 乱序完成 | 合法 | 必验——同 ID 保序、不同 ID 可乱序 |
| `AxBURST` 为保留编码 | **非法** | 保留值必须被拒绝或按规范处理 |

### 2.3 握手 × 响应组合（最容易只写一半的地方）

真正的覆盖点在**激励 × 结果**的交叉上，不是单独一类：

```systemverilog
// AXI：传输类型 × 响应 × 背压（覆盖模型骨架）
cp_trans : coverpoint trans { bins rd = {READ}; bins wr = {WRITE}; }
cp_resp  : coverpoint resp  { bins okay = {OKAY}; bins exokay = {EXOKAY};
                              bins slverr = {SLVERR}; bins decerr = {DECERR}; }
cp_burst : coverpoint burst { bins len1 = {1}; bins lenN = {[2:15]}; bins len16 = {16}; }
cp_bp    : coverpoint bp    { bins no_wait = {NO_WAIT}; bins some_wait = {WAIT};
                              bins max_wait = {MAX_WAIT}; }
X_trans_resp_bp: cross cp_trans, cp_resp, cp_bp;
```

## 三、检查点

按「协议层 → 结构层」两级列，两层都要有。

| 层级 | 检查点 | 手段 |
|---|---|---|
| 握手稳定性 | VALID 拉高后不撤销、载荷不变 | 断言（每通道一条） |
| 长度自洽 | `AxLEN` 与实际拍数、`LAST` 一致 | 断言 + scoreboard |
| 地址约束 | 不跨 4KB、对齐与 SIZE 匹配 | 断言 |
| ID 保序 | 同 ID 读/写完成顺序；不同 ID 不约束 | scoreboard 按 ID 分桶核对 |
| 响应合法性 | `RESP` 取值 + 与请求类型匹配 | 覆盖点 `illegal_bins` |
| 背压 | 每通道都能被独立拉长（含最坏等待） | 覆盖点 + 定向用例 |
| 死锁 / 活锁 | 通道互等不出现循环依赖 | 形式验证 / 长跑回归 |
| 边界水位 | 互连 FIFO 满/空时行为 | 覆盖点（满时写、空时读） |

**AHB / APB 的差异检查点**：AHB 要额外查 `HREADY` 插入等待态时**地址相位是否被正确保持**、
转移类型（IDLE / BUSY / NONSEQ / SEQ）与突发的对应；APB 要查 `PSEL`→`PENABLE` 两拍的
先后与 `PREADY` 拉长时的 `PENABLE` 保持。

## 四、VIP 怎么接（通用做法）

不假设存在哪个具体 VIP，只说结构上通用怎么接。

| 部件 | 职责 | 接的时候注意 |
|---|---|---|
| master agent | 产生激励（driver 按握手规则挂起/推进） | driver 必须实现「VALID 不撤、READY 可等」；别在 driver 里写死零等待 |
| slave agent | 响应请求（可选随机背压） | 背压策略要可配，才能覆盖 `max_wait` |
| monitor | 旁路采样，重建事务 | 采样点放在**握手达成的那一拍**，不是 VALID 或 READY 单独一拍 |
| 协议检查器 | 直接接在 pin 上，独立于 monitor | 检查器与激励解耦，才能抓到 driver 自己的违规 |
| scoreboard | 事务级比对 | 按 ID 分桶处理乱序；读通道与写通道分别建模 |

**接 VIP 的常见误区**：把协议检查塞进 monitor（激励错了检查器跟着错，抓不到）；
monitor 采样时机取 VALID 而非握手拍（背压路径全部采错）。

## 五、能写出它的 coverpoint——本卡的出口

每张协议卡的成功标准是：**看完能列出该协议的 coverpoint 方向**。AMBA 的覆盖维度清单：

| 维度 | 覆盖点方向 |
|---|---|
| 传输类型 | 读 / 写，单拍 / 突发 |
| 突发长度 | 1 / 中间值 / 最大（AXI 16） |
| 突发类型 | INCR / WRAP / FIXED（AXI），INCR/WRAP（AHB） |
| 响应类型 | OKAY / EXOKAY / SLVERR / DECERR |
| 背压 | 每通道独立拉长，含最大等待 |
| 地址对齐 | 对齐 / 非对齐 / 跨边界（非法要 `illegal_bins`） |
| ID 顺序 | 同 ID 保序 / 异 ID 乱序完成 |
| 并发 | 读写同时进行、多 ID 交叉 |
| 非法 | VALID 撤销、长度不符、保留编码 |

## 六、坑

| 坑 | 为什么诱人 | 修正 |
|---|---|---|
| 只在零等待下跑通就收工 | 零等待路径最"干净"，波形好看 | 背压是最容易藏 bug 的地方，必须定向加长等待 |
| 把"仿真能过"当"硬件保证" | 仿真里 VALID 撤销常被容忍 | 稳定性的保证来自断言与规范，不是仿真器默认行为 |
| monitor 采样时机随手取 VALID | 代码更好写 | 必须取握手达成拍，否则背压路径全采错 |
| 非法组合不写 `illegal_bins` | 写了怕 0% 难看 | 非法不可达要显式声明，否则覆盖 100% 是假象 |
| 只验功能不验协议 | 功能对了就以为协议对 | 协议违规常不表现为数据错，只表现为时序违规 |
| 跨 4KB 约束当"建议" | 仿真里跨了也没崩 | 这是 AXI 硬约束，得用断言挡住 |
| AHB 忘了等待态保持 | 只在 `HREADY` 恒高时验 | 等待态下地址/控制必须被保持 |

## 七、出口

| 下一步 | 去哪 |
|---|---|
| 覆盖点 → 完整覆盖模型 | `verify/07_度量与报告/覆盖率模型/` |
| 覆盖率收敛（缺口分析、补激励） | `verify/07_度量与报告/覆盖率收敛/` |
| 目标值 / waiver 门槛 / 签核标准 | `02_流程与签核/` |
| VIP 组件代码结构 | `verify/03_技术与组件/` |
