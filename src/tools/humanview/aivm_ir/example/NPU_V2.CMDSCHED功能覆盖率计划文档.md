# NPU\_V2\.CMDSCHED功能覆盖率计划文档

|字段|值|
|---|---|
|Owner|@刘江清@王翔|
|Reviewer|资深验证、TL|
|状态|模板|
|难度|★★★☆☆|
|适用阶段|环境搭建, 功能覆盖率|
|版本记录|V\.0\.0\.1@2026\-10\-12：<br>建立NPU\_V2\.CMDSCHED 功能覆盖率模板<br>V\.1\.0\.0@2026\-11\-03：按HM057 CDD（L5\-\[NPU\-HM057\]\-\[CDD\]\-CMD\_SCH\_Dev）全面更新覆盖率计划，对齐5 MST/ISTB/scoreboard 架构，新增10个覆盖率组并建立Feat\-1\~40需求追溯矩阵<br>V\.1\.1\.0@2026\-11\-03：完备性评审补齐4个覆盖点（cp\_third\_inst\_blocked/cp\_spad\_tile\_map/cp\_wr\_lmem\_rmw/cp\_int\_info\_save）及对应约束与场景，覆盖点计数与追溯矩阵同步更新|
|引用CMDSCHED vplan 链接|https://nanocorechip\.feishu\.cn/wiki/TLsJwTAJziivwekhfy4c3ieD|
|标签|cmsched，Function coverage, covergroup|
|创建时间|2026\-10\-12|

## 1\. 概述

### 1\.1 目的

本文档定义 HM057 NPU 指令调度器（Command Scheduler，CMD\_SCH）的功能覆盖率模型、配套约束设计及种子管理策略，建立**约束 → 激励 → 覆盖率 → 收敛**的完整闭环，确保验证完备性可度量、可追溯、可签核。本文档依据《L5\-\[NPU\-HM057\]\-\[CDD\]\-CMD\_SCH\_Dev》编写，覆盖点、约束与测试用例均与 CDD 功能特性一一对应。

### 1\.2 范围

覆盖 CMD\_SCH 指令调度器的以下功能维度：

- 指令接收与分类（NICE/VNICE 指令、普通功能/状态返回/数值返回指令、七类功能组件指令）

- ISTB 指令缓存管理（链表存储、深度参数、满时反压、cfg/drv 拼接存储）

- 数据依赖处理（RAW/WAW/WAR，SPAD tile/CIMC page/DRAM 粒度，2\~5 组件 data hazard）

- 乱序发射与并行调度（发射窗口 ISTB\_DP、2\~5 组件并行、同组件双指令）

- 各执行单元（MST：GLSU/LLSU/MPU/VPU/NIU）调度及特例（NIU 单条 dst、GLSU/NIU load\-store 并行、TMU 竞争）

- 存储资源管理（SPAD 8 块 × 4 tile、CIMC 4 page、DRAM 整块，占用/释放）

- 返回值与握手（sync/noc\_fence 状态返回、rd\_lmem/V\_S 数值返回、tag 乱序返回、指令/数据握手）

- 反压流控（读请求反压、写请求反压、VPU scalar 反压、ISTB 满反压）

- 异常与中断（指令异常、读写 LMEM 异常、block\_en 行为、中断清除）

- 性能统计与 debug（并行度、各组件拥塞数、debug 寄存器）

- CSR 配置与低功耗（creg\_cmd\_icg\_en、creg\_cmd\_tile\_rls\_en 等，IDLE/ICG）

### 1\.3 术语

|术语|含义|
|---|---|
|CMD / cmd\_sch|Command Scheduler，指令调度模块，下发 send/receive 描述符|
|IDU / inst\_disp|Inst Dispatcher Unit，指令分发单元，CMD 的上游|
|ISTB|Inst Buffer，指令存储缓存单元，采用链表存储|
|MST|Master，各功能组件，包括 GLSU、LLSU、MPU、VPU 和 NIU|
|GLSU / LLSU|Global / Local Load Store Unit，全局/本地数据搬运单元|
|MPU / VPU|Matrix / Vector Process Unit，矩阵/向量运算单元|
|NIU|Network Interface Unit，网络接口单元|
|SPAD|Scratchpad Memory，片上低延迟 SRAM，逻辑上切分为 8 块 × 4 tile|
|CIMC|Compute\-in\-Memory Cluster，存内计算簇，访问粒度为 page（4 个）|
|DRAM|全局存储，仅 GLSU 可访问，作为一整块占用|
|NICE / VNICE|按 inst\_flag 区分的两类指令，值为 1 代表 VNICE，0 代表 NICE，core 内无功能区别|
|sync|同步指令，与所有 MST 存在 structure hazard，返回 32'h1|
|noc\_fence|NOC 同步屏障，与 NOC 组件存在 structure hazard，返回 32'h1|
|xd|指令是否产生返回数据，xd=1 指令需给 inst\_disp 返回值（含 tag）|
|RAW / WAW / WAR|真数据依赖 / 输出依赖 / 反依赖；RAR 无需判断|
|tile / page|SPAD 按 tile 切分（4 个/块），CIMC 按 page 切分（4 个），hazard 以 tile/page 为粒度判断|
|TMU|Tensor Manipulation Unit，GLSU/LLSU 均可调用，GLSU 优先级更高|
|CP / CG / Bin / Cross|Coverpoint 功能覆盖点 / Coverage Group 覆盖率组 / 覆盖点取值区间 / 交叉覆盖|
|种子基线|回归时固定使用的随机种子集合|
|平台期|增加种子数覆盖率不再显著增长的拐点|

## 2\. 设计功能概述

### 2\.1 调度器职责

CMD\_SCH 位于 inst\_disp 与各功能组件之间，根据硬件资源和数据依赖关系完成指令的乱序发射，以提高 MPU、VPU、GLSU、LLSU、NIU 的硬件利用率。主要职责如下：

1. 和 inst\_disp 进行指令握手，cmd 无法接收指令时反压 inst\_disp（cmd\_valid/cmd\_ready）。

2. 和 inst\_disp 进行数据握手，inst\_disp 无法接收 xd=1 指令的 rsp 数据时反压 cmd，支持数据带原 tag 乱序返回（rsp\_valid/rsp\_ready）。

3. 接收 inst\_disp 下发的指令序列，解决指令间 RAW/WAR/WAW 冲突，并根据组件执行情况将指令发射或存储到 ISTB。

4. 对发射后的指令进行解码，将 cfg 信息发送到各个组件。

5. 存储无法发射的指令，产生对应 hazard 信息，每拍判断指令能否发射。

6. 和各组件进行 start\-done 交互，用于启动组件和接收组件结束信息。

7. 接收各组件 rd\_release 和 wr\_release 信号，用于提前释放存储资源。

### 2\.2 接口信号

CMD\_SCH 的接口按交互对象划分如下（信号名以 CDD 接口文件为准）：

|接口|交互对象|说明|
|---|---|---|
|cmd\_valid / cmd\_ready|inst\_disp|指令握手接口，cmd 满时拉低 cmd\_ready 反压|
|rsp\_valid / rsp\_ready|inst\_disp|数据握手接口，xd=1 指令返回值，支持乱序返回|
|i\_ch1\_req\_rrdy|读通路|读请求反压信号|
|i\_ch0\_req\_wrdy|写通路|写请求反压信号|
|start / start\_inst\_id / cfg|cmd → 各 MST|启动信号，每个 MST 最多拉高两拍且 inst\_id 不同，cfg 仅在 start 当拍有效|
|done\_vld / done\_inst\_id|各 MST → cmd|指令完成信号，与 inst\_id 匹配|
|rls\_vld / rls\_inst\_id|各 MST → cmd|资源释放信号，须在 done\_vld 之前或同拍拉高，与 inst\_id 匹配|
|rd\_release / wr\_release|各 MST → cmd|按 tile/page/dram 粒度的提前释放信号|
|xxx\_masked\_int|各组件 → cmd|组件中断信号，受 block\_en 控制|
|scalar / scalar\_ready|VPU → cmd|V\_S 指令标量返回值，握手传输|
|各 MST cfg 接口|cmd → 各 MST|指令解码后的配置信息|

CMD\_SCH 主要由 inst buffer（ISTB）、decode（含 slicer、sp\_inst）、scoreboard（含各 MST inst\_disp 与 hazard\_det）、dispatch、cmd\_int\_perf 五个二级模块组成。

## 3\. 功能覆盖率组与覆盖点

### 3\.1 覆盖率组总览

按 CDD 功能维度将覆盖点划分为 10 个覆盖率组（Coverage Group），每个组聚焦一类功能契约。

|CG ID|覆盖率组名称|需求 ID|覆盖点数|交叉数|目标|
|---|---|---|---|---|---|
|CG\_CMDSCHED\_ITYPE|指令类型覆盖组|Feat\-3, 28|4|2|100%|
|CG\_CMDSCHED\_INSTB|ISTB 管理覆盖组|Feat\-19|4|2|100%|
|CG\_CMDSCHED\_DEP|数据依赖覆盖组|Feat\-2, 5, 7, 10, 11\~14|4|2|100%|
|CG\_CMDSCHED\_UNIT|执行单元调度覆盖组|Feat\-1, 8, 9, 10, 15\~18, 23|6|2|100%|
|CG\_CMDSCHED\_ISSUE|发射决策覆盖组|Feat\-19|4|2|100%|
|CG\_CMDSCHED\_MEM|存储资源管理覆盖组|Feat\-6, 21, 22|6|2|100%|
|CG\_CMDSCHED\_RSP|返回值与握手覆盖组|Feat\-2, 4, 7, 20, 26, 27|7|2|100%|
|CG\_CMDSCHED\_EXCP|异常与中断覆盖组|Feat\-28, 29, 30|5|1|100%|
|CG\_CMDSCHED\_PERF|性能与 Debug 覆盖组|Feat\-31\~37, 38\~40|4|0|100%|
|CG\_CMDSCHED\_CSR|CSR 与低功耗覆盖组|Feat\-24, 25|6|0|100%|

**覆盖组之间的关系：**

```plaintext
CG_CMDSCHED_ITYPE ──┐
CG_CMDSCHED_INSTB ──┤
CG_CMDSCHED_DEP   ──┼──→ 跨组交叉：X_ISSUE_DEP_PATH（DEP×ISSUE）
CG_CMDSCHED_UNIT  ──┤            X_MEM_OCC_MST（MEM×UNIT）
CG_CMDSCHED_ISSUE ──┤            X_MEM_GRAN（MEM×DEP）
CG_CMDSCHED_MEM   ──┤
CG_CMDSCHED_RSP   ──┤
CG_CMDSCHED_EXCP  ──┘
CG_CMDSCHED_PERF / CG_CMDSCHED_CSR：独立组，按需引用
```

**每个覆盖率组内包含：**一个或多个覆盖点（coverpoint）、组内交叉（cross）、组内非法 bin 和忽略 bin。

### 3\.2 CG\_CMDSCHED\_ITYPE：指令类型覆盖组

#### 3\.2\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_ITYPE|
|需求 ID|Feat\-3：删除 rd\_csr 指令；Feat\-28：异常指令产生中断（指令字段合法性）|
|功能描述|覆盖指令分类契约：NICE/VNICE、普通功能/状态返回/数值返回、七类功能组件指令及 primitive 类型|
|采样信号|inst\_flag、inst\_func、inst\_comp、prim\_type|
|采样事件|@\(posedge clk\) iff cmd\_valid \&\& cmd\_ready|
|放置位置|cmdsched\_monitor（decode 输出侧）|
|目标|100%|

#### 3\.2\.2 覆盖点定义

##### CP\_CMDSCHED\_ITYPE\_001：指令类型（NICE/VNICE）

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ITYPE\_001|
|覆盖点名称|cp\_inst\_flag|
|采样信号|inst\_flag（1bit，1=VNICE，0=NICE）|
|Bin 数|2 normal|

```systemverilog
cp_inst_flag: coverpoint inst_flag {
  bins nice  = {0};
  bins vnice = {1};
}
```

##### CP\_CMDSCHED\_ITYPE\_002：指令功能分类

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ITYPE\_002|
|覆盖点名称|cp\_inst\_func|
|采样信号|inst\_func|
|Bin 数|3 normal|

```systemverilog
cp_inst_func: coverpoint inst_func {
  bins normal    = {INST_NORMAL};  // 普通功能指令：无需返回值
  bins state_rsp = {INST_STATE};   // 状态返回指令：sync / noc_fence，返回 32'h1
  bins value_rsp = {INST_VALUE};   // 数值返回指令：rd_lmem / V_S
}
```

##### CP\_CMDSCHED\_ITYPE\_003：功能组件分类

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ITYPE\_003|
|覆盖点名称|cp\_inst\_comp|
|采样信号|inst\_comp（decode 译码出的组件分类）|
|Bin 数|7 normal|

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

##### CP\_CMDSCHED\_ITYPE\_004：primitive 类型与指令合法性

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ITYPE\_004|
|覆盖点名称|cp\_prim\_type|
|采样信号|prim\_type（funct7/inst\_flag/xd/xs1/xs2 联合译码）|
|Bin 数|12 normal \+ 2 illegal|

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

#### 3\.2\.3 组内交叉

##### X\_CMDSCHED\_ITYPE\_001：功能分类 × 组件分类

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_ITYPE\_001|
|交叉对象|cp\_inst\_func × cp\_inst\_comp|
|目的|验证功能分类与组件分类的合法组合（普通/状态返回/数值返回分别出现在正确的组件类别）|
|Bin 数|3 normal|

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

##### X\_CMDSCHED\_ITYPE\_002：指令类型 × 功能分类

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_ITYPE\_002|
|交叉对象|cp\_inst\_flag × cp\_inst\_func|
|目的|NICE 与 VNICE 指令在 core 内无功能区别，三类功能指令均需两种类型覆盖|
|Bin 数|6 normal|

```systemverilog
X_itype_flag_func: cross cp_inst_flag, cp_inst_func;
```

#### 3\.2\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_inst\_flag\_dist|npu\_instr|nice, vnice|
|c\_inst\_func\_dist|npu\_instr|normal, state\_rsp, value\_rsp|
|c\_inst\_comp\_dist|npu\_instr|cfg, lmem, noc, glsu, llsu, mpu, vpu|
|c\_prim\_dist|npu\_instr|全部 primitive（加权）|
|c\_illegal\_inst|illegal\_seq|il\_rd\_csr, il\_reserved|

