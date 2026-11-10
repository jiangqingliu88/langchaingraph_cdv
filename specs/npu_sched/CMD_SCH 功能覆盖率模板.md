# HM057 NPU CMD_SCH 功能覆盖率模板（V.2.0.0）

| 字段 | 值 |
|---|---|
| Owner | @刘江清 @王翔 |
| Reviewer | 资深验证、TL |
| 状态 | 模板 |
| 难度 | ★★★☆☆ |
| 适用阶段 | 环境搭建, 功能覆盖率 |
| 引用 CMDSCHED vplan 链接 | https://nanocorechip.feishu.cn/wiki/TLsJwTAJziivwekhfy4c3ieD |
| 标签 | cmsched，Function coverage, covergroup |
| 创建时间 | 2026-10-12 |

**版本记录**

- V.0.0.1@2026-10-12：建立 NPU_V2.CMDSCHED 功能覆盖率模板
- V.1.0.0@2026-11-03：按 HM057 CDD（L5-[NPU-HM057]-[CDD]-CMD_SCH_Dev）全面更新覆盖率计划，对齐 5 MST/ISTB/scoreboard 架构，新增 10 个覆盖率组并建立 Feat-1~40 需求追溯矩阵
- V.1.1.0@2026-11-03：完备性评审补齐 4 个覆盖点（cp_third_inst_blocked / cp_spad_tile_map / cp_wr_lmem_rmw / cp_int_info_save）及对应约束与场景，覆盖点计数与追溯矩阵同步更新
- V.1.2.0@2026-11-10：新增验证专题体系，引入主功能树专题、横向切面专题、端到端场景专题、微架构专题；新增 CSR × 行为跨 agent 联合交叉；拆分组内/同 agent 跨组/跨 agent 联合三张交叉表；补 mid_reset/data_format/ost2/drf_dp/longrun 等覆盖点
- V.2.0.0@2026-11-10：按“验证什么 → 怎么采 → 怎么激励 → 怎么算过”四层结构重排全文。原第 10 章“补丁式”内容拆分归位：专题体系前移为第 3 章；交叉统一归 4.12；新增覆盖点/SVA 归 4.13/4.14；约束归 5.6；联合 covergroup 归 8.3；签核门禁归第 10 章。删除“与原章节衔接”章节，全文不再有补丁章

---

## 1. 概述

### 1.1 目的

本文档定义 HM057 NPU 指令调度器（Command Scheduler，CMD_SCH）的功能覆盖率模型、配套约束设计及种子管理策略，建立约束 → 激励 → 覆盖率 → 收敛的完整闭环，确保验证完备性可度量、可追溯、可签核。本文档依据《L5-[NPU-HM057]-[CDD]-CMD_SCH_Dev》编写，覆盖点、约束与测试用例均与 CDD 功能特性一一对应。

本文档按四层组织：

| 层 | 回答什么 | 对应章节 |
|---|---|---|
| 验证策略层 | 验证什么、不漏项 | 第 3 章 验证专题体系 |
| 覆盖实现层 | 在哪采、bin 怎么定义、交叉怎么分 | 第 4 章 功能覆盖率组与覆盖点 |
| 激励与约束层 | 怎么产生激励、怎么分批 | 第 5~7 章 约束、批次、种子 |
| 签核层 | 怎么算过、怎么豁免 | 第 10 章 签核标准 |

**核心思想**：主功能树专题保证“每个功能验证了”，横向切面专题保证“每个功能在各切面上验证了”，场景专题保证“功能串起来跑通了”，微架构专题保证“白盒子模块正确”，覆盖组负责“怎么采”，跨 agent 联合 covergroup 负责“配置 × 行为”的组合。五者结合，避免 CSR 100% 但配置下指令交叉未验证的虚高。

### 1.2 范围

覆盖 CMD_SCH 指令调度器的以下功能维度：

- 指令接收与分类（NICE/VNICE 指令、普通功能/状态返回/数值返回指令、七类功能组件指令）
- ISTB 指令缓存管理（链表存储、深度参数、满时反压、cfg/drv 拼接存储）
- 数据依赖处理（RAW/WAW/WAR，SPAD tile/CIMC page/DRAM 粒度，2~5 组件 data hazard）
- 乱序发射与并行调度（发射窗口 ISTB_DP、2~5 组件并行、同组件双指令）
- 各执行单元（MST：GLSU/LLSU/MPU/VPU/NIU）调度及特例（NIU 单条 dst、GLSU/NIU load-store 并行、TMU 竞争）
- 存储资源管理（SPAD 8 块 × 4 tile、CIMC 4 page、DRAM 整块，占用/释放）
- 返回值与握手（sync/noc_fence 状态返回、rd_lmem/V_S 数值返回、tag 乱序返回、指令/数据握手）
- 反压流控（读请求反压、写请求反压、VPU scalar 反压、ISTB 满反压）
- 异常与中断（指令异常、读写 LMEM 异常、block_en 行为、中断清除）
- 性能统计与 debug（并行度、各组件拥塞数、debug 寄存器）
- CSR 配置与低功耗（creg_cmd_icg_en、creg_cmd_tile_rls_en 等，IDLE/ICG）
- 横向切面：接口、时钟复位、参数配置、数据值域、数据形状、错误异常、中间复位、边界、流控反压、性能长稳（见第 3 章）

### 1.3 术语

| 术语 | 含义 |
|---|---|
| CMD / cmd_sch | Command Scheduler，指令调度模块，下发 send/receive 描述符 |
| IDU / inst_disp | Inst Dispatcher Unit，指令分发单元，CMD 的上游 |
| ISTB | Inst Buffer，指令存储缓存单元，采用链表存储 |
| MST | Master，各功能组件，包括 GLSU、LLSU、MPU、VPU 和 NIU |
| GLSU / LLSU | Global / Local Load Store Unit，全局/本地数据搬运单元 |
| MPU / VPU | Matrix / Vector Process Unit，矩阵/向量运算单元 |
| NIU | Network Interface Unit，网络接口单元 |
| SPAD | Scratchpad Memory，片上低延迟 SRAM，逻辑上切分为 8 块 × 4 tile |
| CIMC | Compute-in-Memory Cluster，存内计算簇，访问粒度为 page（4 个） |
| DRAM | 全局存储，仅 GLSU 可访问，作为一整块占用 |
| NICE / VNICE | 按 inst_flag 区分的两类指令，值为 1 代表 VNICE，0 代表 NICE，core 内无功能区别 |
| sync | 同步指令，与所有 MST 存在 structure hazard，返回 32'h1 |
| noc_fence | NOC 同步屏障，与 NOC 组件存在 structure hazard，返回 32'h1 |
| xd | 指令是否产生返回数据，xd=1 指令需给 inst_disp 返回值（含 tag） |
| RAW / WAW / WAR | 真数据依赖 / 输出依赖 / 反依赖；RAR 无需判断 |
| tile / page | SPAD 按 tile 切分（4 个/块），CIMC 按 page 切分（4 个），hazard 以 tile/page 为粒度判断 |
| TMU | Tensor Manipulation Unit，GLSU/LLSU 均可调用，GLSU 优先级更高 |
| CP / CG / Bin / Cross | Coverpoint 功能覆盖点 / Coverage Group 覆盖率组 / 覆盖点取值区间 / 交叉覆盖 |
| 种子基线 | 回归时固定使用的随机种子集合 |
| 平台期 | 增加种子数覆盖率不再显著增长的拐点 |
| 专题（Topic） | 验证评审维度，按主功能、横向切面、场景、微架构组织；不直接产生 covergroup，但约束覆盖实现与签核 |
| 联合 covergroup | 跨 agent 场景下，在行为侧 monitor 采样生效配置后与行为 coverpoint 做组内 cross 的 covergroup |
| 配置上下文（csr_ctx） | 行为采样拍生效 CSR 值快照，来源为白盒探针或 RAL mirror |

---

## 2. 设计功能概述

### 2.1 调度器职责

CMD_SCH 位于 inst_disp 与各功能组件之间，根据硬件资源和数据依赖关系完成指令的乱序发射，以提高 MPU、VPU、GLSU、LLSU、NIU 的硬件利用率。主要职责如下：

1. 和 inst_disp 进行指令握手，cmd 无法接收指令时反压 inst_disp（cmd_valid/cmd_ready）。
2. 和 inst_disp 进行数据握手，inst_disp 无法接收 xd=1 指令的 rsp 数据时反压 cmd，支持数据带原 tag 乱序返回（rsp_valid/rsp_ready）。
3. 接收 inst_disp 下发的指令序列，解决指令间 RAW/WAR/WAW 冲突，并根据组件执行情况将指令发射或存储到 ISTB。
4. 对发射后的指令进行解码，将 cfg 信息发送到各个组件。
5. 存储无法发射的指令，产生对应 hazard 信息，每拍判断指令能否发射。
6. 和各组件进行 start-done 交互，用于启动组件和接收组件结束信息。
7. 接收各组件 rd_release 和 wr_release 信号，用于提前释放存储资源。

### 2.2 接口信号

CMD_SCH 的接口按交互对象划分如下（信号名以 CDD 接口文件为准）：

| 接口 | 交互对象 | 说明 |
|---|---|---|
| cmd_valid / cmd_ready | inst_disp | 指令握手接口，cmd 满时拉低 cmd_ready 反压 |
| rsp_valid / rsp_ready | inst_disp | 数据握手接口，xd=1 指令返回值，支持乱序返回 |
| i_ch1_req_rrdy | 读通路 | 读请求反压信号 |
| i_ch0_req_wrdy | 写通路 | 写请求反压信号 |
| start / start_inst_id / cfg | cmd → 各 MST | 启动信号，每个 MST 最多拉高两拍且 inst_id 不同，cfg 仅在 start 当拍有效 |
| done_vld / done_inst_id | 各 MST → cmd | 指令完成信号，与 inst_id 匹配 |
| rls_vld / rls_inst_id | 各 MST → cmd | 资源释放信号，须在 done_vld 之前或同拍拉高，与 inst_id 匹配 |
| rd_release / wr_release | 各 MST → cmd | 按 tile/page/dram 粒度的提前释放信号 |
| xxx_masked_int | 各组件 → cmd | 组件中断信号，受 block_en 控制 |
| scalar / scalar_ready | VPU → cmd | V_S 指令标量返回值，握手传输 |
| 各 MST cfg 接口 | cmd → 各 MST | 指令解码后的配置信息 |

CMD_SCH 主要由 inst buffer（ISTB）、decode（含 slicer、sp_inst）、scoreboard（含各 MST inst_disp 与 hazard_det）、dispatch、cmd_int_perf 五个二级模块组成。

---

## 3. 验证专题体系

本章回答“验证什么”，是验证策略层。专题不直接产生 covergroup，但每个专题必须落到“主责 CG / coverpoint / cross / SVA / scoreboard / 测试”至少一项。覆盖实现见第 4 章，约束见第 5 章，签核见第 10 章。

### 3.1 专题体系与四层模型

| 维度 | 作用 | 落地章节 |
|---|---|---|
| 主功能树专题（纵向） | 逐项确认 CMD_SCH 主功能是否验证 | 3.2 + 第 9 章需求追溯 |
| 横向切面专题（横向） | 每个功能在接口/复位/配置/值域/形状/异常/中间复位/边界/反压/长稳切面上是否验证 | 3.3 |
| 端到端场景专题 | 多主功能串联是否跑通 | 3.4 |
| 微架构专题 | 白盒子模块是否正确 | 3.5 |
| 覆盖组 | 怎么采、bin 怎么定义、交叉怎么分 | 第 4 章 |
| 约束/批次/种子 | 怎么产生激励 | 第 5~7 章 |
| 签核 | 怎么算过 | 第 10 章 |

**原则**：

1. 专题不直接产生 covergroup，但每个专题必须落到“主责 CG / coverpoint / cross / SVA / scoreboard / 测试”至少一项。
2. 不适用的专题项必须写“不适用 + 理由”，不允许留空。
3. 一个功能节点至少挂一个 Feat，一个 Feat 至少挂一个 CP/Cross，避免孤立需求或孤立覆盖点。
4. 跨 agent（配置 vs 指令）不做跨 covergroup 直接 `cross`，统一在行为侧联合 covergroup 中采样生效配置值后组内 `cross`（见 4.12.3 与 8.3）。

### 3.2 主功能树专题（纵向）

#### 3.2.1 功能树节点定义

| 节点 ID | 主功能树节点 | 需求 ID | 主责 CG | 配套检查 | 测试/批次 | 状态 |
|---|---|---|---|---|---|---|
| FT-01 | 指令接收与分类 | Feat-3, 28 | CG_CMDSCHED_ITYPE | SVA：cmd_valid/ready 保持；illegal_bins | cmdsched_instype_test（批次 2） | 计划中 |
| FT-02 | ISTB 管理 | Feat-19 | CG_CMDSCHED_INSTB | SVA：head/tail/pre_inst_idx 一致性；scoreboard 链表镜像 | cmdsched_instb_test（批次 3） | 计划中 |
| FT-03 | 数据依赖处理 | Feat-2, 5, 7, 10, 11~14 | CG_CMDSCHED_DEP | scoreboard：在飞表、tile/page/dram 占用表 | cmdsched_dep_test / hazard_scope_test（批次 4、5） | 计划中 |
| FT-04 | 乱序发射与并行调度 | Feat-19, 15~18 | CG_CMDSCHED_ISSUE | SVA：can_issue = dependency_ready && mst_avail | cmdsched_basic_test / parallel_test（批次 1、6） | 计划中 |
| FT-05 | 执行单元调度 | Feat-1, 8, 9, 10, 23 | CG_CMDSCHED_UNIT | SVA：start 最多两拍、cfg 仅 start 当拍；start-done-rls 时序 | cmdsched_parallel_test（批次 6） | 计划中 |
| FT-06 | 存储资源管理 | Feat-6, 21, 22 | CG_CMDSCHED_MEM | scoreboard：tile/page/dram 占用/释放镜像；泄漏检查 | cmdsched_mem_test（批次 7） | 计划中 |
| FT-07 | 返回值与握手 | Feat-2, 4, 7, 20, 26, 27 | CG_CMDSCHED_RSP | SVA：rsp_valid 保持到 rsp_ready；scoreboard 按 tag 比对 | cmdsched_rsp_test（批次 8） | 计划中 |
| FT-08 | 异常与中断 | Feat-28, 29, 30 | CG_CMDSCHED_EXCP | SVA：block_en 后停止收发；scoreboard 现场保存 | cmdsched_excp_perf_test（批次 9） | 计划中 |
| FT-09 | 性能统计与 debug | Feat-31~37, 38~40 | CG_CMDSCHED_PERF | scoreboard：RTL 寄存器 vs monitor 统计比对 | cmdsched_excp_perf_test（批次 9） | 计划中 |
| FT-10 | CSR 与低功耗 | Feat-24, 25 | CG_CMDSCHED_CSR | SVA：门控时钟开/关条件；联合 covergroup | cmdsched_excp_perf_test（批次 9） | 计划中 |

#### 3.2.2 功能树节点到覆盖率组与覆盖点映射

| 功能树节点 | 组内覆盖点 | 组内交叉 | 关键 Feat |
|---|---|---|---|
| FT-01 | cp_inst_flag, cp_inst_func, cp_inst_comp, cp_prim_type（+cp_data_format） | X_ITYPE_001, X_ITYPE_002 | Feat-3, 28 |
| FT-02 | cp_instb_level, cp_instb_chain, cp_instb_cfg_drv, cp_instb_dp（+cp_mid_reset_istb） | X_INSTB_001, X_INSTB_002 | Feat-19 |
| FT-03 | cp_hazard_type, cp_hazard_gran, cp_hazard_scope, cp_struct_hazard（+cp_mid_reset_sb） | X_DEP_001, X_DEP_002 | Feat-2,5,7,10,11~14 |
| FT-04 | cp_issue_path, cp_issue_priority, cp_start_done_seq, cp_mst_avail（+cp_ost2_full, cp_drf_dp_full） | X_ISSUE_001, X_ISSUE_002 | Feat-19,15~18 |
| FT-05 | cp_mst_id, cp_mst_slot, cp_paral_scope, cp_ls_parallel, cp_tmu_arb, cp_third_inst_blocked | X_UNIT_001, X_UNIT_002 | Feat-1,8,9,10,23 |
| FT-06 | cp_spad_tile_occ, cp_cimc_page_occ, cp_dram_occ, cp_multi_mst_spad, cp_mem_release_src, cp_spad_tile_map（+cp_mid_reset_mem, cp_tensor_shape, cp_wstrb） | X_MEM_001, X_MEM_002 | Feat-6,21,22 |
| FT-07 | cp_rsp_type, cp_rsp_data, cp_rsp_tag, cp_rsp_prio, cp_cmd_handshake, cp_backpressure, cp_wr_lmem_rmw（+cp_data_format, cp_rsp_data_boundary, cp_mid_reset_rsp） | X_RSP_001, X_RSP_002 | Feat-2,4,7,20,26,27 |
| FT-08 | cp_int_type, cp_block_en, cp_int_clear, cp_excep_en, cp_int_info_save（+cp_mid_reset_excp, cp_timeout_err, cp_protocol_err, cp_int_storm） | X_EXCP_001 | Feat-28,29,30 |
| FT-09 | cp_perf_paral, cp_perf_cong, cp_debug_reg, cp_perf_en（+cp_perf_longrun） | 见 4.12.2 与 4.12.3 | Feat-31~40 |
| FT-10 | cp_csr_icg, cp_csr_excep_en, cp_csr_perf_en, cp_csr_block_en, cp_csr_tile_rls, cp_csr_spad_excl, cp_idle_icg | 见 4.12.2 与 4.12.3 | Feat-24,25 |

> 注：Feat-1~40 在主功能树节点下均有归属，无孤立 Feat；每个功能树节点至少一个主责 CG，无孤立覆盖点。

### 3.3 横向切面专题（横向）

列定义：I=接口，R=时钟复位，C=参数配置，V=数据值域，S=数据形状，E=错误异常，MR=中间复位，B=边界，F=流控反压，P=性能长稳。格内填 `主责覆盖点/交叉 + 配套检查`，不适用填 `N/A + 理由`。

#### 3.3.1 切面专题定义

| Topic | Applicability | Reason |
|---|---|---|
| 接口 | applicable | CMD_SCH 包含与 inst_disp、SPAD XBAR、各 MST、中断/性能/debug/预留/SPAD exclusive 等接口，需验证握手、位宽、方向、时序 |
| 时钟复位 | applicable | 规格定义 clk 目标 700MHz@T22、rst_n 低有效及复位初始化要求，需验证时钟复位行为 |
| 参数和配置 | applicable | 规格含 cfg/pre 解析存储、core_reg cfg、buffer 深度、ost=2、tile 个数、SPAD exclusive、中断/性能使能 |
| 数据值域 | applicable | 规格涉及 FP32/FP16/BF16/F143/F152/FP4、Int、MXFP8/MXFP4/MXINT8/MXINT4、wstrb、32bit 返回值、地址和 ID 值域 |
| 数据形状 | applicable | 规格涉及 Tensor dim0/dim1/dim2、stride、tile 切分、CIMC 默认 2x2、dram/tile 地址范围 |
| 错误异常 | applicable | 规格列出指令错误、协议错误、超时、系统/硬件异常及检测、上报、恢复策略 |
| 中间复位 | applicable | 规格提供 rst_n 复位及错误恢复中的复位/队列清理策略，需验证复位后 FIFO、寄存器、状态机恢复 |
| 边界 | applicable | 规格含 buffer 深度 2/4、tile 最小 1/最大 SPAD 深度、乱序窗口 dRF_DP、outstanding=2、地址对齐 |
| 流控和反压 | applicable | 规格定义 master ins_fifo_full 反压、cfg/drv buffer 满反压 decode、decode 满反压 inst_disp、xd 返回仲裁 |
| 性能长稳 | applicable | 规格定义典型场景 1 条/cycle、乱序发射、多 xd=1、TMU 优先级、性能监控计数器 |

#### 3.3.2 主功能 × 横向切面矩阵

