---
id: KB-DV-PROT-007
title: UCIe 验证要点 —— Die-to-Die 的分层、链路训练、侧带通道该怎么验证
type: 协议卡
domain: 协议与VIP
subdomain: UCIe
tags: [UCIe]
roles: [DV工程师, 架构师, Emulation]
stages: [计划, TB架构, 覆盖率]
summary: >
  UCIe 是 Die-to-Die 互连的「官方标准壳」，它把 PCIe/CXL 的协议层套在一层新的物理/链路层上。
  验证的重点不在数据搬运，而在**链路训练能否收敛、侧带通道能否独立工作、以及主带与侧带的纠错分工**。
  本卡给分层骨架、训练状态机、合法非法组合、检查点与覆盖维度。
applicable: |
  验证 UCIe 的 Die-to-Die 适配层 / 物理层 / 链路层；验证 chiplet 之间（如 2.5D/3D 封装内）的
  互连；评审一个 UCIe 验证计划是否只测了「数据通了」。
not_applicable: |
  验证封装内相邻 Die 的纯并行接口（如 AIB / 厂商私有 D2D）—— 协议栈不同；
  验证片内总线（AXI/CHI）—— 那是片上互连，不是 D2D；
  只关心封装的 SI/PI 或 bump 布局 —— 那是封装设计的活。
prerequisites: [接口时序与协议基础, 功能覆盖率建模, PCIe 验证要点]
references: [UCIe Specification（分层、链路训练、侧带见正文对应章节）]
related: [KB-DV-COV-001]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# UCIe 验证要点

> **一句话**：UCIe 不是「更快的 PCIe」，而是**把 PCIe/CXL 协议层架在一层新的 D2D 物理层上**。验证的核心是 **链路能否训练到可用、侧带能否独立工作和纠错分工是否被遵守**，而不是搬运速度。

## 一、信号与时序

### 分层（从下往上）

| 层 | 职责 | 验证关注 |
|---|---|---|
| **物理层（PHY）** | 高速串行/并行信号、通道对齐、修复 | 通道数、lane 冗余与修复、训练序列 |
| **Die-to-Die 适配层（D2D Adapter）** | 链路管理、CRC/重传、参数协商 | 链路状态机、重传、流控 |
| **协议层（复用 PCIe / CXL / 流式）** | 上层事务（内存/IO/CXL.cache） | 复用哪套协议决定上层检查点 |

**关键判据**：**UCIe 的物理层被明确定义成可插拔的**（标准 PHY vs 厂商定制 PHY）—— 验证计划里必须写清用的是哪一种，否则「通道数」这个维度会扯不清。

### 两条独立通道

| 通道 | 用途 | 特征 |
|---|---|---|
| **主带（Mainband）** | 承载高速数据 | 高速、需要训练、有 CRC/重传纠错 |
| **侧带（Sideband）** | 低速控制/管理/训练协商 | 低速、独立、可用于把主带从坏状态救回来 |

**关键判据**：**侧带与主带是两条独立链路**。一个常见的错误假设是「主带挂了侧带也挂」——实际上侧带正是用来协商主带参数的，验证必须证明**主带失效时侧带仍可工作**。

### 链路训练

链路不是上电即通，而是**双方通过训练序列协商出可用参数**的过程。训练包含参数协商（速率/宽度/通道映射等）与对齐（lane 间 deskew）。

---

## 二、合法/非法组合

### 合法组合

| 维度 | 合法取值空间 |
|---|---|
| 通道/宽度 | 训练后协商出的有效宽度（按配置，需查实现） |
| 速率 | 协商后的速率档 |
| 协议复用 | PCIe / CXL / 流式（Streaming）—— 决定上层语义 |
| PHY 类型 | 标准封装 PHY / 高级封装 PHY（面朝上/面朝下） |
| 训练状态 | RESET → 训练中 → ACTIVE → 低功耗 → 重训 |

### 非法/异常组合（必须主动造）