### 3\.3 CG\_CMDSCHED\_INSTB：ISTB 管理覆盖组

#### 3\.3\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_INSTB|
|需求 ID|Feat\-19：乱序发射最大查询窗口为 ISTB\_DP（1/2/4，默认 4）|
|功能描述|覆盖 ISTB 链表存储、深度参数、满反压、cfg/drv 拼接存储与插空写入|
|采样信号|instb\_valid\[DP\-1:0\]、head\_flag、tail\_flag、pre\_inst\_idx、instb\_wren、instb\_rden|
|采样事件|@\(posedge clk\) iff instb\_wren \|\| instb\_rden|
|放置位置|cmdsched\_monitor（ISTB 侧）|
|目标|100%|

#### 3\.3\.2 覆盖点定义

##### CP\_CMDSCHED\_INSTB\_001：ISTB 水位

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_INSTB\_001|
|覆盖点名称|cp\_instb\_level|
|采样信号|instb\_level（有效指令条数，DP=4 时取 0\~4）|
|Bin 数|5 normal|

```systemverilog
cp_instb_level: coverpoint instb_level {
  bins empty = {0};
  bins one   = {1};
  bins two   = {2};
  bins three = {3};
  bins full  = {4};   // 所有位置 valid=1，反压 IDU
}
```

##### CP\_CMDSCHED\_INSTB\_002：链表节点操作

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_INSTB\_002|
|覆盖点名称|cp\_instb\_chain|
|采样信号|chain\_op（链表操作类型）|
|Bin 数|6 normal|

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

##### CP\_CMDSCHED\_INSTB\_003：cfg/drv 拼接存储

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_INSTB\_003|
|覆盖点名称|cp\_instb\_cfg\_drv|
|采样信号|instb\_alloc\_mode|
|Bin 数|4 normal|

```systemverilog
cp_instb_cfg_drv: coverpoint instb_alloc_mode {
  bins cfg_only            = {ALLOC_CFG_ONLY};             // 仅 cfg 指令写入
  bins drv_only            = {ALLOC_DRV_ONLY};             // 仅 drv 指令写入
  bins cfg_then_drv_stored = {ALLOC_CFG_DRV_STORED};       // cfg+drv 拼接后一起存入 ISTB
  bins cfg_issued_drv_stor = {ALLOC_CFG_ISSUED_DRV_STORED};// cfg 已发射、后续 drv 无法发射 → 拼接存入
}
```

##### CP\_CMDSCHED\_INSTB\_004：ISTB 深度参数

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_INSTB\_004|
|覆盖点名称|cp\_instb\_dp|
|采样信号|P\_INST\_BUF\_DP（编译参数，1/2/4/8）|
|Bin 数|4 normal|

```systemverilog
cp_instb_dp: coverpoint P_INST_BUF_DP {
  bins dp1 = {1};
  bins dp2 = {2};
  bins dp4 = {4};
  bins dp8 = {8};
}
```

#### 3\.3\.3 组内交叉

##### X\_CMDSCHED\_INSTB\_001：ISTB 水位 × 链表操作

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_INSTB\_001|
|交叉对象|cp\_instb\_level × cp\_instb\_chain|
|目的|验证各水位下的链表头/尾/中间节点操作正确|
|Bin 数|6 normal|

```systemverilog
X_instb_level_chain: cross cp_instb_level, cp_instb_chain {
  bins empty_head_wr = binsof(cp_instb_level.empty) && binsof(cp_instb_chain.head_write);
  bins one_tail_wr   = binsof(cp_instb_level.one)   && binsof(cp_instb_chain.tail_write);
  bins two_tail_wr  = binsof(cp_instb_level.two)   && binsof(cp_instb_chain.tail_write);
  bins full_head_rd  = binsof(cp_instb_level.full)  && binsof(cp_instb_chain.head_read);
  bins mid_rd        = binsof(cp_instb_level.three) && binsof(cp_instb_chain.mid_read);
  bins full_refill   = binsof(cp_instb_level.full)  && binsof(cp_instb_chain.refill);
}
```

##### X\_CMDSCHED\_INSTB\_002：深度参数 × 满水位

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_INSTB\_002|
|交叉对象|cp\_instb\_dp × cp\_instb\_level\.full|
|目的|各深度参数下 ISTB 满时均能反压 IDU|
|Bin 数|4 normal|

```systemverilog
X_instb_dp_full: cross cp_instb_dp, cp_instb_level {
  bins dp_full = binsof(cp_instb_dp) && binsof(cp_instb_level.full);
}
```

#### 3\.3\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_instb\_dp|npu\_instr（参数遍历）|dp1, dp2, dp4, dp8|
|c\_instb\_fill|instb\_fill\_seq|full, two\_tail\_wr, dp\_full|
|c\_cfg\_drv\_pair|instb\_fill\_seq|cfg\_then\_drv\_stored, cfg\_issued\_drv\_stor|
|c\_chain\_seq|instb\_chain\_seq|head/tail/mid 读写、refill|

### 3\.4 CG\_CMDSCHED\_DEP：数据依赖覆盖组

#### 3\.4\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_DEP|
|需求 ID|Feat\-2（sync hazard）、Feat\-5（lmem vs LLSU）、Feat\-7（noc\_fence）、Feat\-10（同组件双指令）、Feat\-11\~14（2\~5 组件 data hazard）|
|功能描述|覆盖 RAW/WAW/WAR 依赖、tile/page/dram 三种判断粒度、2\~5 组件 hazard 范围及各类 structure hazard|
|采样信号|wmem\_alrdy、rmem\_alrdy、wmem\_will、rmem\_will、dependency\_ready、struct\_hazard|
|采样事件|@\(posedge clk\) iff 指令发射或存入 ISTB|
|放置位置|cmdsched\_scoreboard\_monitor|
|目标|100%|

#### 3\.4\.2 覆盖点定义

##### CP\_CMDSCHED\_DEP\_001：依赖类型

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_DEP\_001|
|覆盖点名称|cp\_hazard\_type|
|采样信号|hazard\_type（由 raw/war/waw 信号推导）|
|Bin 数|4 normal|

```systemverilog
cp_hazard_type: coverpoint hazard_type {
  bins no_dep = {NONE};
  bins raw    = {RAW};   // |(wmem_alrdy & rmem_will)
  bins waw    = {WAW};   // |(wmem_alrdy & wmem_will)
  bins war    = {WAR};   // |(rmem_alrdy & wmem_will)
}
```

##### CP\_CMDSCHED\_DEP\_002：依赖判断粒度

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_DEP\_002|
|覆盖点名称|cp\_hazard\_gran|
|采样信号|hazard\_gran|
|Bin 数|3 normal|

```systemverilog
cp_hazard_gran: coverpoint hazard_gran {
  bins tile  = {GRAN_TILE};  // SPAD tile 粒度（8 SPAD × 4 tile）
  bins page  = {GRAN_PAGE};  // CIMC page 粒度（4 page）
  bins dram  = {GRAN_DRAM};  // DRAM 整块粒度（仅 GLSU）
}
```

##### CP\_CMDSCHED\_DEP\_003：hazard 范围（组件数）

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_DEP\_003|
|覆盖点名称|cp\_hazard\_scope|
|采样信号|hazard\_scope（产生依赖的组件数）|
|Bin 数|5 normal|

```systemverilog
cp_hazard_scope: coverpoint hazard_scope {
  bins same_mst   = {1};  // 同组件两条指令间依赖
  bins two_mst    = {2};  // Feat-11：任意两组件
  bins three_mst  = {3};  // Feat-12：任意三组件
  bins four_mst   = {4};  // Feat-13：任意四组件
  bins five_mst   = {5};  // Feat-14：五组件
}
```

##### CP\_CMDSCHED\_DEP\_004：structure hazard 类型

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_DEP\_004|
|覆盖点名称|cp\_struct\_hazard|
|采样信号|struct\_hazard|
|Bin 数|5 normal|

```systemverilog
cp_struct_hazard: coverpoint struct_hazard {
  bins sync_all      = {SHT_SYNC_ALL};    // sync 与所有 MST 存在 structure hazard
  bins noc_fence     = {SHT_NOC_FENCE};   // noc_fence 与 NOC 存在 structure hazard
  bins lmem_llsu     = {SHT_LMEM_LLSU};   // wr/rd_lmem 与 LLSU 指令存在 structure hazard
  bins niu_dst_single= {SHT_NIU_DST};     // NIU 最多接收 1 条 noc_dst_drv
  bins niu_store_dual= {SHT_NIU_STORE};   // NIU 不能同时下发两条 store
}
```

#### 3\.4\.3 组内交叉

##### X\_CMDSCHED\_DEP\_001：依赖类型 × 判断粒度

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_DEP\_001|
|交叉对象|cp\_hazard\_type × cp\_hazard\_gran|
|目的|RAW/WAW/WAR 在 tile/page/dram 各粒度均被覆盖；RAR 无需判断|
|Bin 数|9 normal|

```systemverilog
X_dep_gran: cross cp_hazard_type, cp_hazard_gran {
  ignore_bins rar = binsof(cp_hazard_type.no_dep) && binsof(cp_hazard_gran);
  // RAR（多组件同读）不产生依赖阻塞
}
```

##### X\_CMDSCHED\_DEP\_002：依赖类型 × 组件数

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_DEP\_002|
|交叉对象|cp\_hazard\_type × cp\_hazard\_scope|
|目的|覆盖任意 2\~5 个组件间的 RAW/WAW/WAR 组合|
|Bin 数|12 normal|

```systemverilog
X_dep_scope: cross cp_hazard_type, cp_hazard_scope {
  ignore_bins no_dep_multi = binsof(cp_hazard_type.no_dep) &&
                             binsof(cp_hazard_scope) intersect {2, 3, 4, 5};
}
```

#### 3\.4\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_dep\_dist|npu\_instr|no\_dep, raw, waw, war|
|c\_raw / c\_waw / c\_war|npu\_stream|X\_dep\_gran 各粒度|
|c\_hazard\_scope\_2\~5|npu\_stream|two\_mst \~ five\_mst|
|c\_same\_mst\_pair|npu\_stream|same\_mst|
|c\_lmem\_llsu\_conflict|conflict\_seq|lmem\_llsu|
|c\_sync\_barrier / c\_noc\_fence\_barrier|barrier\_seq|sync\_all, noc\_fence|
|c\_niu\_dst / c\_niu\_store|niu\_seq|niu\_dst\_single, niu\_store\_dual|

### 3\.5 CG\_CMDSCHED\_UNIT：执行单元调度覆盖组

#### 3\.5\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_UNIT|
|需求 ID|Feat\-1（组件配置和启动）、Feat\-8/9（NIU/GLSU load\-store 并行）、Feat\-10（同组件双指令）、Feat\-15\~18（2\~5 组件并行）、Feat\-23（TMU 竞争）|
|功能描述|覆盖 5 个 MST 的调度、双指令槽、并行执行范围、load\-store 并行与 TMU 竞争仲裁|
|采样信号|mst\_id、mst\_slot\_busy\[1:0\]、paral\_scope、tmu\_owner|
|采样事件|@\(posedge clk\) iff start 拉高或并行度变化|
|放置位置|cmdsched\_dispatch\_monitor|
|目标|100%|

#### 3\.5\.2 覆盖点定义

##### CP\_CMDSCHED\_UNIT\_001：执行单元（MST）

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_UNIT\_001|
|覆盖点名称|cp\_mst\_id|
|采样信号|mst\_id|
|Bin 数|5 normal|

```systemverilog
cp_mst_id: coverpoint mst_id {
  bins glsu = {MST_GLSU};
  bins llsu = {MST_LLSU};
  bins mpu  = {MST_MPU};
  bins vpu  = {MST_VPU};
  bins niu  = {MST_NIU};
}
```

##### CP\_CMDSCHED\_UNIT\_002：MST 指令槽占用

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_UNIT\_002|
|覆盖点名称<br>|cp\_mst\_slot|
|采样信号|mst\_slot\_busy\[1:0\]|
|Bin 数|4 normal|

```systemverilog
cp_mst_slot: coverpoint mst_slot_busy {
  bins slot0_only = {2'b01};
  bins slot1_only = {2'b10};
  bins both       = {2'b11};  // 两条指令并行执行（无 data hazard）
  bins empty      = {2'b00};
}
```

##### CP\_CMDSCHED\_UNIT\_003：并行执行范围

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_UNIT\_003|
|覆盖点名称|cp\_paral\_scope|
|采样信号|paral\_scope（同拍执行的组件数）|
|Bin 数|4 normal|

```systemverilog
cp_paral_scope: coverpoint paral_scope {
  bins two_mst   = {2};  // Feat-15：任意两组件并行
  bins three_mst = {3};  // Feat-16
  bins four_mst  = {4};  // Feat-17
  bins five_mst  = {5};  // Feat-18
}
```

##### CP\_CMDSCHED\_UNIT\_004：load/store 并行

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_UNIT\_004|
|覆盖点名称|cp\_ls\_parallel|
|采样信号|ls\_parallel（load 与 store 并行状态）|
|Bin 数|4 normal|

```systemverilog
cp_ls_parallel: coverpoint ls_parallel {
  bins glsu_ls_par  = {GLSU_LS_PAR};   // Feat-9：GLSU 内部 load 和 store 并行
  bins niu_ls_par   = {NIU_LS_PAR};    // Feat-8：NIU 内部 load 和 store 并行
  bins glsu_ls_ser  = {GLSU_LS_SER};   // 有 data hazard 时串行
  bins niu_ls_ser   = {NIU_LS_SER};
}
```

##### CP\_CMDSCHED\_UNIT\_005：TMU 竞争仲裁

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_UNIT\_005|
|覆盖点名称|cp\_tmu\_arb|
|采样信号|tmu\_owner / tmu\_req|
|Bin 数|4 normal|

```systemverilog
cp_tmu_arb: coverpoint tmu_arb {
  bins glsu_tmu        = {TMU_GLSU};         // GLSU 单独占用 TMU
  bins llsu_tmu        = {TMU_LLSU};         // LLSU 单独占用 TMU
  bins glsu_pri_contend= {TMU_GLSU_PRI};     // Feat-23：同时抢占时 GLSU 优先
  bins llsu_wait       = {TMU_LLSU_WAIT};    // LLSU 等待 TMU 释放
}
```