| 功能 \ 切面 | I 接口 | R 时钟复位 | C 参数配置 | V 数据值域 | S 数据形状 | E 错误异常 | MR 中间复位 | B 边界 | F 流控反压 | P 性能长稳 |
|---|---|---|---|---|---|---|---|---|---|---|
| FT-01 指令接收分类 | cmd 握手 SVA；cp_cmd_handshake | 复位初值；复位期间握手屏蔽 SVA | cfg/pre 解析；cp_prim_type | primitive 编码值域；cp_prim_type；cp_data_format | N/A（分类不涉形状） | cp_prim_type.il_rd_csr/il_reserved；cmd_int0 | 复位清译码队列；cp_mid_reset_istb | 保留编码边界 | cmd_ready 反压 | N/A（单指令分类） |
| FT-02 ISTB 管理 | ISTB 读写时序 SVA | 复位清 head/tail/链表；cp_mid_reset_istb | cp_instb_dp；DP=1/2/4/8 | N/A | N/A | N/A | 复位清 ISTB；在飞指令处理；cp_mid_reset_istb | cp_instb_level.full；插空 refill | ISTB 满反压 IDU；cp_issue_path.backpressure | 长稳不泄漏；链表指针 scoreboard |
| FT-03 数据依赖 | hazard 信号时序 SVA | 复位清 scoreboard；cp_mid_reset_sb | N/A | N/A | tile/page/dram 粒度；cp_hazard_gran；CIMC 2x2 | lmem-LLSU 冲突；cmd_int1 | 复位清在飞表/占用表；cp_mid_reset_sb | 2~5 组件边界；cp_hazard_scope | N/A（依赖不涉反压） | N/A（依赖非性能项） |
| FT-04 发射调度 | start/done/rls SVA | 复位清发射状态机 | dRF_DP/ost=2；cp_mst_avail；cp_ost2_full；cp_drf_dp_full | N/A | N/A | N/A | 复位清发射队列 | 窗口满/ost=2 满；cp_mst_avail.full | 多级反压传播；cp_issue_path | 1 条/cycle；cp_perf_paral |
| FT-05 执行单元 | start/cfg/done SVA | 复位清双槽 | N/A | N/A | N/A | N/A | 复位清槽位 | 双槽满/第三条；cp_third_inst_blocked | ins_fifo_full；cp_backpressure | TMU 不饿死；cp_tmu_arb |
| FT-06 存储资源 | rd/wr_release 时序 SVA | 复位清占用表；cp_mid_reset_mem | cp_csr_tile_rls | N/A | 32 tile/4 page；cp_spad_tile_map；cp_tensor_shape | 非 SPAD 地址；cmd_int1 | 复位释放占用；cp_mid_reset_mem | tile 最小/最大；cp_tensor_shape | N/A（资源非反压源） | 长稳不泄漏；scoreboard 占用镜像 |
| FT-07 返回值握手 | rsp_valid/ready SVA | 复位清 rsp_fifo；cp_mid_reset_rsp | cp_csr_spad_excl | FP32/FP16/...；cp_data_format；cp_rsp_data_boundary；cp_wstrb | N/A | 超时/协议错误（见 4.13） | 复位清 tag；cp_mid_reset_rsp | ost=2 满；cp_rsp_tag.multi_xd | xd 返回仲裁；cp_rsp_prio | 多 xd=1 长稳；tag 不丢 |
| FT-08 异常中断 | 中断上报时序 SVA | 复位清中断；cp_int_clear.reset_clear | cp_csr_excep_en/block_en | N/A | N/A | cp_int_type 全部；cp_timeout_err；cp_protocol_err | 复位清现场；cp_mid_reset_excp | 首次/后续中断；cp_int_info_save | block 后反压 | 中断风暴；cp_int_storm |
| FT-09 性能 debug | debug 寄存器读时序 SVA | 复位初值 | cp_csr_perf_en | 计数器位宽 | N/A | N/A | 复位清计数器 | 计数器溢出 | N/A | 长稳计数正确；cp_perf_longrun；scoreboard 比对 |
| FT-10 CSR 低功耗 | CSR 写时序 SVA | 复位默认值；cp_csr_icg | 全部 CSR；cp_csr_* | N/A | N/A | N/A | 复位恢复默认 | 32 位边界；cp_csr_tile_rls.part_en | N/A | ICG 长稳；cp_idle_icg |

#### 3.3.3 矩阵落地要求

1. 每个格子必须是以下之一：覆盖点/交叉 ID、SVA 名称、scoreboard 检查名、`N/A + 理由`。
2. 不允许空格；评审时按格子检查。
3. 新增覆盖点定义见 4.13，新增 SVA/scoreboard 见 4.14，新增约束见 5.6。
4. 标记“见 4.13”的项，需在对应小节给出具体定义。

### 3.4 端到端场景专题

| 场景 ID | 场景 | Applicability | Reason | 涉及功能树 | 检查 | 测试/批次 |
|---|---|---|---|---|---|---|
| SC-01 | 典型推理指令流 | applicable | 规格定义典型场景 1 条/cycle；需端到端验证 inst_disp→CMD→MST→done→rsp→rls | FT-01~07 | 吞吐率、无死锁、返回正确 | cmdsched_basic_test + 长流（批次 1/10） |
| SC-02 | 多组件并行流水 | applicable | 规格定义 2~5 组件并行、乱序发射、多 xd=1 | FT-03~05, FT-07 | 并行度达标、无资源泄漏、tag 不乱序错位 | cmdsched_parallel_test / rsp_test（批次 6、8） |
| SC-03 | 中断触发-上报-清除-恢复 | applicable | 规格定义异常中断、block_en、清中断恢复 | FT-08, FT-10 | 端到端恢复后正常收发 | cmdsched_excp_perf_test（批次 9） |
| SC-04 | 低功耗唤醒流 | applicable | 规格定义 ICG/IDLE、perf/中断开时钟 | FT-10, FT-01, FT-09 | IDLE→指令→开时钟→执行→回 IDLE | 新增 csr_icg_idle_wakeup_seq（批次 9） |
| SC-05 | 长稳混合流 | applicable | 规格定义长稳、ost=2、buffer 深度 | FT-02~09 | 计数器不溢出、FIFO 不泄漏、TMU 不饿死 | cmdsched_random_mix_test（批次 10，长跑） |

场景专题不替代功能树；覆盖实现复用功能树 CG，另加端到端 scoreboard 检查。

### 3.5 微架构专题（白盒）

| 微架构 ID | 子模块 | Applicability | Reason | 检查方式 | 关联 CG |
|---|---|---|---|---|---|
| MA-01 | ISTB 链表与指针 | applicable | 规格采用链表存储，head/tail/pre_inst_idx 正确性无法只靠黑盒覆盖 | scoreboard 链表镜像 + A_ISTB_PTR SVA | INSTB |
| MA-02 | scoreboard 与 hazard_det | applicable | 在飞表、tile/page/dram 占用表、释放时序是核心白盒逻辑 | scoreboard 占用镜像 + A_ISSUE_COND SVA | DEP, ISSUE, MEM |
| MA-03 | decode / slicer / sp_inst | applicable | cfg 下发、start 时序、rsp_fifo 出队优先级 | A_START_CFG、A_RSP_HS + scoreboard | ITYPE, RSP |
| MA-04 | dispatch | applicable | 直发/存储/ISTB 发射路径与资源判定 | A_ISSUE_COND + 路径 scoreboard | ISSUE, UNIT |
| MA-05 | cmd_int_perf | applicable | 中断现场、计数器、debug 寄存器 | scoreboard 比对 + A_PERF_MATCH | EXCP, PERF |
| MA-06 | 时钟门控单元 | applicable | ICG 门控条件、性能/中断模块独立开时钟 | A_ICG_GATE SVA + 门控时钟覆盖率 | CSR |

微架构专题以 SVA/白盒覆盖/scoreboard 为主，functional covergroup 只做场景入口，不替代断言。

### 3.6 专题到覆盖组/约束/签核的映射

| 专题 | 主责覆盖组 | 约束 | 签核门禁 |
|---|---|---|---|
| FT-01~10 | 见 3.2.2 | 见第 5 章 | 见 10.3.1 主功能树完整 |
| I/R/C/V/S/E/MR/B/F/P | 见 4.13 新增覆盖点 | 见 5.6 | 见 10.3.1 横向切面无空格 |
| SC-01~05 | 复用功能树 CG | 见 5.4 场景约束 | 见 10.3.1 场景专题 |
| MA-01~06 | 见 3.5 关联 CG | — | 见 10.3.1 微架构专题 |
| X_CFG_* | 见 4.12.3 | 见 5.6 | 见 10.4 跨 agent 联合交叉 |

---

## 4. 功能覆盖率组与覆盖点

本章回答“在哪采、bin 怎么定义、交叉怎么分”，是覆盖实现层。交叉覆盖只在 4.12 定义一次；专题带来的新增覆盖点见 4.13；新增 SVA/scoreboard 见 4.14；约束见第 5 章；采样实现见第 8 章。

### 4.1 覆盖率组总览

按 CDD 功能维度将覆盖点划分为 10 个覆盖率组（Coverage Group），每个组聚焦一类功能契约。

| CG ID | 覆盖率组名称 | 需求 ID | 覆盖点数 | 交叉数 | 目标 |
|---|---|---|---|---|---|
| CG_CMDSCHED_ITYPE | 指令类型覆盖组 | Feat-3, 28 | 4 | 2 | 100% |
| CG_CMDSCHED_INSTB | ISTB 管理覆盖组 | Feat-19 | 4 | 2 | 100% |
| CG_CMDSCHED_DEP | 数据依赖覆盖组 | Feat-2, 5, 7, 10, 11~14 | 4 | 2 | 100% |
| CG_CMDSCHED_UNIT | 执行单元调度覆盖组 | Feat-1, 8, 9, 10, 15~18, 23 | 6 | 2 | 100% |
| CG_CMDSCHED_ISSUE | 发射决策覆盖组 | Feat-19 | 4 | 2 | 100% |
| CG_CMDSCHED_MEM | 存储资源管理覆盖组 | Feat-6, 21, 22 | 6 | 2 | 100% |
| CG_CMDSCHED_RSP | 返回值与握手覆盖组 | Feat-2, 4, 7, 20, 26, 27 | 7 | 2 | 100% |
| CG_CMDSCHED_EXCP | 异常与中断覆盖组 | Feat-28, 29, 30 | 5 | 1 | 100% |
| CG_CMDSCHED_PERF | 性能与 Debug 覆盖组 | Feat-31~37, 38~40 | 4 | 0 | 100% |
| CG_CMDSCHED_CSR | CSR 与低功耗覆盖组 | Feat-24, 25 | 6 | 0 | 100% |

**注**：上表为组内覆盖点/交叉基线；跨组交叉与跨 agent 联合交叉见 4.12；新增覆盖点（cp_mid_reset_*、cp_data_format、cp_ost2_full、cp_drf_dp_full、cp_perf_longrun 等）定义见 4.13。

覆盖组之间的关系：

```
CG_CMDSCHED_ITYPE ──┐
CG_CMDSCHED_INSTB ──┤
CG_CMDSCHED_DEP   ──┼──→ 同 agent 跨组交叉：X_ISSUE_DEP_PATH（DEP×ISSUE）
CG_CMDSCHED_UNIT  ──┤                       X_MEM_OCC_MST（MEM×UNIT）
CG_CMDSCHED_ISSUE ──┤                       X_MEM_GRAN（MEM×DEP）
CG_CMDSCHED_MEM   ──┤
CG_CMDSCHED_RSP   ──┤
CG_CMDSCHED_EXCP  ──┘
CG_CMDSCHED_PERF / CG_CMDSCHED_CSR：独立组，与行为组合通过跨 agent 联合交叉（4.12.3）覆盖
```

每个覆盖率组内包含：一个或多个覆盖点（coverpoint）、组内交叉（cross）、组内非法 bin 和忽略 bin。

### 4.2 CG_CMDSCHED_ITYPE：指令类型覆盖组

#### 4.2.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_ITYPE |
| 需求 ID | Feat-3：删除 rd_csr 指令；Feat-28：异常指令产生中断（指令字段合法性） |
| 功能描述 | 覆盖指令分类契约：NICE/VNICE、普通功能/状态返回/数值返回、七类功能组件指令及 primitive 类型 |
| 采样信号 | inst_flag、inst_func、inst_comp、prim_type |
| 采样事件 | @(posedge clk) iff cmd_valid && cmd_ready |
| 放置位置 | cmdsched_monitor（decode 输出侧） |
| 目标 | 100% |

#### 4.2.2 覆盖点定义

**CP_CMDSCHED_ITYPE_001：指令类型（NICE/VNICE）**

```systemverilog
cp_inst_flag: coverpoint inst_flag {
  bins nice  = {0};
  bins vnice = {1};
}
```

**CP_CMDSCHED_ITYPE_002：指令功能分类**

```systemverilog
cp_inst_func: coverpoint inst_func {
  bins normal    = {INST_NORMAL};  // 普通功能指令：无需返回值
  bins state_rsp = {INST_STATE};   // 状态返回指令：sync / noc_fence，返回 32'h1
  bins value_rsp = {INST_VALUE};   // 数值返回指令：rd_lmem / V_S
}
```

**CP_CMDSCHED_ITYPE_003：功能组件分类**

```systemverilog
cp_inst_comp: coverpoint inst_comp {
  bins cfg  = {COMP_CFG};   // 配置信息指令（CFG/switch_CIMC_drv 等 Control Primitive，含 sync）
  bins lmem = {COMP_LMEM};  // LMEM 指令（wr_lmem_drv / rd_lmem_drv）
  bins noc  = {COMP_NOC};   // NOC 指令（含 noc_fence）
  bins glsu = {COMP_GLSU};
  bins llsu = {COMP_LLSU};
  bins mpu  = {COMP_MPU};
  bins vpu  = {COMP_VPU};
}
```

**CP_CMDSCHED_ITYPE_004：primitive 类型与指令合法性**

```systemverilog
cp_prim_type: coverpoint prim_type {
  bins cfg_inst        = {PRIM_CFG};
  bins wr_lmem_drv     = {PRIM_WR_LMEM};
  bins rd_lmem_drv     = {PRIM_RD_LMEM};
  bins switch_cimc_drv = {PRIM_SW_CIMC};
  bins tld             = {PRIM_TLD};
  bins tst             = {PRIM_TST};
  bins tensor_manip    = {PRIM_TENSOR_MANIP};
  bins tensor_proc     = {PRIM_TENSOR_PROC};
  bins vec_proc        = {PRIM_VEC_PROC};
  bins v_s             = {PRIM_V_S};
  bins sync            = {PRIM_SYNC};
  bins noc_fence       = {PRIM_NOC_FENCE};
  illegal_bins il_rd_csr   = {PRIM_RD_CSR};   // Feat-3：rd_csr_inst 已删除
  illegal_bins il_reserved = {PRIM_RESERVED}; // 不在指令集中的编码，触发 cmd_int[0]
}
```

> `illegal_bins` 与 `excep_en=off` 的语义拆分见 4.12.3：`il_*` 表示 RTL 不应接受的编码；屏蔽行为用 `cp_cfg_excep.off × cp_int_type.no_int` 单独 bin，不冲突。

#### 4.2.3 组内交叉

**X_CMDSCHED_ITYPE_001：功能分类 × 组件分类**

```systemverilog
X_itype_func_comp: cross cp_inst_func, cp_inst_comp {
  bins normal_comp = binsof(cp_inst_func.normal) &&
                     binsof(cp_inst_comp) intersect {COMP_CFG, COMP_LMEM, COMP_NOC,
                                                     COMP_GLSU, COMP_LLSU, COMP_MPU, COMP_VPU};
  bins state_comp  = binsof(cp_inst_func.state_rsp) &&
                     binsof(cp_inst_comp) intersect {COMP_CFG, COMP_NOC};  // sync / noc_fence
  bins value_comp  = binsof(cp_inst_func.value_rsp) &&
                     binsof(cp_inst_comp) intersect {COMP_LMEM, COMP_VPU}; // rd_lmem / V_S
}
```

**X_CMDSCHED_ITYPE_002：指令类型 × 功能分类**

```systemverilog
X_itype_flag_func: cross cp_inst_flag, cp_inst_func;
```

#### 4.2.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_inst_flag_dist | npu_instr | nice, vnice |
| c_inst_func_dist | npu_instr | normal, state_rsp, value_rsp |
| c_inst_comp_dist | npu_instr | cfg, lmem, noc, glsu, llsu, mpu, vpu |
| c_prim_dist | npu_instr | 全部 primitive（加权） |
| c_illegal_inst | illegal_seq | il_rd_csr, il_reserved |

> 新增覆盖点 `cp_data_format`（数据值域切面）见 4.13，随 ITYPE/RSP 采样。

### 4.3 CG_CMDSCHED_INSTB：ISTB 管理覆盖组

#### 4.3.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_INSTB |
| 需求 ID | Feat-19：乱序发射最大查询窗口为 ISTB_DP（1/2/4，默认 4） |
| 功能描述 | 覆盖 ISTB 链表存储、深度参数、满反压、cfg/drv 拼接存储与插空写入 |
| 采样信号 | instb_valid[DP-1:0]、head_flag、tail_flag、pre_inst_idx、instb_wren、instb_rden |
| 采样事件 | @(posedge clk) iff instb_wren \|\| instb_rden |
| 放置位置 | cmdsched_monitor（ISTB 侧） |
| 目标 | 100% |

#### 4.3.2 覆盖点定义

**CP_CMDSCHED_INSTB_001：ISTB 水位**

```systemverilog
cp_instb_level: coverpoint instb_level {
  bins empty = {0};
  bins one   = {1};
  bins two   = {2};
  bins three = {3};
  bins full  = {4};   // 所有位置 valid=1，反压 IDU
}
```

**CP_CMDSCHED_INSTB_002：链表节点操作**

```systemverilog
cp_instb_chain: coverpoint chain_op {
  bins head_write = {CHAIN_HEAD_WR};  // 空表首次写入，head_flag/tail_flag 均置 1
  bins tail_write = {CHAIN_TAIL_WR};  // 追加尾节点，更新 pre_inst_idx
  bins head_read  = {CHAIN_HEAD_RD};  // 读出头节点，后继节点 head_flag 置 1
  bins tail_read  = {CHAIN_TAIL_RD};  // 读出尾节点，前驱节点 tail_flag 置 1
  bins mid_read   = {CHAIN_MID_RD};   // 读出中间节点，链表指针更新
  bins refill     = {CHAIN_REFILL};   // 发射后插空写入（原位复用）
}
```

**CP_CMDSCHED_INSTB_003：cfg/drv 拼接存储**

```systemverilog
cp_instb_cfg_drv: coverpoint instb_alloc_mode {
  bins cfg_only            = {ALLOC_CFG_ONLY};             // 仅 cfg 指令写入
  bins drv_only            = {ALLOC_DRV_ONLY};             // 仅 drv 指令写入
  bins cfg_then_drv_stored = {ALLOC_CFG_DRV_STORED};       // cfg+drv 拼接后一起存入 ISTB
  bins cfg_issued_drv_stor = {ALLOC_CFG_ISSUED_DRV_STORED};// cfg 已发射、后续 drv 无法发射 → 拼接存入
}
```

**CP_CMDSCHED_INSTB_004：ISTB 深度参数**

```systemverilog
cp_instb_dp: coverpoint P_INST_BUF_DP {
  bins dp1 = {1};
  bins dp2 = {2};
  bins dp4 = {4};
  bins dp8 = {8};
}
```

#### 4.3.3 组内交叉

**X_CMDSCHED_INSTB_001：ISTB 水位 × 链表操作**

```systemverilog
X_instb_level_chain: cross cp_instb_level, cp_instb_chain {
  bins empty_head_wr = binsof(cp_instb_level.empty) && binsof(cp_instb_chain.head_write);
  bins one_tail_wr   = binsof(cp_instb_level.one)   && binsof(cp_instb_chain.tail_write);
  bins two_tail_wr   = binsof(cp_instb_level.two)   && binsof(cp_instb_chain.tail_write);
  bins full_head_rd  = binsof(cp_instb_level.full)  && binsof(cp_instb_chain.head_read);
  bins mid_rd        = binsof(cp_instb_level.three) && binsof(cp_instb_chain.mid_read);
  bins full_refill   = binsof(cp_instb_level.full)  && binsof(cp_instb_chain.refill);
}
```

**X_CMDSCHED_INSTB_002：深度参数 × 满水位**

```systemverilog
X_instb_dp_full: cross cp_instb_dp, cp_instb_level {
  bins dp_full = binsof(cp_instb_dp) && binsof(cp_instb_level.full);
}
```

#### 4.3.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_instb_dp | npu_instr（参数遍历） | dp1, dp2, dp4, dp8 |
| c_instb_fill | instb_fill_seq | full, two_tail_wr, dp_full |
| c_cfg_drv_pair | instb_fill_seq | cfg_then_drv_stored, cfg_issued_drv_stor |
| c_chain_seq | instb_chain_seq | head/tail/mid 读写、refill |

> 新增中间复位覆盖点 `cp_mid_reset_istb` 见 4.13，随 INSTB 采样。

### 4.4 CG_CMDSCHED_DEP：数据依赖覆盖组

