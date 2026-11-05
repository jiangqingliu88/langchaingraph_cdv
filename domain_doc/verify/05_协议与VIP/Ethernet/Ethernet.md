---
id: KB-DV-PROT-009
title: Ethernet 验证要点 —— 帧结构、MAC 层、流控与背压该怎么覆盖
type: 协议卡
domain: 协议与VIP
subdomain: Ethernet
tags: [Ethernet]
roles: [DV工程师, 架构师, Emulation]
stages: [计划, TB架构, 覆盖率]
summary: >
  Ethernet 验证的难点不在「帧发对」，而在**帧长/速率/流控这张组合网**：非法帧的处置、
  暂停帧的响应、以及背压下不丢帧。本卡给帧结构骨架、MAC 层要点、流控机制、
  合法非法组合、检查点与覆盖维度。
applicable: |
  验证以太网 MAC（含 MAC-PHY 接口如 GMII/RGMII/XGMII）、交换机端口、NIC；
  验证网络子系统与上层（PCIe/DMA）的交互。
not_applicable: |
  验证以太网 PHY 的模拟/SerDes 部分 —— 那是 PHY 设计，功能验证只到 MAC-PHY 数字接口；
  验证 TCP/IP 协议栈 —— 那是软件/网络层，不是 MAC 层功能验证；
  只关心 PCS/PMA 的编码与链路训练细节 —— 那偏 PHY 数字层，另有侧重。
prerequisites: [接口时序与协议基础, 功能覆盖率建模]
references: [IEEE 802.3（帧格式、MAC、流控章节）]
related: [KB-DV-COV-001]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# Ethernet 验证要点

> **一句话**：以太网 MAC 层验证的重点是 **帧长 × 帧类型 × 流控 × 背压** 这张组合网 —— 尤其是「非法/异常帧该丢还是该收」这条分界，它决定了网络能否在有错环境下仍然稳定。

## 一、信号与时序

### 帧结构（MAC 层的「一句话」）

| 字段 | 说明 |
|---|---|
| 前导码 / SFD | 收发双方对齐帧起始 |
| **目的 MAC 地址** | 6 字节；组播/广播由地址位区分 |
| **源 MAC 地址** | 6 字节 |
| 长度/类型 | 两义字段：值小于某阈值按长度解释，否则按 EtherType 解释 |
| **负载** | 上层数据，长度受最小/最大帧长约束 |
| 填充（Pad） | 负载不足最小帧长时补齐 |
| **FCS** | 帧校验序列；错了整帧丢 |

**关键判据**：**「长度/类型」是一个两义字段**，接收方要按阈值决定解释方式 —— 这是以太网验证里最容易写错的一处解析逻辑，必须两种解释路径都覆盖。

### MAC 层要点

| 能力 | 说明 | 验证关注 |
|---|---|---|
| 帧收发 / 地址过滤 | 组帧、解帧；单播/组播/广播/混杂 | 每种过滤模式的收/丢判定 |
| 帧长限制 | 最小/最大帧长（含巨帧配置） | 刚好在边界的帧怎么处理 |
| FCS 校验 | 计算与校验 | 错帧必须丢，不能上报 |
| 半双工 / 全双工 | 载波监听、冲突检测、退避；全双工无冲突 | 冲突、退避、迟到冲突、碰撞丢弃 |
| 统计计数 | 好的/坏的帧计数 | 计数与帧的最终命运一致 |
| MAC-PHY 接口 | GMII/RGMII/XGMII 等的收发时序 | 接口握手、时钟域、速率切换 |

### 流控与背压（本协议最值得细看的一块）

| 机制 | 说明 | 验证关注 |
|---|---|---|
| **暂停帧（PAUSE）** | 全双工流控：收方请求对端暂停一段时间 | 收到暂停帧后是否真的停发；暂停时长的量化；暂停中再收暂停帧 |
| **背压（半双工）** | 用载波冲突/延迟发送来施压 | 背压下不丢帧 |
| **反压到上游** | RX 侧缓冲满时把压力传回 MAC/PHY | 缓冲满时的丢帧策略与计数一致 |
| **优先级流控（PFC）** | 按优先级暂停某一类流量 | 只暂停指定优先级，其他不受影响 |

**关键判据**：**流控的核心是「暂停谁、暂停多久、暂停时新到的帧怎么办」**。暂停帧不是「停一下」这么简单 —— 时间量化单位、暂停中再收暂停帧的叠加规则、暂停到期前的提前恢复，都是必测边界。

---

## 二、合法/非法组合

### 合法帧

