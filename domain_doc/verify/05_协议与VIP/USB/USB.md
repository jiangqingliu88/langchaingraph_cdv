---
id: KB-DV-PROT-005
title: USB 验证要点 —— 端点与传输类型、枚举过程、以及该怎么写它的 coverpoint
type: 协议卡
domain: 协议与VIP
subdomain: USB
tags: [USB]
roles: [DV工程师, 架构师, Emulation]
stages: [计划, TB架构, 覆盖率]
summary: >
  USB 不是「一条总线」，而是「四种传输类型 + 一个主机轮询的拓扑」。验证失控几乎都来自
  把传输类型当细节、把枚举当一次性动作。本卡给出四类传输的语义、枚举的状态骨架、
  合法/非法组合、检查点，以及可用的覆盖维度。
applicable: |
  验证 USB 设备控制器 / 主机控制器 / PHY 之上的链路层；写 USB 子系统或 SoC 验证计划。
not_applicable: |
  验证 Type-C 的 PD 协议与 CC 逻辑 —— 那是 USB-PD，另一套消息协议，查 `USB-PD 规范`，不是本卡；
  只关心 PHY 的电气眼图 / 一致性测试 —— 那是 SI 与认证实验室的活，不是功能验证。
prerequisites: [接口时序与协议基础, 功能覆盖率建模]
references: [USB 2.0 Specification, USB 3.2 Specification, USB Type-C Specification（各章节见正文）]
related: [KB-DV-COV-001]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# USB 验证要点

> **一句话**：USB 验证的重点不在「把包发对」，而在**四种传输类型 × 三种速度模式 × 主机轮询调度 × 枚举状态机**这张组合网能不能被穷举到。

## 一、信号与时序

### 分层的两组信号

USB 验证要分清「总线信号」和「控制器接口信号」，混淆这两层是最常见的开局错误。

| 层 | 信号/概念 | 说明 |
|---|---|---|
| 物理层 | D+ / D- / VBUS | 差分对；高速时先做 chirp 握手再切高速驱动。VBUS 上电时序本身是验证对象 |
| 链路层 | SOF / 帧 / 微帧 | 全速 1ms 帧、高速 125µs 微帧，主机按微帧调度 |
| 链路层 | Token / Data / Handshake 包 | PID 区分包类型，是协议状态的核心 |
| 事务层 | Token → Data → Handshake | 一次「事务」的三段式；控制传输由多个事务串成 |
| 控制器接口 | 寄存器 / DMA / 中断 | 设备控制器对软件暴露的接口，是 SoC 级验证真正读写的对象 |

### 传输类型：USB 的四种「语义」

**四类传输不是性能档位，而是四种不同的可靠性契约** —— 这是本卡的骨架。

| 传输类型 | 契约 | 时序特征 | 验证重点 |
|---|---|---|---|
| **控制（Control）** | 保证送达且被确认 | SETUP → 可选 DATA → STATUS，三段串行 | 枚举全过程、请求语义、STALL 分支 |
| **批量（Bulk）** | 保证送达但不保证时延 | 利用空闲带宽，可被主机无限推迟 | 大数据量、背压、NAK 重试、短包收尾 |
| **中断（Interrupt）** | 有界时延、周期性轮询 | 主机按固定间隔 poll，设备可 NAK | 轮询间隔边界、NAK 后恢复、延迟抖动 |
| **同步（Isochronous）** | 保证时延、不保证送达（不重传） | 每微帧固定带宽预留 | 带宽预留、丢包容忍、微帧对齐 |

**关键判据**：**同步传输永远不会重传，也不会有握手包** —— 断言「每个 DATA 包后必有 ACK」在同步传输上是错的。这类「按传输类型分叉的规则」是 USB 覆盖率最容易漏的维度。

---

## 二、枚举过程（控制传输的一次完整走查）

枚举是**主机与设备通过控制传输做的一次协商**，不是「一次复位」。它天然是状态机，验证时必须按状态覆盖。

| 阶段 | 干什么 | 典型验证关注点 |
|---|---|---|
| 连接检测 | 设备上拉 D+（全速/高速）或 D-（低速）宣告接入 | 上拉时序、主机检测去抖 |
| 复位 | 主机拉 SE0 一段时间 | 复位时长边界、复位后地址归零 |
| 获取描述符 | GET_DESCRIPTOR 读设备/配置/字符串描述符 | 短包、分多次读、描述符长度自洽 |
| 分配地址 | SET_ADDRESS 赋唯一地址 | 地址切换时机、0 地址窗口 |
| 读配置 | 读完整配置集合（配置/接口/端点） | 配置组合、接口多备选（alternate setting） |
| 选择配置 / 使能 | SET_CONFIGURATION 选定配置，端点开始按类型调度 | 未选中配置时端点必须不可用；使能前访问应 STALL 或忽略 |