##### CP\_CMDSCHED\_UNIT\_006：第三条同组件指令阻塞

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_UNIT\_006|
|覆盖点名称|cp\_third\_inst\_blocked|
|需求 ID|Feat\-10（同组件两条指令无 structure hazard 处理：再下一条同组件指令会被阻塞）|
|采样信号|mst\_slot\_busy\[1:0\]、issue\_path、同组件连续指令序号|
|Bin 数|2 normal|

```systemverilog
cp_third_inst_blocked: coverpoint third_inst_behavior {
  bins third_blocked = {THIRD_BLOCKED};  // Feat-10：前两条占满双槽时，第三条同组件指令被阻塞（存入 ISTB）
  bins third_issued  = {THIRD_ISSUED};   // 前两条执行完成释放槽位后，第三条不被阻塞（直发）
}
```

#### 3\.5\.3 组内交叉

##### X\_CMDSCHED\_UNIT\_001：MST × 指令槽

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_UNIT\_001|
|交叉对象|cp\_mst\_id × cp\_mst\_slot|
|目的|每个 MST 的 inst0/inst1 双指令槽均被覆盖，验证 Feat\-10 同组件无 structure hazard 处理|
|Bin 数|5 normal|

```systemverilog
X_unit_slot: cross cp_mst_id, cp_mst_slot {
  bins niu_both = binsof(cp_mst_id.niu) && binsof(cp_mst_slot.both);
  // 注意：NIU 不能同时两条 store，若出现即视为场景错误（配合断言）
}
```

##### X\_CMDSCHED\_UNIT\_002：MST × 并行范围

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_UNIT\_002|
|交叉对象|cp\_mst\_id × cp\_paral\_scope|
|目的|验证各 MST 参与 2\~5 组件并行执行|
|Bin 数|20 normal|

```systemverilog
X_unit_paral: cross cp_mst_id, cp_paral_scope;
```

#### 3\.5\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_mst\_dist|npu\_instr|glsu, llsu, mpu, vpu, niu|
|c\_mst\_dual|npu\_stream|both, X\_unit\_slot|
|c\_multi\_parallel\_2\~5|parallel\_seq|two\_mst \~ five\_mst, X\_unit\_paral|
|c\_ls\_pair\_seq|ls\_parallel\_seq|glsu\_ls\_par, niu\_ls\_par|
|c\_tmu\_contend|tmu\_seq|glsu\_pri\_contend, llsu\_wait|
|c\_third\_inst\_blocked|third\_inst\_seq|third\_blocked, third\_issued|

### 3\.6 CG\_CMDSCHED\_ISSUE：发射决策覆盖组

#### 3\.6\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_ISSUE|
|需求 ID|Feat\-19（乱序发射窗口与发射策略）|
|功能描述|覆盖指令发射路径（直发/ISTB 存储/ISTB 发射）、发射优先级、start\-done\-rls 时序与 MST 可用资源判定|
|采样信号|issue\_path、dependency\_ready、mst\_avail、start\_inst\_id、done\_vld、rls\_vld|
|采样事件|@\(posedge clk\)|
|放置位置|cmdsched\_scoreboard\_monitor|
|目标|100%|

#### 3\.6\.2 覆盖点定义

##### CP\_CMDSCHED\_ISSUE\_001：发射路径

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ISSUE\_001|
|覆盖点名称|cp\_issue\_path|
|采样信号|issue\_path|
|Bin 数|4 normal|

```systemverilog
cp_issue_path: coverpoint issue_path {
  bins direct      = {ISSUE_DIRECT};    // 无冲突，新指令直接发射到 MST
  bins istb_stored = {ISSUE_STORED};    // 有冲突，指令存入 ISTB
  bins istb_issued = {ISSUE_ISTB_ISSUE};// ISTB 中指令满足条件后发射
  bins backpressure= {ISSUE_BACKPR};    // ISTB 满 / MST 满，反压 IDU
}
```

##### CP\_CMDSCHED\_ISSUE\_002：发射优先级

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ISSUE\_002|
|覆盖点名称|cp\_issue\_priority|
|采样信号|issue\_priority|
|Bin 数|2 normal|

```systemverilog
cp_issue_priority: coverpoint issue_priority {
  bins new_first    = {PRIO_NEW_INST};  // 同一 MST 下，新指令优先于 ISTB 中指令发射
  bins istb_issued  = {PRIO_ISTB};      // 无新指令时，ISTB 指令发射
}
```

##### CP\_CMDSCHED\_ISSUE\_003：start\-done\-rls 时序

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ISSUE\_003|
|覆盖点名称|cp\_start\_done\_seq|
|采样信号|start\_inst\_id、done\_vld、done\_inst\_id、rls\_vld、rls\_inst\_id|
|Bin 数|5 normal|

```systemverilog
cp_start_done_seq: coverpoint start_done_seq {
  bins start0_done0     = {SD_S0_D0};  // 先启动先 done（默认顺序）
  bins start1_done1     = {SD_S1_D1};
  bins start1_done0     = {SD_S1_D0};  // 后启动先 done（仅 GLSU/NIU load-store 并行）
  bins rls_before_done  = {SD_RLS_BEFORE};  // rls_vld 先于 done_vld
  bins rls_same_done    = {SD_RLS_SAME};    // rls_vld 与 done_vld 同拍
}
```

##### CP\_CMDSCHED\_ISSUE\_004：MST 可用资源

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_ISSUE\_004|
|覆盖点名称|cp\_mst\_avail|
|采样信号|mst\_avail（credit\-cnt 状态）|
|Bin 数|4 normal|

```systemverilog
cp_mst_avail: coverpoint mst_avail {
  bins avail0       = {2'b00};  // 无指令在飞，可接收 2 条
  bins avail1       = {2'b01};  // 1 条在飞，可再接收 1 条
  bins full         = {2'b11};  // 2 条在飞，同组件指令被阻塞
  bins niu_dst_full = {2'b10};  // NIU 中 noc_dst 指令已占用（最多 1 条）
}
```

#### 3\.6\.3 组内交叉

##### X\_CMDSCHED\_ISSUE\_001：依赖判定 × 发射路径

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_ISSUE\_001|
|交叉对象|cp\_hazard\_type（CG\_CMDSCHED\_DEP）× cp\_issue\_path|
|目的|验证 dependency\_ready 与发射/存储决策的对应关系：无依赖直发、有依赖存储、依赖消除后发射|
|Bin 数|6 normal|

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

##### X\_CMDSCHED\_ISSUE\_002：MST 可用资源 × 发射路径

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_ISSUE\_002|
|交叉对象|cp\_mst\_avail × cp\_issue\_path|
|目的|验证 can\_issue = dependency\_ready \&\& mst\_avail：资源满时即使无依赖也不发射|
|Bin 数|6 normal|

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

#### 3\.6\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_issue\_direct|npu\_stream|direct, no\_dep\_direct|
|c\_issue\_stall|npu\_stream|istb\_stored, raw\_stored|
|c\_issue\_backpressure|instb\_fill\_seq|backpressure, full\_backpress|
|c\_start\_done\_seq|start\_done\_seq|start0\_done0 \~ start1\_done0|
|c\_rls\_timing|start\_done\_seq|rls\_before\_done, rls\_same\_done|

### 3\.7 CG\_CMDSCHED\_MEM：存储资源管理覆盖组

#### 3\.7\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_MEM|
|需求 ID|Feat\-6（CIMC 仅 2x2）、Feat\-21（多组件访问同一 SPAD）、Feat\-22（按 tile 切分 SPAD）|
|功能描述|覆盖 SPAD tile / CIMC page / DRAM 的占用、释放与冲突，多组件共享 SPAD 的 tile 粒度管理|
|采样信号|wtile\_ongoing\_total、rtile\_ongoing\_total、wpage\_ongoing\_total、rpage\_ongoing\_total、wdram/rdram\_ongoing\_total、rd\_release、wr\_release|
|采样事件|@\(posedge clk\) iff 占用或释放状态变化|
|放置位置|cmdsched\_scoreboard\_monitor|
|目标|100%|

#### 3\.7\.2 覆盖点定义

##### CP\_CMDSCHED\_MEM\_001：SPAD tile 占用/释放

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_MEM\_001|
|覆盖点名称|cp\_spad\_tile\_occ|
|采样信号|wtile/rtile 状态|
|Bin 数|4 normal|

```systemverilog
cp_spad_tile_occ: coverpoint spad_tile_occ {
  bins tile_alloc      = {TILE_ALLOC};       // 指令发射后占用 tile
  bins tile_release    = {TILE_RELEASE};     // done 后释放全部占用 tile
  bins tile_partial_rls= {TILE_PARTIAL_RLS}; // 按 wr_release/rd_release 提前释放部分 tile
  bins tile_conflict   = {TILE_CONFLICT};    // 与在飞指令 tile 冲突，产生 hazard
}
```

##### CP\_CMDSCHED\_MEM\_002：CIMC page 占用/释放

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_MEM\_002|
|覆盖点名称|cp\_cimc\_page\_occ|
|采样信号|wpage/rpage 状态|
|Bin 数|4 normal|

```systemverilog
cp_cimc_page_occ: coverpoint cimc_page_occ {
  bins page_alloc   = {PAGE_ALLOC};
  bins page_release = {PAGE_RELEASE};
  bins page_conflict= {PAGE_CONFLICT};
  bins cimc_2x2     = {CIMC_2X2};   // Feat-6：仅支持 2x2 形状，1x4 已删除
}
```

##### CP\_CMDSCHED\_MEM\_003：DRAM 占用/释放

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_MEM\_003|
|覆盖点名称|cp\_dram\_occ|
|采样信号|wdram/rdram 状态|
|Bin 数|3 normal|

```systemverilog
cp_dram_occ: coverpoint dram_occ {
  bins dram_alloc   = {DRAM_ALLOC};    // GLSU 访问 DRAM 时整块占用
  bins dram_release = {DRAM_RELEASE};
  bins dram_whole   = {DRAM_WHOLE};    // DRAM 作为一整块存储，不分片
}
```

##### CP\_CMDSCHED\_MEM\_004：多组件共享 SPAD

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_MEM\_004|
|覆盖点名称|cp\_multi\_mst\_spad|
|采样信号|multi\_mst\_spad（同拍访问同一 SPAD 的组件数及读写方向）|
|Bin 数|5 normal|

```systemverilog
cp_multi_mst_spad: coverpoint multi_mst_spad {
  bins mst2_same_spad = {2};  // Feat-21：两个组件无冲突访问同一 SPAD（tile 不重叠）
  bins mst3_same_spad = {3};
  bins mst4_same_spad = {4};
  bins mst5_same_spad = {5};
  bins rar_multi_read = {RAR}; // 多组件同读同一 SPAD，无依赖（RAR 不阻塞）
}
```

##### CP\_CMDSCHED\_MEM\_005：资源释放来源

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_MEM\_005|
|覆盖点名称|cp\_mem\_release\_src|
|采样信号|release\_src|
|Bin 数|3 normal|

```systemverilog
cp_mem_release_src: coverpoint mem_release_src {
  bins done_release    = {RLS_DONE};      // 指令 done 后释放
  bins rls_release     = {RLS_PRE};       // rd_release/wr_release 提前释放
  bins tile_rls_en_off = {RLS_DISABLED};  // creg_cmd_tile_rls_en=0，释放逻辑无效
}
```

##### CP\_CMDSCHED\_MEM\_006：SPAD tile 地址空间映射

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_MEM\_006|
|覆盖点名称|cp\_spad\_tile\_map|
|需求 ID|Feat\-22（TILE\_NUM=4、SPAD\_NUM=8，按 tile 切分占用/释放）|
|采样信号|\{spad\_id\[2:0\], tile\_id\[1:0\]\}（8 SPAD × 4 tile = 32 个组合）|
|Bin 数|32 normal|

```systemverilog
cp_spad_tile_map: coverpoint {spad_id, tile_id} {
  bins tile_00  .. tile_31 = {[0:31]};  // Feat-22：32 个 tile 组合均需发生占用/释放
}
```

#### 3\.7\.3 组内交叉

##### X\_CMDSCHED\_MEM\_001：SPAD tile 状态 × MST

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_MEM\_001|
|交叉对象|cp\_spad\_tile\_occ × cp\_mst\_id（CG\_CMDSCHED\_UNIT）|
|目的|验证各 MST 的 tile 占用与释放（含 wtile\_busy\_mst/rtile\_busy\_mst 寄存器更新）|
|Bin 数|20 normal|

```systemverilog
X_mem_occ_mst: cross cp_spad_tile_occ, cp_mst_id;
```

##### X\_CMDSCHED\_MEM\_002：依赖粒度 × 多组件共享

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_MEM\_002|
|交叉对象|cp\_hazard\_gran（CG\_CMDSCHED\_DEP）× cp\_multi\_mst\_spad|
|目的|验证不同存储资源上多组件共享与冲突判定（tile/page/dram）|
|Bin 数|9 normal|

```systemverilog
X_mem_gran: cross cp_hazard_gran, cp_multi_mst_spad;
```

#### 3\.7\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_spad\_tile\_addr|npu\_instr|tile\_alloc, tile\_conflict|
|c\_cimc\_page\_addr|npu\_instr|page\_alloc, page\_conflict, cimc\_2x2|
|c\_dram\_addr|npu\_instr|dram\_alloc, dram\_whole|
|c\_multi\_mst\_spad|parallel\_seq|mst2\~5\_same\_spad, rar\_multi\_read|
|c\_release\_early|release\_seq|rls\_release, tile\_partial\_rls|
|c\_tile\_rls\_en|csr\_seq|tile\_rls\_en\_off|
|c\_tile\_map\_spread|tile\_map\_seq|tile\_00 \~ tile\_31|

### 3\.8 CG\_CMDSCHED\_RSP：返回值与握手覆盖组

#### 3\.8\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_RSP|
|需求 ID|Feat\-2（sync 返回）、Feat\-4（CPU 读写 LMEM）、Feat\-7（noc\_fence 返回）、Feat\-20（多 xd=1 指令乱序返回）、Feat\-26/27（读写反压）|
|功能描述|覆盖状态/数值返回指令的返回值、tag 乱序、rsp\_fifo 优先级、指令/数据握手与反压|
|采样信号|rsp\_type、rsp\_data、rsp\_tag、cmd\_valid/cmd\_ready、rsp\_valid/rsp\_ready、i\_ch1\_req\_rrdy、i\_ch0\_req\_wrdy、scalar\_ready|
|采样事件|@\(posedge clk\) iff rsp\_valid 或握手反压|
|放置位置|cmdsched\_sp\_inst\_monitor|
|目标|100%|

