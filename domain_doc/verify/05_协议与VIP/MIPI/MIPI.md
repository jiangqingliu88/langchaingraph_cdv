---
id: KB-DV-PROT-006
title: MIPI 验证要点 —— CSI-2 / DSI 的 Lane 与包结构、虚拟通道、低功耗模式怎么覆盖
type: 协议卡
domain: 协议与VIP
subdomain: MIPI
tags: [MIPI]
roles: [DV工程师, 架构师]
stages: [计划, TB架构, 覆盖率]
summary: >
  CSI-2 与 DSI 共享同一套 D-PHY 物理层与包结构，差异在高层语义（图像 vs 显示、命令模式）。
  验证失控集中在「Lane 数 / 数据格式 × 虚拟通道 × 低功耗进出」这张组合网。
  本卡给信号与包结构骨架、合法非法组合、检查点与覆盖维度。
applicable: |
  验证 MIPI CSI-2 接收/发送控制器、DSI 控制器、D-PHY 之上的 CSI/DSI 协议层；
  写图像采集或显示子系统的验证计划。
not_applicable: |
  验证 D-PHY 的电气一致性（眼图、skew、阻抗）—— 那是 SI 与合规测试，不是功能验证；
  MIPI UniPro / M-PHY（那是 UFS、CSI-3 用的另一套物理与协议栈），不是 D-PHY 上的 CSI-2/DSI；
  验证与 MIPI 无关的通用并行图像接口（如 DVP）—— 语义不同。
prerequisites: [接口时序与协议基础, 功能覆盖率建模]
references: [MIPI CSI-2 Specification, MIPI DSI Specification, MIPI D-PHY Specification（章节见正文）]
related: [KB-DV-COV-001]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# MIPI 验证要点（CSI-2 / DSI）

> **一句话**：CSI-2 与 DSI 是「同一个 D-PHY 上跑的两种高层语言」。验证的难点不在包长得对不对，而在 **Lane 数 × 数据格式 × 虚拟通道 × 低功耗进出时序** 这张组合网。

## 一、信号与时序

### 物理层（D-PHY）

| 概念 | 说明 |
|---|---|
| Lane | 一条时钟 Lane + 一/多/四条数据 Lane；**Lane 数是配置项，不是常数** |
| 差分对 | 高速用差分信号；低功耗用单端信号，两种模式电平和驱动方式不同 |
| 高速模式（HS） | 差分、突发（burst）传输，Lane 间有 skew 要求 |
| 低功耗模式（LP） | 单端、低速；控制态（如 LP-11/LP-01/LP-00）用于进出 HS |
| LP 进入/退出序列 | HS 与 LP 之间的状态跳转有严格时序，是验证重点 |

**关键判据**：**HS 与 LP 是同一根线上的两种「语言」，切换序列本身就是协议**。验证不能只测 HS 数据，必须覆盖 LP→HS→LP 的完整进出。

### 包结构（CSI-2 / DSI 共享的「短包 / 长包」骨架）

| 包类型 | 结构 | 用途 |
|---|---|---|
| **短包** | 帧/行同步等控制信息，头部信息短 | 帧起始、帧结束、行起始、行结束、同步事件 |
| **长包** | 头部 + 有效负载（像素数据或显示数据）+ 校验 | 实际图像 / 显示数据 |
| 头部 | 含数据类型（DT）与虚拟通道（VC）字段 | 路由与解释载荷的依据 |
| 校验 | 长包尾部有校验字段 | 收到后校验，错了要能识别 |

**关键判据**：**虚拟通道（VC）与数据类型（DT）是从包头解出的两个独立维度**，验证必须把它们交叉，不能只测单通道单格式。

### DSI 与 CSI-2 的差异

| 维度 | CSI-2 | DSI |
|---|---|---|
| 方向 | 摄像头 → 处理器（接收为主） | 处理器 → 显示器（发送为主） |
| 高层语义 | 图像帧/行同步 | 显示时序、命令模式 vs 视频模式 |
| 特有 | 多虚拟通道路由多个摄像头流 | 命令模式下的显示命令、像素流与命令交错 |

---

## 二、合法/非法组合

### 合法组合