#### 4.4.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_DEP |
| 需求 ID | Feat-2（sync hazard）、Feat-5（lmem vs LLSU）、Feat-7（noc_fence）、Feat-10（同组件双指令）、Feat-11~14（2~5 组件 data hazard） |
| 功能描述 | 覆盖 RAW/WAW/WAR 依赖、tile/page/dram 三种判断粒度、2~5 组件 hazard 范围及各类 structure hazard |
| 采样信号 | wmem_alrdy、rmem_alrdy、wmem_will、rmem_will、dependency_ready、struct_hazard |
| 采样事件 | @(posedge clk) iff 指令发射或存入 ISTB |
| 放置位置 | cmdsched_scoreboard_monitor |
| 目标 | 100% |

#### 4.4.2 覆盖点定义

**CP_CMDSCHED_DEP_001：依赖类型**

```systemverilog
cp_hazard_type: coverpoint hazard_type {
  bins no_dep = {NONE};
  bins raw    = {RAW};   // |(wmem_alrdy & rmem_will)
  bins waw    = {WAW};   // |(wmem_alrdy & wmem_will)
  bins war    = {WAR};   // |(rmem_alrdy & wmem_will)
}
```

**CP_CMDSCHED_DEP_002：依赖判断粒度**

```systemverilog
cp_hazard_gran: coverpoint hazard_gran {
  bins tile  = {GRAN_TILE};  // SPAD tile 粒度（8 SPAD × 4 tile）
  bins page  = {GRAN_PAGE};  // CIMC page 粒度（4 page）
  bins dram  = {GRAN_DRAM};  // DRAM 整块粒度（仅 GLSU）
}
```

**CP_CMDSCHED_DEP_003：hazard 范围（组件数）**

```systemverilog
cp_hazard_scope: coverpoint hazard_scope {
  bins same_mst   = {1};  // 同组件两条指令间依赖
  bins two_mst    = {2};  // Feat-11：任意两组件
  bins three_mst  = {3};  // Feat-12：任意三组件
  bins four_mst   = {4};  // Feat-13：任意四组件
  bins five_mst   = {5};  // Feat-14：五组件
}
```

**CP_CMDSCHED_DEP_004：structure hazard 类型**

```systemverilog
cp_struct_hazard: coverpoint struct_hazard {
  bins sync_all      = {SHT_SYNC_ALL};    // sync 与所有 MST 存在 structure hazard
  bins noc_fence     = {SHT_NOC_FENCE};   // noc_fence 与 NOC 存在 structure hazard
  bins lmem_llsu     = {SHT_LMEM_LLSU};   // wr/rd_lmem 与 LLSU 指令存在 structure hazard
  bins niu_dst_single= {SHT_NIU_DST};     // NIU 最多接收 1 条 noc_dst_drv
  bins niu_store_dual= {SHT_NIU_STORE};   // NIU 不能同时下发两条 store
}
```

#### 4.4.3 组内交叉

**X_CMDSCHED_DEP_001：依赖类型 × 判断粒度**

```systemverilog
X_dep_gran: cross cp_hazard_type, cp_hazard_gran {
  ignore_bins rar = binsof(cp_hazard_type.no_dep) && binsof(cp_hazard_gran);
  // RAR（多组件同读）不产生依赖阻塞
}
```

**X_CMDSCHED_DEP_002：依赖类型 × 组件数**

```systemverilog
X_dep_scope: cross cp_hazard_type, cp_hazard_scope {
  ignore_bins no_dep_multi = binsof(cp_hazard_type.no_dep) &&
                             binsof(cp_hazard_scope) intersect {2, 3, 4, 5};
}
```

#### 4.4.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_dep_dist | npu_instr | no_dep, raw, waw, war |
| c_raw / c_waw / c_war | npu_stream | X_dep_gran 各粒度 |
| c_hazard_scope_2~5 | npu_stream | two_mst ~ five_mst |
| c_same_mst_pair | npu_stream | same_mst |
| c_lmem_llsu_conflict | conflict_seq | lmem_llsu |
| c_sync_barrier / c_noc_fence_barrier | barrier_seq | sync_all, noc_fence |
| c_niu_dst / c_niu_store | niu_seq | niu_dst_single, niu_store_dual |

> 新增中间复位覆盖点 `cp_mid_reset_sb` 见 4.13，随 DEP/ISSUE 采样。

### 4.5 CG_CMDSCHED_UNIT：执行单元调度覆盖组

#### 4.5.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_UNIT |
| 需求 ID | Feat-1（组件配置和启动）、Feat-8/9（NIU/GLSU load-store 并行）、Feat-10（同组件双指令）、Feat-15~18（2~5 组件并行）、Feat-23（TMU 竞争） |
| 功能描述 | 覆盖 5 个 MST 的调度、双指令槽、并行执行范围、load-store 并行与 TMU 竞争仲裁 |
| 采样信号 | mst_id、mst_slot_busy[1:0]、paral_scope、tmu_owner |
| 采样事件 | @(posedge clk) iff start 拉高或并行度变化 |
| 放置位置 | cmdsched_dispatch_monitor |
| 目标 | 100% |

#### 4.5.2 覆盖点定义

**CP_CMDSCHED_UNIT_001：执行单元（MST）**

```systemverilog
cp_mst_id: coverpoint mst_id {
  bins glsu = {MST_GLSU};
  bins llsu = {MST_LLSU};
  bins mpu  = {MST_MPU};
  bins vpu  = {MST_VPU};
  bins niu  = {MST_NIU};
}
```

**CP_CMDSCHED_UNIT_002：MST 指令槽占用**

```systemverilog
cp_mst_slot: coverpoint mst_slot_busy {
  bins slot0_only = {2'b01};
  bins slot1_only = {2'b10};
  bins both       = {2'b11};  // 两条指令并行执行（无 data hazard）
  bins empty      = {2'b00};
}
```

**CP_CMDSCHED_UNIT_003：并行执行范围**

```systemverilog
cp_paral_scope: coverpoint paral_scope {
  bins two_mst   = {2};  // Feat-15：任意两组件并行
  bins three_mst = {3};  // Feat-16
  bins four_mst  = {4};  // Feat-17
  bins five_mst  = {5};  // Feat-18
}
```

**CP_CMDSCHED_UNIT_004：load/store 并行**

```systemverilog
cp_ls_parallel: coverpoint ls_parallel {
  bins glsu_ls_par  = {GLSU_LS_PAR};   // Feat-9：GLSU 内部 load 和 store 并行
  bins niu_ls_par   = {NIU_LS_PAR};    // Feat-8：NIU 内部 load 和 store 并行
  bins glsu_ls_ser  = {GLSU_LS_SER};   // 有 data hazard 时串行
  bins niu_ls_ser   = {NIU_LS_SER};
}
```

**CP_CMDSCHED_UNIT_005：TMU 竞争仲裁**

```systemverilog
cp_tmu_arb: coverpoint tmu_arb {
  bins glsu_tmu        = {TMU_GLSU};         // GLSU 单独占用 TMU
  bins llsu_tmu        = {TMU_LLSU};         // LLSU 单独占用 TMU
  bins glsu_pri_contend= {TMU_GLSU_PRI};     // Feat-23：同时抢占时 GLSU 优先
  bins llsu_wait       = {TMU_LLSU_WAIT};    // LLSU 等待 TMU 释放
}
```

**CP_CMDSCHED_UNIT_006：第三条同组件指令阻塞**

```systemverilog
cp_third_inst_blocked: coverpoint third_inst_behavior {
  bins third_blocked = {THIRD_BLOCKED};  // Feat-10：前两条占满双槽时，第三条同组件指令被阻塞（存入 ISTB）
  bins third_issued  = {THIRD_ISSUED};   // 前两条执行完成释放槽位后，第三条不被阻塞（直发）
}
```

#### 4.5.3 组内交叉

**X_CMDSCHED_UNIT_001：MST × 指令槽**

```systemverilog
X_unit_slot: cross cp_mst_id, cp_mst_slot {
  bins niu_both = binsof(cp_mst_id.niu) && binsof(cp_mst_slot.both);
  // 注意：NIU 不能同时两条 store，若出现即视为场景错误（配合断言）
}
```

**X_CMDSCHED_UNIT_002：MST × 并行范围**

```systemverilog
X_unit_paral: cross cp_mst_id, cp_paral_scope;
```

#### 4.5.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_mst_dist | npu_instr | glsu, llsu, mpu, vpu, niu |
| c_mst_dual | npu_stream | both, X_unit_slot |
| c_multi_parallel_2~5 | parallel_seq | two_mst ~ five_mst, X_unit_paral |
| c_ls_pair_seq | ls_parallel_seq | glsu_ls_par, niu_ls_par |
| c_tmu_contend | tmu_seq | glsu_pri_contend, llsu_wait |
| c_third_inst_blocked | third_inst_seq | third_blocked, third_issued |

### 4.6 CG_CMDSCHED_ISSUE：发射决策覆盖组

#### 4.6.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_ISSUE |
| 需求 ID | Feat-19（乱序发射窗口与发射策略） |
| 功能描述 | 覆盖指令发射路径（直发/ISTB 存储/ISTB 发射）、发射优先级、start-done-rls 时序与 MST 可用资源判定 |
| 采样信号 | issue_path、dependency_ready、mst_avail、start_inst_id、done_vld、rls_vld |
| 采样事件 | @(posedge clk) |
| 放置位置 | cmdsched_scoreboard_monitor |
| 目标 | 100% |

#### 4.6.2 覆盖点定义

**CP_CMDSCHED_ISSUE_001：发射路径**

```systemverilog
cp_issue_path: coverpoint issue_path {
  bins direct      = {ISSUE_DIRECT};    // 无冲突，新指令直接发射到 MST
  bins istb_stored = {ISSUE_STORED};    // 有冲突，指令存入 ISTB
  bins istb_issued = {ISSUE_ISTB_ISSUE};// ISTB 中指令满足条件后发射
  bins backpressure= {ISSUE_BACKPR};    // ISTB 满 / MST 满，反压 IDU
}
```

**CP_CMDSCHED_ISSUE_002：发射优先级**

```systemverilog
cp_issue_priority: coverpoint issue_priority {
  bins new_first    = {PRIO_NEW_INST};  // 同一 MST 下，新指令优先于 ISTB 中指令发射
  bins istb_issued  = {PRIO_ISTB};      // 无新指令时，ISTB 指令发射
}
```

**CP_CMDSCHED_ISSUE_003：start-done-rls 时序**

```systemverilog
cp_start_done_seq: coverpoint start_done_seq {
  bins start0_done0     = {SD_S0_D0};  // 先启动先 done（默认顺序）
  bins start1_done1     = {SD_S1_D1};
  bins start1_done0     = {SD_S1_D0};  // 后启动先 done（仅 GLSU/NIU load-store 并行）
  bins rls_before_done  = {SD_RLS_BEFORE};  // rls_vld 先于 done_vld
  bins rls_same_done    = {SD_RLS_SAME};    // rls_vld 与 done_vld 同拍
}
```

**CP_CMDSCHED_ISSUE_004：MST 可用资源**

```systemverilog
cp_mst_avail: coverpoint mst_avail {
  bins avail0       = {2'b00};  // 无指令在飞，可接收 2 条
  bins avail1       = {2'b01};  // 1 条在飞，可再接收 1 条
  bins full         = {2'b11};  // 2 条在飞，同组件指令被阻塞
  bins niu_dst_full = {2'b10};  // NIU 中 noc_dst 指令已占用（最多 1 条）
}
```

#### 4.6.3 组内交叉

**X_CMDSCHED_ISSUE_001：依赖判定 × 发射路径（同 agent 跨组）**

```systemverilog
X_issue_dep_path: cross cp_hazard_type, cp_issue_path {
  bins no_dep_direct  = binsof(cp_hazard_type.no_dep) && binsof(cp_issue_path.direct);
  bins raw_stored     = binsof(cp_hazard_type.raw)    && binsof(cp_issue_path.istb_stored);
  bins waw_stored     = binsof(cp_hazard_type.waw)    && binsof(cp_issue_path.istb_stored);
  bins war_stored     = binsof(cp_hazard_type.war)    && binsof(cp_issue_path.istb_stored);
  bins raw_istb_issue = binsof(cp_hazard_type.raw)    && binsof(cp_issue_path.istb_issued);
  bins no_dep_blocked = binsof(cp_hazard_type.no_dep) && binsof(cp_issue_path.backpressure);
}
```

**X_CMDSCHED_ISSUE_002：MST 可用资源 × 发射路径**

```systemverilog
X_issue_avail: cross cp_mst_avail, cp_issue_path {
  bins avail_direct   = binsof(cp_mst_avail.avail0) && binsof(cp_issue_path.direct);
  bins avail1_issued  = binsof(cp_mst_avail.avail1) && binsof(cp_issue_path.direct);
  bins full_stored    = binsof(cp_mst_avail.full)   && binsof(cp_issue_path.istb_stored);
  bins full_backpress = binsof(cp_mst_avail.full)   && binsof(cp_issue_path.backpressure);
  bins niu_dst_back   = binsof(cp_mst_avail.niu_dst_full) && binsof(cp_issue_path.backpressure);
  bins avail_istb_iss = binsof(cp_mst_avail.avail1) && binsof(cp_issue_path.istb_issued);
}
```

#### 4.6.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_issue_direct | npu_stream | direct, no_dep_direct |
| c_issue_stall | npu_stream | istb_stored, raw_stored |
| c_issue_backpressure | instb_fill_seq | backpressure, full_backpress |
| c_start_done_seq | start_done_seq | start0_done0 ~ start1_done0 |
| c_rls_timing | start_done_seq | rls_before_done, rls_same_done |

> 新增边界覆盖点 `cp_ost2_full`、`cp_drf_dp_full` 见 4.13，随 ISSUE 采样。

### 4.7 CG_CMDSCHED_MEM：存储资源管理覆盖组

#### 4.7.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_MEM |
| 需求 ID | Feat-6（CIMC 仅 2x2）、Feat-21（多组件访问同一 SPAD）、Feat-22（按 tile 切分 SPAD） |
| 功能描述 | 覆盖 SPAD tile / CIMC page / DRAM 的占用、释放与冲突，多组件共享 SPAD 的 tile 粒度管理 |
| 采样信号 | wtile_ongoing_total、rtile_ongoing_total、wpage_ongoing_total、rpage_ongoing_total、wdram/rdram_ongoing_total、rd_release、wr_release |
| 采样事件 | @(posedge clk) iff 占用或释放状态变化 |
| 放置位置 | cmdsched_scoreboard_monitor |
| 目标 | 100% |

#### 4.7.2 覆盖点定义

**CP_CMDSCHED_MEM_001：SPAD tile 占用/释放**

```systemverilog
cp_spad_tile_occ: coverpoint spad_tile_occ {
  bins tile_alloc      = {TILE_ALLOC};       // 指令发射后占用 tile
  bins tile_release    = {TILE_RELEASE};     // done 后释放全部占用 tile
  bins tile_partial_rls= {TILE_PARTIAL_RLS}; // 按 wr_release/rd_release 提前释放部分 tile
  bins tile_conflict   = {TILE_CONFLICT};    // 与在飞指令 tile 冲突，产生 hazard
}
```

**CP_CMDSCHED_MEM_002：CIMC page 占用/释放**

```systemverilog
cp_cimc_page_occ: coverpoint cimc_page_occ {
  bins page_alloc   = {PAGE_ALLOC};
  bins page_release = {PAGE_RELEASE};
  bins page_conflict= {PAGE_CONFLICT};
  bins cimc_2x2     = {CIMC_2X2};   // Feat-6：仅支持 2x2 形状，1x4 已删除
}
```

**CP_CMDSCHED_MEM_003：DRAM 占用/释放**

```systemverilog
cp_dram_occ: coverpoint dram_occ {
  bins dram_alloc   = {DRAM_ALLOC};    // GLSU 访问 DRAM 时整块占用
  bins dram_release = {DRAM_RELEASE};
  bins dram_whole   = {DRAM_WHOLE};    // DRAM 作为一整块存储，不分片
}
```

**CP_CMDSCHED_MEM_004：多组件共享 SPAD**

```systemverilog
cp_multi_mst_spad: coverpoint multi_mst_spad {
  bins mst2_same_spad = {2};  // Feat-21：两个组件无冲突访问同一 SPAD（tile 不重叠）
  bins mst3_same_spad = {3};
  bins mst4_same_spad = {4};
  bins mst5_same_spad = {5};
  bins rar_multi_read = {RAR}; // 多组件同读同一 SPAD，无依赖（RAR 不阻塞）
}
```

**CP_CMDSCHED_MEM_005：资源释放来源**

```systemverilog
cp_mem_release_src: coverpoint mem_release_src {
  bins done_release    = {RLS_DONE};      // 指令 done 后释放
  bins rls_release     = {RLS_PRE};       // rd_release/wr_release 提前释放
  bins tile_rls_en_off = {RLS_DISABLED};  // creg_cmd_tile_rls_en=0，释放逻辑无效
}
```

**CP_CMDSCHED_MEM_006：SPAD tile 地址空间映射**

```systemverilog
cp_spad_tile_map: coverpoint {spad_id, tile_id} {
  bins tile_00  .. tile_31 = {[0:31]};  // Feat-22：32 个 tile 组合均需发生占用/释放
}
```

#### 4.7.3 组内交叉

**X_CMDSCHED_MEM_001：SPAD tile 状态 × MST（同 agent 跨组）**

```systemverilog
X_mem_occ_mst: cross cp_spad_tile_occ, cp_mst_id;
```

**X_CMDSCHED_MEM_002：依赖粒度 × 多组件共享（同 agent 跨组）**

```systemverilog
X_mem_gran: cross cp_hazard_gran, cp_multi_mst_spad;
```

#### 4.7.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_spad_tile_addr | npu_instr | tile_alloc, tile_conflict |
| c_cimc_page_addr | npu_instr | page_alloc, page_conflict, cimc_2x2 |
| c_dram_addr | npu_instr | dram_alloc, dram_whole |
| c_multi_mst_spad | parallel_seq | mst2~5_same_spad, rar_multi_read |
| c_release_early | release_seq | rls_release, tile_partial_rls |
| c_tile_rls_en | csr_seq | tile_rls_en_off |
| c_tile_map_spread | tile_map_seq | tile_00 ~ tile_31 |

> 新增中间复位覆盖点 `cp_mid_reset_mem`、数据形状覆盖点 `cp_tensor_shape`、`cp_wstrb` 见 4.13。

### 4.8 CG_CMDSCHED_RSP：返回值与握手覆盖组

#### 4.8.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_RSP |
| 需求 ID | Feat-2（sync 返回）、Feat-4（CPU 读写 LMEM）、Feat-7（noc_fence 返回）、Feat-20（多 xd=1 指令乱序返回）、Feat-26/27（读写反压） |
| 功能描述 | 覆盖状态/数值返回指令的返回值、tag 乱序、rsp_fifo 优先级、指令/数据握手与反压 |
| 采样信号 | rsp_type、rsp_data、rsp_tag、cmd_valid/cmd_ready、rsp_valid/rsp_ready、i_ch1_req_rrdy、i_ch0_req_wrdy、scalar_ready |
| 采样事件 | @(posedge clk) iff rsp_valid 或握手反压 |
| 放置位置 | cmdsched_sp_inst_monitor |
| 目标 | 100% |

#### 4.8.2 覆盖点定义

**CP_CMDSCHED_RSP_001：返回指令类型**

```systemverilog
cp_rsp_type: coverpoint rsp_type {
  bins sync_rsp      = {RSP_SYNC};     // 等待所有 MST 完成后返回 32'h1
  bins noc_fence_rsp = {RSP_NOC_FENCE};// 等待所有 NOC 指令完成后返回 32'h1
  bins rd_lmem_rsp   = {RSP_RD_LMEM};  // 读 SPAD 数据 + tag
  bins v_s_rsp       = {RSP_V_S};      // VPU scalar + tag
}
```

**CP_CMDSCHED_RSP_002：返回值数据**

```systemverilog
cp_rsp_data: coverpoint rsp_data {
  bins state_1     = {32'h1};    // sync / noc_fence 状态返回值
  bins lmem_data   = {[32'h2:32'hFFFF_FFFF]};  // rd_lmem 读回的 SPAD 数据
  bins scalar_data = {[32'h2:32'hFFFF_FFFF]};  // V_S 返回的 VPU 标量
}
```

**CP_CMDSCHED_RSP_003：tag 与乱序返回**

```systemverilog
cp_rsp_tag: coverpoint rsp_tag_mode {
  bins tag_match  = {TAG_IN_ORDER};   // 返回顺序与下发一致，tag 匹配
  bins tag_ooot   = {TAG_OUT_OF_ORDER};// Feat-20：多 xd=1 指令乱序返回，数据带原 tag
  bins multi_xd   = {MULTI_XD};        // 同拍多条 xd=1 指令在飞
}
```