| 非法场景 | 期望行为 |
|---|---|
| 一部分 lane 训练失败 | 用冗余 lane 修复后恢复；修不好则应报告而非静默半通 |
| 训练超时 | 重试 / 降速 / 报错，不能死等 |
| 主带进错误态 | 侧带仍能工作，并可触发主带重训 |
| 训练中收到非训练数据 | 按状态机忽略或报错，不得误当有效数据 |
| 参数协商结果不一致（双方选的速率/宽度不同） | 必须能检测并重新协商 |
| CRC 错 / 重传请求 | 重传路径正确，重传耗尽后有定义好的失败行为 |
| 电源状态切换（进入/退出低功耗） | 切换序列正确，退出后链路可用 |
| 侧带单独复位 | 主带状态不受影响 / 或按规范联动 |

---

## 三、检查点

| 检查点 | 断言方向 |
|---|---|
| 训练收敛 | 训练能否从冷启动到达 ACTIVE，且参数双方一致 |
| lane 修复 | 冗余 lane 修复路径被激活且不影响数据完整性 |
| 状态机 | 链路状态转移弧完整，非法转移被拦截 |
| 侧带独立 | 主带异常时侧带仍可收发管理包 |
| 纠错 | CRC 错被检测、重传被触发、重传耗尽有定义行为 |
| 流控 | 背压/信用机制下不丢包、不溢出 |
| 协议复用 | 复用的上层协议（PCIe/CXL）检查点在其层验证 |
| 电源状态 | 低功耗进出序列正确，退出后可恢复通信 |
| 数据一致性 | 端到端负载逐字节一致 |

### 覆盖点方向

```systemverilog
// 1) 分层 × 通道 —— UCIe 的第一维
cp_layer    : coverpoint layer { bins phy={PHY}; bins d2d={D2D}; bins proto={PROTO}; }
cp_channel  : coverpoint channel { bins mainband={MAIN}; bins sideband={SIDE}; }
X_layer_ch  : cross cp_layer, cp_channel;

// 2) 链路训练状态机：状态 + 转移弧 + 非法弧
cp_link_state: coverpoint link_state {
  bins reset={RESET}; bins training={TRAINING}; bins active={ACTIVE};
  bins low_power={LOW_POWER}; bins retrain={RETRAIN}; bins error={ERROR};
}
cp_link_trans: coverpoint link_state {
  bins reset_train = (RESET => TRAINING);
  bins train_active= (TRAINING => ACTIVE);
  bins active_lp   = (ACTIVE => LOW_POWER);
  bins active_re   = (ACTIVE => RETRAIN);
  bins err_recover = (ERROR => TRAINING);
}
illegal_bins skip_train = (RESET => ACTIVE);

// 3) 参数协商 —— 双方结果必须一致
cp_speed    : coverpoint neg_speed  { bins low={SPD_LOW}; bins mid={SPD_MID}; bins high={SPD_HIGH}; }
cp_width    : coverpoint neg_width  { bins w8={8}; bins w16={16}; bins w32={32}; bins w64={64}; }
cp_neg_match: coverpoint neg_result { bins match={MATCH}; bins mismatch={MISMATCH}; }
X_spd_width : cross cp_speed, cp_width;

// 4) Lane 健康与修复
cp_lane_health: coverpoint lane_health { bins healthy={HEALTHY}; bins weak={WEAK}; bins dead={DEAD}; }
cp_repair     : coverpoint repair { bins none={NONE}; bins spare_used={SPARE}; bins degraded={DEGRADED}; bins fail={FAIL}; }
cp_lane_count : coverpoint lane_count { bins one_dead={1}; bins two_dead={2}; bins all_dead={ALL}; }

// 5) 校验与重传（主带纠错）
cp_crc      : coverpoint crc_result { bins ok={CRC_OK}; bins bad={CRC_BAD}; }
cp_retry    : coverpoint retry_cnt  { bins none={0}; bins once={1}; bins many={[2:7]}; bins exhausted={EXHAUST}; }
cp_ack_nak  : coverpoint ack_nak    { bins ack={ACK}; bins nak={NAK}; bins timeout={TIMEOUT}; }

// 6) 侧带独立工作 —— 关键是「主带坏时侧带好」
cp_sb_work  : coverpoint sb_status { bins both_ok={BOTH_OK}; bins mb_bad_sb_ok={MB_BAD_SB_OK}; bins sb_bad={SB_BAD}; }
cp_sb_msg   : coverpoint sb_msg    { bins mgmt={MGMT}; bins train_param={TRAIN_PARAM}; bins alert={ALERT}; }

// 7) 电源状态切换
cp_pwr_state: coverpoint pwr_state { bins on={ON}; bins l1={L1}; bins l2={L2}; bins off={OFF}; }
cp_pwr_trans: coverpoint pwr_state { bins down_l1 = (ON => L1); bins up_l1 = (L1 => ON); bins down_l2 = (L1 => L2); }

// 8) 协议复用
cp_proto_use: coverpoint proto_use { bins pcie={PCIE}; bins cxl={CXL}; bins streaming={STREAM}; }
```