| 维度 | 合法取值空间 |
|---|---|
| Lane 数 | 按链路配置（控制器支持哪些 Lane 数是设计约定，需查实现） |
| 数据类型 | 各种像素格式（RGB/YUV/RAW 等）+ 内嵌数据 + 空包 |
| 虚拟通道 | 多 VC 复用到同一物理链路，按包头路由 |
| 传输模式 | HS 突发 + LP 空闲交替 |
| DSI 模式 | 视频模式（连续/非连续时钟）与命令模式 |

### 非法/异常组合（必须主动造）

| 非法场景 | 期望行为 |
|---|---|
| HS 突发长度与包头声明的载荷长度不符 | 接收方应报帧/包错，不能静默接受 |
| 校验字段错误 | 接收方应识别并丢弃/标记，不得当有效数据处理 |
| 未配置的虚拟通道数据到达 | 接收方按设计约定忽略或报错 |
| LP→HS 序列不完整 / 时序越界 | 接收方应不进入 HS，或报协议错 |
| 帧结束时缺少帧结束标记 | 帧状态机不能停在中间态 |
| 内嵌数据（embedded data）与像素数据的顺序错乱 | 上层解析不应误把内嵌数据当像素 |
| DSI 命令模式下命令与像素交错越界 | 显示控制器状态不能被破坏 |
| Lane 间 skew 超限（模型层可造乱序） | 接收方应有对齐/容错策略 |

---

## 三、检查点

| 检查点 | 断言方向 |
|---|---|
| 包完整性 | 短包/长包的结构、字段、校验齐全 |
| 帧结构 | 帧起始→行→帧结束序列完整，无孤立行 |
| Lane 对齐 | 多 Lane 数据能正确重组成一路像素流 |
| 格式正确性 | 收到的数据类型与配置一致，像素解码后与源一致 |
| VC 路由 | 每个虚拟通道的数据送到正确的目的地，不串流 |
| LP/HS 切换 | 进出 HS 的序列与时序符合规范 |
| 时钟 | 连续时钟（HS 常开）与非连续时钟（LP 时空闲）两种模式都覆盖 |
| DSI 模式 | 视频模式与命令模式各自的时序与状态正确 |
| 错误处理 | 校验错、长度错、超时的识别与恢复路径正确 |

### 覆盖点方向

```systemverilog
// 1) Lane 数与方向 —— MIPI 的第一维
cp_lane_num : coverpoint lane_count { bins x1={1}; bins x2={2}; bins x4={4}; }
cp_dir      : coverpoint dir       { bins forward={FWD}; bins reverse={REV}; } // CSI-2 反向控制
X_lane_dir  : cross cp_lane_num, cp_dir;

// 2) 包类型 × 数据类型 —— 短包无负载，长包有负载
cp_pkt_type : coverpoint pkt_type { bins short_pkt={SHORT}; bins long_pkt={LONG}; }
cp_data_type: coverpoint dt {
  bins rgb = {DT_RGB}; bins yuv = {DT_YUV}; bins raw = {DT_RAW};
  bins embedded = {DT_EMBEDDED}; bins null_pkt = {DT_NULL}; bins reserved = {DT_RESERVED};
}
X_type_dt   : cross cp_pkt_type, cp_data_type;

// 3) 虚拟通道 —— 常被漏掉的一维
cp_vc       : coverpoint vc { bins vc0={0}; bins vc1={1}; bins vc2={2}; bins vc3={3}; bins invalid={[4:$]}; }
X_vc_dt     : cross cp_vc, cp_data_type;   // 多摄像头复用的关键交叉

// 4) 低功耗状态机：状态 + 进出弧 —— LP/HS 是本协议最独有的维度
cp_lp_state : coverpoint phy_state {
  bins lp_idle={LP_IDLE}; bins hs_active={HS_ACTIVE}; bins hs_burst={HS_BURST}; bins lp_ctrl={LP_CTRL};
}
cp_lp_trans : coverpoint phy_state {
  bins enter_hs  = (LP_IDLE => HS_ACTIVE);
  bins hs_to_lp  = (HS_ACTIVE => LP_IDLE);
  bins burst_re  = (HS_BURST => HS_BURST);   // 背靠背突发
}
illegal_bins bad_enter = (LP_CTRL => HS_BURST);

// 5) 帧/行结构
cp_frame_state: coverpoint frame_state {
  bins idle={IDLE}; bins in_frame={IN_FRAME}; bins end_frame={END_FRAME};
}
cp_line_seq : coverpoint line_state { bins line_start={LS}; bins line_end={LE}; bins data={DATA}; }
cp_burst_len: coverpoint burst_len { bins one={1}; bins mid={[2:99]}; bins max={100}; }  // 边界按实现取

// 6) 时钟模式（DSI）
cp_clk_mode : coverpoint clk_mode { bins cont={CONTINUOUS}; bins non_cont={NON_CONTINUOUS}; }
cp_dsi_mode : coverpoint dsi_mode { bins video={VIDEO}; bins command={COMMAND}; }
X_clk_dsimode: cross cp_clk_mode, cp_dsi_mode;

// 7) 错误与恢复
cp_err      : coverpoint err_kind { bins ecc={ECC_ERR}; bins crc={CRC_ERR}; bins len_mismatch={LEN_ERR}; bins timeout={TIMEOUT}; }
cp_skew     : coverpoint skew { bins ok={[0:0]}; bins mild={[1:3]}; bins excessive={[4:$]}; }  // 阈值按规范
cp_recovery : coverpoint recovery { bins drop={DROP_PKT}; bins resync={RESYNC}; bins fatal={FATAL}; }
```