**CP_CMDSCHED_RSP_004：rsp_fifo 优先级**

```systemverilog
cp_rsp_prio: coverpoint rsp_prio {
  bins scalar_prio = {PRIO_SCALAR};  // scalar_fifo 最高
  bins lmem_prio   = {PRIO_LMEM};    // 其次 lmem_fifo
  bins fence_prio  = {PRIO_FENCE};   // 再次 fence_fifo
  bins sync_prio   = {PRIO_SYNC};    // 最后 sync_fifo
}
```

**CP_CMDSCHED_RSP_005：指令/数据握手**

```systemverilog
cp_cmd_handshake: coverpoint handshake_mode {
  bins cmd_hs_ok     = {HS_CMD_OK};    // cmd_valid && cmd_ready，指令握手成功
  bins cmd_ready_low = {HS_CMD_BP};    // cmd_ready 拉低，数据保持直到 ready 拉高
  bins rsp_hs_ok     = {HS_RSP_OK};    // rsp_valid && rsp_ready，数据握手成功
  bins rsp_ready_low = {HS_RSP_BP};    // rsp_ready 拉低，反压返回数据
}
```

**CP_CMDSCHED_RSP_006：反压来源**

```systemverilog
cp_backpressure: coverpoint backpressure_src {
  bins rd_bp    = {BP_READ};    // Feat-26：读请求反压（i_ch1_req_rrdy 拉低）
  bins wr_bp    = {BP_WRITE};   // Feat-27：写请求反压（i_ch0_req_wrdy 拉低）
  bins scalar_bp= {BP_SCALAR};  // VPU scalar 返回反压（scalar_ready 拉低）
  bins istb_bp  = {BP_ISTB};    // ISTB 满，反压 IDU 指令下发
}
```

**CP_CMDSCHED_RSP_007：wr_lmem 读改写（RMW）**

```systemverilog
cp_wr_lmem_rmw: coverpoint wr_lmem_rmw {
  bins rmw_performed = {RMW_DONE};    // Feat-4：先读后写回完成（RMW 顺序正确）
  bins rmw_blocked   = {RMW_BLOCKED}; // RMW 被反压/异常打断后恢复
  // 注：RMW 替换后的数据正确性由 scoreboard 比对验证（非覆盖点职责）
}
```

#### 4.8.3 组内交叉

**X_CMDSCHED_RSP_001：返回类型 × fifo 优先级**

```systemverilog
X_rsp_prio: cross cp_rsp_type, cp_rsp_prio {
  bins v_s_scalar = binsof(cp_rsp_type.v_s_rsp)       && binsof(cp_rsp_prio.scalar_prio);
  bins lmem_prio  = binsof(cp_rsp_type.rd_lmem_rsp)   && binsof(cp_rsp_prio.lmem_prio);
  bins fence_prio = binsof(cp_rsp_type.noc_fence_rsp) && binsof(cp_rsp_prio.fence_prio);
  bins sync_prio  = binsof(cp_rsp_type.sync_rsp)      && binsof(cp_rsp_prio.sync_prio);
}
```

**X_CMDSCHED_RSP_002：返回类型 × 乱序**

```systemverilog
X_rsp_tag: cross cp_rsp_type, cp_rsp_tag {
  bins ooo = binsof(cp_rsp_tag.tag_ooot) &&
             binsof(cp_rsp_type) intersect {RSP_SYNC, RSP_NOC_FENCE, RSP_RD_LMEM, RSP_V_S};
}
```

#### 4.8.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_xd1_seq | xd1_seq | multi_xd, tag_ooot |
| c_rsp_priority_seq | xd1_seq | X_rsp_prio 各 bin |
| c_tag_out_of_order | xd1_seq | tag_ooot, ooo |
| c_backpressure_seq | bp_seq | rd_bp, wr_bp, scalar_bp, istb_bp |
| c_wr_lmem_rmw | rsp_rmw_seq | rmw_performed, rmw_blocked |

> 新增数据值域覆盖点 `cp_data_format`、`cp_rsp_data_boundary`、`cp_wstrb`，中间复位覆盖点 `cp_mid_reset_rsp` 见 4.13。

### 4.9 CG_CMDSCHED_EXCP：异常与中断覆盖组

#### 4.9.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_EXCP |
| 需求 ID | Feat-28（异常指令中断）、Feat-29（读写非 SPAD 地址中断）、Feat-30（lmem_drv 与 LLSU 同时工作中断） |
| 功能描述 | 覆盖 cmd_int[0]/cmd_int[1] 中断触发、block_en 行为、中断清除与 excep_en 屏蔽 |
| 采样信号 | cmd_int[31:0]、creg_cmd_block_en、creg_cmd_excep_en、中断清除操作 |
| 采样事件 | @(posedge clk) iff 指令译码或中断状态变化 |
| 放置位置 | cmdsched_int_monitor |
| 目标 | 100% |

#### 4.9.2 覆盖点定义

**CP_CMDSCHED_EXCP_001：中断类型**

```systemverilog
cp_int_type: coverpoint cmd_int[1:0] {
  bins no_int     = {2'b00};
  bins cmd_int0   = {2'b01};  // 指令异常：任一字段与指令集不一致（funct7/inst_flag/xd/xs1/xs2）
  bins cmd_int1   = {2'b10};  // 读写 LMEM 异常：wr_lmem_drv/rd_lmem_drv 指向 CIMC
  illegal_bins int2 = {2'b11};
}
// cmd_int[31:2] 为保留中断，作为 illegal_bins 处理
```

**CP_CMDSCHED_EXCP_002：block_en 行为**

```systemverilog
cp_block_en: coverpoint block_behavior {
  bins block_stop     = {BLOCK_STOP};     // block_en=1：中断后停止收发上下游指令
  bins block_continue = {BLOCK_CONTINUE}; // block_en=0：继续正常收发
}
```

**CP_CMDSCHED_EXCP_003：中断清除**

```systemverilog
cp_int_clear: coverpoint int_clear {
  bins reset_clear   = {CLR_RESET};  // 复位清中断（建议致命中断）
  bins wr1_clear     = {CLR_WR1};    // core_reg 写 1 清中断（建议非致命）
  bins rec_after_clr = {CLR_RECOVER};// 清中断后 block 模式恢复正常收发
}
```

**CP_CMDSCHED_EXCP_004：excep_en 屏蔽**

```systemverilog
cp_excep_en: coverpoint excep_behavior {
  bins en_on  = {EXCEP_ON};  // excep_en=1：异常检测有效，致命中断产生 done 停止
  bins en_off = {EXCEP_OFF}; // excep_en=0：屏蔽检测，不产生 done，功能无法保证
}
```

**CP_CMDSCHED_EXCP_005：中断现场信息保存**

```systemverilog
cp_int_info_save: coverpoint int_info_save {
  bins first_int_saved   = {INFO_FIRST_SAVED};    // 首次中断现场被保存
  bins later_not_saved   = {INFO_LATER_NOT_SAVED};// 后续中断不再覆盖首次现场
  bins info_readable     = {INFO_READABLE};       // 通过 core_reg 可读回现场
}
```

#### 4.9.3 组内交叉

**X_CMDSCHED_EXCP_001：中断类型 × block 行为**

```systemverilog
X_excp_block: cross cp_int_type, cp_block_en {
  bins int0_stop = binsof(cp_int_type.cmd_int0) && binsof(cp_block_en.block_stop);
  bins int0_cont = binsof(cp_int_type.cmd_int0) && binsof(cp_block_en.block_continue);
  bins int1_stop = binsof(cp_int_type.cmd_int1) && binsof(cp_block_en.block_stop);
  bins int1_cont = binsof(cp_int_type.cmd_int1) && binsof(cp_block_en.block_continue);
}
```

#### 4.9.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_illegal_inst | illegal_seq | cmd_int0 |
| c_non_spad_addr | illegal_seq | cmd_int0（非 SPAD 读写） |
| c_cimc_lmem_addr | illegal_seq | cmd_int1 |
| c_lmem_llsu_conflict | conflict_seq | Feat-30 中断场景 |
| c_block_en_cfg | csr_seq | block_stop, block_continue |
| c_int_clear_seq | int_clear_seq | reset_clear, wr1_clear, rec_after_clr |
| c_int_info_save | int_info_seq | first_int_saved, later_not_saved, info_readable |

> 新增中间复位覆盖点 `cp_mid_reset_excp`、超时/协议错误覆盖点（若 CMD_SCH 负责）`cp_timeout_err`、`cp_protocol_err`、中断风暴 `cp_int_storm` 见 4.13。

### 4.10 CG_CMDSCHED_PERF：性能与 Debug 覆盖组

#### 4.10.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_PERF |
| 需求 ID | Feat-31~35（各组件 ISTB 拥塞统计）、Feat-36/37（并行度统计）、Feat-38~40（debug 寄存器） |
| 功能描述 | 覆盖性能统计使能、并行度统计、各 MST 拥塞计数与 debug 寄存器可读性 |
| 采样信号 | creg_cmd_perf_en、perf_paral_total、perf_paral_mpu、perf_cong_mst、debug0/1/2 |
| 采样事件 | @(posedge clk) iff creg_cmd_perf_en |
| 放置位置 | cmdsched_perf_monitor |
| 目标 | 100% |

#### 4.10.2 覆盖点定义

**CP_CMDSCHED_PERF_001：并行度统计**

```systemverilog
cp_perf_paral: coverpoint perf_paral {
  bins total_paral = {PERF_TOTAL};  // Feat-36：所有组件平均并行度
  bins mpu_paral   = {PERF_MPU};    // Feat-37：MPU 平均并行度
  bins win_open    = {PERF_WIN};    // 性能统计窗口开启期间采样
}
```

**CP_CMDSCHED_PERF_002：各 MST 拥塞统计**

```systemverilog
cp_perf_cong: coverpoint perf_cong_mst {
  bins mpu_cong  = {CONG_MPU};   // Feat-31
  bins vpu_cong  = {CONG_VPU};   // Feat-32
  bins glsu_cong = {CONG_GLSU};  // Feat-33
  bins llsu_cong = {CONG_LLSU};  // Feat-34
  bins niu_cong  = {CONG_NIU};   // Feat-35
}
```

**CP_CMDSCHED_PERF_003：debug 寄存器**

```systemverilog
cp_debug_reg: coverpoint debug_reg {
  bins dbg0_busy     = {DBG0};  // Feat-38：各组件 busy 状态
  bins dbg1_inst_cnt = {DBG1};  // Feat-39：inst_disp 总下发指令数（含 cfg/pre/drv）
  bins dbg2_iss_cnt  = {DBG2};  // Feat-40：cmd_sch 总发射 primitive 数（仅 drv）
}
```

**CP_CMDSCHED_PERF_004：性能统计使能**

```systemverilog
cp_perf_en: coverpoint creg_cmd_perf_en {
  bins en_on  = {1'b1};  // 性能监测打开
  bins en_off = {1'b0};  // 性能监测关闭
}
```

#### 4.10.3 组内交叉

性能与 Debug 覆盖组不定义组内交叉；并行度与拥塞统计的计数正确性通过 scoreboard 校验（RTL 寄存器值与 monitor 统计值比对）。CSR × PERF 联合交叉见 4.12.3。

#### 4.10.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_perf_window | perf_seq | win_open, total_paral, mpu_paral |
| c_perf_cong_seq | perf_seq | mpu_cong ~ niu_cong |
| c_perf_en | csr_seq | en_on, en_off |

> 新增长稳覆盖点 `cp_perf_longrun` 见 4.13，配合 scoreboard A_PERF_MATCH、A_NO_TILE_LEAK 使用。

### 4.11 CG_CMDSCHED_CSR：CSR 与低功耗覆盖组

#### 4.11.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_CMDSCHED_CSR |
| 需求 ID | Feat-24（creg_cmd_icg_en[31:0]）、Feat-25（删除各组件低功耗模式） |
| 功能描述 | 覆盖 CMD 内部 CSR 配置（icg/excep/perf/block/tile_rls/spad_excl）及 IDLE/ICG 低功耗行为 |
| 采样信号 | creg_cmd_icg_en、creg_cmd_excep_en、creg_cmd_perf_en、creg_cmd_block_en、creg_cmd_tile_rls_en、creg_cmd_spad_excl_en、idle/gate 状态 |
| 采样事件 | @(posedge clk) iff CSR 写或 ICG 状态变化 |
| 放置位置 | cmdsched_csr_monitor |
| 目标 | 100% |

#### 4.11.2 覆盖点定义

**CP_CMDSCHED_CSR_001：ICG 使能**

```systemverilog
cp_csr_icg: coverpoint creg_cmd_icg_en {
  bins icg_on  = {[1:$]};  // Feat-24：打开 CMD 内部 ICG，低功耗模式
  bins icg_off = {0};      // 关闭 ICG，时钟常开
}
```

**CP_CMDSCHED_CSR_002~005：异常/性能/阻塞/释放使能**

```systemverilog
cp_csr_excep_en: coverpoint creg_cmd_excep_en { bins on = {1}; bins off = {0}; }
cp_csr_perf_en:  coverpoint creg_cmd_perf_en  { bins on = {1}; bins off = {0}; }
cp_csr_block_en: coverpoint creg_cmd_block_en { bins on = {1}; bins off = {0}; }
cp_csr_tile_rls: coverpoint creg_cmd_tile_rls_en {
  bins all_en  = {32'hFFFF_FFFF};
  bins all_off = {32'h0};
  bins part_en = {[1:32'hFFFF_FFFE]};
}
cp_csr_spad_excl: coverpoint creg_cmd_spad_excl_en {
  bins non_excl = {32'h0};
  bins excl_cfg = {[1:$]};  // 当前架构暂不支持独占模式，验证默认值与非独占行为
}
```

**CP_CMDSCHED_CSR_007：IDLE 与 ICG 状态**

```systemverilog
cp_idle_icg: coverpoint idle_icg_state {
  bins idle      = {IDLE_NO_CLK};  // 无指令下发时各模块无时钟
  bins gate_on   = {GATE_OPEN};    // 指令下发后按译码结果打开子模块时钟
  bins perf_gate = {GATE_PERF};    // 中断/性能使能打开时给 cmd_int_perf 开时钟
}
```

#### 4.11.3 组内交叉

CSR 与低功耗覆盖组不定义组内交叉；CSR 配置与行为结果的联动由 4.12.3 跨 agent 联合交叉覆盖。配置侧仍保留 8.2 的配置事务 covergroup（值 × 写时序）。

#### 4.11.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| c_csr_icg | csr_seq | icg_on, icg_off, idle, gate_on |
| c_csr_tile_rls | csr_seq | all_en, part_en, all_off |
| c_csr_block | csr_seq | block on/off（联动 EXCP） |
| c_csr_spad_excl | csr_seq | non_excl（默认），excl_cfg 仅验证配置通路 |

> CSR 配置 × 行为的联合交叉见 4.12.3；配置侧值 × 写时序见 8.2。

### 4.12 交叉覆盖汇总

V.2.0.0 起，交叉覆盖统一在本节定义一次，拆为三张表：组内交叉、同 agent 跨组交叉、跨 agent 联合交叉。

#### 4.12.1 组内交叉

| 交叉 ID | 交叉对象 | 所属 CG | Bin 数 | 目标 |
|---|---|---|---|---|
| X_CMDSCHED_ITYPE_001 | cp_inst_func × cp_inst_comp | ITYPE | 3 | 100% |
| X_CMDSCHED_ITYPE_002 | cp_inst_flag × cp_inst_func | ITYPE | 6 | 100% |
| X_CMDSCHED_INSTB_001 | cp_instb_level × cp_instb_chain | INSTB | 6 | 100% |
| X_CMDSCHED_INSTB_002 | cp_instb_dp × cp_instb_level.full | INSTB | 4 | 100% |
| X_CMDSCHED_DEP_001 | cp_hazard_type × cp_hazard_gran | DEP | 9 | 100% |
| X_CMDSCHED_DEP_002 | cp_hazard_type × cp_hazard_scope | DEP | 12 | 100% |
| X_CMDSCHED_UNIT_001 | cp_mst_id × cp_mst_slot | UNIT | 5 | 100% |
| X_CMDSCHED_UNIT_002 | cp_mst_id × cp_paral_scope | UNIT | 20 | 100% |
| X_CMDSCHED_ISSUE_002 | cp_mst_avail × cp_issue_path | ISSUE | 6 | 100% |
| X_CMDSCHED_RSP_001 | cp_rsp_type × cp_rsp_prio | RSP | 4 | 100% |
| X_CMDSCHED_RSP_002 | cp_rsp_type × cp_rsp_tag | RSP | 4 | 100% |
| X_CMDSCHED_EXCP_001 | cp_int_type × cp_block_en | EXCP | 4 | 100% |

#### 4.12.2 同 agent 跨组交叉

| 交叉 ID | 交叉对象 | 涉及 CG | Bin 数 | 目标 |
|---|---|---|---|---|
| X_CMDSCHED_ISSUE_001 | cp_hazard_type × cp_issue_path | DEP × ISSUE | 6 | 100% |
| X_CMDSCHED_MEM_001 | cp_spad_tile_occ × cp_mst_id | MEM × UNIT | 20 | 100% |
| X_CMDSCHED_MEM_002 | cp_hazard_gran × cp_multi_mst_spad | MEM × DEP | 9 | 100% |
| X_CMDSCHED_PERF_001 | cp_csr_perf_en × cp_perf_paral | CSR × PERF | 6 | 100% |
| X_CMDSCHED_PERF_002 | cp_csr_perf_en × cp_perf_cong | CSR × PERF | 10 | 100% |
| X_CMDSCHED_PERF_003 | cp_csr_perf_en × cp_debug_reg | CSR × PERF | 6 | 100% |

> 说明：CSR 与 PERF 若在同一 cmd_int_perf monitor 采样，可归入同 agent 跨组；若分属不同 agent，则归入 4.12.3 联合交叉。

#### 4.12.3 跨 agent 联合交叉（CSR × 行为）

**实现原则**：配置侧 agent 只覆盖 CSR 值与写时序；行为侧 monitor 在采样行为事件的同一拍，从白盒探针或 RAL mirror 读取**生效 CSR 值**，作为本侧 coverpoint 采样变量，再与行为 coverpoint 做组内 `cross`。禁止跨 covergroup 实例直接 `cross`。联合 covergroup 代码见 8.3。

**交叉清单与采样口径**：

| 交叉 ID | 交叉对象 | 采样事件 | 配置值来源 | Bin 数 | 目标 |
|---|---|---|---|---|---|
| X_CFG_EXCP_INT | cp_cfg_excep × cp_int_type × cp_cfg_stable | 指令译码/中断置位拍 | RTL `creg_cmd_excep_en` | 2×3×2 | 100% |
| X_CFG_BLOCK_INT | cp_cfg_block × cp_int_type × cp_cfg_stable | 中断置位拍 | `creg_cmd_block_en` | 2×3×2 | 100% |
| X_CFG_TILE_RLS | cp_cfg_tile_rls × cp_mem_release_src × cp_spad_tile_occ | 占用/释放变化拍 | `creg_cmd_tile_rls_en` | 3×3×4 | 100%（按通道分组） |
| X_CFG_PERF_PARAL | cp_cfg_perf × cp_perf_paral | perf 窗口采样拍 | `creg_cmd_perf_en` | 2×3 | 100% |
| X_CFG_PERF_CONG | cp_cfg_perf × cp_perf_cong | perf 窗口采样拍 | 同上 | 2×5 | 100% |
| X_CFG_PERF_DEBUG | cp_cfg_perf × cp_debug_reg | debug 读回拍 | 同上 | 2×3 | 100% |
| X_CFG_ICG_ISSUE | cp_cfg_icg × cp_idle_icg × cp_issue_path | ICG 状态变化/发射拍 | `creg_cmd_icg_en` | 2×3×4 | 100% |
| X_CFG_ICG_FUNC | cp_cfg_icg × cp_inst_func × cp_prim_type | 指令译码拍 | 同上 | 2×3×12 | 100% |
| X_CFG_BLOCK_RSP | cp_cfg_block × cp_rsp_type × cp_cmd_handshake | rsp 握手拍 | `creg_cmd_block_en` | 2×4×4 | 100% |
| X_CFG_BLOCK_BP | cp_cfg_block × cp_backpressure × cp_issue_path | 反压/发射拍 | 同上 | 2×4×4 | 100% |
| X_CFG_SPAD_EXCL | cp_cfg_spad_excl × cp_multi_mst_spad | 多组件同 SPAD 拍 | `creg_cmd_spad_excl_en` | 2×5 | non_excl 100%；excl_cfg 仅配置通路 |

**采样口径约束**：

