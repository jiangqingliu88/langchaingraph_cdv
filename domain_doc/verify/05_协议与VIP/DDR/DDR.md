---
id: KB-DV-PROT-008
title: DDR 验证要点 —— 命令与寻址、时序参数的语义与相互关系、刷新该怎么覆盖
type: 协议卡
domain: 协议与VIP
subdomain: DDR
tags: [DDR]
roles: [DV工程师, 架构师]
stages: [计划, TB架构, 覆盖率]
summary: >
  DDR 验证的两条主线是「命令序列是否正确」与「时序约束是否被违反」。时序参数（tRCD/tRP/CL 等）
  的价值不在具体数值，而在**它们之间的相互依赖关系**，这决定了检查器怎么写、覆盖怎么建。
  本卡给命令/寻址骨架、参数语义与关系、合法非法组合、检查点与覆盖维度。
applicable: |
  验证 DDR 控制器（Memory Controller）、PHY 之上的命令与调度逻辑、DFI 接口；写内存子系统验证计划。
not_applicable: |
  验证 DRAM 颗粒内部的模拟电路（sense amp、电荷泵）—— 那是器件设计/流片，不是数字验证；
  只关心 DDR PHY 的电气训练（读写均衡、眼图）—— 那偏 SI 与 PHY 固件，功能验证只测数字接口；
  验证片内 SRAM/Cache —— 那是片上存储，不涉及 DDR 协议。
prerequisites: [接口时序与协议基础, 功能覆盖率建模]
references: [JEDEC DDR 系列标准（DDR3/DDR4/DDR5/LPDDR，命令集与时序参数章节）]
related: [KB-DV-COV-001]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# DDR 验证要点

> **一句话**：DDR 验证不背时序数字，而是理解**时序参数之间的依赖关系**——因为写检查器和建覆盖点靠的是关系，不是数值。数值一变（换速率/换器件），关系不变。

## 一、信号与时序

### 主要信号

| 信号组 | 说明 |
|---|---|
| CK / CK# , CKE | 时钟差分对；时钟使能（低功耗/掉电控制） |
| CS# / RAS# / CAS# / WE# | 命令编码引脚（组合成命令） |
| 地址（A / BA / BG） | 行/列/体（bank）/体组（bank group）地址 |
| DQ / DQS / DM | 数据、数据选通、数据掩码 |
| ODT / ZQ | 片上端接与校准 |

### 命令集（DDR 的「词汇表」）

| 命令 | 作用 |
|---|---|
| ACT（激活） | 打开某 bank 的某一行，把行数据读到行缓冲 |
| RD / WR | 对已激活行做读/写，给出列地址 |
| PRE（预充电） | 关闭已打开的行 / 全部 bank |
| REF（刷新） | 对存储阵列做刷新 |
| MRS（模式寄存器设置） | 配置 CL、突发长度、ODT 等 |
| ZQ 校准 / 掉电 / 自刷新 | 校准端接阻抗；CKE 控制的低功耗态 |

### 时序参数：写「含义 + 关系」，不写数字

**下表故意不给具体数值 —— 数值随速率/器件/标准版本变化，写死即错。要用时查对应 JEDEC 标准的时序表。**

| 参数组 | 含义 | 与谁相关（关系才是检查器的依据） |
|---|---|---|
| **命令到命令（tRCD）** | ACT 到 RD/WR 的最小间隔 | 行缓冲读取所需，与列命令的启动条件绑定 |
| **行预充电（tRP）** | PRE 到下一个 ACT 的最小间隔 | 与 tRCD 共同决定「行切换」的总代价 |
| **CAS 潜伏（CL）** | RD 命令到数据出现在 DQ 的延迟 | 读路径的固定延迟；决定读数据何时可采样 |
| **写恢复（tWR）** | WR 到 PRE 的最小间隔 | 保证写数据真正进入阵列 |
| **写延迟（CWL，DDR4/5）** | WR 命令到写数据/选通的延迟 | 写方向的类似 CL；决定 DQS 何时发给器件 |
| **ACT 到 ACT（tRC / tRRD）** | 同行激活到激活 / 不同 bank 激活到激活 | 决定 bank 并行度与调度上限 |
| **四个激活窗口（tFAW）** | 一段窗口内最多激活几次 | 限制瞬时功耗；调度器必须遵守 |
| **刷新间隔/周期（tREFI/tRFC）** | 平均刷新间隔 / 一次刷新的占用时间 | 器件电荷保持要求；刷新期间命令不可用，是带宽损失来源 |
| **模式寄存器（tMRD/tMOD）** | 两次 MRS 之间 / MRS 生效所需间隔 | 初始化与在线改配置的约束 |
| **数据选通（tDQSS/tDSS/tDSH）** | 写方向 DQS 与数据的相对关系 | 写时序对齐，PHY 训练目标 |
| **ODT 时序（tAOND/tAOFD 等）** | ODT 开关与命令/数据的相对时序 | 与读写切换的端接切换绑定 |