**判据**：一个 UCIe 覆盖模型如果只有「数据端到端通了」而没有 `cp_link_trans`（训练转移弧）和 `cp_sb_work`（侧带在主带坏时仍工作），它漏掉的正是 D2D 互连最核心的鲁棒性 —— 链路训练不收敛是 chiplet 流片后最常见、也最贵的现场问题。

---

## 四、VIP 怎么接（通用做法）

**注意：本卡写的是通用做法，不声称任何仓库有哪个 VIP。**

| 环节 | 做法 |
|---|---|
| 分层建模 | PHY 行为模型 + D2D Adapter VIP + 上层协议 VIP，三层分别可观测 |
| 双端对跑 | 两个 die 模型对跑（或 DUT 与参考模型对跑），比对端到端数据 |
| 训练建模 | 把链路训练状态机做成序列，能注入「部分 lane 失败」「训练超时」 |
| 侧带建模 | 侧带单独建模并可单独控制，用于验证主带坏时侧带可用 |
| lane 修复 | 显式注入 lane 失效，覆盖冗余修复与降级 |
| 错误注入 | 在 D2D 适配层注 CRC 错、丢包、乱序，不在 PHY 电气层注 |
| 电源序列 | 建模低功耗进出序列，覆盖状态切换边界 |
| 协议复用 | 复用 PCIe/CXL 时，其检查点回到对应协议卡里写 |

**接入判据**：VIP 能不能**分别控制主带与侧带**？不能分开控制主带的模型，就没法验证「主带失效、侧带救场」这条最关键的路径。

---

## 五、坑

| 坑 | 为什么诱人 | 后果 | 修正 |
|---|---|---|---|
| 只验证「数据端到端通了」 | 通了看着就完成了 | 训练、纠错、侧带、电源全漏 | 按链路状态机与通道维度建模 |
| 假设主带侧带一起死活 | 物理上挨在一起 | 侧带独立性的验证被跳过 | 显式造「主带坏、侧带好」场景 |
| 只测理想训练 | 冷启动一次就通 | 部分 lane 坏、超时、参数不一致全漏 | 注入 lane 失效 / 超时 / 参数不匹配 |
| 忽略参数协商一致性 | 双方都照默认值 | 双方选了不同速率/宽度时的处理未验证 | 协商结果作为 coverpoint 交叉 |
| 在 PHY 层注错 | 方便 | D2D 适配层的 CRC/重传/乱序覆盖不到 | 错误注入放在适配层包粒度 |
| 不区分标准 PHY 与定制 PHY | 都用「UCIe」称呼 | 通道数与训练细节扯不清 | 计划里写清 PHY 类型 |
| 把 UCIe 当 PCIe 验 | 协议层复用 PCIe | 新引入的 D2D 层被忽略 | D2D 层单独建检查点，PCIe 检查点回其卡 |
| 电源状态切换无覆盖 | 默认常开 | 低功耗进出时序与恢复未验证 | 电源状态机 + 转移弧覆盖 |

**最值钱的两条**：**只测数据通路** 和 **假设主带侧带同命运** —— 前者让链路训练的全部失败模式逃逸，后者恰好漏掉了 UCIe 侧带存在的设计意图。