| 维度 | 合法取值空间 |
|---|---|
| 地址类型 | 单播 / 组播 / 广播 |
| 帧长 / 速率 | 最小帧长到最大帧长之间（含边界）；按配置的链路速率 |
| 类型 | 按 EtherType 解释（IPv4/IPv6/VLAN 等）/ 按长度解释 |
| VLAN 标签 | 无标签 / 单标签 / 多标签 |

### 非法/异常帧（必须主动造）

| 非法场景 | 期望行为 |
|---|---|
| FCS 错 | 整帧丢弃，不入统计的「好帧」，坏帧计数 +1 |
| 帧太短（低于最小帧长） | 丢弃，判定为坏帧/碰撞碎片 |
| 帧太长（超过最大帧长） | 丢弃或截断（按实现），不得当正常帧上报 |
| 前导码/SFD 缺或错 | 无法对齐，丢弃 |
| 目的地址非本机且非组播/广播 | 在非混杂模式下丢弃 |
| 长度字段与实际负载不符 | 按规范判定，不得静默接受 |
| 半双工下冲突 / 流控禁用时收到暂停帧 | 冲突退避重发、超上限丢弃并计数；流控禁用的暂停帧忽略，不改变发送行为 |

---

## 三、检查点

| 检查点 | 断言方向 |
|---|---|
| 帧完整性 / FCS | 前导/SFD/地址/类型/FCS 结构完整；错帧被丢弃且计数正确 |
| 帧长 / 地址过滤 / 两义字段 | 边界帧判定正确；各过滤模式收丢正确；长度/类型两种解释路径都被识别 |
| 流控响应与叠加 | 收到暂停帧后发送确实暂停、时长正确；暂停中再收暂停帧的处理正确 |
| 背压 | RX 缓冲满时丢帧策略与计数一致，不静默丢 |
| 半双工冲突 | 冲突检测、退避、重试上限正确 |
| 统计计数 | 各计数器与帧的实际命运一致 |
| MAC-PHY 接口 | 接口握手、速率/双工切换正确 |

### 覆盖点方向

```systemverilog
// 1) 帧长边界 —— 以太网的第一维
cp_frame_len: coverpoint frame_len {
  bins min={MIN_LEN}; bins min_plus1={MIN_LEN+1}; bins max={MAX_LEN};
  bins max_plus1={MAX_LEN+1}; bins too_short={[0:MIN_LEN-1]}; bins too_long={[MAX_LEN+1:$]};
  bins jumbo={JUMBO_LEN};
}

// 2) 地址与过滤
cp_dst_addr : coverpoint dst_kind { bins unicast={UNI}; bins multicast={MULTI}; bins broadcast={BCAST}; bins other={OTHER}; }
cp_rx_mode  : coverpoint rx_mode  { bins normal={NORMAL}; bins promiscuous={PROMISC}; bins all_multi={ALLMULTI}; }
X_addr_mode : cross cp_dst_addr, cp_rx_mode;

// 3) FCS 与坏帧
cp_fcs      : coverpoint fcs_ok { bins good={GOOD}; bins bad={BAD}; }
cp_bad_kind : coverpoint bad_kind { bins short_frame={RUNT}; bins long_frame={GIANT}; bins bad_fcs={FCS_ERR}; bins align_err={ALIGN}; }
cp_rx_result: coverpoint rx_result { bins accepted={ACCEPT}; bins dropped={DROP}; bins errored={ERROR}; }
X_bad_result: cross cp_bad_kind, cp_rx_result;

// 4) 长度/类型两义字段
cp_len_type : coverpoint lt_kind { bins as_length={LEN}; bins as_ethertype={TYPE}; bins boundary={BOUNDARY}; }
cp_ethertype: coverpoint ethertype { bins ipv4={16'h0800}; bins ipv6={16'h86DD}; bins vlan={16'h8100}; bins arp={16'h0806}; bins unknown={16'hFFFF}; }
cp_vlan_layers: coverpoint vlan_depth { bins none={0}; bins single={1}; bins double={2}; }

// 5) 流控：暂停帧 —— 本协议最独有的维度
cp_pause_rx : coverpoint pause_opcode {
  bins pause={PAUSE}; bins pfc_prio0={PFC0}; bins pfc_prio7={PFC7}; bins unknown={UNKNOWN_OPCODE};
}
cp_pause_time: coverpoint pause_quanta {
  bins zero={0}; bins one={1}; bins small={[2:100]}; bins max={16'hFFFF};
}
cp_tx_after : coverpoint tx_action {
  bins keep_sending={SEND}; bins pause={PAUSED}; bins pause_overlap={PAUSE_DURING_PAUSE};
}
X_pause_tx  : cross cp_pause_rx, cp_tx_after;

// 6) 背压与缓冲
cp_level    : coverpoint rx_fifo_level { bins empty={0}; bins low={[1:3]}; bins full={DEPTH}; }
cp_backpress: coverpoint bp_event { bins none={NONE}; bins assert={ASSERT}; bins deassert={DEASSERT}; }
cp_drop     : coverpoint drop_policy { bins drop_new={DROP_NEW}; bins drop_old={DROP_OLD}; bins no_drop={NO_DROP}; }

// 7) 半双工冲突
cp_duplex   : coverpoint duplex { bins half={HALF}; bins full={FULL}; }
cp_collision: coverpoint coll { bins none={NONE}; bins early={EARLY}; bins late={LATE}; bins excessive={EXCESSIVE}; }
cp_backoff  : coverpoint backoff_slot { bins first={0}; bins mid={[1:9]}; bins max={10}; }

// 8) 速率与接口
cp_speed    : coverpoint speed { bins m10={10}; bins m100={100}; bins g1={1000}; bins g10={10000}; bins g25={25000}; }
cp_mii_type : coverpoint mii { bins gmii={GMII}; bins rgmii={RGMII}; bins xgmii={XGMII}; }
```