**关键判据**：**这些参数不是孤立的常数，而是一组不等式约束**（例如「PRE 只在满足 tRAS 后才能发」「ACT 之间要满足 tRRD 和 tFAW」）。检查器要检查的是**约束是否被违反**，而不是「某个延迟是不是等于某个数」。

---

## 二、合法/非法组合

### 合法命令序列（按状态机）

| 序列 | 说明 |
|---|---|
| ACT → RD/WR → PRE | 一次完整的行访问 |
| ACT → RD → ACT(同 bank 不同行) → RD | 需要先 PRE（行冲突） |
| ACT(bankA) → RD(bankA) → ACT(bankB) → RD(bankB) | bank 并行，交错访存 |
| 周期性 REF 插入 | 与访存交错，受 tRFC 约束 |
| MRS 改配置 → 生效 / 进入退出掉电、自刷新 | 初始化与在线重配置；CKE 控制的低功耗 |

### 非法/异常组合（必须主动造）

| 非法场景 | 期望行为 |
|---|---|
| 未 ACT 就 RD/WR 同一行 | 非法命令，检查器必须报 |
| 违反 tRCD 就在 ACT 后立刻 RD / 违反 tRP 就在 PRE 后立刻 ACT | 时序越界，必须被检测 |
| 违反 tFAW 在窗口内过多 ACT | 功耗约束越界 |
| 同一 bank 未 PRE 就 ACT 另一行 | 行冲突未处理，数据可能错 |
| 超过 tREFI 未刷新 / 刷新期间发访存命令 | 器件保持风险；刷新期命令冲突被忽略或报错 |
| 写入后未满足 tWR 就 PRE | 写数据损坏风险 |
| MRS 间隔不足 | 配置未生效，后续行为错 |
| 地址越界（超出行/列/bank 范围） | 应被地址解码拦截而非发到器件 |

---

## 三、检查点

| 检查点 | 断言方向 |
|---|---|
| 命令合法性 / 行 bank 状态 | 命令组合与当前 bank/行状态一致；每 bank 的「开/关」跟踪正确，无未开就访 |
| 时序约束 | 每条命令之间的间隔满足对应参数（**按不等式检查，不按定值**） |
| 刷新周期 / 低功耗 / 校准 | tREFI 内确有刷新且期间不发访存；掉电自刷新进出正确；ZQ 校准按周期触发且不打断关键访存 |
| 数据一致性 / 突发边界 | 写入读回与 scoreboard 一致（含掩码、突发边界）；突发长度与地址对齐符合配置 |
| 初始化序列 / 模式寄存器 | 上电初始化序列符合标准；MRS 配置生效且被后续行为反映 |
| 调度 | 仲裁策略在冲突/饥饿下的行为正确 |

### 覆盖点方向

```systemverilog
// 1) 命令类型 —— 第一维
cp_cmd      : coverpoint cmd {
  bins act={ACT}; bins rd={RD}; bins wr={WR}; bins pre={PRE};
  bins pre_all={PREA}; bins ref={REF}; bins mrs={MRS}; bins zq={ZQCS};
  bins illegal={ILLEGAL};
}
cp_cmd_seq  : coverpoint last_cmd {
  bins act_rd = (ACT => RD);   bins act_wr = (ACT => WR);
  bins rd_pre = (RD => PRE);   bins wr_pre = (WR => PRE);
  bins pre_act= (PRE => ACT);  bins rd_wr  = (RD => WR);   // 读写切换
}

// 2) Bank / 地址空间 —— bank 并行与冲突
cp_bank     : coverpoint bank { bins b0={0}; bins b1={1}; bins b3={3}; bins all={ALL_BANKS}; }
cp_bankgrp  : coverpoint bg   { bins g0={0}; bins g1={1}; }   // DDR4/5 的 bank group
cp_row_hit  : coverpoint row_result { bins row_hit={HIT}; bins row_miss={MISS}; bins row_conflict={CONFLICT}; }
X_bank_grp  : cross cp_bank, cp_bankgrp;
cp_map      : coverpoint {bank, row} {
  bins same_bank_same_row={0}; bins same_bank_diff_row={1}; bins diff_bank={2};
}

// 3) 时序窗口 —— 关键是「接近边界」而非「等于某值」
cp_t_rcd    : coverpoint gap_act_rd { bins below={[-$:-1]}; bins at_min={0}; bins above={[1:$]}; }  // 差值为负=越界
cp_t_rp     : coverpoint gap_pre_act{ bins below={[-$:-1]}; bins at_min={0}; bins above={[1:$]}; }
cp_t_faw    : coverpoint act_in_window { bins one={1}; bins four={4}; bins over={[5:$]}; }  // 超窗=越界
cp_t_refi   : coverpoint since_last_ref { bins in_time={[0:0]}; bins late={[1:$]}; }        // 阈值按规范取

// 4) 读写切换与总线周转
cp_rw_turn  : coverpoint turn { bins rd_rd={RD_RD}; bins rd_wr={RD_WR}; bins wr_wr={WR_WR}; bins wr_rd={WR_RD}; }
cp_odt      : coverpoint odt_state { bins off={ODT_OFF}; bins on={ODT_ON}; bins switching={ODT_SW}; }

// 5) 刷新 + 模式寄存器与初始化
cp_ref_type : coverpoint ref_kind { bins all_bank={REF_AB}; bins per_bank={REF_PB}; bins auto={AUTO_REF}; }
cp_ref_phase: coverpoint ref_phase { bins idle={IDLE}; bins during_burst={DURING_BURST}; bins during_wr={DURING_WR}; }
cp_mrs_reg  : coverpoint mrs_reg { bins mr0={MR0}; bins mr1={MR1}; bins mr2={MR2}; bins mr5={MR5}; }
cp_init_seq : coverpoint init_step { bins reset={RESET}; bins cke_on={CKE_ON}; bins mrs_step={MRS}; bins zq_cal={ZQ_CAL}; bins ready={READY}; }

// 6) 数据路径边界 + 错误 + 低功耗
cp_burst_len: coverpoint burst_len { bins bc4={4}; bins bl8={8}; bins bl16={16}; }
cp_dm       : coverpoint dm { bins masked={MASKED}; bins unmasked={UNMASKED}; }
cp_err      : coverpoint err_kind { bins illegal_cmd={ILLEGAL_CMD}; bins timing_viol={TIMING}; bins addr_oob={ADDR_OOB}; bins ecc={ECC_ERR}; }
cp_pwr      : coverpoint pwr_state { bins active={ACTIVE}; bins precharge_pd={PRE_PD}; bins self_refresh={SELF_REF}; }
cp_pwr_trans: coverpoint pwr_state { bins enter_sr=(ACTIVE=>SELF_REF); bins exit_sr=(SELF_REF=>ACTIVE); }
```