1. **配置值来源**：优先白盒探针 RTL 生效寄存器；无白盒时用 RAL mirror + 生效延迟预测。
2. **采样点**：行为事件有效拍（`cmd_valid && cmd_ready`、`start`、`rsp_valid`、中断置位、占用/释放变化）。
3. **切换窗口**：CSR 写与行为事件同拍/相邻拍时，`cfg_stable=0`，单独 bin；不混入稳定期。
4. **配置版本**：行为 item 带 `cfg_epoch_snapshot`，scoreboard 可按 epoch 过滤。
5. **不可达组合**：用 `ignore_bins` 并记录理由；禁止用 `illegal_bins` 掩盖架构不可达。
6. **illegal_bins 与 excep_en=off 语义拆分**：`cp_prim_type.il_*` 表示 RTL 不应接受的编码；`excep_en=off` 屏蔽行为用 `cp_cfg_excep.off × cp_int_type.no_int` 单独 bin，二者不冲突。

### 4.13 专题带来的新增覆盖点

| 新增覆盖点 | 所属 CG | 切面 | 定义 |
|---|---|---|---|
| cp_mid_reset_istb | INSTB | MR | bins：复位时 ISTB 空/非空；复位后 head/tail 归零、链表可重建 |
| cp_mid_reset_sb | DEP/ISSUE | MR | bins：复位时有在飞指令/无；复位后占用表清空、可重新分配 |
| cp_mid_reset_mem | MEM | MR | bins：复位时 tile/page/dram 有占用；复位后全部释放，无泄漏 |
| cp_mid_reset_rsp | RSP | MR | bins：复位时 rsp_fifo 非空；复位后 tag 丢弃、后续返回正常 |
| cp_mid_reset_excp | EXCP | MR | bins：复位清中断/现场；复位后 block 模式恢复 |
| cp_data_format | RSP/ITYPE | V | bins：FP32/FP16/BF16/F143/F152/FP4/Int/MXFP8/MXFP4/MXINT8/MXINT4（按 primitive 关联） |
| cp_rsp_data_boundary | RSP | V | bins：0/最大/最小/NaN/Inf（若适用） |
| cp_wstrb | MEM/RSP | V | bins：字节使能组合等价类（全 1/单字节/部分） |
| cp_tensor_shape | ITYPE/MEM | S | bins：dim0/1/2 等价类；stride 等价类；tile 最小/最大 |
| cp_ost2_full | ISSUE | B | bins：ost=2 满时第三条被阻塞；释放后恢复 |
| cp_drf_dp_full | ISSUE | B | bins：乱序窗口 dRF_DP 满时发射阻塞 |
| cp_timeout_err | EXCP | E | bins：超时异常触发/上报/恢复（若 CMD_SCH 负责；否则 N/A 并注明归属模块） |
| cp_protocol_err | EXCP/RSP | E | bins：协议错误（若 CMD_SCH 负责；否则 N/A） |
| cp_int_storm | EXCP | P | bins：连续中断下现场不被覆盖、清除后恢复 |
| cp_perf_longrun | PERF | P | bins：长跑窗口内计数器不溢出/不归零错误；与 scoreboard 统计一致 |

> `cp_timeout_err / cp_protocol_err` 若规格明确由其他模块负责，需在 3.3.2 对应格写 `N/A + 归属模块`，不得留空，也不得强行造覆盖点。

### 4.14 专题带来的新增 SVA / scoreboard 检查

| 检查 ID | 类型 | 检查内容 | 关联功能树 |
|---|---|---|---|
| A_CMD_HS | SVA | cmd_valid 拉高后保持到 cmd_ready；不得中途撤销 | FT-01, FT-04 |
| A_RSP_HS | SVA | rsp_valid 保持到 rsp_ready；tag 与数据同拍稳定 | FT-07 |
| A_START_CFG | SVA | 每个 MST start 最多两拍且 inst_id 不同；cfg 仅 start 当拍有效 | FT-05 |
| A_RLS_DONE | SVA | rls_vld 不晚于 done_vld；rls_inst_id 匹配 | FT-05, FT-06 |
| A_ISSUE_COND | SVA | can_issue == dependency_ready && mst_avail | FT-04 |
| A_BLOCK_STOP | SVA | block_en=1 且中断后停止收发；清除后恢复 | FT-08 |
| A_ICG_GATE | SVA | IDLE 下子模块时钟关；指令/中断/性能使能到来按条件开 | FT-10 |
| A_NO_TILE_LEAK | scoreboard | 长跑后 tile/page/dram 占用表归零 | FT-06, FT-09 |
| A_PERF_MATCH | scoreboard | RTL perf/debug 寄存器与 monitor 统计一致 | FT-09 |
| A_TAG_MATCH | scoreboard | 多 xd=1 返回数据按 tag 与预期比对 | FT-07 |

### 4.15 覆盖率组与约束映射总表

| 覆盖率组 | 覆盖点 | 约束 | 目标 Bin |
|---|---|---|---|
| CG_CMDSCHED_ITYPE | cp_inst_flag, cp_inst_func, cp_inst_comp, cp_prim_type（+cp_data_format） | c_inst_flag_dist, c_inst_func_dist, c_inst_comp_dist, c_prim_dist, c_illegal_inst | nice/vnice、三类功能、七类组件、全部 primitive |
| CG_CMDSCHED_INSTB | cp_instb_level, cp_instb_chain, cp_instb_cfg_drv, cp_instb_dp（+cp_mid_reset_istb） | c_instb_dp, c_instb_fill, c_cfg_drv_pair, c_chain_seq | empty~full、链表操作、拼接存储、dp1/2/4/8 |
| CG_CMDSCHED_DEP | cp_hazard_type, cp_hazard_gran, cp_hazard_scope, cp_struct_hazard（+cp_mid_reset_sb） | c_dep_dist, c_raw/c_waw/c_war, c_hazard_scope_2~5, c_same_mst_pair, c_lmem_llsu_conflict, c_sync_barrier, c_noc_fence_barrier, c_niu_dst, c_niu_store | no_dep/raw/waw/war、tile/page/dram、1~5 组件、5 类结构冲突 |
| CG_CMDSCHED_UNIT | cp_mst_id, cp_mst_slot, cp_paral_scope, cp_ls_parallel, cp_tmu_arb, cp_third_inst_blocked | c_mst_dist, c_mst_dual, c_multi_parallel_2~5, c_ls_pair_seq, c_tmu_contend, c_third_inst_blocked | 5 MST、双指令槽、2~5 并行、load-store 并行、TMU 竞争、第三条阻塞 |
| CG_CMDSCHED_ISSUE | cp_issue_path, cp_issue_priority, cp_start_done_seq, cp_mst_avail（+cp_ost2_full, cp_drf_dp_full） | c_issue_direct, c_issue_stall, c_issue_backpressure, c_start_done_seq, c_rls_timing, c_ost2_full, c_drf_dp_full | 直发/存储/ISTB 发射/反压、优先级、start-done-rls、资源判定、ost=2、dRF_DP 满 |
| CG_CMDSCHED_MEM | cp_spad_tile_occ, cp_cimc_page_occ, cp_dram_occ, cp_multi_mst_spad, cp_mem_release_src, cp_spad_tile_map（+cp_mid_reset_mem, cp_tensor_shape, cp_wstrb） | c_spad_tile_addr, c_cimc_page_addr, c_dram_addr, c_multi_mst_spad, c_release_early, c_tile_rls_en, c_tile_map_spread, c_tensor_shape_eqv | tile/page/dram 占用释放、多组件共享、释放来源、32 个 tile 地址、形状边界、wstrb |
| CG_CMDSCHED_RSP | cp_rsp_type, cp_rsp_data, cp_rsp_tag, cp_rsp_prio, cp_cmd_handshake, cp_backpressure, cp_wr_lmem_rmw（+cp_data_format, cp_rsp_data_boundary, cp_wstrb, cp_mid_reset_rsp） | c_xd1_seq, c_rsp_priority_seq, c_tag_out_of_order, c_backpressure_seq, c_wr_lmem_rmw, c_data_format_dist | 四类返回、乱序 tag、fifo 优先级、握手、四类反压、wr_lmem 读改写、数据格式/边界 |
| CG_CMDSCHED_EXCP | cp_int_type, cp_block_en, cp_int_clear, cp_excep_en, cp_int_info_save（+cp_mid_reset_excp, cp_timeout_err, cp_protocol_err, cp_int_storm） | c_illegal_inst, c_non_spad_addr, c_cimc_lmem_addr, c_lmem_llsu_conflict, c_block_en_cfg, c_int_clear_seq, c_int_info_save | cmd_int[0]/[1]、block 行为、清除方式、屏蔽、中断现场保存、中间复位、超时/协议错误（若适用）、中断风暴 |
| CG_CMDSCHED_PERF | cp_perf_paral, cp_perf_cong, cp_debug_reg, cp_perf_en（+cp_perf_longrun） | c_perf_window, c_perf_cong_seq, c_perf_en, c_longrun_mix | 并行度、拥塞、debug、使能、长稳计数正确 |
| CG_CMDSCHED_CSR | cp_csr_icg, cp_csr_excep_en, cp_csr_perf_en, cp_csr_block_en, cp_csr_tile_rls, cp_csr_spad_excl, cp_idle_icg | c_csr_icg, c_csr_tile_rls, c_csr_block, c_csr_spad_excl, c_csr_mode_pairwise, c_csr_write_order | icg/excep/perf/block/tile_rls/spad_excl、IDLE/ICG、配置模式 pairwise、写时序 |

### 4.16 覆盖率组与批次映射

| 批次 | 测试名 | 激活的覆盖率组 | 覆盖专题 | 目标覆盖率 |
|---|---|---|---|---|
| 1 | cmdsched_basic_test | CG_CMDSCHED_ISSUE | FT-04, SC-01, I/F/B | 20% |
| 2 | cmdsched_instype_test | CG_CMDSCHED_ITYPE | FT-01, V | 32% |
| 3 | cmdsched_instb_test | CG_CMDSCHED_INSTB | FT-02, B/F/MR | 42% |
| 4 | cmdsched_dep_test | CG_CMDSCHED_DEP | FT-03, S/E | 55% |
| 5 | cmdsched_hazard_scope_test | CG_CMDSCHED_DEP, CG_CMDSCHED_ISSUE | FT-03, B | 65% |
| 6 | cmdsched_parallel_test | CG_CMDSCHED_UNIT | FT-04/05, SC-02, P | 74% |
| 7 | cmdsched_mem_test | CG_CMDSCHED_MEM, CG_CMDSCHED_UNIT | FT-06, S/C | 82% |
| 8 | cmdsched_rsp_test | CG_CMDSCHED_RSP | FT-07, V/F, SC-02 | 89% |
| 9 | cmdsched_excp_perf_test | CG_CMDSCHED_EXCP, CG_CMDSCHED_PERF, CG_CMDSCHED_CSR | FT-08/09/10, SC-03/04, C/E/MR/P | 96% |
| 10 | cmdsched_random_mix_test | 全部 | 全部, SC-05, 长稳 | 防过拟合 |

---

## 5. 约束设计

本章回答“怎么产生激励”，是激励与约束层。约束的设计必须与覆盖点一一对应：每个覆盖点的每个 bin，都要有对应的约束能生成命中它的激励。

### 5.1 约束层次结构

约束按三层组织，从宽到严逐层收紧：

```
第 1 层：指令生成约束（单条指令的编码、类型、数据与访存地址）
    ↓
第 2 层：序列依赖约束（指令之间的依赖关系、组件组合）
    ↓
第 3 层：场景约束（针对特定覆盖率缺口的定向约束）
```

### 5.2 第 1 层：指令生成约束

对应覆盖点：cp_inst_flag、cp_inst_func、cp_inst_comp、cp_prim_type、cp_mst_id、cp_spad_tile_occ、cp_cimc_page_occ、cp_dram_occ、cp_data_format

```systemverilog
class npu_instr extends uvm_sequence_item;
  rand bit        inst_flag;          // 0=NICE, 1=VNICE
  rand inst_func_e inst_func;         // 普通/状态返回/数值返回
  rand inst_comp_e inst_comp;         // cfg/lmem/noc/glsu/llsu/mpu/vpu
  rand prim_type_e prim_type;         // primitive 类型
  rand mst_id_e    mst_id;            // 目标组件
  rand bit         xd;                // 是否需要返回值
  rand bit [7:0]   tag;               // xd=1 指令 tag
  rand bit [21:0]  spad_addr;         // SPAD 地址（含 tile 位）
  rand bit [3:0]   cimc_page;         // CIMC page 选择
  rand bit [39:0]  dram_addr;         // DRAM 地址（仅 GLSU）
  rand bit [15:0]  size, stride;      // tensor 尺寸/步长
  rand data_fmt_e  data_fmt;          // FP32/FP16/.../Int/MX 格式

  // 对应 cp_inst_flag
  constraint c_inst_flag_dist { inst_flag dist {0 := 50, 1 := 50}; }
  // 对应 cp_inst_func
  constraint c_inst_func_dist { inst_func dist {
    INST_NORMAL := 70, INST_STATE := 15, INST_VALUE := 15 }; }
  // 对应 cp_inst_comp / cp_mst_id：组件分类与目标 MST 一致
  constraint c_inst_comp_dist { inst_comp dist {
    COMP_CFG := 15, COMP_LMEM := 15, COMP_NOC := 15,
    COMP_GLSU := 15, COMP_LLSU := 10, COMP_MPU := 15, COMP_VPU := 15 }; }
  constraint c_mst_dist { mst_id inside {MST_GLSU, MST_LLSU, MST_MPU, MST_VPU, MST_NIU}; }
  // 对应 cp_prim_type：各 primitive 加权分布
  constraint c_prim_dist { prim_type dist {
    PRIM_CFG := 10, PRIM_WR_LMEM := 8, PRIM_RD_LMEM := 8, PRIM_SW_CIMC := 4,
    PRIM_TLD := 10, PRIM_TST := 10, PRIM_TENSOR_MANIP := 15,
    PRIM_TENSOR_PROC := 15, PRIM_VEC_PROC := 10, PRIM_V_S := 4,
    PRIM_SYNC := 3, PRIM_NOC_FENCE := 3 }; }
  // 对应 cp_spad_tile_occ：SPAD 地址按 8 块 × 4 tile 编码
  constraint c_spad_tile_addr { spad_addr[4:0] inside {[0:31]}; }
  // 对应 cp_cimc_page_occ：CIMC 仅 2x2 形状（Feat-6），page 0~3
  constraint c_cimc_page_addr { cimc_page inside {[0:3]}; }
  constraint c_addr_align { spad_addr[0] == 0; }  // 32bit 对齐
  // 对应 cp_data_format
  constraint c_data_format_dist { data_fmt dist {
    FMT_FP32 := 15, FMT_FP16 := 15, FMT_BF16 := 15, FMT_F143 := 10, FMT_F152 := 10,
    FMT_FP4 := 5, FMT_INT := 10, FMT_MXFP8 := 5, FMT_MXFP4 := 5,
    FMT_MXINT8 := 5, FMT_MXINT4 := 5 }; }
endclass
```

### 5.3 第 2 层：序列依赖约束

对应覆盖点：cp_hazard_type、cp_hazard_gran、cp_hazard_scope、cp_struct_hazard、X_dep_gran、X_dep_scope、cp_mst_slot、cp_paral_scope

```systemverilog
class npu_stream extends uvm_sequence #(npu_instr);
  rand int unsigned num_instr;
  rand npu_instr   instrs[];

  constraint c_size { num_instr inside {[5:50]}; instrs.size() == num_instr; }

  // 对应 cp_hazard_type / X_dep_gran：RAW/WAW/WAR 均需产生
  constraint c_dep_dist { foreach (instrs[i]) {
    if (i > 0) instrs[i].hazard_type dist { NONE := 50, RAW := 20, WAW := 15, WAR := 15 }; } }

  // 对应 X_dep_gran.raw：RAW 依赖，写后读地址（tile）重叠
  constraint c_raw { foreach (instrs[i]) {
    if (i > 0 && instrs[i].hazard_type == RAW) {
      instrs[i].spad_addr[4:0] == instrs[i-1].spad_addr[4:0]; } } }

  // 对应 X_dep_gran.waw：WAW 依赖，写后写地址重叠
  constraint c_waw { foreach (instrs[i]) {
    if (i > 1 && instrs[i].hazard_type == WAW) {
      instrs[i].spad_addr[4:0] == instrs[i-2].spad_addr[4:0]; } } }

  // 对应 X_dep_gran.war：WAR 依赖，读后写地址重叠
  constraint c_war { foreach (instrs[i]) {
    if (i > 0 && instrs[i].hazard_type == WAR) {
      instrs[i].spad_addr[4:0] == instrs[i-1].spad_addr[4:0]; } } }

  // 对应 cp_hazard_scope / X_dep_scope：2~5 组件 hazard
  constraint c_hazard_scope_2~5 { foreach (instrs[i]) {
    if (i > 0 && instrs[i].hazard_type != NONE) {
      instrs[i].hazard_scope inside {[2:5]}; } } }

  // 对应 cp_mst_slot / Feat-10：同组件连续两条指令（第二条无依赖则不被阻塞）
  constraint c_same_mst_pair { foreach (instrs[i]) {
    if (i > 0 && instrs[i].mst_id == instrs[i-1].mst_id) {
      instrs[i].hazard_type == NONE; } } }
endclass
```

### 5.4 第 3 层：场景约束

**场景 1：ISTB 满反压**

目标覆盖点：cp_instb_level.full、X_instb_level_chain.full_tail_wr、X_instb_dp_full、cp_issue_path.backpressure

```systemverilog
class instb_fill_seq extends npu_stream;
  constraint c_instb_fill {
    num_instr == 20;
    foreach (instrs[i]) {
      if (i > 0) { instrs[i].hazard_type == RAW;
                   instrs[i].spad_addr[4:0] == instrs[i-1].spad_addr[4:0]; }
    }
  }
  constraint c_cfg_drv_pair { instrs[0].prim_type == PRIM_CFG;
                              instrs[1].prim_type == PRIM_WR_LMEM; }
endclass
```

**场景 2：连续 RAW 依赖链（2~5 组件）**

目标覆盖点：X_dep_scope 的 raw×two/four/five_mst、X_issue_dep_path.raw_stored

```systemverilog
class raw_chain_seq extends npu_stream;
  constraint c_raw_chain {
    num_instr == 25;
    foreach (instrs[i]) {
      if (i > 0) {
        instrs[i].hazard_type == RAW;
        instrs[i].spad_addr[4:0] == instrs[i-1].spad_addr[4:0];
        instrs[i].mst_id == mst_id_e'(i % 5);
      }
    }
  }
endclass
```

**场景 3：多组件并行执行**

目标覆盖点：cp_paral_scope 的 two/three/four/five_mst、X_unit_paral、cp_multi_mst_spad

```systemverilog
class parallel_seq extends npu_stream;
  constraint c_multi_parallel_2~5 {
    num_instr == 20;
    foreach (instrs[i]) {
      instrs[i].hazard_type == NONE;
      instrs[i].mst_id == mst_id_e'(i % 5);
      instrs[i].spad_addr[4:0] == i % 32;
    }
  }
endclass
```

**场景 4：sync / noc_fence 屏障**

目标覆盖点：cp_struct_hazard.sync_all / noc_fence、cp_rsp_type.sync_rsp / noc_fence_rsp、cp_rsp_data.state_1

```systemverilog
class barrier_seq extends npu_stream;
  constraint c_sync_barrier {
    instrs[5].prim_type == PRIM_SYNC;
    foreach (instrs[i]) { if (i > 5) instrs[i].hazard_type == RAW; }
  }
  constraint c_noc_fence_barrier {
    instrs[8].prim_type == PRIM_NOC_FENCE;
    foreach (instrs[i]) { if (i > 8) instrs[i].inst_comp == COMP_NOC; }
  }
endclass
```

**场景 5：多 xd=1 指令乱序返回**

目标覆盖点：cp_rsp_tag.multi_xd / tag_ooot、X_rsp_tag.ooo、cp_rsp_prio

```systemverilog
class xd1_seq extends npu_stream;
  constraint c_xd1_seq {
    foreach (instrs[i]) {
      if (i % 4 == 0) { instrs[i].xd == 1;
                        instrs[i].prim_type inside {PRIM_RD_LMEM, PRIM_V_S,
                                                    PRIM_SYNC, PRIM_NOC_FENCE};
                        instrs[i].tag == i; }
      else instrs[i].xd == 0;
    }
  }
endclass
```

**场景 6：GLSU/NIU load-store 并行与后启动先 done**

目标覆盖点：cp_ls_parallel.glsu_ls_par / niu_ls_par、cp_start_done_seq.start1_done0、cp_rls_timing