#### 3\.8\.2 覆盖点定义

##### CP\_CMDSCHED\_RSP\_001：返回指令类型

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_RSP\_001|
|覆盖点名称|cp\_rsp\_type|
|采样信号|rsp\_type|
|Bin 数|4 normal|

```systemverilog
cp_rsp_type: coverpoint rsp_type {
  bins sync_rsp      = {RSP_SYNC};     // 等待所有 MST 完成后返回 32'h1
  bins noc_fence_rsp = {RSP_NOC_FENCE};// 等待所有 NOC 指令完成后返回 32'h1
  bins rd_lmem_rsp   = {RSP_RD_LMEM};  // 读 SPAD 数据 + tag
  bins v_s_rsp       = {RSP_V_S};      // VPU scalar + tag
}
```

##### CP\_CMDSCHED\_RSP\_002：返回值数据

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_RSP\_002|
|覆盖点名称|cp\_rsp\_data|
|采样信号|rsp\_data|
|Bin 数|3 normal|

```systemverilog
cp_rsp_data: coverpoint rsp_data {
  bins state_1     = {32'h1};    // sync / noc_fence 状态返回值
  bins lmem_data   = {[32'h2:32'hFFFF_FFFF]};  // rd_lmem 读回的 SPAD 数据
  bins scalar_data = {[32'h2:32'hFFFF_FFFF]};  // V_S 返回的 VPU 标量
}
```

##### CP\_CMDSCHED\_RSP\_003：tag 与乱序返回

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_RSP\_003|
|覆盖点名称|cp\_rsp\_tag|
|采样信号|rsp\_tag、下发顺序|
|Bin 数|3 normal|

```systemverilog
cp_rsp_tag: coverpoint rsp_tag_mode {
  bins tag_match  = {TAG_IN_ORDER};   // 返回顺序与下发一致，tag 匹配
  bins tag_ooot   = {TAG_OUT_OF_ORDER};// Feat-20：多 xd=1 指令乱序返回，数据带原 tag
  bins multi_xd   = {MULTI_XD};        // 同拍多条 xd=1 指令在飞
}
```

##### CP\_CMDSCHED\_RSP\_004：rsp\_fifo 优先级

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_RSP\_004|
|覆盖点名称|cp\_rsp\_prio|
|采样信号|rsp\_prio（出队顺序）|
|Bin 数|4 normal|

```systemverilog
cp_rsp_prio: coverpoint rsp_prio {
  bins scalar_prio = {PRIO_SCALAR};  // scalar_fifo 最高
  bins lmem_prio   = {PRIO_LMEM};    // 其次 lmem_fifo
  bins fence_prio  = {PRIO_FENCE};   // 再次 fence_fifo
  bins sync_prio   = {PRIO_SYNC};    // 最后 sync_fifo
}
```

##### CP\_CMDSCHED\_RSP\_005：指令/数据握手

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_RSP\_005|
|覆盖点名称|cp\_cmd\_handshake|
|采样信号|cmd\_valid/cmd\_ready/rsp\_valid/rsp\_ready|
|Bin 数|4 normal|

```systemverilog
cp_cmd_handshake: coverpoint handshake_mode {
  bins cmd_hs_ok     = {HS_CMD_OK};    // cmd_valid && cmd_ready，指令握手成功
  bins cmd_ready_low = {HS_CMD_BP};    // cmd_ready 拉低，数据保持直到 ready 拉高
  bins rsp_hs_ok     = {HS_RSP_OK};    // rsp_valid && rsp_ready，数据握手成功
  bins rsp_ready_low = {HS_RSP_BP};    // rsp_ready 拉低，反压返回数据
}
```

##### CP\_CMDSCHED\_RSP\_006：反压来源

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_RSP\_006|
|覆盖点名称|cp\_backpressure|
|采样信号|i\_ch1\_req\_rrdy、i\_ch0\_req\_wrdy、scalar\_ready、istb\_full|
|Bin 数|4 normal|

```systemverilog
cp_backpressure: coverpoint backpressure_src {
  bins rd_bp    = {BP_READ};    // Feat-26：读请求反压（i_ch1_req_rrdy 拉低）
  bins wr_bp    = {BP_WRITE};   // Feat-27：写请求反压（i_ch0_req_wrdy 拉低）
  bins scalar_bp= {BP_SCALAR};  // VPU scalar 返回反压（scalar_ready 拉低）
  bins istb_bp  = {BP_ISTB};    // ISTB 满，反压 IDU 指令下发
}
```

##### CP\_CMDSCHED\_RSP\_007：wr\_lmem 读改写（RMW）

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_RSP\_007|
|覆盖点名称|cp\_wr\_lmem\_rmw|
|需求 ID|Feat\-4（wr\_lmem\_drv：先读 SPAD 地址数据、数据替换后写回原地址）|
|采样信号|wr\_lmem\_rmw（读\-改写\-写回行为状态）|
|Bin 数|2 normal|

```systemverilog
cp_wr_lmem_rmw: coverpoint wr_lmem_rmw {
  bins rmw_performed = {RMW_DONE};    // Feat-4：先读后写回完成（RMW 顺序正确）
  bins rmw_blocked   = {RMW_BLOCKED}; // RMW 被反压/异常打断后恢复
  // 注：RMW 替换后的数据正确性由 scoreboard 比对验证（非覆盖点职责）
}
```

#### 3\.8\.3 组内交叉

##### X\_CMDSCHED\_RSP\_001：返回类型 × fifo 优先级

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_RSP\_001|
|交叉对象|cp\_rsp\_type × cp\_rsp\_prio|
|目的|多类返回数据同时就绪时，按 scalar \> lmem \> fence \> sync 优先级出队|
|Bin 数|4 normal|

```systemverilog
X_rsp_prio: cross cp_rsp_type, cp_rsp_prio {
  bins v_s_scalar = binsof(cp_rsp_type.v_s_rsp)       && binsof(cp_rsp_prio.scalar_prio);
  bins lmem_prio  = binsof(cp_rsp_type.rd_lmem_rsp)   && binsof(cp_rsp_prio.lmem_prio);
  bins fence_prio = binsof(cp_rsp_type.noc_fence_rsp) && binsof(cp_rsp_prio.fence_prio);
  bins sync_prio  = binsof(cp_rsp_type.sync_rsp)      && binsof(cp_rsp_prio.sync_prio);
}
```

##### X\_CMDSCHED\_RSP\_002：返回类型 × 乱序

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_RSP\_002|
|交叉对象|cp\_rsp\_type × cp\_rsp\_tag|
|目的|各返回类型均需覆盖 tag 乱序返回场景|
|Bin 数|4 normal|

```systemverilog
X_rsp_tag: cross cp_rsp_type, cp_rsp_tag {
  bins ooo = binsof(cp_rsp_tag.tag_ooot) &&
             binsof(cp_rsp_type) intersect {RSP_SYNC, RSP_NOC_FENCE, RSP_RD_LMEM, RSP_V_S};
}
```

#### 3\.8\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_xd1\_seq|xd1\_seq|multi\_xd, tag\_ooot|
|c\_rsp\_priority\_seq|xd1\_seq|X\_rsp\_prio 各 bin|
|c\_tag\_out\_of\_order|xd1\_seq|tag\_ooot, ooo|
|c\_backpressure\_seq|bp\_seq|rd\_bp, wr\_bp, scalar\_bp, istb\_bp|
|c\_wr\_lmem\_rmw|rsp\_rmw\_seq|rmw\_performed, rmw\_blocked|

### 3\.9 CG\_CMDSCHED\_EXCP：异常与中断覆盖组

#### 3\.9\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_EXCP|
|需求 ID|Feat\-28（异常指令中断）、Feat\-29（读写非 SPAD 地址中断）、Feat\-30（lmem\_drv 与 LLSU 同时工作中断）|
|功能描述|覆盖 cmd\_int\[0\]/cmd\_int\[1\] 中断触发、block\_en 行为、中断清除与 excep\_en 屏蔽|
|采样信号|cmd\_int\[31:0\]、creg\_cmd\_block\_en、creg\_cmd\_excep\_en、中断清除操作|
|采样事件|@\(posedge clk\) iff 指令译码或中断状态变化|
|放置位置|cmdsched\_int\_monitor|
|目标|100%|

#### 3\.9\.2 覆盖点定义

##### CP\_CMDSCHED\_EXCP\_001：中断类型

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_EXCP\_001|
|覆盖点名称|cp\_int\_type|
|采样信号|cmd\_int\[1:0\]|
|Bin 数|3 normal \+ 1 illegal|

```systemverilog
cp_int_type: coverpoint cmd_int[1:0] {
  bins no_int     = {2'b00};
  bins cmd_int0   = {2'b01};  // 指令异常：任一字段与指令集不一致（funct7/inst_flag/xd/xs1/xs2）
  bins cmd_int1   = {2'b10};  // 读写 LMEM 异常：wr_lmem_drv/rd_lmem_drv 指向 CIMC
  illegal_bins int2 = {2'b11};
}
// cmd_int[31:2] 为保留中断，作为 illegal_bins 处理
```

##### CP\_CMDSCHED\_EXCP\_002：block\_en 行为

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_EXCP\_002|
|覆盖点名称|cp\_block\_en|
|采样信号|creg\_cmd\_block\_en 与收发状态|
|Bin 数|2 normal|

```systemverilog
cp_block_en: coverpoint block_behavior {
  bins block_stop     = {BLOCK_STOP};     // block_en=1：中断后停止收发上下游指令
  bins block_continue = {BLOCK_CONTINUE}; // block_en=0：继续正常收发
}
```

##### CP\_CMDSCHED\_EXCP\_003：中断清除

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_EXCP\_003|
|覆盖点名称|cp\_int\_clear|
|采样信号|中断清除方式|
|Bin 数|3 normal|

```systemverilog
cp_int_clear: coverpoint int_clear {
  bins reset_clear   = {CLR_RESET};  // 复位清中断（建议致命中断）
  bins wr1_clear     = {CLR_WR1};    // core_reg 写 1 清中断（建议非致命）
  bins rec_after_clr = {CLR_RECOVER};// 清中断后 block 模式恢复正常收发
}
```

##### CP\_CMDSCHED\_EXCP\_004：excep\_en 屏蔽

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_EXCP\_004|
|覆盖点名称|cp\_excep\_en|
|采样信号|creg\_cmd\_excep\_en 与中断产生|
|Bin 数|2 normal|

```systemverilog
cp_excep_en: coverpoint excep_behavior {
  bins en_on  = {EXCEP_ON};  // excep_en=1：异常检测有效，致命中断产生 done 停止
  bins en_off = {EXCEP_OFF}; // excep_en=0：屏蔽检测，不产生 done，功能无法保证
}
```

##### CP\_CMDSCHED\_EXCP\_005：中断现场信息保存

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_EXCP\_005|
|覆盖点名称|cp\_int\_info\_save|
|需求 ID|Feat\-28（中断现场：首次中断后保存 inst0/inst1 指令信息，后续不再覆盖）|
|采样信号|int\_info\_save（现场保存状态）、core\_reg 中断信息寄存器读回|
|Bin 数|3 normal|

```systemverilog
cp_int_info_save: coverpoint int_info_save {
  bins first_int_saved   = {INFO_FIRST_SAVED};    // 首次中断现场被保存
  bins later_not_saved   = {INFO_LATER_NOT_SAVED};// 后续中断不再覆盖首次现场
  bins info_readable     = {INFO_READABLE};       // 通过 core_reg 可读回现场（inst0/inst1 序列 id、funct7/inst_flag/xd/xs1/xs2）
}
```

#### 3\.9\.3 组内交叉

##### X\_CMDSCHED\_EXCP\_001：中断类型 × block 行为

|项目|内容|
|---|---|
|交叉 ID|X\_CMDSCHED\_EXCP\_001|
|交叉对象|cp\_int\_type × cp\_block\_en|
|目的|两类致命中断在 block\_en 两种配置下的行为均被覆盖|
|Bin 数|4 normal|

```systemverilog
X_excp_block: cross cp_int_type, cp_block_en {
  bins int0_stop = binsof(cp_int_type.cmd_int0) && binsof(cp_block_en.block_stop);
  bins int0_cont = binsof(cp_int_type.cmd_int0) && binsof(cp_block_en.block_continue);
  bins int1_stop = binsof(cp_int_type.cmd_int1) && binsof(cp_block_en.block_stop);
  bins int1_cont = binsof(cp_int_type.cmd_int1) && binsof(cp_block_en.block_continue);
}
```

#### 3\.9\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_illegal\_inst|illegal\_seq|cmd\_int0|
|c\_non\_spad\_addr|illegal\_seq|cmd\_int0（非 SPAD 读写）|
|c\_cimc\_lmem\_addr|illegal\_seq|cmd\_int1|
|c\_lmem\_llsu\_conflict|conflict\_seq|Feat\-30 中断场景|
|c\_block\_en\_cfg|csr\_seq|block\_stop, block\_continue|
|c\_int\_clear\_seq|int\_clear\_seq|reset\_clear, wr1\_clear, rec\_after\_clr|
|c\_int\_info\_save|int\_info\_seq|first\_int\_saved, later\_not\_saved, info\_readable|

### 3\.10 CG\_CMDSCHED\_PERF：性能与 Debug 覆盖组

#### 3\.10\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_PERF|
|需求 ID|Feat\-31\~35（各组件 ISTB 拥塞统计）、Feat\-36/37（并行度统计）、Feat\-38\~40（debug 寄存器）|
|功能描述|覆盖性能统计使能、并行度统计、各 MST 拥塞计数与 debug 寄存器可读性|
|采样信号|creg\_cmd\_perf\_en、perf\_paral\_total、perf\_paral\_mpu、perf\_cong\_mst、debug0/1/2|
|采样事件|@\(posedge clk\) iff creg\_cmd\_perf\_en|
|放置位置|cmdsched\_perf\_monitor|
|目标|100%|

#### 3\.10\.2 覆盖点定义

##### CP\_CMDSCHED\_PERF\_001：并行度统计

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_PERF\_001|
|覆盖点名称|cp\_perf\_paral|
|采样信号|perf\_paral\_total、perf\_paral\_mpu|
|Bin 数|3 normal|