### 枚举失败的那些分支（枚举卡住时几乎都在这）

描述符长度不对 → 短包策略 / wLength 处理；配置选不上 → 描述符内 bNumInterfaces 或端点地址与控制器能力不符；
装完驱动端点无数据 → SET_INTERFACE 没做、alternate setting 未切换；复位后要重枚举 → 地址归零而设备未保存配置状态。

**验证判据**：枚举不是「跑通一次」就够，而是「每个描述符字段的每个边界值都要被走一次」。

---

## 三、合法/非法组合

### 合法的「按类型分叉」

| 传输类型 | DATA 包后必有握手？ | 可重传？ | 可 STALL？ |
|---|---|---|---|
| 控制 | 是 | 是 | 是（协议层拒请求） |
| 批量 | 是 | 是 | 是（端点 halt 时） |
| 中断 | 是 | 是 | 是 |
| 同步 | **否** | **否** | 无握手，不适用 |

### 非法/异常组合（验证必须主动造）

| 非法场景 | 期望行为 |
|---|---|
| 事务中途主机发 RESET | 设备回到地址 0、端点复位、不再响应原事务 |
| 对未使能端点发 Token | 设备忽略（不是应答错数据） |
| 同步端点收到握手包 | 视为协议错，检查设计是否误判 |
| 主机发超过 wMaxPacketSize | 设备应报错或按规范处理，不能静默截断 |
| 短包出现在应有后续数据的批量传输中 | 短包即传输结束 —— 双方对「结束」的理解必须一致 |
| 连续 NAK 超时 / 错误 PID / CRC 错 | 上层应有超时重试；接收方丢弃并等重传 |
| 高速 chirp 握手失败 | 回退全速，链路仍可用 —— 这一分支常被漏测 |

---

## 四、检查点

### 协议检查点（记在 scoreboard / 断言里）

| 检查点 | 断言方向 |
|---|---|
| PID 类型齐全 | Token/Data/Handshake 的每种 PID 都被观测到 |
| 三段事务完整性 | Token→Data→Handshake 顺序完整（同步传输除外） |
| 端点状态 | 未配置/未使能端点收到请求时的行为符合规范 |
| 数据一致性 | 主设备发 / 收的负载与 scoreboard 逐字节一致 |
| 握手正确性 | ACK/NAK/STALL 的语义与当前事务状态匹配 |
| 复位语义 / 时序 | 复位后地址端点配置归零；SOF 与轮询间隔在规范窗口内 |

### 覆盖点方向（可直接落成 coverpoint）

```systemverilog
// 1) 传输类型 × 速度模式 —— 最基础的交叉
cp_xfer_type: coverpoint xfer_type { bins ctrl={CTRL}; bins bulk={BULK}; bins int={INT}; bins iso={ISO}; }
cp_speed    : coverpoint speed     { bins low={LS}; bins full={FS}; bins high={HS}; bins ss={SS}; }
cp_ep_dir   : coverpoint ep_dir    { bins in={IN}; bins out={OUT}; bins bidir={BIDIR}; }
X_type_speed: cross cp_xfer_type, cp_speed;

// 2) 枚举状态机：状态 + 转移弧（含复位回退） + 非法弧
cp_enum_state: coverpoint enum_state {
  bins attached={ATTACHED}; bins powered={POWERED}; bins default_s={DEFAULT};
  bins addressed={ADDRESSED}; bins configured={CONFIGURED};
}
cp_enum_trans: coverpoint enum_state {
  bins attach_power=(ATTACHED=>POWERED); bins power_default=(POWERED=>DEFAULT);
  bins default_addr=(DEFAULT=>ADDRESSED); bins addr_config =(ADDRESSED=>CONFIGURED);
  bins reset_back  =(CONFIGURED=>DEFAULT);   // 复位回退弧
}
illegal_bins skip_reset = (ATTACHED => CONFIGURED);

// 3) 请求种类（标准 / 类 / 厂商）与端点配置空间
cp_bmRequest: coverpoint bmRequestType {
  bins standard={[8'h00:8'h1F]}; bins class_req={[8'h20:8'h3F]};
  bins vendor={[8'h40:8'h5F]};   bins reserved={[8'h60:8'hFF]};  // 保留编码，非法
}
cp_bRequest : coverpoint bRequest {
  bins get_descriptor={GET_DESCRIPTOR}; bins set_address={SET_ADDRESS};
  bins set_config={SET_CONFIGURATION}; bins set_interface={SET_INTERFACE};
}
cp_ep_num   : coverpoint ep_number { bins ep0={0}; bins ep1={1}; bins ep15={15}; bins invalid={[16:$]}; }
cp_maxpkt   : coverpoint wMaxPacketSize { bins pkt8={8}; bins pkt64={64}; bins pkt1024={1024}; }

// 4) 描述符边界 —— 枚举卡住时最先怀疑的地方；5) 握手结果 × 传输类型
cp_desc_len : coverpoint desc_len { bins zero={0}; bins tiny={[1:7]}; bins exact={18}; bins long={[19:$]}; }
cp_wLength  : coverpoint wLength { bins zero={0}; bins small={[1:8]}; bins max={16'hFFFF}; }
cp_handshake: coverpoint handshake { bins ack={ACK}; bins nak={NAK}; bins stall={STALL}; bins none={NONE}; }
X_hs_type   : cross cp_xfer_type, cp_handshake;   // 同步传输没有握手这一列

// 6) 错误恢复 + 背压（满时写 / 空时读）
cp_err      : coverpoint err_kind { bins crc={CRC}; bins pid={BAD_PID}; bins timeout={TIMEOUT}; bins babble={BABBLE}; }
cp_recovery : coverpoint recovery { bins retry_ok={RETRY_OK}; bins retry_exhaust={RETRY_EXHAUST}; bins fatal={FATAL}; }
cp_level    : coverpoint fifo_level { bins empty={0}; bins low={[1:3]}; bins full={DEPTH}; }
cp_blocked  : coverpoint op { bins wr_when_full={WR_FULL}; bins rd_when_empty={RD_EMPTY}; }
```