```systemverilog
class ls_parallel_seq extends npu_stream;
  constraint c_ls_pair_seq {
    num_instr == 12;
    instrs[0].mst_id == MST_GLSU; instrs[0].prim_type == PRIM_TLD;
    instrs[1].mst_id == MST_GLSU; instrs[1].prim_type == PRIM_TST;
    instrs[1].spad_addr[4:0] != instrs[0].spad_addr[4:0];
    instrs[2].mst_id == MST_NIU;  instrs[2].prim_type == PRIM_TLD;
    instrs[3].mst_id == MST_NIU;  instrs[3].prim_type == PRIM_TST;
  }
endclass
```

**场景 7：TMU 竞争**

目标覆盖点：cp_tmu_arb.glsu_pri_contend / llsu_wait

```systemverilog
class tmu_seq extends npu_stream;
  constraint c_tmu_contend {
    num_instr == 8;
    instrs[0].mst_id == MST_GLSU; instrs[0].use_tmu == 1;
    instrs[1].mst_id == MST_LLSU; instrs[1].use_tmu == 1;
    instrs[1].spad_addr[4:0] != instrs[0].spad_addr[4:0];
  }
endclass
```

**场景 8：异常指令与非法地址**

目标覆盖点：cp_int_type.cmd_int0 / cmd_int1、cp_prim_type.il_rd_csr / il_reserved、cp_block_en

```systemverilog
class illegal_seq extends npu_stream;
  constraint c_illegal_inst {
    num_instr == 8;
    instrs[3].prim_type == PRIM_RESERVED;
    instrs[4].prim_type == PRIM_RD_CSR;
    instrs[5].prim_type == PRIM_WR_LMEM; instrs[5].addr_space == ADDR_CIMC;
    instrs[6].prim_type == PRIM_RD_LMEM; instrs[6].addr_space == ADDR_CIMC;
  }
endclass
```

**场景 9：反压流控**

目标覆盖点：cp_backpressure 的 rd_bp/wr_bp/scalar_bp/istb_bp、cp_cmd_handshake

```systemverilog
class bp_seq extends npu_stream;
  constraint c_backpressure_seq {
    num_instr == 16;
    foreach (instrs[i]) { if (i % 5 == 0) instrs[i].prim_type == PRIM_WR_LMEM;
                          else if (i % 5 == 1) instrs[i].prim_type == PRIM_RD_LMEM;
                          else if (i % 5 == 2) instrs[i].prim_type == PRIM_V_S; }
  }
endclass
```

**场景 10：性能统计窗口**

目标覆盖点：cp_perf_paral、cp_perf_cong、cp_debug_reg

```systemverilog
class perf_seq extends npu_stream;
  constraint c_perf_window {
    num_instr == 40;
    foreach (instrs[i]) { instrs[i].mst_id == mst_id_e'(i % 5);
                          instrs[i].hazard_type == NONE; }
  }
endclass
```

**场景 11：第三条同组件指令阻塞**

目标覆盖点：cp_third_inst_blocked（Feat-10）

```systemverilog
class third_inst_seq extends npu_stream;
  constraint c_third_inst_blocked {
    num_instr == 10;
    foreach (instrs[i]) { if (i < 4) instrs[i].mst_id == MST_GLSU; }
    instrs[0].hazard_type == NONE;
    instrs[1].hazard_type == NONE;
    instrs[1].spad_addr[4:0] != instrs[0].spad_addr[4:0];
    instrs[2].spad_addr[4:0] == instrs[1].spad_addr[4:0];
  }
endclass
```

**场景 12：SPAD tile 地址空间遍历**

目标覆盖点：cp_spad_tile_map（Feat-22）

```systemverilog
class tile_map_seq extends npu_stream;
  constraint c_tile_map_spread {
    num_instr == 40;
    foreach (instrs[i]) {
      instrs[i].spad_id == i % 8;
      instrs[i].tile_id == (i / 8) % 4;
    }
  }
endclass
```

**场景 13：wr_lmem 读改写（RMW）**

目标覆盖点：cp_wr_lmem_rmw（Feat-4）

```systemverilog
class rsp_rmw_seq extends npu_stream;
  constraint c_wr_lmem_rmw {
    num_instr == 12;
    foreach (instrs[i]) { if (i % 3 == 0) instrs[i].prim_type == PRIM_WR_LMEM; }
  }
endclass
```

**场景 14：中断现场信息保存**

目标覆盖点：cp_int_info_save（Feat-28）

```systemverilog
class int_info_seq extends npu_stream;
  constraint c_int_info_save {
    num_instr == 10;
    instrs[2].prim_type == PRIM_RESERVED;
  }
endclass
```

**场景 15~20：专题驱动场景**

- 场景 15：中间复位（mid_reset_seq）→ cp_mid_reset_*
- 场景 16：数据格式遍历（data_fmt_seq）→ cp_data_format / cp_rsp_data_boundary
- 场景 17：ost=2 / dRF_DP 边界（parallel_seq 子类）→ cp_ost2_full / cp_drf_dp_full
- 场景 18：CSR 模式 pairwise（csr_mode_seq）→ X_CFG_* 联合交叉
- 场景 19：ICG IDLE 唤醒（csr_icg_seq）→ X_CFG_ICG_ISSUE / cp_idle_icg
- 场景 20：长稳混合（longrun_seq）→ cp_perf_longrun / A_NO_TILE_LEAK / A_PERF_MATCH

### 5.5 约束与覆盖点映射表

| 约束 | 所属类 | 目标覆盖点 | 目标 Bin |
|---|---|---|---|
| c_inst_flag_dist | npu_instr | cp_inst_flag | nice, vnice |
| c_inst_func_dist | npu_instr | cp_inst_func | normal, state_rsp, value_rsp |
| c_inst_comp_dist | npu_instr | cp_inst_comp | cfg, lmem, noc, glsu, llsu, mpu, vpu |
| c_prim_dist | npu_instr | cp_prim_type | 全部 primitive |
| c_mst_dist | npu_instr | cp_mst_id | glsu, llsu, mpu, vpu, niu |
| c_spad_tile_addr / c_cimc_page_addr / c_dram_addr | npu_instr | cp_spad_tile_occ / cp_cimc_page_occ / cp_dram_occ | tile/page/dram 占用 |
| c_data_format_dist | npu_instr | cp_data_format | 全部数据格式 |
| c_dep_dist | npu_stream | cp_hazard_type | no_dep, raw, waw, war |
| c_raw / c_waw / c_war | npu_stream | X_dep_gran | raw/waw/war × tile/page/dram |
| c_hazard_scope_2~5 | npu_stream | cp_hazard_scope, X_dep_scope | two_mst ~ five_mst |
| c_same_mst_pair | npu_stream | cp_mst_slot, Feat-10 | both, same_mst |
| c_instb_dp | 参数遍历 | cp_instb_dp | dp1, dp2, dp4, dp8 |
| c_instb_fill / c_cfg_drv_pair | instb_fill_seq | cp_instb_level, cp_instb_cfg_drv | full, cfg_then_drv_stored |
| c_chain_seq | instb_chain_seq | cp_instb_chain | head/tail/mid/refill |
| c_lmem_llsu_conflict | conflict_seq | cp_struct_hazard | lmem_llsu |
| c_sync_barrier / c_noc_fence_barrier | barrier_seq | cp_struct_hazard, cp_rsp_type | sync_all, noc_fence |
| c_niu_dst / c_niu_store | niu_seq | cp_struct_hazard | niu_dst_single, niu_store_dual |
| c_multi_parallel_2~5 | parallel_seq | cp_paral_scope, X_unit_paral | two_mst ~ five_mst |
| c_ls_pair_seq | ls_parallel_seq | cp_ls_parallel | glsu_ls_par, niu_ls_par |
| c_tmu_contend | tmu_seq | cp_tmu_arb | glsu_pri_contend, llsu_wait |
| c_multi_mst_spad | parallel_seq | cp_multi_mst_spad | mst2~5_same_spad, rar_multi_read |
| c_release_early / c_tile_rls_en | release_seq / csr_seq | cp_mem_release_src | rls_release, tile_rls_en_off |
| c_xd1_seq / c_tag_out_of_order | xd1_seq | cp_rsp_tag, X_rsp_tag | multi_xd, tag_ooot, ooo |
| c_rsp_priority_seq | xd1_seq | cp_rsp_prio, X_rsp_prio | scalar > lmem > fence > sync |
| c_backpressure_seq | bp_seq | cp_backpressure | rd_bp, wr_bp, scalar_bp, istb_bp |
| c_illegal_inst / c_non_spad_addr / c_cimc_lmem_addr | illegal_seq | cp_int_type, cp_prim_type | cmd_int0, cmd_int1 |
| c_block_en_cfg / c_int_clear_seq | csr_seq / int_clear_seq | cp_block_en, cp_int_clear | block_stop/continue, 清除方式 |
| c_perf_window / c_perf_cong_seq / c_perf_en | perf_seq / csr_seq | cp_perf_paral, cp_perf_cong, cp_perf_en | 并行度、拥塞、使能 |
| c_csr_icg / c_csr_tile_rls / c_csr_block / c_csr_spad_excl | csr_seq | cp_csr_icg, cp_csr_tile_rls, cp_csr_block_en, cp_csr_spad_excl, cp_idle_icg | icg/tile_rls/block/spad_excl/IDLE |
| c_third_inst_blocked | third_inst_seq | cp_third_inst_blocked | third_blocked, third_issued |
| c_tile_map_spread | tile_map_seq | cp_spad_tile_map | tile_00 ~ tile_31 |
| c_wr_lmem_rmw | rsp_rmw_seq | cp_wr_lmem_rmw | rmw_performed, rmw_blocked |
| c_int_info_save | int_info_seq | cp_int_info_save | first_int_saved, later_not_saved, info_readable |
| c_mid_reset | mid_reset_seq | cp_mid_reset_* | ISTB/sb/mem/rsp/excp 复位恢复 |
| c_ost2_full / c_drf_dp_full | parallel_seq | cp_ost2_full / cp_drf_dp_full | 边界满 |
| c_tensor_shape_eqv | npu_stream | cp_tensor_shape | dim/stride/tile 等价类 |
| c_longrun_mix | longrun_seq | cp_perf_longrun | 长稳计数正确 |
| c_csr_mode_pairwise / c_csr_write_order | csr_write_seq / cmdsched_cfg_vseq | X_CFG_* / cp_csr_wr_order | 配置模式组合、写时序 |

### 5.6 专题与跨 agent 新增约束

| 约束 | 所属类 | 目标交叉/覆盖点 |
|---|---|---|
| c_csr_mode_pairwise | csr_write_seq / cmdsched_cfg_vseq | 配置模式 pairwise 组合 |
| c_csr_write_order | csr_write_seq | cp_csr_wr_order |
| c_csr_icg_idle_wakeup | csr_icg_seq | X_CFG_ICG_ISSUE, X_CFG_ICG_FUNC |
| c_csr_tile_rls_part | csr_tile_rls_seq | X_CFG_TILE_RLS（part_on 按通道分组） |
| c_csr_excep_off | csr_excep_seq | X_CFG_EXCP_INT 的 excep=off × no_int |
| c_csr_block_recover | csr_block_seq | X_CFG_BLOCK_INT, X_CFG_BLOCK_RSP |
| c_csr_perf_win | csr_perf_seq | X_CFG_PERF_PARAL/CONG/DEBUG |
| c_csr_spad_excl_cfg | csr_spad_seq | X_CFG_SPAD_EXCL（excl_cfg 仅配置通路） |
| c_ost2_full | parallel_seq | cp_ost2_full |
| c_drf_dp_full | parallel_seq | cp_drf_dp_full |
| c_data_format_dist | npu_instr | cp_data_format |
| c_tensor_shape_eqv | npu_stream | cp_tensor_shape |
| c_mid_reset | mid_reset_seq | cp_mid_reset_* |
| c_longrun_mix | longrun_seq | cp_perf_longrun, A_NO_TILE_LEAK |

### 5.7 配置与指令的 virtual sequence 组织

配置与指令由 virtual sequence 协调，不塞进同一事务：

```systemverilog
class cmdsched_cfg_vseq extends uvm_sequence;
  csr_write_seq csr_seq;
  npu_stream    cmd_seq;

  task body();
    // 场景 A：默认配置跑指令流
    csr_seq.write_default();
    cmd_seq.start(p_sequencer.cmd_sqr);
    // 场景 B：指令流前配置
    csr_seq.write(cfg_a);
    cmd_seq.start(p_sequencer.cmd_sqr);
    // 场景 C：运行中切换（cfg_stable=0 单独覆盖）
    fork
      cmd_seq.start(p_sequencer.cmd_sqr);
      begin #delay; csr_seq.write(cfg_b); end
    join
    // 场景 D：中断后 block/清中断恢复
    // 场景 E：ICG IDLE 唤醒
  endtask
endclass
```

---

## 6. 批次设计与覆盖率演进

### 6.1 批次规划

| 批次 | 测试名 | 约束 | 目标覆盖点 | 覆盖专题 | 种子数 | 预期覆盖率 |
|---|---|---|---|---|---|---|
| 1 | cmdsched_basic_test | 基础约束 | cp_issue_path.direct, cp_mst_id | FT-04, SC-01 | 5 | 20% |
| 2 | cmdsched_instype_test | c_inst_flag_dist + c_inst_func_dist + c_inst_comp_dist + c_prim_dist + c_data_format_dist | CG_CMDSCHED_ITYPE 全部 | FT-01, V | 30 | 32% |
| 3 | cmdsched_instb_test | c_instb_fill + c_chain_seq + c_cfg_drv_pair | CG_CMDSCHED_INSTB 全部 | FT-02, B/F/MR | 30 | 42% |
| 4 | cmdsched_dep_test | c_dep_dist + c_raw/c_waw/c_war | cp_hazard_type + X_dep_gran | FT-03, S/E | 50 | 55% |
| 5 | cmdsched_hazard_scope_test | c_hazard_scope_2~5 + c_same_mst_pair | cp_hazard_scope + X_dep_scope | FT-03, B | 30 | 65% |
| 6 | cmdsched_parallel_test | c_multi_parallel_2~5 + c_ls_pair_seq + c_tmu_contend + c_third_inst_blocked + c_ost2_full + c_drf_dp_full | CG_CMDSCHED_UNIT 全部 | FT-04/05, SC-02, P | 30 | 74% |
| 7 | cmdsched_mem_test | c_spad_tile_addr + c_multi_mst_spad + c_release_early + c_tile_map_spread + c_tensor_shape_eqv | CG_CMDSCHED_MEM 全部 | FT-06, S/C | 30 | 82% |
| 8 | cmdsched_rsp_test | c_xd1_seq + c_rsp_priority_seq + c_backpressure_seq + c_wr_lmem_rmw + c_data_format_dist | CG_CMDSCHED_RSP 全部 | FT-07, V/F, SC-02 | 40 | 89% |
| 9 | cmdsched_excp_perf_test | c_illegal_inst + c_block_en_cfg + c_perf_window + c_csr_icg + c_int_info_save + c_mid_reset + c_csr_mode_pairwise + c_csr_write_order | CG_CMDSCHED_EXCP/PERF/CSR 全部 + X_CFG_* | FT-08/09/10, SC-03/04, C/E/MR/P | 40 | 96% |
| 10 | cmdsched_random_mix_test | 宽松混合 + c_longrun_mix | 探索性 + 长稳 | 全部, SC-05, 长稳 | 100 | 防过拟合 |

### 6.2 批次演进逻辑

```
批次 1：基础发射（直发 + 5 MST 识别）
  → 20%，缺口：指令类型未覆盖
批次 2：指令类型（NICE/VNICE、功能分类、组件分类、primitive、数据格式）
  → 32%，缺口：ISTB 管理未覆盖
批次 3：ISTB 管理（链表、满反压、拼接存储、中间复位）
  → 42%，缺口：依赖类型未覆盖
批次 4：依赖类型（RAW/WAW/WAR × tile/page/dram）
  → 55%，缺口：多组件 hazard 未覆盖
批次 5：hazard 范围（2~5 组件 + 同组件双指令）
  → 65%，缺口：并行执行未覆盖
批次 6：并行执行（2~5 组件并行、load-store 并行、TMU 竞争、ost=2/dRF_DP 边界）
  → 74%，缺口：存储资源管理未覆盖
批次 7：存储资源（SPAD tile/CIMC page/DRAM、多组件共享、提前释放、形状边界）
  → 82%，缺口：返回值与握手未覆盖
批次 8：返回值与握手（sync/fence/rd_lmem/V_S、乱序、反压、数据格式边界）
  → 89%，缺口：异常/性能/CSR 未覆盖
批次 9：异常/性能/CSR（中断、并行度、debug、icg、中间复位、CSR × 行为联合交叉）
  → 96%，剩余 bin 定向补齐
批次 10：随机混合 + 长稳
  → 防过拟合 + 长稳正确性
```

### 6.3 覆盖率缺口与约束变化对应

| 缺口 | 根因分析 | 约束变化 | 新增/修改类 |
|---|---|---|---|
| raw_stored 未命中 | RAW 链未强制跨组件构造 | 增加 c_raw_chain | raw_chain_seq |
| full 未命中 | 依赖链不足，ISTB 未填满 | 增加 c_instb_fill 前 4 条强制依赖 | instb_fill_seq |
| five_mst 并行未覆盖 | 未轮转全部 5 个 MST | 增加 c_multi_parallel_2~5 | parallel_seq |
| tag_ooot 未命中 | xd=1 指令未并发 | 增加 c_xd1_seq | xd1_seq |
| glsu_pri_contend 未命中 | 未构造 GLSU/LLSU 同时抢占 TMU | 增加 c_tmu_contend | tmu_seq |
| cmd_int1 未命中 | lmem 指令地址未指向 CIMC | 增加 c_cimc_lmem_addr | illegal_seq |
| start1_done0 未命中 | 未构造 GLSU/NIU load-store 并行 | 增加 c_ls_pair_seq | ls_parallel_seq |
| niu_dst_full 未覆盖 | NIU dst 指令连续下发场景缺失 | 增加 c_niu_dst | niu_seq |
| CSR × 行为未交叉 | 两个 agent 事务独立，CSR 孤立采样 | 增加 c_csr_mode_pairwise / c_csr_write_order，联合 covergroup | csr_write_seq / cmdsched_cfg_vseq / cmdsched_joint_coverage |
| 中间复位空白 | 原模型只有 reset_clear | 增加 c_mid_reset | mid_reset_seq |
| 数据格式未覆盖 | cp_rsp_data 只分三段 | 增加 c_data_format_dist | npu_instr / data_fmt_seq |
| ost=2/dRF_DP 边界缺失 | 原模型只有 mst_avail.full | 增加 c_ost2_full / c_drf_dp_full | parallel_seq |
| 长稳未验证 | 原 PERF 只证明采样过 | 增加 c_longrun_mix + scoreboard A_PERF_MATCH/A_NO_TILE_LEAK | longrun_seq |

---

## 7. 种子管理

### 7.1 种子基线建立流程

1. 每个测试跑 200-500 个种子
2. 记录每个种子的覆盖率贡献、运行时间、pass/fail
3. 按覆盖率贡献排名
4. 找覆盖率平台期
5. 从高贡献种子里选出基线种子
6. 纳入回归，固定使用
7. 定期维护（设计变更后重新评估）

### 7.2 种子基线表

| 测试名 | 类型 | 种子基线 | 基线长度 | 探索种子 | 总运行次数 |
|---|---|---|---|---|---|
| cmdsched_basic_test | 定向 | {1001} | 1 | 0 | 1 |
| cmdsched_instype_test | 随机 | {2001, 2005, ...} | 15 | 3 | 18 |
| cmdsched_instb_test | 随机 | {3001, 3005, ...} | 15 | 3 | 18 |
| cmdsched_dep_test | 随机 | {4001, 4005, ...} | 25 | 5 | 30 |
| cmdsched_hazard_scope_test | 定向 | {5001, 5003, ...} | 10 | 2 | 12 |
| cmdsched_parallel_test | 随机 | {6001, 6005, ...} | 15 | 3 | 18 |
| cmdsched_mem_test | 随机 | {7001, 7003, ...} | 15 | 3 | 18 |
| cmdsched_rsp_test | 随机 | {8001, 8003, ...} | 20 | 4 | 24 |
| cmdsched_excp_perf_test | 定向 | {9001, 9002, ...} | 15 | 3 | 18 |
| cmdsched_random_mix_test | 随机 | {10001, 10012, ...} | 40 | 8 | 48 |

### 7.3 种子筛选示例

以 cmdsched_dep_test 为例：

| 种子范围 | 数量 | 覆盖率贡献 | 保留数 |
|---|---|---|---|
| 4001-4100 | 100 | 贡献 50% | 15 |
| 4101-4200 | 100 | 贡献 30% | 7 |
| 4201-4300 | 100 | 贡献 20% | 3 |