```systemverilog
cp_perf_paral: coverpoint perf_paral {
  bins total_paral = {PERF_TOTAL};  // Feat-36：所有组件平均并行度
  bins mpu_paral   = {PERF_MPU};    // Feat-37：MPU 平均并行度
  bins win_open    = {PERF_WIN};    // 性能统计窗口开启期间采样
}
```

##### CP\_CMDSCHED\_PERF\_002：各 MST 拥塞统计

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_PERF\_002|
|覆盖点名称|cp\_perf\_cong|
|采样信号|perf\_cong\_mst（ISTB 中对应组件指令数）|
|Bin 数|5 normal|

```systemverilog
cp_perf_cong: coverpoint perf_cong_mst {
  bins mpu_cong  = {CONG_MPU};   // Feat-31
  bins vpu_cong  = {CONG_VPU};   // Feat-32
  bins glsu_cong = {CONG_GLSU};  // Feat-33
  bins llsu_cong = {CONG_LLSU};  // Feat-34
  bins niu_cong  = {CONG_NIU};   // Feat-35
}
```

##### CP\_CMDSCHED\_PERF\_003：debug 寄存器

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_PERF\_003|
|覆盖点名称|cp\_debug\_reg|
|采样信号|debug0/1/2 寄存器值|
|Bin 数|3 normal|

```systemverilog
cp_debug_reg: coverpoint debug_reg {
  bins dbg0_busy     = {DBG0};  // Feat-38：各组件 busy 状态
  bins dbg1_inst_cnt = {DBG1};  // Feat-39：inst_disp 总下发指令数（含 cfg/pre/drv）
  bins dbg2_iss_cnt  = {DBG2};  // Feat-40：cmd_sch 总发射 primitive 数（仅 drv）
}
```

##### CP\_CMDSCHED\_PERF\_004：性能统计使能

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_PERF\_004|
|覆盖点名称|cp\_perf\_en|
|采样信号|creg\_cmd\_perf\_en|
|Bin 数|2 normal|

```systemverilog
cp_perf_en: coverpoint creg_cmd_perf_en {
  bins en_on  = {1'b1};  // 性能监测打开
  bins en_off = {1'b0};  // 性能监测关闭
}
```

#### 3\.10\.3 组内交叉

性能与 Debug 覆盖组不定义组内交叉；并行度与拥塞统计的计数正确性通过 scoreboard 校验（RTL 寄存器值与 monitor 统计值比对）。

#### 3\.10\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_perf\_window|perf\_seq|win\_open, total\_paral, mpu\_paral|
|c\_perf\_cong\_seq|perf\_seq|mpu\_cong \~ niu\_cong|
|c\_perf\_en|csr\_seq|en\_on, en\_off|

### 3\.11 CG\_CMDSCHED\_CSR：CSR 与低功耗覆盖组

#### 3\.11\.1 覆盖组信息

|项目|内容|
|---|---|
|CG ID|CG\_CMDSCHED\_CSR|
|需求 ID|Feat\-24（creg\_cmd\_icg\_en\[31:0\]）、Feat\-25（删除各组件低功耗模式）|
|功能描述|覆盖 CMD 内部 CSR 配置（icg/excep/perf/block/tile\_rls/spad\_excl）及 IDLE/ICG 低功耗行为|
|采样信号|creg\_cmd\_icg\_en、creg\_cmd\_excep\_en、creg\_cmd\_perf\_en、creg\_cmd\_block\_en、creg\_cmd\_tile\_rls\_en、creg\_cmd\_spad\_excl\_en、idle/gate 状态|
|采样事件|@\(posedge clk\) iff CSR 写或 ICG 状态变化|
|放置位置|cmdsched\_csr\_monitor|
|目标|100%|

#### 3\.11\.2 覆盖点定义

##### CP\_CMDSCHED\_CSR\_001：ICG 使能

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_CSR\_001|
|覆盖点名称|cp\_csr\_icg|
|采样信号|creg\_cmd\_icg\_en|
|Bin 数|2 normal|

```systemverilog
cp_csr_icg: coverpoint creg_cmd_icg_en {
  bins icg_on  = {[1:$]};  // Feat-24：打开 CMD 内部 ICG，低功耗模式
  bins icg_off = {0};      // 关闭 ICG，时钟常开
}
```

##### CP\_CMDSCHED\_CSR\_002\~005：异常/性能/阻塞/释放使能

|覆盖点 ID|覆盖点名称|Bin|
|---|---|---|
|CP\_CMDSCHED\_CSR\_002|cp\_csr\_excep\_en（creg\_cmd\_excep\_en）|on / off|
|CP\_CMDSCHED\_CSR\_003|cp\_csr\_perf\_en（creg\_cmd\_perf\_en）|on / off|
|CP\_CMDSCHED\_CSR\_004|cp\_csr\_block\_en（creg\_cmd\_block\_en）|on / off|
|CP\_CMDSCHED\_CSR\_005|cp\_csr\_tile\_rls（creg\_cmd\_tile\_rls\_en\[31:0\]）|all\_en（默认 32'hFFFF\_FFFF）/ part\_en（部分通道）/ all\_off|
|CP\_CMDSCHED\_CSR\_006|cp\_csr\_spad\_excl（creg\_cmd\_spad\_excl\_en）|non\_excl（默认 0，当前仅支持非独占）/ excl（暂不支持，可配寄存器验证）|

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

##### CP\_CMDSCHED\_CSR\_007：IDLE 与 ICG 状态

|项目|内容|
|---|---|
|覆盖点 ID|CP\_CMDSCHED\_CSR\_007|
|覆盖点名称|cp\_idle\_icg|
|采样信号|idle\_state、clk\_gate|
|Bin 数|3 normal|

```systemverilog
cp_idle_icg: coverpoint idle_icg_state {
  bins idle      = {IDLE_NO_CLK};  // 无指令下发时各模块无时钟
  bins gate_on   = {GATE_OPEN};    // 指令下发后按译码结果打开子模块时钟
  bins perf_gate = {GATE_PERF};    // 中断/性能使能打开时给 cmd_int_perf 开时钟
}
```

#### 3\.11\.3 组内交叉

CSR 与低功耗覆盖组不定义组内交叉，CSR 配置与行为结果的联动由对应行为组（EXCP/PERF/RSP）交叉覆盖。

#### 3\.11\.4 覆盖组约束映射

|约束|所属类|目标 Bin|
|---|---|---|
|c\_csr\_icg|csr\_seq|icg\_on, icg\_off, idle, gate\_on|
|c\_csr\_tile\_rls|csr\_seq|all\_en, part\_en, all\_off|
|c\_csr\_block|csr\_seq|block on/off（联动 EXCP）|
|c\_csr\_spad\_excl|csr\_seq|non\_excl（默认），excl\_cfg 仅验证配置通路|

### 3\.12 跨组交叉覆盖汇总

以下交叉覆盖跨越多个覆盖率组，统一在此汇总（各交叉的完整定义见对应组内）。

|交叉 ID|交叉对象|涉及覆盖组|Bin 数|目标|
|---|---|---|---|---|
|X\_CMDSCHED\_ITYPE\_001|功能分类 × 组件分类|CG\_CMDSCHED\_ITYPE|3|100%|
|X\_CMDSCHED\_ITYPE\_002|指令类型 × 功能分类|CG\_CMDSCHED\_ITYPE|6|100%|
|X\_CMDSCHED\_INSTB\_001|ISTB 水位 × 链表操作|CG\_CMDSCHED\_INSTB|6|100%|
|X\_CMDSCHED\_INSTB\_002|深度参数 × 满水位|CG\_CMDSCHED\_INSTB|4|100%|
|X\_CMDSCHED\_DEP\_001|依赖类型 × 判断粒度|CG\_CMDSCHED\_DEP|9|100%|
|X\_CMDSCHED\_DEP\_002|依赖类型 × 组件数|CG\_CMDSCHED\_DEP|12|100%|
|X\_CMDSCHED\_UNIT\_001|MST × 指令槽|CG\_CMDSCHED\_UNIT|5|100%|
|X\_CMDSCHED\_UNIT\_002|MST × 并行范围|CG\_CMDSCHED\_UNIT|20|100%|
|X\_CMDSCHED\_ISSUE\_001|依赖判定 × 发射路径|CG\_CMDSCHED\_DEP × CG\_CMDSCHED\_ISSUE|6|100%|
|X\_CMDSCHED\_ISSUE\_002|MST 可用资源 × 发射路径|CG\_CMDSCHED\_ISSUE|6|100%|
|X\_CMDSCHED\_MEM\_001|SPAD tile 状态 × MST|CG\_CMDSCHED\_MEM × CG\_CMDSCHED\_UNIT|20|100%|
|X\_CMDSCHED\_MEM\_002|依赖粒度 × 多组件共享|CG\_CMDSCHED\_MEM × CG\_CMDSCHED\_DEP|9|100%|
|X\_CMDSCHED\_RSP\_001|返回类型 × fifo 优先级|CG\_CMDSCHED\_RSP|4|100%|
|X\_CMDSCHED\_RSP\_002|返回类型 × 乱序|CG\_CMDSCHED\_RSP|4|100%|
|X\_CMDSCHED\_EXCP\_001|中断类型 × block 行为|CG\_CMDSCHED\_EXCP|4|100%|

### 3\.13 覆盖率组与约束映射总表

|覆盖率组|覆盖点|约束|目标 Bin|
|---|---|---|---|
|CG\_CMDSCHED\_ITYPE|cp\_inst\_flag, cp\_inst\_func, cp\_inst\_comp, cp\_prim\_type|c\_inst\_flag\_dist, c\_inst\_func\_dist, c\_inst\_comp\_dist, c\_prim\_dist, c\_illegal\_inst|nice/vnice、三类功能、七类组件、全部 primitive|
|CG\_CMDSCHED\_INSTB|cp\_instb\_level, cp\_instb\_chain, cp\_instb\_cfg\_drv, cp\_instb\_dp|c\_instb\_dp, c\_instb\_fill, c\_cfg\_drv\_pair, c\_chain\_seq|empty\~full、链表操作、拼接存储、dp1/2/4/8|
|CG\_CMDSCHED\_DEP|cp\_hazard\_type, cp\_hazard\_gran, cp\_hazard\_scope, cp\_struct\_hazard|c\_dep\_dist, c\_raw/c\_waw/c\_war, c\_hazard\_scope\_2\~5, c\_same\_mst\_pair, c\_lmem\_llsu\_conflict, c\_sync\_barrier, c\_noc\_fence\_barrier, c\_niu\_dst, c\_niu\_store|no\_dep/raw/waw/war、tile/page/dram、1\~5 组件、5 类结构冲突|
|CG\_CMDSCHED\_UNIT|cp\_mst\_id, cp\_mst\_slot, cp\_paral\_scope, cp\_ls\_parallel, cp\_tmu\_arb, cp\_third\_inst\_blocked|c\_mst\_dist, c\_mst\_dual, c\_multi\_parallel\_2\~5, c\_ls\_pair\_seq, c\_tmu\_contend, c\_third\_inst\_blocked|5 MST、双指令槽、2\~5 并行、load\-store 并行、TMU 竞争、第三条阻塞|
|CG\_CMDSCHED\_ISSUE|cp\_issue\_path, cp\_issue\_priority, cp\_start\_done\_seq, cp\_mst\_avail|c\_issue\_direct, c\_issue\_stall, c\_issue\_backpressure, c\_start\_done\_seq, c\_rls\_timing|直发/存储/ISTB 发射/反压、优先级、start\-done\-rls、资源判定|
|CG\_CMDSCHED\_MEM|cp\_spad\_tile\_occ, cp\_cimc\_page\_occ, cp\_dram\_occ, cp\_multi\_mst\_spad, cp\_mem\_release\_src, cp\_spad\_tile\_map|c\_spad\_tile\_addr, c\_cimc\_page\_addr, c\_dram\_addr, c\_multi\_mst\_spad, c\_release\_early, c\_tile\_rls\_en, c\_tile\_map\_spread|tile/page/dram 占用释放、多组件共享、释放来源、32 个 tile 地址|
|CG\_CMDSCHED\_RSP|cp\_rsp\_type, cp\_rsp\_data, cp\_rsp\_tag, cp\_rsp\_prio, cp\_cmd\_handshake, cp\_backpressure, cp\_wr\_lmem\_rmw|c\_xd1\_seq, c\_rsp\_priority\_seq, c\_tag\_out\_of\_order, c\_backpressure\_seq, c\_wr\_lmem\_rmw|四类返回、乱序 tag、fifo 优先级、握手、四类反压、wr\_lmem 读改写|
|CG\_CMDSCHED\_EXCP|cp\_int\_type, cp\_block\_en, cp\_int\_clear, cp\_excep\_en, cp\_int\_info\_save|c\_illegal\_inst, c\_non\_spad\_addr, c\_cimc\_lmem\_addr, c\_lmem\_llsu\_conflict, c\_block\_en\_cfg, c\_int\_clear\_seq, c\_int\_info\_save|cmd\_int\[0\]/\[1\]、block 行为、清除方式、屏蔽、中断现场保存|
|CG\_CMDSCHED\_PERF|cp\_perf\_paral, cp\_perf\_cong, cp\_debug\_reg, cp\_perf\_en|c\_perf\_window, c\_perf\_cong\_seq, c\_perf\_en|并行度、拥塞、debug、使能|
|CG\_CMDSCHED\_CSR|cp\_csr\_icg, cp\_csr\_excep\_en, cp\_csr\_perf\_en, cp\_csr\_block\_en, cp\_csr\_tile\_rls, cp\_csr\_spad\_excl, cp\_idle\_icg|c\_csr\_icg, c\_csr\_tile\_rls, c\_csr\_block, c\_csr\_spad\_excl|icg/excep/perf/block/tile\_rls/spad\_excl、IDLE/ICG|

### 3\.14 覆盖率组与批次映射