**判据**：一个以太网覆盖模型如果只有「各种帧长发过」，而没有 `cp_bad_kind × cp_rx_result`（坏帧最终命运）和 `cp_pause_rx × cp_tx_after`（流控响应），它测的只是「好帧能过」，而以太网在现场出问题几乎都在坏帧处置和流控响应上。

---

## 四、VIP 怎么接（通用做法）

**注意：本卡写的是通用做法，不声称任何仓库有哪个 VIP。**

| 环节 | 做法 |
|---|---|
| 分层 | MAC VIP 组帧/解帧；PHY 侧用接口模型（GMII/RGMII/XGMII）承载 |
| 双向 | 两个端口对跑或 DUT 与参考模型对跑，端到端比对负载 |
| 帧类型 | sequence 支持生成单播/组播/广播、各 EtherType、带/不带 VLAN |
| 坏帧注入 | 显式生成短帧、长帧、FCS 错帧，验证丢弃与计数 |
| 流控用例 | 生成暂停帧（含 PFC 优先级），观测对端发送行为 |
| 背压建模 | 让接收侧缓冲可控地变满，测丢帧策略与计数 |
| 半双工 / 速率切换 | 建模冲突与退避（多数现代用例全双工，但配置切换要覆盖）；覆盖速率与双工切换时的接口握手 |

**接入判据**：VIP 能不能**生成坏帧和暂停帧**？只能发「好帧」的以太网 VIP，等于放弃了两个最关键的验证方向（错误处置与流控）。

---

## 五、坑

| 坑 | 为什么诱人 | 后果 | 修正 |
|---|---|---|---|
| 只发好帧 | 好帧能过看着就«通了» | 坏帧处置（丢/计数）整块没验证 | 显式生成短/长/FCS 错帧 |
| FCS 错帧被上报 | 数据「看着对」就放过 | 上层收到损坏数据，错误被掩盖 | 断言错帧必丢，且计数一致 |
| 忽略长度/类型两义 | 多数流量按类型解释 | 按长度解释的路径从未执行 | 两种解释都覆盖 |
| 流控只测「收到暂停」 | 收到就该停，看着直观 | 暂停时长、叠加、提前恢复没测 | 暂停帧 + 时长的联合覆盖 |
| 背压导致静默丢帧 | 「缓冲满了当然丢」 | 丢了不计数，问题被隐藏 | 丢帧策略显式化 + 计数校验 |
| 只测全双工 | 现代网络都是全双工 | 半双工冲突/退避整条线没测 | 配置切半双工，造冲突 |
| 帧长只测中间值 | 中间值最省事 | 最小/最大/巨帧边界没碰 | 帧长边界作为 coverpoint |
| 地址过滤只测单播 / 忽略统计计数 | 单播是常态；计数像「附属信息」 | 组播/广播/混杂的收丢判定没验证；计数与帧命运不一致，排障失去依据 | 地址类型 × 接收模式交叉；每个坏帧分支都断言计数 |

**最值钱的两条**：**只发好帧** 和 **背压静默丢帧** —— 前者让以太网最核心的鲁棒性（对有错环境的容忍）从未被验证，后者让「丢了但没记录」变成现场排障的无解之谜。