最终种子基线：25 个。

### 7.4 种子管理工具

| 工具 | 能力 |
|---|---|
| VCS urg -grade | 基于功能覆盖率对种子分级 |
| VSO.ai | AI 驱动的种子优化，减少 10 倍种子数 |
| 覆盖率合并 | urg -dir *.vdb -cm merge |

---

## 8. 覆盖率采样实现

本章回答“怎么采”，与第 4 章“采什么”配合。内部信号名以 RTL 实现为准。

### 8.1 行为侧 covergroup 骨架

按第 4 章 10 个覆盖组组织；跨 agent 联合 covergroup 见 8.3。

```systemverilog
class cmdsched_coverage extends uvm_subscriber #(cmdsched_item);
  `uvm_component_utils(cmdsched_coverage)

  covergroup cmdsched_cg @(posedge clk);
    option.per_instance = 1;

    // ============ CG_CMDSCHED_ITYPE ============
    cp_inst_flag: coverpoint inst_flag iff (cmd_valid && cmd_ready) {
      bins nice  = {0};  bins vnice = {1}; }
    cp_inst_func: coverpoint inst_func {
      bins normal = {INST_NORMAL}; bins state_rsp = {INST_STATE}; bins value_rsp = {INST_VALUE}; }
    cp_inst_comp: coverpoint inst_comp {
      bins cfg = {COMP_CFG}; bins lmem = {COMP_LMEM}; bins noc = {COMP_NOC};
      bins glsu = {COMP_GLSU}; bins llsu = {COMP_LLSU}; bins mpu = {COMP_MPU}; bins vpu = {COMP_VPU}; }
    cp_prim_type: coverpoint prim_type {
      bins cfg_inst = {PRIM_CFG}; bins wr_lmem_drv = {PRIM_WR_LMEM}; bins rd_lmem_drv = {PRIM_RD_LMEM};
      bins switch_cimc_drv = {PRIM_SW_CIMC}; bins tld = {PRIM_TLD}; bins tst = {PRIM_TST};
      bins tensor_manip = {PRIM_TENSOR_MANIP}; bins tensor_proc = {PRIM_TENSOR_PROC};
      bins vec_proc = {PRIM_VEC_PROC}; bins v_s = {PRIM_V_S}; bins sync = {PRIM_SYNC};
      bins noc_fence = {PRIM_NOC_FENCE};
      illegal_bins il_rd_csr = {PRIM_RD_CSR}; illegal_bins il_reserved = {PRIM_RESERVED}; }

    // ============ CG_CMDSCHED_INSTB ============
    cp_instb_level: coverpoint instb_level {
      bins empty = {0}; bins one = {1}; bins two = {2}; bins three = {3}; bins full = {4}; }
    cp_instb_chain: coverpoint chain_op {
      bins head_write = {CHAIN_HEAD_WR}; bins tail_write = {CHAIN_TAIL_WR};
      bins head_read = {CHAIN_HEAD_RD}; bins tail_read = {CHAIN_TAIL_RD};
      bins mid_read = {CHAIN_MID_RD}; bins refill = {CHAIN_REFILL}; }
    cp_instb_dp: coverpoint P_INST_BUF_DP { bins dp1 = {1}; bins dp2 = {2}; bins dp4 = {4}; bins dp8 = {8}; }

    // ============ CG_CMDSCHED_DEP ============
    cp_hazard_type: coverpoint hazard_type {
      bins no_dep = {NONE}; bins raw = {RAW}; bins waw = {WAW}; bins war = {WAR}; }
    cp_hazard_gran: coverpoint hazard_gran { bins tile = {GRAN_TILE}; bins page = {GRAN_PAGE}; bins dram = {GRAN_DRAM}; }
    cp_hazard_scope: coverpoint hazard_scope {
      bins same_mst = {1}; bins two_mst = {2}; bins three_mst = {3}; bins four_mst = {4}; bins five_mst = {5}; }
    cp_struct_hazard: coverpoint struct_hazard {
      bins sync_all = {SHT_SYNC_ALL}; bins noc_fence = {SHT_NOC_FENCE}; bins lmem_llsu = {SHT_LMEM_LLSU};
      bins niu_dst_single = {SHT_NIU_DST}; bins niu_store_dual = {SHT_NIU_STORE}; }

    // ============ CG_CMDSCHED_UNIT ============
    cp_mst_id: coverpoint mst_id {
      bins glsu = {MST_GLSU}; bins llsu = {MST_LLSU}; bins mpu = {MST_MPU};
      bins vpu = {MST_VPU}; bins niu = {MST_NIU}; }
    cp_mst_slot: coverpoint mst_slot_busy {
      bins slot0_only = {2'b01}; bins slot1_only = {2'b10}; bins both = {2'b11}; bins empty = {2'b00}; }
    cp_paral_scope: coverpoint paral_scope {
      bins two_mst = {2}; bins three_mst = {3}; bins four_mst = {4}; bins five_mst = {5}; }
    cp_ls_parallel: coverpoint ls_parallel {
      bins glsu_ls_par = {GLSU_LS_PAR}; bins niu_ls_par = {NIU_LS_PAR};
      bins glsu_ls_ser = {GLSU_LS_SER}; bins niu_ls_ser = {NIU_LS_SER}; }
    cp_tmu_arb: coverpoint tmu_arb {
      bins glsu_tmu = {TMU_GLSU}; bins llsu_tmu = {TMU_LLSU};
      bins glsu_pri_contend = {TMU_GLSU_PRI}; bins llsu_wait = {TMU_LLSU_WAIT}; }
    cp_third_inst_blocked: coverpoint third_inst_behavior {
      bins third_blocked = {THIRD_BLOCKED}; bins third_issued = {THIRD_ISSUED}; }

    // ============ CG_CMDSCHED_ISSUE ============
    cp_issue_path: coverpoint issue_path {
      bins direct = {ISSUE_DIRECT}; bins istb_stored = {ISSUE_STORED};
      bins istb_issued = {ISSUE_ISTB_ISSUE}; bins backpressure = {ISSUE_BACKPR}; }
    cp_start_done_seq: coverpoint start_done_seq {
      bins start0_done0 = {SD_S0_D0}; bins start1_done1 = {SD_S1_D1};
      bins start1_done0 = {SD_S1_D0}; bins rls_before_done = {SD_RLS_BEFORE};
      bins rls_same_done = {SD_RLS_SAME}; }
    cp_mst_avail: coverpoint mst_avail {
      bins avail0 = {2'b00}; bins avail1 = {2'b01}; bins full = {2'b11}; bins niu_dst_full = {2'b10}; }

    // ============ CG_CMDSCHED_MEM ============
    cp_spad_tile_occ: coverpoint spad_tile_occ {
      bins tile_alloc = {TILE_ALLOC}; bins tile_release = {TILE_RELEASE};
      bins tile_partial_rls = {TILE_PARTIAL_RLS}; bins tile_conflict = {TILE_CONFLICT}; }
    cp_cimc_page_occ: coverpoint cimc_page_occ {
      bins page_alloc = {PAGE_ALLOC}; bins page_release = {PAGE_RELEASE};
      bins page_conflict = {PAGE_CONFLICT}; bins cimc_2x2 = {CIMC_2X2}; }
    cp_dram_occ: coverpoint dram_occ {
      bins dram_alloc = {DRAM_ALLOC}; bins dram_release = {DRAM_RELEASE}; bins dram_whole = {DRAM_WHOLE}; }
    cp_multi_mst_spad: coverpoint multi_mst_spad {
      bins mst2_same_spad = {2}; bins mst3_same_spad = {3};
      bins mst4_same_spad = {4}; bins mst5_same_spad = {5}; bins rar_multi_read = {RAR}; }
    cp_mem_release_src: coverpoint mem_release_src {
      bins done_release = {RLS_DONE}; bins rls_release = {RLS_PRE}; bins tile_rls_en_off = {RLS_DISABLED}; }
    cp_spad_tile_map: coverpoint {spad_id, tile_id} {
      bins tile_00 .. tile_31 = {[0:31]}; }

    // ============ CG_CMDSCHED_RSP ============
    cp_rsp_type: coverpoint rsp_type {
      bins sync_rsp = {RSP_SYNC}; bins noc_fence_rsp = {RSP_NOC_FENCE};
      bins rd_lmem_rsp = {RSP_RD_LMEM}; bins v_s_rsp = {RSP_V_S}; }
    cp_rsp_tag: coverpoint rsp_tag_mode {
      bins tag_match = {TAG_IN_ORDER}; bins tag_ooot = {TAG_OUT_OF_ORDER}; bins multi_xd = {MULTI_XD}; }
    cp_rsp_prio: coverpoint rsp_prio {
      bins scalar_prio = {PRIO_SCALAR}; bins lmem_prio = {PRIO_LMEM};
      bins fence_prio = {PRIO_FENCE}; bins sync_prio = {PRIO_SYNC}; }
    cp_backpressure: coverpoint backpressure_src {
      bins rd_bp = {BP_READ}; bins wr_bp = {BP_WRITE}; bins scalar_bp = {BP_SCALAR}; bins istb_bp = {BP_ISTB}; }
    cp_wr_lmem_rmw: coverpoint wr_lmem_rmw {
      bins rmw_performed = {RMW_DONE}; bins rmw_blocked = {RMW_BLOCKED}; }

    // ============ CG_CMDSCHED_EXCP ============
    cp_int_type: coverpoint cmd_int[1:0] {
      bins no_int = {2'b00}; bins cmd_int0 = {2'b01}; bins cmd_int1 = {2'b10};
      illegal_bins int2 = {2'b11}; }
    cp_block_en: coverpoint block_behavior {
      bins block_stop = {BLOCK_STOP}; bins block_continue = {BLOCK_CONTINUE}; }
    cp_int_clear: coverpoint int_clear {
      bins reset_clear = {CLR_RESET}; bins wr1_clear = {CLR_WR1}; bins rec_after_clr = {CLR_RECOVER}; }
    cp_int_info_save: coverpoint int_info_save {
      bins first_int_saved = {INFO_FIRST_SAVED}; bins later_not_saved = {INFO_LATER_NOT_SAVED};
      bins info_readable = {INFO_READABLE}; }

    // ============ CG_CMDSCHED_PERF ============
    cp_perf_paral: coverpoint perf_paral {
      bins total_paral = {PERF_TOTAL}; bins mpu_paral = {PERF_MPU}; bins win_open = {PERF_WIN}; }
    cp_perf_cong: coverpoint perf_cong_mst {
      bins mpu_cong = {CONG_MPU}; bins vpu_cong = {CONG_VPU}; bins glsu_cong = {CONG_GLSU};
      bins llsu_cong = {CONG_LLSU}; bins niu_cong = {CONG_NIU}; }
    cp_debug_reg: coverpoint debug_reg {
      bins dbg0_busy = {DBG0}; bins dbg1_inst_cnt = {DBG1}; bins dbg2_iss_cnt = {DBG2}; }

    // ============ CG_CMDSCHED_CSR ============
    cp_csr_icg: coverpoint creg_cmd_icg_en { bins icg_on = {[1:$]}; bins icg_off = {0}; }
    cp_csr_tile_rls: coverpoint creg_cmd_tile_rls_en {
      bins all_en = {32'hFFFF_FFFF}; bins all_off = {32'h0}; bins part_en = {[1:32'hFFFF_FFFE]}; }
    cp_idle_icg: coverpoint idle_icg_state {
      bins idle = {IDLE_NO_CLK}; bins gate_on = {GATE_OPEN}; bins perf_gate = {GATE_PERF}; }

    // ============ 关键同 agent 跨组交叉 ============
    X_dep_gran: cross cp_hazard_type, cp_hazard_gran;
    X_dep_scope: cross cp_hazard_type, cp_hazard_scope;
    X_unit_paral: cross cp_mst_id, cp_paral_scope;
    X_mem_occ_mst: cross cp_spad_tile_occ, cp_mst_id;
    X_issue_dep_path: cross cp_hazard_type, cp_issue_path;
    X_rsp_prio: cross cp_rsp_type, cp_rsp_prio;
    X_excp_block: cross cp_int_type, cp_block_en;
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    cmdsched_cg = new();
  endfunction

  function void write(cmdsched_item t);
    inst_flag = t.inst_flag;   inst_func = t.inst_func;   inst_comp = t.inst_comp;
    prim_type = t.prim_type;   mst_id = t.mst_id;         instb_level = t.instb_level;
    hazard_type = t.hazard_type; hazard_gran = t.hazard_gran; hazard_scope = t.hazard_scope;
    struct_hazard = t.struct_hazard; mst_slot_busy = t.mst_slot_busy; paral_scope = t.paral_scope;
    ls_parallel = t.ls_parallel; tmu_arb = t.tmu_arb; issue_path = t.issue_path;
    start_done_seq = t.start_done_seq; mst_avail = t.mst_avail;
    spad_tile_occ = t.spad_tile_occ; cimc_page_occ = t.cimc_page_occ; dram_occ = t.dram_occ;
    multi_mst_spad = t.multi_mst_spad; mem_release_src = t.mem_release_src;
    spad_id = t.spad_id; tile_id = t.tile_id;
    rsp_type = t.rsp_type; rsp_tag_mode = t.rsp_tag_mode; rsp_prio = t.rsp_prio;
    backpressure_src = t.backpressure_src; wr_lmem_rmw = t.wr_lmem_rmw;
    cmd_int = t.cmd_int; block_behavior = t.block_behavior;
    int_clear = t.int_clear; int_info_save = t.int_info_save;
    third_inst_behavior = t.third_inst_behavior; perf_paral = t.perf_paral; perf_cong_mst = t.perf_cong_mst;
    debug_reg = t.debug_reg; creg_cmd_icg_en = t.creg_cmd_icg_en;
    creg_cmd_tile_rls_en = t.creg_cmd_tile_rls_en; idle_icg_state = t.idle_icg_state;
    cmdsched_cg.sample();
  endfunction
endclass
```

### 8.2 配置侧 covergroup 骨架

配置 agent 仍保留独立 covergroup，只覆盖配置事务本身：

```systemverilog
covergroup csr_cfg_cg;
  cp_csr_icg:       coverpoint item.icg_en;
  cp_csr_tile_rls:  coverpoint item.tile_rls_en {
    bins all_off = {32'h0};
    bins all_on  = {32'hFFFF_FFFF};
    bins part_on = {[1:32'hFFFF_FFFE]};
  }
  cp_csr_block:     coverpoint item.block_en;
  cp_csr_excep:     coverpoint item.excep_en;
  cp_csr_perf:      coverpoint item.perf_en;
  cp_csr_spad_excl: coverpoint item.spad_excl_en;
  cp_csr_wr_order:  coverpoint item.write_order {
    bins before_stream = {WR_BEFORE};
    bins during_stream = {WR_DURING};
    bins after_stream  = {WR_AFTER};
    bins back_to_back  = {WR_B2B};
  }
endgroup
```

配置侧与行为侧的分工：
- 配置侧：CSR 值写过、写时序、写与指令流的先后关系；
- 行为侧联合 covergroup：行为发生时的生效配置 × 行为结果；
- 二者不重复 `cross` 同一组合。

### 8.3 跨 agent 联合 covergroup

**实现原则**：配置侧 agent 只覆盖 CSR 值与写时序；行为侧 monitor 在采样行为事件的同一拍，从白盒探针或 RAL mirror 读取**生效 CSR 值**，作为本侧 coverpoint 采样变量，再与行为 coverpoint 做组内 `cross`。禁止跨 covergroup 实例直接 `cross`。

```systemverilog
class cmdsched_joint_coverage extends uvm_subscriber #(cmdsched_item);
  `uvm_component_utils(cmdsched_joint_coverage)

  csr_ctx cfg;  // 行为采样拍从探针/mirror 获取的生效配置快照

  covergroup joint_cg @(posedge clk);
    option.per_instance = 1;

    // --- 行为侧 coverpoint ---
    cp_int_type:          coverpoint item.cmd_int[1:0];
    cp_issue_path:        coverpoint item.issue_path;
    cp_mem_release_src:   coverpoint item.mem_release_src;
    cp_spad_tile_occ:     coverpoint item.spad_tile_occ;
    cp_rsp_type:          coverpoint item.rsp_type;
    cp_rsp_tag:           coverpoint item.rsp_tag_mode;
    cp_perf_paral:        coverpoint item.perf_paral;
    cp_perf_cong:         coverpoint item.perf_cong_mst;
    cp_debug_reg:         coverpoint item.debug_reg;
    cp_idle_icg:          coverpoint item.idle_icg_state;
    cp_multi_mst_spad:    coverpoint item.multi_mst_spad;
    cp_cmd_handshake:     coverpoint item.handshake_mode;
    cp_backpressure:      coverpoint item.backpressure_src;
    cp_inst_func:         coverpoint item.inst_func;
    cp_prim_type:         coverpoint item.prim_type;

    // --- CSR 生效值快照 coverpoint（来自 cfg，不是配置 agent 的 covergroup）---
    cp_cfg_icg:      coverpoint cfg.icg_en;
    cp_cfg_tile_rls: coverpoint cfg.tile_rls_en {
      bins all_off = {32'h0};
      bins all_on  = {32'hFFFF_FFFF};
      bins part_on = {[1:32'hFFFF_FFFE]};
    }
    cp_cfg_block:    coverpoint cfg.block_en;
    cp_cfg_excep:    coverpoint cfg.excep_en;
    cp_cfg_perf:     coverpoint cfg.perf_en;
    cp_cfg_spad_excl:coverpoint cfg.spad_excl_en {
      bins non_excl = {0};
      bins excl_cfg = {[1:$]};
    }

    // --- 配置稳定期标记，切换期单独 bin ---
    cp_cfg_stable: coverpoint item.cfg_stable;  // 1=稳定期，0=切换窗口

    // --- 跨 agent 联合交叉 ---
    X_CFG_EXCP_INT:    cross cp_cfg_excep, cp_int_type, cp_cfg_stable;
    X_CFG_BLOCK_INT:   cross cp_cfg_block, cp_int_type, cp_cfg_stable;
    X_CFG_TILE_RLS:    cross cp_cfg_tile_rls, cp_mem_release_src, cp_spad_tile_occ;
    X_CFG_PERF_PARAL:  cross cp_cfg_perf, cp_perf_paral;
    X_CFG_PERF_CONG:   cross cp_cfg_perf, cp_perf_cong;
    X_CFG_PERF_DEBUG:  cross cp_cfg_perf, cp_debug_reg;
    X_CFG_ICG_ISSUE:   cross cp_cfg_icg, cp_idle_icg, cp_issue_path;
    X_CFG_ICG_FUNC:    cross cp_cfg_icg, cp_inst_func, cp_prim_type;
    X_CFG_BLOCK_RSP:   cross cp_cfg_block, cp_rsp_type, cp_cmd_handshake;
    X_CFG_BLOCK_BP:    cross cp_cfg_block, cp_backpressure, cp_issue_path;
    X_CFG_SPAD_EXCL:   cross cp_cfg_spad_excl, cp_multi_mst_spad;
  endgroup
endclass
```

**采样口径**：完整交叉清单与采样口径见 4.12.3，本节不重复。

### 8.4 采样位置原则

| 原则 | 说明 |
|---|---|
| 在 monitor 采样 | 不在 sequence 采样，保证垂直复用 |
| 按子模块分 monitor | ITYPE/INSTB 在 decode-ISTB 侧；DEP/MEM/ISSUE 在 scoreboard 侧；RSP 在 sp_inst 侧；EXCP/PERF/CSR 在 cmd_int_perf 侧 |
| 联合采样激励和结果 | 区分“场景发生”和“场景正确处理”（如 hazard 产生 vs 正确阻塞） |
| 用 iff 限定有效周期 | 复位、握手未成功、性能关闭等无效周期不采样 |
| 非法 bin 用 illegal_bins | 命中即报错（如保留指令编码、cmd_int[2] 等） |
| 参数类覆盖点独立采样 | ISTB_DP 等编译参数在各参数化回归中分别收集 |
| 新增覆盖点随组采样 | cp_spad_tile_map 在 scoreboard 侧随 MEM 组采样；cp_wr_lmem_rmw 在 sp_inst 侧随 RSP 组采样；cp_third_inst_blocked 在 decode-ISTB 侧随 UNIT 组采样；cp_int_info_save 在 cmd_int_perf 侧随 EXCP 组采样 |
| 跨 agent 联合采样 | 行为侧 monitor 在采样拍读取生效 CSR 快照，作为本侧 coverpoint 后组内 cross；禁止跨 covergroup 实例直接 cross（见 8.3） |
| 配置切换窗口单独 bin | `cfg_stable=0` 与稳定期分开，不混入虚高 |

---

## 9. 需求追溯矩阵

以下按 HM057 CDD 3.2 Feature List 逐条映射（Feat-1~40），并挂到主功能树节点，确保无孤立需求、无孤立覆盖点。

| 需求 ID | 需求描述 | 优先级 | 主功能树节点 | 覆盖组/覆盖点 | 约束 | 测试用例 | 状态 |
|---|---|---|---|---|---|---|---|
| Feat-1 | 支持各功能组件信息配置和启动 | P0 | FT-05 | UNIT：cp_mst_id, cp_mst_slot | c_mst_dist, c_mst_dual | cmdsched_basic_test | 计划中 |
| Feat-2 | 支持指令间 sync 同步 | P0 | FT-03, FT-07 | DEP：cp_struct_hazard.sync_all；RSP：cp_rsp_type.sync_rsp | c_sync_barrier | cmdsched_rsp_test | 计划中 |
| Feat-3 | 删除 CPU 读取 csr 配置寄存器功能 | P0 | FT-01 | ITYPE：cp_prim_type.il_rd_csr | c_illegal_inst | cmdsched_excp_perf_test | 计划中 |
| Feat-4 | 支持 CPU 读写 LMEM（SPAD） | P0 | FT-07 | RSP：cp_rsp_type.rd_lmem_rsp, cp_wr_lmem_rmw；ITYPE：wr/rd_lmem_drv | c_prim_dist, c_wr_lmem_rmw | cmdsched_rsp_test | 计划中 |
| Feat-5 | lmem 与 LLSU 指令 structure hazard | P0 | FT-03 | DEP：cp_struct_hazard.lmem_llsu | c_lmem_llsu_conflict | cmdsched_hazard_scope_test | 计划中 |
| Feat-6 | 删除 CIMC 的 1x4 形状 | P0 | FT-06 | MEM：cp_cimc_page_occ.cimc_2x2 | c_cimc_page_addr | cmdsched_mem_test | 计划中 |
| Feat-7 | 支持 NIU 指令间同步 | P0 | FT-03, FT-07 | DEP：cp_struct_hazard.noc_fence；RSP：noc_fence_rsp | c_noc_fence_barrier | cmdsched_rsp_test | 计划中 |
| Feat-8 | NIU 内部 load/store 并行 | P0 | FT-05 | UNIT：cp_ls_parallel.niu_ls_par | c_ls_pair_seq | cmdsched_parallel_test | 计划中 |
| Feat-9 | GLSU 内部 load/store 并行 | P0 | FT-05 | UNIT：cp_ls_parallel.glsu_ls_par | c_ls_pair_seq | cmdsched_parallel_test | 计划中 |
| Feat-10 | 同组件两条指令无 structure hazard | P0 | FT-03, FT-05 | UNIT：cp_mst_slot.both, cp_third_inst_blocked；DEP：same_mst | c_same_mst_pair, c_mst_dual, c_third_inst_blocked | cmdsched_hazard_scope_test | 计划中 |
| Feat-11 | 任意两组件 data hazard | P0 | FT-03 | DEP：cp_hazard_scope.two_mst | c_hazard_scope_2~5 | cmdsched_hazard_scope_test | 计划中 |
| Feat-12 | 任意三组件 data hazard | P0 | FT-03 | DEP：cp_hazard_scope.three_mst | c_hazard_scope_2~5 | cmdsched_hazard_scope_test | 计划中 |
| Feat-13 | 任意四组件 data hazard | P0 | FT-03 | DEP：cp_hazard_scope.four_mst | c_hazard_scope_2~5 | cmdsched_hazard_scope_test | 计划中 |
| Feat-14 | 五组件 data hazard | P0 | FT-03 | DEP：cp_hazard_scope.five_mst | c_hazard_scope_2~5 | cmdsched_hazard_scope_test | 计划中 |
| Feat-15 | 任意两组件并行执行 | P0 | FT-04 | UNIT：cp_paral_scope.two_mst | c_multi_parallel_2~5 | cmdsched_parallel_test | 计划中 |
| Feat-16 | 任意三组件并行执行 | P0 | FT-04 | UNIT：cp_paral_scope.three_mst | c_multi_parallel_2~5 | cmdsched_parallel_test | 计划中 |
| Feat-17 | 任意四组件并行执行 | P0 | FT-04 | UNIT：cp_paral_scope.four_mst | c_multi_parallel_2~5 | cmdsched_parallel_test | 计划中 |
| Feat-18 | 五组件并行执行 | P0 | FT-04 | UNIT：cp_paral_scope.five_mst | c_multi_parallel_2~5 | cmdsched_parallel_test | 计划中 |
| Feat-19 | 指令序列乱序发射（窗口 ISTB_DP） | P0 | FT-02, FT-04 | INSTB：cp_instb_dp；ISSUE：cp_issue_path | c_instb_dp, c_issue_stall | cmdsched_instb_test | 计划中 |
| Feat-20 | 支持多 xd=1 指令下发，带 tag 乱序返回 | P0 | FT-07 | RSP：cp_rsp_tag.multi_xd / tag_ooot | c_xd1_seq, c_tag_out_of_order | cmdsched_rsp_test | 计划中 |
| Feat-21 | 多组件访问同一 SPAD | P0 | FT-06 | MEM：cp_multi_mst_spad | c_multi_mst_spad | cmdsched_mem_test | 计划中 |
| Feat-22 | 按 tile 切分 SPAD，各组件占用/释放 | P0 | FT-06 | MEM：cp_spad_tile_occ, cp_spad_tile_map | c_spad_tile_addr, c_release_early, c_tile_map_spread | cmdsched_mem_test | 计划中 |
| Feat-23 | GLSU/LLSU 同时调用 TMU，GLSU 优先 | P0 | FT-05 | UNIT：cp_tmu_arb.glsu_pri_contend | c_tmu_contend | cmdsched_parallel_test | 计划中 |
| Feat-24 | creg_cmd_icg_en 扩展为 [31:0] | P1 | FT-10 | CSR：cp_csr_icg；联合 X_CFG_ICG_ISSUE | c_csr_icg, c_csr_mode_pairwise | cmdsched_excp_perf_test | 计划中 |
| Feat-25 | 删除各组件低功耗模式 | P1 | FT-10 | CSR：cp_idle_icg, cp_csr_icg | c_csr_icg | cmdsched_excp_perf_test | 计划中 |
| Feat-26 | 支持读请求反压（i_ch1_req_rrdy） | P0 | FT-07 | RSP：cp_backpressure.rd_bp | c_backpressure_seq | cmdsched_rsp_test | 计划中 |
| Feat-27 | 支持写请求反压（i_ch0_req_wrdy） | P0 | FT-07 | RSP：cp_backpressure.wr_bp | c_backpressure_seq | cmdsched_rsp_test | 计划中 |
| Feat-28 | 异常指令产生中断并上报 | P1 | FT-08 | EXCP：cp_int_type.cmd_int0, cp_int_info_save | c_illegal_inst, c_int_info_save | cmdsched_excp_perf_test | 计划中 |
| Feat-29 | 读写非 SPAD 地址产生中断 | P1 | FT-08 | EXCP：cp_int_type.cmd_int0（非 SPAD） | c_non_spad_addr | cmdsched_excp_perf_test | 计划中 |
| Feat-30 | lmem_drv 与 LLSU 同时工作产生中断 | P0 | FT-08 | EXCP：cp_int_type.cmd_int1；DEP：lmem_llsu | c_lmem_llsu_conflict | cmdsched_excp_perf_test | 计划中 |
| Feat-31 | 统计 MPU 指令在 ISTB 中的拥塞数 | P1 | FT-09 | PERF：cp_perf_cong.mpu_cong | c_perf_cong_seq | cmdsched_excp_perf_test | 计划中 |
| Feat-32 | 统计 VPU 指令在 ISTB 中的拥塞数 | P1 | FT-09 | PERF：cp_perf_cong.vpu_cong | c_perf_cong_seq | cmdsched_excp_perf_test | 计划中 |
| Feat-33 | 统计 GLSU 指令在 ISTB 中的拥塞数 | P1 | FT-09 | PERF：cp_perf_cong.glsu_cong | c_perf_cong_seq | cmdsched_excp_perf_test | 计划中 |
| Feat-34 | 统计 LLSU 指令在 ISTB 中的拥塞数 | P1 | FT-09 | PERF：cp_perf_cong.llsu_cong | c_perf_cong_seq | cmdsched_excp_perf_test | 计划中 |
| Feat-35 | 统计 NIU 指令在 ISTB 中的拥塞数 | P1 | FT-09 | PERF：cp_perf_cong.niu_cong | c_perf_cong_seq | cmdsched_excp_perf_test | 计划中 |
| Feat-36 | 统计所有组件并行度 | P1 | FT-09 | PERF：cp_perf_paral.total_paral | c_perf_window | cmdsched_excp_perf_test | 计划中 |
| Feat-37 | 统计 MPU 并行度 | P1 | FT-09 | PERF：cp_perf_paral.mpu_paral | c_perf_window | cmdsched_excp_perf_test | 计划中 |
| Feat-38 | debug0：各组件工作状态 | P1 | FT-09 | PERF：cp_debug_reg.dbg0_busy | 寄存器比对 | cmdsched_excp_perf_test | 计划中 |
| Feat-39 | debug1：inst_disp 总下发指令数 | P1 | FT-09 | PERF：cp_debug_reg.dbg1_inst_cnt | 寄存器比对 | cmdsched_excp_perf_test | 计划中 |
| Feat-40 | debug2：cmd_sch 总发射指令数 | P1 | FT-09 | PERF：cp_debug_reg.dbg2_iss_cnt | 寄存器比对 | cmdsched_excp_perf_test | 计划中 |

**要求**：不能有孤立需求，也不能有孤立覆盖点。Feat-1~40 全部挂到 FT-01~10，见 3.2。

---

## 10. 覆盖率收敛签核标准

### 10.1 签核条件总表

| 条件 | 标准 |
|---|---|
| 功能覆盖点 | 100% bin 命中 |
| 组内交叉 | 100% 有意义组合命中 |
| 同 agent 跨组交叉 | 100% 有意义组合命中 |
| 跨 agent 联合交叉 | 100% 有意义组合命中；配置切换期 bin 单独达标 |
| 非法 bin | 0 命中 |
| 忽略 bin | 已审批并记录理由 |
| 配置组合 | pairwise 或场景矩阵 100% |
| 需求追溯 | 无孤立需求，无孤立覆盖点（Feat-1~40 全部映射到 FT-01~10） |
| 专题矩阵 | 3.3.2 无空格；3.4/3.5 场景与微架构全部 pass |
| 种子基线 | 已建立并纳入回归 |
| 豁免项 | 有理由、有审批人、有记录 |
| 回归稳定性 | 固定回归集覆盖率稳定 |
| 长稳 | 长跑场景计数器/占用表与 scoreboard 一致，无泄漏 |

### 10.2 豁免流程

```
发现未覆盖 bin
    ↓
分析原因
    ├─ 约束可覆盖但种子没抽到 → 加种子 / 调约束
    ├─ 约束覆盖不到 → 补约束 / 写定向 case
    ├─ 架构不可达 → 申请豁免（如独占 SPAD 模式暂不支持）
    └─ 命中了但结果错 → DUT bug，进 debug
    ↓
豁免申请 → 验证负责人审批 → 记录理由和审批人
```

### 10.3 专题门禁

| 门禁项 | 标准 | 证据 |
|---|---|---|
| 主功能树完整 | FT-01~10 每个节点至少一个 Feat、至少一个 CP/Cross | 3.2 矩阵 |
| 横向切面无空格 | 3.3.2 每格为覆盖点/交叉/SVA/scoreboard 或 `N/A + 理由` | 3.3.2 矩阵 |
| 场景专题 | SC-01~05 全部有测试且 pass | 3.4 表 |
| 微架构专题 | MA-01~06 全部有 SVA/scoreboard 并命中 | 3.5 表 |
| SVA 命中 | A_CMD_HS 等 10 条断言 0 fail | 4.14 表 + 回归报告 |
| 中间复位 | cp_mid_reset_* 全部命中且复位后无泄漏 | scoreboard 报告 |

### 10.4 覆盖率门禁

| 项 | 标准 |
|---|---|
| 组内覆盖点 | 100% bin 命中 |
| 组内交叉 | 100% 有意义 bin 命中 |
| 同 agent 跨组交叉 | 100% 有意义 bin 命中 |
| 跨 agent 联合交叉 | 100% 有意义 bin 命中；配置切换期 bin 单独达标 |
| 非法 bin | 0 命中 |
| 忽略 bin | 已审批并记录理由 |
| 配置组合 | pairwise 或场景矩阵 100% |
| 长稳 | 长跑场景计数器/占用表与 scoreboard 一致，无泄漏 |
| 需求追溯 | Feat-1~40 全部挂到功能树节点；无孤立需求、无孤立覆盖点 |
| 种子基线 | 已建立并纳入回归 |
| 豁免 | 有理由、有审批人、有记录 |

### 10.5 豁免与语义冲突处理

| 场景 | 处理 |
|---|---|
| 架构不可达组合 | `ignore_bins` + 豁免记录（理由/审批人/日期） |
| `excep_en=off` 下非法编码 | 不用 `illegal_bins` 表达屏蔽；用 `cp_cfg_excep.off × cp_int_type.no_int` 单独 bin |
| 超时/协议错误不由 CMD_SCH 负责 | 3.3.2 对应格写 `N/A + 归属模块`，不强行造覆盖点 |
| SPAD 独占模式暂不支持 | `cp_csr_spad_excl.excl_cfg` 仅验证配置通路，行为豁免 |
| 跨 agent 采样不可达 | 明确“不可达”而非“未覆盖”，记录采样口径限制 |

### 10.6 豁免记录表

| Bin | 所属覆盖点 | 豁免理由 | 审批人 | 日期 |
|---|---|---|---|---|
| excl_cfg | cp_csr_spad_excl | 独占 SPAD 模式当前架构暂不支持（creg_cmd_spad_excl_en 默认 0），仅验证配置通路 | | |
| （待补） | cp_timeout_err / cp_protocol_err | 若超时/协议错误由其他模块负责，需在此记录归属模块 | | |

### 10.7 批次与专题对应

| 批次 | 测试 | 覆盖专题 | 目标覆盖率 |
|---|---|---|---|
| 1 | cmdsched_basic_test | FT-04, SC-01, I/F/B | 20% |
| 2 | cmdsched_instype_test | FT-01, V | 32% |
| 3 | cmdsched_instb_test | FT-02, B/F/MR | 42% |
| 4 | cmdsched_dep_test | FT-03, S/E | 55% |
| 5 | cmdsched_hazard_scope_test | FT-03, B | 65% |
| 6 | cmdsched_parallel_test | FT-04/05, SC-02, P | 74% |
| 7 | cmdsched_mem_test | FT-06, S/C | 82% |
| 8 | cmdsched_rsp_test | FT-07, V/F, SC-02 | 89% |
| 9 | cmdsched_excp_perf_test | FT-08/09/10, SC-03/04, C/E/MR/P | 96% |
| 10 | cmdsched_random_mix_test | 全部, SC-05, 长稳 | 防过拟合 |

---

## 11. 附录

### 11.1 批次执行命令示例

```bash
# 批次8：返回值与握手测试
for seed in 8001 8003 8007 8012 8015; do
  simv +ntb_random_seed=$seed +UVM_TESTNAME=cmdsched_rsp_test \
       -cm line+cond+fsm+tgl+functional -cm_dir ./cov_$seed.vdb
done

# 合并覆盖率
urg -dir cov_*.vdb -cm merge -report ./report_batch8

# 种子分级
urg -dir cov_*.vdb -grade -metric group
```

### 11.2 覆盖率组速查卡

```
┌──────────────────────────────────────────────────────────────┐
│  CG_CMDSCHED_ITYPE  → 指令类型（flag/功能/组件/primitive/格式）│
│  CG_CMDSCHED_INSTB  → ISTB 管理（链表/深度/反压/拼接/中间复位）│
│  CG_CMDSCHED_DEP    → 数据依赖（RAW/WAW/WAR/结构冲突）        │
│  CG_CMDSCHED_UNIT   → 执行单元（5 MST/双槽/并行/TMU）         │
│  CG_CMDSCHED_ISSUE  → 发射决策（路径/优先级/start-done/边界） │
│  CG_CMDSCHED_MEM    → 存储资源（tile/page/dram/共享/形状）    │
│  CG_CMDSCHED_RSP    → 返回值（类型/乱序/优先级/反压/格式）    │
│  CG_CMDSCHED_EXCP   → 异常中断（cmd_int[0]/[1]/block/现场）   │
│  CG_CMDSCHED_PERF   → 性能与 debug（并行度/拥塞/寄存器/长稳） │
│  CG_CMDSCHED_CSR    → CSR 与低功耗（icg/使能/IDLE/配置模式）  │
└──────────────────────────────────────────────────────────────┘
专题速查：
  FT-01~10 主功能树 | I/R/C/V/S/E/MR/B/F/P 横向切面
  SC-01~05 场景    | MA-01~06 微架构
  跨 agent 联合：X_CFG_EXCP_INT / X_CFG_BLOCK_INT / X_CFG_TILE_RLS
                X_CFG_PERF_* / X_CFG_ICG_* / X_CFG_BLOCK_* / X_CFG_SPAD_EXCL
```

### 11.3 常见坑清单

| 坑 | 后果 | 避免方式 |
|---|---|---|
| 只采激励不采结果 | 无法区分“场景发生”和“正确处理” | 联合采样（hazard 产生 vs 正确阻塞） |
| 按地址而非 tile 粒度判断冲突 | 与 RTL hazard 判定口径不一致，覆盖率虚高/虚低 | SPAD 冲突以 tile 为粒度（8 SPAD × 4 tile） |
| 漏掉 NIU 特例 | NIU 双 store、noc_dst 单条等设计约束未验证 | cp_struct_hazard 强制覆盖 niu_dst/niu_store |
| 忽略后启动先 done 场景 | GLSU/NIU load-store 并行时序 bug 漏检 | ls_parallel_seq + start1_done0 断言 |
| rls_vld 时序未校验 | 资源提前释放错误导致 tile 占用泄漏 | cp_start_done_seq 覆盖 rls_before/same_done |
| 乱序返回未校验 tag | 多 xd=1 指令返回数据错位 | cp_rsp_tag + scoreboard 按 tag 比对 |
| TMU 竞争场景缺失 | GLSU/LLSU 抢占仲裁 bug 漏检 | c_tmu_contend 定向场景 |
| 已删除功能未做非法覆盖 | rd_csr、CIMC 1x4 等旧指令被误用 | illegal_bins 覆盖 il_rd_csr/il_reserved |
| 异常场景未配 block_en | 中断后停止/继续收发两种行为只验证一种 | X_excp_block 交叉覆盖 |
| 忽略 ISTB_DP 参数遍历 | 1/2/8 深度下链表与反压行为未验证 | cp_instb_dp 各参数回归 |
| 忽略 bin 滥用 | 掩盖真实缺口 | 豁免需审批并记录 |
| CSR 孤立采样 | CSR 100% 但配置下指令行为未验证 | 4.12.3 跨 agent 联合 covergroup |
| 跨 agent 直接 cross | SV 语法不支持跨 covergroup 实例 cross | 行为侧采样生效配置后组内 cross（8.3） |
| 配置切换期混入稳定期 | 覆盖率虚高 | cfg_stable 单独 bin |
| excep_en=off 与 illegal_bins 冲突 | 语义矛盾 | 屏蔽行为用 cp_cfg_excep.off × cp_int_type.no_int 单独 bin |
| 中间复位空白 | 复位后 FIFO/状态机恢复未验证 | cp_mid_reset_* + scoreboard 泄漏检查 |
| 长稳只证明采样过 | 计数器溢出/资源泄漏漏检 | cp_perf_longrun + A_PERF_MATCH + A_NO_TILE_LEAK |
| 超时/协议错误强行造点 | 与架构归属冲突 | 明确 N/A + 归属模块，不强行造覆盖点 |

---

**本文档核心思想**：HM057 CMD_SCH 的功能覆盖率按四层组织——验证策略层（第 3 章专题体系，回答“验证什么”）、覆盖实现层（第 4 章覆盖组与交叉，回答“怎么采”）、激励与约束层（第 5~7 章，回答“怎么激励”）、签核层（第 10 章，回答“怎么算过”）。10 个覆盖率组是采样基线；主功能树专题保证每个功能有归属；横向切面专题保证每个功能在各切面上有落点；场景与微架构专题保证端到端与白盒正确；CSR 与指令行为分属两个 agent，通过行为侧联合 covergroup 采样生效配置后组内 cross，解决配置 × 行为交叉缺口。约束、覆盖点、测试用例、种子基线、专题门禁五者形成闭环。