|批次|测试名|激活的覆盖率组|目标覆盖率|
|---|---|---|---|
|1|cmdsched\_basic\_test|CG\_CMDSCHED\_ISSUE|20%|
|2|cmdsched\_instype\_test|CG\_CMDSCHED\_ITYPE|32%|
|3|cmdsched\_instb\_test|CG\_CMDSCHED\_INSTB|42%|
|4|cmdsched\_dep\_test|CG\_CMDSCHED\_DEP|55%|
|5|cmdsched\_hazard\_scope\_test|CG\_CMDSCHED\_DEP, CG\_CMDSCHED\_ISSUE|65%|
|6|cmdsched\_parallel\_test|CG\_CMDSCHED\_UNIT|74%|
|7|cmdsched\_mem\_test|CG\_CMDSCHED\_MEM, CG\_CMDSCHED\_UNIT|82%|
|8|cmdsched\_rsp\_test|CG\_CMDSCHED\_RSP|89%|
|9|cmdsched\_excp\_perf\_test|CG\_CMDSCHED\_EXCP, CG\_CMDSCHED\_PERF, CG\_CMDSCHED\_CSR|96%|
|10|cmdsched\_random\_mix\_test|全部|防过拟合|

### 3\.15 覆盖率组签核标准

|覆盖率组|覆盖点目标|交叉目标|非法 Bin|豁免|
|---|---|---|---|---|
|CG\_CMDSCHED\_ITYPE|100%|100%|0 命中|需审批|
|CG\_CMDSCHED\_INSTB|100%|100%|0 命中|需审批|
|CG\_CMDSCHED\_DEP|100%|100%<br>|0 命中|需审批|
|CG\_CMDSCHED\_UNIT|100%|100%|0 命中|需审批|
|CG\_CMDSCHED\_ISSUE|100%|100%|0 命中|需审批|
|CG\_CMDSCHED\_MEM|100%|100%|0 命中|需审批|
|CG\_CMDSCHED\_RSP|100%|100%|0 命中|需审批|
|CG\_CMDSCHED\_EXCP|100%|100%|0 命中|需审批|
|CG\_CMDSCHED\_PERF|100%|—|0 命中|需审批|
|CG\_CMDSCHED\_CSR|100%|—|0 命中|需审批|

**签核条件：所有覆盖率组达到 100%，或已通过正式豁免流程。**

## 4\. 约束设计

### 4\.1 约束层次结构

约束按三层组织，从宽到严逐层收紧：

```plaintext
第 1 层：指令生成约束（单条指令的编码、类型、数据与访存地址）
    ↓
第 2 层：序列依赖约束（指令之间的依赖关系、组件组合）
    ↓
第 3 层：场景约束（针对特定覆盖率缺口的定向约束）

```

**核心原则：约束的设计必须与覆盖点一一对应。每个覆盖点的每个 bin，都要有对应的约束能生成命中它的激励。**

### 4\.2 第 1 层：指令生成约束

**对应覆盖点**：cp\_inst\_flag、cp\_inst\_func、cp\_inst\_comp、cp\_prim\_type、cp\_mst\_id、cp\_spad\_tile\_occ、cp\_cimc\_page\_occ、cp\_dram\_occ

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
  constraint c_spad_tile_addr { spad_addr[4:0] inside {[0:31]}; }  // 覆盖 8 SPAD × 4 tile
  // 对应 cp_cimc_page_occ：CIMC 仅 2x2 形状（Feat-6），page 0~3
  constraint c_cimc_page_addr { cimc_page inside {[0:3]}; }
  constraint c_addr_align { spad_addr[0] == 0; }  // 32bit 对齐（wr/rd_lmem 每次 32bit）
endclass
```

### 4\.3 第 2 层：序列依赖约束

**对应覆盖点**：cp\_hazard\_type、cp\_hazard\_gran、cp\_hazard\_scope、cp\_struct\_hazard、X\_dep\_gran、X\_dep\_scope、cp\_mst\_slot、cp\_paral\_scope

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

### 4\.4 第 3 层：场景约束

#### 场景 1：ISTB 满反压

**目标覆盖点**：cp\_instb\_level\.full、X\_instb\_level\_chain\.full\_tail\_wr、X\_instb\_dp\_full、cp\_issue\_path\.backpressure

```systemverilog
class instb_fill_seq extends npu_stream;
  constraint c_instb_fill {
    num_instr == 20;
    foreach (instrs[i]) {
      // 前 4 条产生依赖链填满 ISTB（DP=4），后续指令触发反压
      if (i > 0) { instrs[i].hazard_type == RAW;
                   instrs[i].spad_addr[4:0] == instrs[i-1].spad_addr[4:0]; }
    }
  }
  // cfg 与 drv 配对存储场景
  constraint c_cfg_drv_pair { instrs[0].prim_type == PRIM_CFG;
                              instrs[1].prim_type == PRIM_WR_LMEM; }
endclass
```

#### 场景 2：连续 RAW 依赖链（2\~5 组件）

**目标覆盖点**：X\_dep\_scope 的 raw×two/four/five\_mst、X\_issue\_dep\_path\.raw\_stored

```systemverilog
class raw_chain_seq extends npu_stream;
  constraint c_raw_chain {
    num_instr == 25;
    foreach (instrs[i]) {
      if (i > 0) {
        instrs[i].hazard_type == RAW;
        instrs[i].spad_addr[4:0] == instrs[i-1].spad_addr[4:0];
        // 轮转 5 个 MST，构造跨组件依赖链
        instrs[i].mst_id == mst_id_e'(i % 5);
      }
    }
  }
endclass
```

#### 场景 3：多组件并行执行

**目标覆盖点**：cp\_paral\_scope 的 two/three/four/five\_mst、X\_unit\_paral、cp\_multi\_mst\_spad

```systemverilog
class parallel_seq extends npu_stream;
  constraint c_multi_parallel_2~5 {
    num_instr == 20;
    foreach (instrs[i]) {
      instrs[i].hazard_type == NONE;
      // 轮转 5 个 MST，地址 tile 不重叠，支持并行
      instrs[i].mst_id == mst_id_e'(i % 5);
      instrs[i].spad_addr[4:0] == i % 32;
    }
  }
endclass
```

#### 场景 4：sync / noc\_fence 屏障

**目标覆盖点**：cp\_struct\_hazard\.sync\_all / noc\_fence、cp\_rsp\_type\.sync\_rsp / noc\_fence\_rsp、cp\_rsp\_data\.state\_1

```systemverilog
class barrier_seq extends npu_stream;
  constraint c_sync_barrier {
    instrs[5].prim_type == PRIM_SYNC;   // sync 与所有 MST 存在 structure hazard
    foreach (instrs[i]) { if (i > 5) instrs[i].hazard_type == RAW; }
  }
  constraint c_noc_fence_barrier {
    instrs[8].prim_type == PRIM_NOC_FENCE;
    foreach (instrs[i]) { if (i > 8) instrs[i].inst_comp == COMP_NOC; }
  }
endclass
```

#### 场景 5：多 xd=1 指令乱序返回

**目标覆盖点**：cp\_rsp\_tag\.multi\_xd / tag\_ooot、X\_rsp\_tag\.ooo、cp\_rsp\_prio

```systemverilog
class xd1_seq extends npu_stream;
  constraint c_xd1_seq {
    foreach (instrs[i]) {
      if (i % 4 == 0) { instrs[i].xd == 1;
                        instrs[i].prim_type inside {PRIM_RD_LMEM, PRIM_V_S,
                                                    PRIM_SYNC, PRIM_NOC_FENCE};
                        instrs[i].tag == i; }   // 不同 tag，验证乱序返回
      else instrs[i].xd == 0;
    }
  }
endclass
```

#### 场景 6：GLSU/NIU load\-store 并行与后启动先 done

**目标覆盖点**：cp\_ls\_parallel\.glsu\_ls\_par / niu\_ls\_par、cp\_start\_done\_seq\.start1\_done0、cp\_rls\_timing

```systemverilog
class ls_parallel_seq extends npu_stream;
  constraint c_ls_pair_seq {
    num_instr == 12;
    // GLSU load + store 无 data hazard 并行下发
    instrs[0].mst_id == MST_GLSU; instrs[0].prim_type == PRIM_TLD;  // load
    instrs[1].mst_id == MST_GLSU; instrs[1].prim_type == PRIM_TST;  // store
    instrs[1].spad_addr[4:0] != instrs[0].spad_addr[4:0];
    // NIU load + store 并行
    instrs[2].mst_id == MST_NIU;  instrs[2].prim_type == PRIM_TLD;
    instrs[3].mst_id == MST_NIU;  instrs[3].prim_type == PRIM_TST;
  }
endclass
```

#### 场景 7：TMU 竞争

**目标覆盖点**：cp\_tmu\_arb\.glsu\_pri\_contend / llsu\_wait

```systemverilog
class tmu_seq extends npu_stream;
  constraint c_tmu_contend {
    num_instr == 8;
    instrs[0].mst_id == MST_GLSU; instrs[0].use_tmu == 1;  // GLSU 先下发
    instrs[1].mst_id == MST_LLSU; instrs[1].use_tmu == 1;  // LLSU 同时抢占
    instrs[1].spad_addr[4:0] != instrs[0].spad_addr[4:0];   // 无 data hazard
    // 预期：GLSU 优先占用 TMU，LLSU 等待
  }
endclass
```

#### 场景 8：异常指令与非法地址

**目标覆盖点**：cp\_int\_type\.cmd\_int0 / cmd\_int1、cp\_prim\_type\.il\_rd\_csr / il\_reserved、cp\_block\_en

```systemverilog
class illegal_seq extends npu_stream;
  constraint c_illegal_inst {
    num_instr == 8;
    // 指令字段与指令集不一致：保留编码触发 cmd_int[0]
    instrs[3].prim_type == PRIM_RESERVED;
    // rd_csr 已删除：下发即异常（Feat-3）
    instrs[4].prim_type == PRIM_RD_CSR;
    // wr_lmem_drv/rd_lmem_drv 指向 CIMC 触发 cmd_int[1]
    instrs[5].prim_type == PRIM_WR_LMEM; instrs[5].addr_space == ADDR_CIMC;
    instrs[6].prim_type == PRIM_RD_LMEM; instrs[6].addr_space == ADDR_CIMC;
  }
endclass
```

#### 场景 9：反压流控

**目标覆盖点**：cp\_backpressure 的 rd\_bp/wr\_bp/scalar\_bp/istb\_bp、cp\_cmd\_handshake

```systemverilog
class bp_seq extends npu_stream;
  // 读/写请求反压：通过 DUT 侧 force 或 XBAR 模型注入 ready 拉低
  constraint c_backpressure_seq {
    num_instr == 16;
    foreach (instrs[i]) { if (i % 5 == 0) instrs[i].prim_type == PRIM_WR_LMEM;
                          else if (i % 5 == 1) instrs[i].prim_type == PRIM_RD_LMEM;
                          else if (i % 5 == 2) instrs[i].prim_type == PRIM_V_S; }
  }
  // 配合测试平台：BP_READ/BP_WRITE/BP_SCALAR/BP_ISTB 分别注入
endclass
```

#### 场景 10：性能统计窗口

**目标覆盖点**：cp\_perf\_paral、cp\_perf\_cong、cp\_debug\_reg

```systemverilog
class perf_seq extends npu_stream;
  constraint c_perf_window {
    num_instr == 40;
    // 混合 5 个 MST 指令制造并行度与拥塞，统计窗口开启后采样
    foreach (instrs[i]) { instrs[i].mst_id == mst_id_e'(i % 5);
                          instrs[i].hazard_type == NONE; }
  }
endclass
```

#### 场景 11：第三条同组件指令阻塞

**目标覆盖点**：cp\_third\_inst\_blocked（Feat\-10：第三条同组件指令被阻塞）

```systemverilog
class third_inst_seq extends npu_stream;
  constraint c_third_inst_blocked {
    num_instr == 10;
    // 同组件（以 GLSU 为例）连续三条指令
    foreach (instrs[i]) { if (i < 4) instrs[i].mst_id == MST_GLSU; }
    instrs[0].hazard_type == NONE;                  // 第一条发射，占用 inst0
    instrs[1].hazard_type == NONE;                  // 第二条无 data hazard，占用 inst1（并行）
    instrs[1].spad_addr[4:0] != instrs[0].spad_addr[4:0];
    instrs[2].spad_addr[4:0] == instrs[1].spad_addr[4:0];  // 第三条 RAW 依赖 → 双槽占满被阻塞
  }
endclass
```

#### 场景 12：SPAD tile 地址空间遍历

**目标覆盖点**：cp\_spad\_tile\_map（Feat\-22：8 SPAD × 4 tile = 32 组合）

```systemverilog
class tile_map_seq extends npu_stream;
  constraint c_tile_map_spread {
    num_instr == 40;
    foreach (instrs[i]) {
      instrs[i].spad_id == i % 8;          // 覆盖 spad 0~7
      instrs[i].tile_id == (i / 8) % 4;    // 覆盖 tile 0~3
      // spad_id/tile_id 由 spad_addr 编码：spad_id = spad_addr[4:2]，tile_id = spad_addr[1:0]
    }
  }
endclass
```

#### 场景 13：wr\_lmem 读改写（RMW）

**目标覆盖点**：cp\_wr\_lmem\_rmw（Feat\-4：wr\_lmem\_drv 先读后改写回写）

```systemverilog
class rsp_rmw_seq extends npu_stream;
  constraint c_wr_lmem_rmw {
    num_instr == 12;
    foreach (instrs[i]) { if (i % 3 == 0) instrs[i].prim_type == PRIM_WR_LMEM; }
    // scoreboard：校验 wr_lmem_drv 发射后先读 SPAD 地址数据、替换后写回原地址（RMW）
    // 配合反压注入：验证 RMW 被打断后可恢复（rmw_blocked）
  }
endclass
```

#### 场景 14：中断现场信息保存

**目标覆盖点**：cp\_int\_info\_save（Feat\-28：首次中断保存现场，后续不覆盖）

```systemverilog
class int_info_seq extends npu_stream;
  constraint c_int_info_save {
    num_instr == 10;
    instrs[2].prim_type == PRIM_RESERVED;  // 首条非法指令触发 cmd_int[0]
    // 触发后再下发指令：校验后续中断不再覆盖首次现场
    // 通过 core_reg 读中断信息寄存器：inst0/inst1 的指令序列 id、funct7/inst_flag/xd/xs1/xs2
  }