**判据**：一个 CSI-2 覆盖模型如果只有「发一张 RGB 图收对」而没有 `cp_vc × cp_data_type` 和 `cp_lp_trans`，它漏掉的正是多摄像头路由和低功耗时序 —— 这两块占了现场问题的绝大多数。

---

## 四、VIP 怎么接（通用做法）

**注意：本卡写的是通用做法，不声称任何仓库有哪个 VIP。**

| 环节 | 做法 |
|---|---|
| 分层 | CSI-2/DSI 协议层 VIP 收发包；PHY 用行为模型做 LP/HS 序列 —— 电气细节不在功能验证范围 |
| 源端 | 摄像头模型 VIP 发短包/长包，支持可配置 Lane 数与 VC |
| 宿端 | 接收 VIP 解包，把像素流交给 scoreboard 逐像素比对 |
| 图像模型 | 用生成图案（渐变、棋盘、随机）而非常量，才能暴露 Lane 重组/格式解码的错 |
| 序列建模 | 帧序列、行序列、LP/HS 切换序列都做成 sequence，可随机长度与时序 |
| 错误注入 | 在协议层注 ECC/CRC 错、长度错、VC 越界，不要只在 PHY 注 |
| 时钟建模 | DSI 要显式建模连续与非连续时钟两种模式 |

**接入判据**：VIP 能不能**按 Lane 数和对 VC 数参数化**？一个写死单 Lane 单 VC 的模型，在多摄像头 SoC 上等于没用 —— 这是判断 MIPI VIP 够不够用的第一个问题。

---

## 五、坑

| 坑 | 为什么诱人 | 后果 | 修正 |
|---|---|---|---|
| 只测单 Lane 单 VC | 单 Lane 最好调、图像最直观 | 多 Lane 重组、多 VC 路由的 bug 全漏 | Lane 数与 VC 作为交叉维度 |
| 只测 HS 数据不测 LP | HS 里才有「数据」 | 进出 HS 的序列与时序从未执行 | LP/HS 状态机 + 转移弧覆盖 |
| 用常量图案做图像 | 常量图搭起来快、比对简单 | Lane 间错位/格式解码错看不出来 | 用渐变/棋盘/随机图案 |
| 忽略嵌入数据 | 内嵌数据不是「像素」 | 上层把内嵌数据当像素，图像错位 | 内嵌数据单列数据类型并覆盖 |
| 假设 Lane 数固定 | 项目里多半固定 | 换项目/换配置直接失效 | 参数化，覆盖合法 Lane 数集合 |
| DSI 只测视频模式 | 视频模式直观 | 命令模式的状态与时序没验证 | 两种模式都覆盖并交叉时钟模式 |
| 校验错当警告放过 | 「反正数据看着对」 | 错误检测路径未被验证 | 注校验错并断言识别路径 |
| PHY 层注错代替协议层 | PHY 注错方便 | 协议层 ECC/CRC/长度错覆盖不到 | 错误注入放在包粒度 |

**最值钱的两条**：**只测单 Lane 单 VC** 和 **跳过 LP/HS 切换** —— 前者让多摄像头/高分辨率场景的 bug 逃逸，后者让链路在低功耗进出处的时序问题完全没被触碰。