**判据**：一个 USB 覆盖模型如果只有 `cp_xfer_type` 而没有「枚举转移弧」和「描述符边界」，它大约是漏了枚举这条主线 —— 而枚举恰恰是 USB 设备第一次点亮时最常挂的地方。

---

## 五、VIP 怎么接（通用做法）

**注意：本卡写的是通用做法，不声称任何仓库有哪个 VIP。**

| 环节 | 做法 |
|---|---|
| 分层 | 链路层 VIP 发事务，PHY 用行为模型——**不要在 PHY 电气层写功能用例** |
| 主机/设备端 | 主机 VIP 驱动 SOF/微帧并按传输类型调度；设备 VIP 响应 Token 并暴露端点缓冲；双端 VIP 对跑比对双向数据 |
| 枚举建模 | 枚举状态机做成序列（sequence），而非硬编码一长串请求；描述符字段随机化逼出边界 |
| 速度模式 | 覆盖全速与高速两条路径；高速要显式覆盖 chirp 成功与失败两分支 |
| 错误注入 | 在链路层注 CRC/PID 错、乱序、超时，不要只在 PHY 注 |

**接入判据**：VIP 的 sequence 库能不能**按传输类型分叉**？只有「发批量数据」一个 sequence，就还没法验证控制/中断/同步的差异 —— 这是判断一个 USB VIP 够不够用的第一个问题。

---

## 六、坑

| 坑 | 为什么诱人 | 后果 | 修正 |
|---|---|---|---|
| 只测批量传输 | bulk 最容易搭、最像「发数据」 | 控制（枚举）与同步（无握手）两条线全空 | 四种传输类型各建一条 sequence，交叉覆盖 |
| 把枚举当一次性动作 | 枚举「跑通一次」看起来就万事大吉 | 描述符边界、失败分支、复位回退全漏 | 枚举建模成状态机，覆盖每个转移弧 |
| 断言「DATA 后必有握手」 | 握手是绝大多数情况 | 同步传输被误报，或在同步上漏测 | 断言按传输类型分叉 |
| 忽略速度回退 | 默认都能跑高速 | chirp 失败回退全速的路径从未执行 | 显式造 chirp 失败用例 |
| 短包语义含糊 | 短包看起来像「数据少了一点」 | 收发双方对传输结束理解不一致、挂死 | 短包 = 结束，写成断言并双向覆盖 |
| 只在 PHY 注错 | PHY 注错最方便 | 链路层的乱序/坏 PID/超时覆盖不到 | 错误注入放在链路层事务粒度 |
| 端点未配置就访问被静默忽略 | 设计「没崩」看着像通过 | 规范要求与实现的差异被掩盖；也漏了轮询间隔边界 | 先定规范期望再断言实现行为；间隔作为 coverpoint |

**最值钱的两条**：**只测批量** 和 **断言不分传输类型** —— 前者让「覆盖率 90%」的水分集中在最容易的那条线，后者会在同步传输上给出假阳性/假阴性。