endclass
```

### 4\.5 约束与覆盖点映射表

|约束|所属类|目标覆盖点|目标 Bin|
|---|---|---|---|
|c\_inst\_flag\_dist|npu\_instr|cp\_inst\_flag|nice, vnice|
|c\_inst\_func\_dist|npu\_instr|cp\_inst\_func|normal, state\_rsp, value\_rsp|
|c\_inst\_comp\_dist|npu\_instr|cp\_inst\_comp|cfg, lmem, noc, glsu, llsu, mpu, vpu|
|c\_prim\_dist|npu\_instr|cp\_prim\_type|全部 primitive|
|c\_mst\_dist|npu\_instr|cp\_mst\_id|glsu, llsu, mpu, vpu, niu|
|c\_spad\_tile\_addr / c\_cimc\_page\_addr / c\_dram\_addr|npu\_instr|cp\_spad\_tile\_occ / cp\_cimc\_page\_occ / cp\_dram\_occ|tile/page/dram 占用|
|c\_dep\_dist|npu\_stream|cp\_hazard\_type|no\_dep, raw, waw, war|
|c\_raw / c\_waw / c\_war|npu\_stream|X\_dep\_gran|raw/waw/war × tile/page/dram|
|c\_hazard\_scope\_2\~5|npu\_stream|cp\_hazard\_scope, X\_dep\_scope|two\_mst \~ five\_mst|
|c\_same\_mst\_pair|npu\_stream|cp\_mst\_slot, Feat\-10|both, same\_mst|
|c\_instb\_dp|参数遍历|cp\_instb\_dp|dp1, dp2, dp4, dp8|
|c\_instb\_fill / c\_cfg\_drv\_pair|instb\_fill\_seq|cp\_instb\_level, cp\_instb\_cfg\_drv|full, cfg\_then\_drv\_stored|
|c\_chain\_seq|instb\_chain\_seq|cp\_instb\_chain|head/tail/mid/refill|
|c\_lmem\_llsu\_conflict|conflict\_seq|cp\_struct\_hazard|lmem\_llsu|
|c\_sync\_barrier / c\_noc\_fence\_barrier|barrier\_seq|cp\_struct\_hazard, cp\_rsp\_type|sync\_all, noc\_fence|
|c\_niu\_dst / c\_niu\_store|niu\_seq|cp\_struct\_hazard|niu\_dst\_single, niu\_store\_dual|
|c\_multi\_parallel\_2\~5|parallel\_seq|cp\_paral\_scope, X\_unit\_paral|two\_mst \~ five\_mst|
|c\_ls\_pair\_seq|ls\_parallel\_seq|cp\_ls\_parallel|glsu\_ls\_par, niu\_ls\_par|
|c\_tmu\_contend|tmu\_seq|cp\_tmu\_arb|glsu\_pri\_contend, llsu\_wait|
|c\_multi\_mst\_spad|parallel\_seq|cp\_multi\_mst\_spad|mst2\~5\_same\_spad, rar\_multi\_read|
|c\_release\_early / c\_tile\_rls\_en|release\_seq / csr\_seq|cp\_mem\_release\_src|rls\_release, tile\_rls\_en\_off|
|c\_xd1\_seq / c\_tag\_out\_of\_order|xd1\_seq|cp\_rsp\_tag, X\_rsp\_tag|multi\_xd, tag\_ooot, ooo|
|c\_rsp\_priority\_seq|xd1\_seq|cp\_rsp\_prio, X\_rsp\_prio|scalar \> lmem \> fence \> sync|
|c\_backpressure\_seq|bp\_seq|cp\_backpressure|rd\_bp, wr\_bp, scalar\_bp, istb\_bp|
|c\_illegal\_inst / c\_non\_spad\_addr / c\_cimc\_lmem\_addr|illegal\_seq|cp\_int\_type, cp\_prim\_type|cmd\_int0, cmd\_int1|
|c\_block\_en\_cfg / c\_int\_clear\_seq|csr\_seq / int\_clear\_seq|cp\_block\_en, cp\_int\_clear|block\_stop/continue, 清除方式|
|c\_perf\_window / c\_perf\_cong\_seq / c\_perf\_en|perf\_seq / csr\_seq|cp\_perf\_paral, cp\_perf\_cong, cp\_perf\_en|并行度、拥塞、使能|
|c\_csr\_icg / c\_csr\_tile\_rls / c\_csr\_block / c\_csr\_spad\_excl|csr\_seq|cp\_csr\_icg, cp\_csr\_tile\_rls, cp\_csr\_block\_en, cp\_csr\_spad\_excl, cp\_idle\_icg|icg/tile\_rls/block/spad\_excl/IDLE|
|c\_third\_inst\_blocked|third\_inst\_seq|cp\_third\_inst\_blocked|third\_blocked, third\_issued|
|c\_tile\_map\_spread|tile\_map\_seq|cp\_spad\_tile\_map|tile\_00 \~ tile\_31|
|c\_wr\_lmem\_rmw|rsp\_rmw\_seq|cp\_wr\_lmem\_rmw|rmw\_performed, rmw\_blocked|
|c\_int\_info\_save|int\_info\_seq|cp\_int\_info\_save|first\_int\_saved, later\_not\_saved, info\_readable|

## 5\. 批次设计与覆盖率演进

### 5\.1 批次规划

|批次|测试名|约束|目标覆盖点|种子数|预期覆盖率|
|---|---|---|---|---|---|
|1|cmdsched\_basic\_test|基础约束|cp\_issue\_path\.direct, cp\_mst\_id|5|20%|
|2|cmdsched\_instype\_test|c\_inst\_flag\_dist \+ c\_inst\_func\_dist \+ c\_inst\_comp\_dist \+ c\_prim\_dist|CG\_CMDSCHED\_ITYPE 全部|30|32%|
|3|cmdsched\_instb\_test|c\_instb\_fill \+ c\_chain\_seq \+ c\_cfg\_drv\_pair|CG\_CMDSCHED\_INSTB 全部|30|42%|
|4|cmdsched\_dep\_test|c\_dep\_dist \+ c\_raw/c\_waw/c\_war|cp\_hazard\_type \+ X\_dep\_gran|50|55%|
|5|cmdsched\_hazard\_scope\_test|c\_hazard\_scope\_2\~5 \+ c\_same\_mst\_pair|cp\_hazard\_scope \+ X\_dep\_scope|30|65%|
|6|cmdsched\_parallel\_test|c\_multi\_parallel\_2\~5 \+ c\_ls\_pair\_seq \+ c\_tmu\_contend \+ c\_third\_inst\_blocked|CG\_CMDSCHED\_UNIT 全部|30|74%|
|7|cmdsched\_mem\_test|c\_spad\_tile\_addr \+ c\_multi\_mst\_spad \+ c\_release\_early \+ c\_tile\_map\_spread|CG\_CMDSCHED\_MEM 全部|30|82%|
|8|cmdsched\_rsp\_test|c\_xd1\_seq \+ c\_rsp\_priority\_seq \+ c\_backpressure\_seq \+ c\_wr\_lmem\_rmw|CG\_CMDSCHED\_RSP 全部|40|89%|
|9|cmdsched\_excp\_perf\_test|c\_illegal\_inst \+ c\_block\_en\_cfg \+ c\_perf\_window \+ c\_csr\_icg \+ c\_int\_info\_save|CG\_CMDSCHED\_EXCP / PERF / CSR 全部|40|96%|
|10|cmdsched\_random\_mix\_test|宽松混合|探索性|100|防过拟合|

### 5\.2 批次演进逻辑

```plaintext
批次 1：基础发射（直发 + 5 MST 识别）
  → 20%，缺口：指令类型未覆盖
批次 2：指令类型（NICE/VNICE、功能分类、组件分类、primitive）
  → 32%，缺口：ISTB 管理未覆盖
批次 3：ISTB 管理（链表、满反压、拼接存储）
  → 42%，缺口：依赖类型未覆盖
批次 4：依赖类型（RAW/WAW/WAR × tile/page/dram）
  → 55%，缺口：多组件 hazard 未覆盖
批次 5：hazard 范围（2~5 组件 + 同组件双指令）
  → 65%，缺口：并行执行未覆盖
批次 6：并行执行（2~5 组件并行、load-store 并行、TMU 竞争）
  → 74%，缺口：存储资源管理未覆盖
批次 7：存储资源（SPAD tile/CIMC page/DRAM、多组件共享、提前释放）
  → 82%，缺口：返回值与握手未覆盖
批次 8：返回值与握手（sync/fence/rd_lmem/V_S、乱序、反压）
  → 89%，缺口：异常/性能/CSR 未覆盖
批次 9：异常/性能/CSR（中断、并行度、debug、icg）
  → 96%，剩余 bin 定向补齐
批次 10：随机混合
  → 防过拟合

```

### 5\.3 覆盖率缺口与约束变化对应

|缺口|根因分析|约束变化|新增/修改类|
|---|---|---|---|
|raw\_stored 未命中|RAW 链未强制跨组件构造|增加 c\_raw\_chain（raw\_chain\_seq）|raw\_chain\_seq|
|full 未命中|依赖链不足，ISTB 未填满|增加 c\_instb\_fill 前 4 条强制依赖|instb\_fill\_seq|
|five\_mst 并行未覆盖|未轮转全部 5 个 MST|增加 c\_multi\_parallel\_2\~5|parallel\_seq|
|tag\_ooot 未命中|xd=1 指令未并发|增加 c\_xd1\_seq（多 xd=1 并发、不同 tag）|xd1\_seq|
|glsu\_pri\_contend 未命中|未构造 GLSU/LLSU 同时抢占 TMU|增加 c\_tmu\_contend|tmu\_seq|
|cmd\_int1 未命中|lmem 指令地址未指向 CIMC|增加 c\_cimc\_lmem\_addr|illegal\_seq|
|start1\_done0 未命中|未构造 GLSU/NIU load\-store 并行|增加 c\_ls\_pair\_seq 并配合后启动先 done 断言|ls\_parallel\_seq|
|niu\_dst\_full 未覆盖|NIU dst 指令连续下发场景缺失|增加 c\_niu\_dst 定向场景|niu\_seq|

## 6\. 种子管理

### 6\.1 种子基线建立流程

```plaintext
第 1 步：每个测试跑 200-500 个种子
第 2 步：记录每个种子的覆盖率贡献、运行时间、pass/fail
第 3 步：按覆盖率贡献排名
第 4 步：找覆盖率平台期
第 5 步：从高贡献种子里选出基线种子
第 6 步：纳入回归，固定使用
第 7 步：定期维护（设计变更后重新评估）