**判据**：一个 DDR 覆盖模型如果只覆盖了「各种命令都发过」，而没有 `cp_t_rcd` / `cp_t_faw` 这类**「接近边界与越界」的时序覆盖**，那它测的只是命令集，不是 DDR —— DDR 的 bug 绝大多数藏在时序边界上。

---

## 四、VIP 怎么接（通用做法）

**注意：本卡写的是通用做法，不声称任何仓库有哪个 VIP。**

| 环节 | 做法 |
|---|---|
| 分层 | 控制器 VIP 发命令；DDR 器件模型（memory model）响应并按参数反压 |
| 器件模型 | 带时序参数的器件模型，**参数由配置给定**（换速率只换配置，不改 TB），并实现真实存储阵列支持回读与掩码 |
| 时序检查 | 放在监视器 / 断言里，用**参数化**的不等式，而非硬编码延时 |
| 随机化 | 随机地址、bank、读写比例、突发长度，逼出行冲突与切换 |
| 刷新压力 | 让刷新与高负载访存交错，测调度器在刷新开销下的行为 |
| 错误注入 | 注入非法命令、越界地址、时序压紧的序列 |
| 覆盖关联 | 把命令序列与「距上一次命令的间隔」联合采样，才能测边界 |

**接入判据**：器件模型的时间参数**是不是配置**？写死数值的模型，一换速率就得重写 TB，覆盖点里那些「边界」也失去意义。

---

## 五、坑

| 坑 | 为什么诱人 | 后果 | 修正 |
|---|---|---|---|
| 背时序数字写死 | 手边正好有一组数 | 换速率/器件全失效，检查器变成错的 | 写成参数化不等式，只查关系不查定值 |
| 只覆盖命令类型 | 命令集看着「都测了」 | 时序边界这条主线完全没覆盖 | 加「接近边界/越界」的时序覆盖点 |
| 只测顺序访问 | 顺序访存最直观 | 行冲突、bank 交错、读写切换全漏 | 随机化地址与 bank，专门造冲突 |
| 忽略 bank group | 老标准没有 | 新标准的并行度利用与约束漏测 | bank/bank group 双维覆盖 |
| 刷新当背景 | 刷新「反正会来」 | tREFI/tRFC 的调度开销与冲突未验证 | 刷新与高负载交错，单列覆盖点 |
| 假设参数独立 | 每个参数看着像常数 | 参数间的约束（如 PRE 需 tRAS）被忽略 | 检查器按约束组合检查 |
| 数据只用单一图案 | 省事 | 位翻转/掩码/突发对齐错看不出来 | 多图案 + 边界突发长度 |
| 低功耗只测进入 / 地址越界不拦 | 进入看着「省电成功」；越界「过就过了」 | 退出后能否恢复访存没验证；越界被当合法发到器件 | 状态机 + 进出转移弧覆盖；地址解码拦截单列检查点 |

**最值钱的两条**：**背时序数字** 和 **只覆盖命令类型** —— 前者让知识一换器件就过期，后者让覆盖率数字掩盖了「时序从未被真正压到边界」这个事实。