```

### 6\.2 种子基线表

|测试名|类型|种子基线|基线长度|探索种子|总运行次数|
|---|---|---|---|---|---|
|cmdsched\_basic\_test|定向|\{1001\}|1|0|1|
|cmdsched\_instype\_test|随机|\{2001, 2005, \.\.\.\}|15|3|18|
|cmdsched\_instb\_test|随机|\{3001, 3005, \.\.\.\}|15|3|18|
|cmdsched\_dep\_test|随机|\{4001, 4005, \.\.\.\}|25|5|30|
|cmdsched\_hazard\_scope\_test|定向|\{5001, 5003, \.\.\.\}|10|2|12|
|cmdsched\_parallel\_test|随机|\{6001, 6005, \.\.\.\}|15|3|18|
|cmdsched\_mem\_test|随机|\{7001, 7003, \.\.\.\}|15|3|18|
|cmdsched\_rsp\_test|随机|\{8001, 8003, \.\.\.\}|20|4|24|
|cmdsched\_excp\_perf\_test|定向|\{9001, 9002, \.\.\.\}|15|3|18|
|cmdsched\_random\_mix\_test|随机|\{10001, 10012, \.\.\.\}|40|8|48|

### 6\.3 种子筛选示例

以 cmdsched\_dep\_test 为例：

|种子范围|数量|覆盖率贡献|保留数|
|---|---|---|---|
|4001\-4100|100|贡献 50%|15|
|4101\-4200|100|贡献 30%|7|
|4201\-4300|100|贡献 20%|3|

**最终种子基线：25 个。**

### 6\.4 种子管理工具

|工具|能力|
|---|---|
|VCS urg \-grade|基于功能覆盖率对种子分级|
|VSO\.ai|AI 驱动的种子优化，减少 10 倍种子数|
|覆盖率合并|urg \-dir \*\.vdb \-cm merge|

## 7\. 覆盖率采样实现

### 7\.1 Covergroup 定义

以下为 CMD\_SCH 功能覆盖率模型的 covergroup 骨架，按第 3 章 10 个覆盖组组织；内部信号名以 RTL 实现为准，采样位置见 7\.2。

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
      bins tile_00 .. tile_31 = {[0:31]}; }  // Feat-22：8 SPAD × 4 tile 地址遍历

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

    // ============ 关键跨组交叉 ============
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

### 7\.2 采样位置原则

|原则|说明|
|---|---|
|在 monitor 采样|不在 sequence 采样，保证垂直复用|
|按子模块分 monitor|ITYPE/INSTB 在 decode\-ISTB 侧；DEP/MEM/ISSUE 在 scoreboard 侧；RSP 在 sp\_inst 侧；EXCP/PERF/CSR 在 cmd\_int\_perf 侧|
|联合采样激励和结果|区分"场景发生"和"场景正确处理"（如 hazard 产生 vs 正确阻塞）|
|用 iff 限定有效周期|复位、握手未成功、性能关闭等无效周期不采样|
|非法 bin 用 illegal\_bins|命中即报错（如保留指令编码、cmd\_int\[2\] 等）|
|参数类覆盖点独立采样|ISTB\_DP 等编译参数在各参数化回归中分别收集|
|新增覆盖点随组采样|cp\_spad\_tile\_map 在 scoreboard 侧随 MEM 组采样；cp\_wr\_lmem\_rmw 在 sp\_inst 侧随 RSP 组采样；cp\_third\_inst\_blocked 在 decode\-ISTB 侧随 UNIT 组采样；cp\_int\_info\_save 在 cmd\_int\_perf 侧随 EXCP 组采样|

## 8\. 需求追溯矩阵

以下按 HM057 CDD 3\.2 Feature List 逐条映射（Feat\-1\~40），确保无孤立需求、无孤立覆盖点。

|需求 ID|需求描述|优先级|覆盖组/覆盖点|约束|测试用例|状态|
|---|---|---|---|---|---|---|
|Feat\-1|支持各功能组件信息配置和启动|P0|UNIT：cp\_mst\_id, cp\_mst\_slot|c\_mst\_dist, c\_mst\_dual|cmdsched\_basic\_test|计划中|
|Feat\-2|支持指令间 sync 同步|P0|DEP：cp\_struct\_hazard\.sync\_all；RSP：cp\_rsp\_type\.sync\_rsp|c\_sync\_barrier|cmdsched\_rsp\_test|计划中|
|Feat\-3|删除 CPU 读取 csr 配置寄存器功能|P0|ITYPE：cp\_prim\_type\.il\_rd\_csr|c\_illegal\_inst|cmdsched\_excp\_perf\_test|计划中|
|Feat\-4|支持 CPU 读写 LMEM（SPAD）|P0|RSP：cp\_rsp\_type\.rd\_lmem\_rsp, cp\_wr\_lmem\_rmw；ITYPE：wr/rd\_lmem\_drv|c\_prim\_dist, c\_wr\_lmem\_rmw|cmdsched\_rsp\_test|计划中|
|Feat\-5|lmem 与 LLSU 指令 structure hazard|P0|DEP：cp\_struct\_hazard\.lmem\_llsu|c\_lmem\_llsu\_conflict|cmdsched\_hazard\_scope\_test|计划中|
|Feat\-6|删除 CIMC 的 1x4 形状|P0|MEM：cp\_cimc\_page\_occ\.cimc\_2x2|c\_cimc\_page\_addr|cmdsched\_mem\_test|计划中|
|Feat\-7|支持 NIU 指令间同步|P0|DEP：cp\_struct\_hazard\.noc\_fence；RSP：noc\_fence\_rsp|c\_noc\_fence\_barrier|cmdsched\_rsp\_test|计划中|
|Feat\-8|NIU 内部 load/store 并行|P0|UNIT：cp\_ls\_parallel\.niu\_ls\_par|c\_ls\_pair\_seq|cmdsched\_parallel\_test|计划中|
|Feat\-9|GLSU 内部 load/store 并行|P0|UNIT：cp\_ls\_parallel\.glsu\_ls\_par|c\_ls\_pair\_seq|cmdsched\_parallel\_test|计划中|
|Feat\-10|同组件两条指令无 structure hazard|P0|UNIT：cp\_mst\_slot\.both, cp\_third\_inst\_blocked；DEP：same\_mst|c\_same\_mst\_pair, c\_mst\_dual, c\_third\_inst\_blocked|cmdsched\_hazard\_scope\_test|计划中|
|Feat\-11|任意两组件 data hazard|P0|DEP：cp\_hazard\_scope\.two\_mst|c\_hazard\_scope\_2\~5|cmdsched\_hazard\_scope\_test|计划中|
|Feat\-12|任意三组件 data hazard|P0|DEP：cp\_hazard\_scope\.three\_mst|c\_hazard\_scope\_2\~5|cmdsched\_hazard\_scope\_test|计划中|
|Feat\-13|任意四组件 data hazard|P0|DEP：cp\_hazard\_scope\.four\_mst|c\_hazard\_scope\_2\~5|cmdsched\_hazard\_scope\_test|计划中|
|Feat\-14|五组件 data hazard|P0|DEP：cp\_hazard\_scope\.five\_mst|c\_hazard\_scope\_2\~5|cmdsched\_hazard\_scope\_test|计划中|
|Feat\-15|任意两组件并行执行|P0|UNIT：cp\_paral\_scope\.two\_mst|c\_multi\_parallel\_2\~5|cmdsched\_parallel\_test|计划中|
|Feat\-16|任意三组件并行执行|P0|UNIT：cp\_paral\_scope\.three\_mst|c\_multi\_parallel\_2\~5|cmdsched\_parallel\_test|计划中|
|Feat\-17|任意四组件并行执行|P0|UNIT：cp\_paral\_scope\.four\_mst|c\_multi\_parallel\_2\~5|cmdsched\_parallel\_test|计划中|
|Feat\-18|五组件并行执行|P0|UNIT：cp\_paral\_scope\.five\_mst|c\_multi\_parallel\_2\~5|cmdsched\_parallel\_test|计划中|
|Feat\-19|指令序列乱序发射（窗口 ISTB\_DP）|P0|INSTB：cp\_instb\_dp；ISSUE：cp\_issue\_path|c\_instb\_dp, c\_issue\_stall|cmdsched\_instb\_test|计划中|
|Feat\-20|支持多 xd=1 指令下发，带 tag 乱序返回|P0|RSP：cp\_rsp\_tag\.multi\_xd / tag\_ooot|c\_xd1\_seq, c\_tag\_out\_of\_order|cmdsched\_rsp\_test|计划中|
|Feat\-21|多组件访问同一 SPAD|P0|MEM：cp\_multi\_mst\_spad|c\_multi\_mst\_spad|cmdsched\_mem\_test|计划中|
|Feat\-22|按 tile 切分 SPAD，各组件占用/释放|P0|MEM：cp\_spad\_tile\_occ, cp\_spad\_tile\_map|c\_spad\_tile\_addr, c\_release\_early, c\_tile\_map\_spread|cmdsched\_mem\_test|计划中|
|Feat\-23|GLSU/LLSU 同时调用 TMU，GLSU 优先|P0|UNIT：cp\_tmu\_arb\.glsu\_pri\_contend|c\_tmu\_contend|cmdsched\_parallel\_test|计划中|
|Feat\-24|creg\_cmd\_icg\_en 扩展为 \[31:0\]|P1|CSR：cp\_csr\_icg|c\_csr\_icg|cmdsched\_excp\_perf\_test|计划中|
|Feat\-25|删除各组件低功耗模式|P1|CSR：cp\_idle\_icg, cp\_csr\_icg|c\_csr\_icg|cmdsched\_excp\_perf\_test|计划中|
|Feat\-26|支持读请求反压（i\_ch1\_req\_rrdy）|P0|RSP：cp\_backpressure\.rd\_bp|c\_backpressure\_seq|cmdsched\_rsp\_test|计划中|
|Feat\-27|支持写请求反压（i\_ch0\_req\_wrdy）|P0|RSP：cp\_backpressure\.wr\_bp|c\_backpressure\_seq|cmdsched\_rsp\_test|计划中|
|Feat\-28|异常指令产生中断并上报|P1|EXCP：cp\_int\_type\.cmd\_int0, cp\_int\_info\_save|c\_illegal\_inst, c\_int\_info\_save|cmdsched\_excp\_perf\_test|计划中|
|Feat\-29|读写非 SPAD 地址产生中断|P1|EXCP：cp\_int\_type\.cmd\_int0（非 SPAD）|c\_non\_spad\_addr|cmdsched\_excp\_perf\_test|计划中|
|Feat\-30|lmem\_drv 与 LLSU 同时工作产生中断|P0|EXCP：cp\_int\_type\.cmd\_int1；DEP：lmem\_llsu|c\_lmem\_llsu\_conflict|cmdsched\_excp\_perf\_test|计划中|
|Feat\-31|统计 MPU 指令在 ISTB 中的拥塞数|P1|PERF：cp\_perf\_cong\.mpu\_cong|c\_perf\_cong\_seq|cmdsched\_excp\_perf\_test|计划中|
|Feat\-32|统计 VPU 指令在 ISTB 中的拥塞数|P1|PERF：cp\_perf\_cong\.vpu\_cong|c\_perf\_cong\_seq|cmdsched\_excp\_perf\_test|计划中|
|Feat\-33|统计 GLSU 指令在 ISTB 中的拥塞数|P1|PERF：cp\_perf\_cong\.glsu\_cong|c\_perf\_cong\_seq|cmdsched\_excp\_perf\_test|计划中|
|Feat\-34|统计 LLSU 指令在 ISTB 中的拥塞数|P1|PERF：cp\_perf\_cong\.llsu\_cong|c\_perf\_cong\_seq|cmdsched\_excp\_perf\_test|计划中|
|Feat\-35|统计 NIU 指令在 ISTB 中的拥塞数|P1|PERF：cp\_perf\_cong\.niu\_cong|c\_perf\_cong\_seq|cmdsched\_excp\_perf\_test|计划中|
|Feat\-36|统计所有组件并行度|P1|PERF：cp\_perf\_paral\.total\_paral|c\_perf\_window|cmdsched\_excp\_perf\_test|计划中|
|Feat\-37|统计 MPU 并行度|P1|PERF：cp\_perf\_paral\.mpu\_paral|c\_perf\_window|cmdsched\_excp\_perf\_test|计划中|
|Feat\-38|debug0：各组件工作状态|P1|PERF：cp\_debug\_reg\.dbg0\_busy|寄存器比对|cmdsched\_excp\_perf\_test|计划中|
|Feat\-39|debug1：inst\_disp 总下发指令数|P1|PERF：cp\_debug\_reg\.dbg1\_inst\_cnt|寄存器比对|cmdsched\_excp\_perf\_test|计划中|
|Feat\-40|debug2：cmd\_sch 总发射指令数|P1|PERF：cp\_debug\_reg\.dbg2\_iss\_cnt|寄存器比对|cmdsched\_excp\_perf\_test|计划中|

**要求：不能有孤立需求，也不能有孤立覆盖点。**

## 9\. 覆盖率收敛签核标准

### 9\.1 签核条件

|条件|标准|
|---|---|
|功能覆盖点|100% bin 命中|
|交叉覆盖|100% 有意义组合命中|
|非法 bin|0 命中|
|忽略 bin|已审批并记录理由|
|需求追溯|无孤立需求，无孤立覆盖点（Feat\-1\~40 全部映射）|
|种子基线|已建立并纳入回归|
|豁免项|有理由、有审批人、有记录|
|回归稳定性|固定回归集覆盖率稳定|

### 9\.2 豁免流程

```plaintext
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

### 9\.3 豁免记录表

|Bin|所属覆盖点|豁免理由|审批人|日期|
|---|---|---|---|---|
|excl\_cfg|cp\_csr\_spad\_excl|独占 SPAD 模式当前架构暂不支持（creg\_cmd\_spad\_excl\_en 默认 0）|||

## 10\. 附录

### 10\.1 批次执行命令示例

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

### 10\.2 覆盖率组速查卡

```plaintext
┌──────────────────────────────────────────────┐
│  CG_CMDSCHED_ITYPE  → 指令类型（flag/功能/组件/primitive）│
│  CG_CMDSCHED_INSTB  → ISTB 管理（链表/深度/反压/拼接）    │
│  CG_CMDSCHED_DEP    → 数据依赖（RAW/WAW/WAR/结构冲突）    │
│  CG_CMDSCHED_UNIT   → 执行单元（5 MST/双槽/并行/TMU）     │
│  CG_CMDSCHED_ISSUE  → 发射决策（路径/优先级/start-done）  │
│  CG_CMDSCHED_MEM    → 存储资源（tile/page/dram/共享）     │
│  CG_CMDSCHED_RSP    → 返回值（类型/乱序/优先级/反压）     │
│  CG_CMDSCHED_EXCP   → 异常中断（cmd_int[0]/[1]/block）    │
│  CG_CMDSCHED_PERF   → 性能与 debug（并行度/拥塞/寄存器）  │
│  CG_CMDSCHED_CSR    → CSR 与低功耗（icg/使能/IDLE）       │
└──────────────────────────────────────────────┘
```

### 10\.3 常见坑清单

|坑|后果|避免方式|
|---|---|---|
|只采激励不采结果|无法区分"场景发生"和"正确处理"|联合采样（hazard 产生 vs 正确阻塞）|
|按地址而非 tile 粒度判断冲突|与 RTL hazard 判定口径不一致，覆盖率虚高/虚低|SPAD 冲突以 tile 为粒度（8 SPAD × 4 tile）|
|漏掉 NIU 特例|NIU 双 store、noc\_dst 单条等设计约束未验证|cp\_struct\_hazard 强制覆盖 niu\_dst/niu\_store|
|忽略后启动先 done 场景|GLSU/NIU load\-store 并行时序 bug 漏检|ls\_parallel\_seq \+ start1\_done0 断言|
|rls\_vld 时序未校验|资源提前释放错误导致 tile 占用泄漏|cp\_start\_done\_seq 覆盖 rls\_before/same\_done|
|乱序返回未校验 tag|多 xd=1 指令返回数据错位|cp\_rsp\_tag \+ scoreboard 按 tag 比对|
|TMU 竞争场景缺失|GLSU/LLSU 抢占仲裁 bug 漏检|c\_tmu\_contend 定向场景|
|已删除功能未做非法覆盖|rd\_csr、CIMC 1x4 等旧指令被误用|illegal\_bins 覆盖 il\_rd\_csr/il\_reserved|
|异常场景未配 block\_en|中断后停止/继续收发两种行为只验证一种|X\_excp\_block 交叉覆盖|
|忽略 ISTB\_DP 参数遍历|1/2/8 深度下链表与反压行为未验证|cp\_instb\_dp 各参数回归|
|忽略 bin 滥用|掩盖真实缺口|豁免需审批并记录|

## 11\. 文档变更记录

|版本|日期|修改人|修改内容|
|---|---|---|---|
|V\.0\.0\.1|2026\-10\-12|刘江清|建立 NPU\_V2\.CMDSCHED 功能覆盖率模板|
|V\.1\.0\.0|2026\-11\-03|刘江清|按 HM057 CDD（L5\-\[NPU\-HM057\]\-\[CDD\]\-CMD\_SCH\_Dev）全面更新：覆盖组对齐 5 个 MST/ISTB/scoreboard/异常/性能/CSR 架构，新增 10 个覆盖率组（ITYPE/INSTB/DEP/UNIT/ISSUE/MEM/RSP/EXCP/PERF/CSR），重写约束、批次、采样实现与 Feat\-1\~40 需求追溯矩阵|
|V\.1\.1\.0|2026\-11\-03|刘江清|完备性评审补齐：新增 4 个覆盖点——cp\_third\_inst\_blocked（第三条同组件指令阻塞，Feat\-10）、cp\_spad\_tile\_map（8 SPAD×4 tile 地址遍历，Feat\-22）、cp\_wr\_lmem\_rmw（wr\_lmem 读改写，Feat\-4）、cp\_int\_info\_save（中断现场保存，Feat\-28）；同步新增 c\_third\_inst\_blocked/c\_tile\_map\_spread/c\_wr\_lmem\_rmw/c\_int\_info\_save 约束与场景 11\~14，更新覆盖点计数、约束映射、追溯矩阵|

**本文档的核心思想：HM057 CMD\_SCH 的功能覆盖率按 CDD 功能维度划分为 10 个覆盖率组，每组聚焦一类功能契约；每个约束对准一个覆盖点的 bin；每个测试的种子基线由覆盖率平台期决定；每个批次由上一批的缺口驱动。约束、覆盖点、测试用例、种子基线四者形成闭环。**

> （注：部分内容由豆包工作 AI 生成）
