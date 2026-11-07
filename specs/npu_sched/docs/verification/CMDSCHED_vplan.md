# CMD_SCH 功能覆盖率验证计划（Spec Target Plan）

| 项 | 内容 |
|---|---|
| 文档编号 | CMDSCHED-VP-01（target） |
| 来源 | `docs/specs/cmdsched.md` |
| 对象 | HM057 NPU_V2 CMD_SCH |
| 状态 | **目标计划**：feature/TP/契约已建，全部 TP 为 `planned`，没有执行证据 |
| 当前执行状态 | 执行层尚未接入；当前只有 target plan，无执行门禁/证据 |
| 生成器 | `scripts/gen_spec_plan.py` |
| 配套分析 | `CMDSCHED_spec_analysis.md` |

> 本文只写验证结论和引用。feature、专题、TP、契约候选的明细在 `CMDSCHED_*.csv`；
> 矩阵由 `CMDSCHED_matrix.md` 展示。所有测试点当前都是 `planned`，不冒充已有证据。

## 1. 目的与范围

验证 CMD_SCH 作为**黑盒命令调度器**的以下能力：

- 指令接收、解析、配置/启动；
- SHazard / DHazard、地址范围冲突、依赖阻塞；
- OST=2、decode/cfg-drv/master 反压链；
- 乱序发射、多 xd=1 乱序返回；
- SPAD tile/page/DRAM 资源、tile_rls 释放；
- 多组件并行、GLSU/LLSU TMU 竞争；
- 非法指令/地址、中断现场/清除、block_en；
- debug/perf 可观测性、ICG/复位；
- 典型分发吞吐 1 指令/cycle。

**不在本轮 demo 内**：真实 UVM/VCS 执行、urg 覆盖率、功耗/电源域、FPGA/样片。它们属于后续落地阶段。

## 2. 验证策略：黑盒 feature 树 × 专题

### 2.1 组织轴

- **feature 树**：从主功能域按路径/资源/并行/竞争/时序拆分。
- **专题**：接口、时钟复位、参数和配置、数据值域、数据形状、错误异常、中间复位、边界、流控和反压、性能长稳。
- **测试点**：feature × 专题的可判定条件，可挂在任意节点；父节点由子节点汇总。
- **case**：执行容器，只通过 `case_plan` 映射，不作为组织轴。

| 黑盒维度 | 树上的体现 |
|---|---|
| 路径 | CMD_IN、SCHED、RSP |
| 路径上的资源 | OST2/ins_buffer、MEM(tile/page/dram)、LMEM、RELEASE |
| 一级多路并行 | PAR/MST、PAR/LS |
| 多路竞争 | PAR/TMU、SH、DH、RANGE、xbar 仲裁 |
| 复杂输入输出时序 | HS、ISSUE、XD1、PRIO、BP |
| 黑盒描述 | 叶子只描述 Ins Dispatcher/SPAD/master 可见行为，不映射 RTL 模块 |

### 2.2 Feature 拆分树

```text
1      CMDSCHED (root, 黑盒)
1.1    CMD_IN (branch)       命令输入与解码路径
1.1.1  HS (leaf)             指令握手与反压
1.1.2  DECODE (leaf)         指令解析/配置/精度
1.1.3  OST2 (leaf)           指令 outstanding=2 与缓冲
1.2    SCHED (branch)        调度/依赖/发射
1.2.1  SH (leaf)             结构冒险 sync/noc_fence/lmem-LLSU
1.2.2  DH (leaf)             数据冒险 RAW/WAW/WAR 与粒度
1.2.3  RANGE (leaf)          地址范围冲突 tile/dram
1.2.4  ISSUE (leaf)          乱序发射与 ins_buffer 窗口
1.3    PAR (branch)          并行与竞争
1.3.1  MST (leaf)            2~5 组件并行/同组件双 drv
1.3.2  LS (leaf)             GLSU/NIU load/store 并行
1.3.3  TMU (leaf)            GLSU/LLSU TMU 竞争
1.4    MEM (branch)          SPAD/page/dram 资源
1.4.1  TILE (leaf)           SPAD tile 切分/冲突
1.4.2  PAGEDRAM (leaf)       CIMC page/DRAM 整块
1.4.3  SHARE (leaf)          多组件共享 SPAD/xbar 仲裁
1.4.4  RELEASE (leaf)        tile/page/dram 释放
1.4.5  LMEM (leaf)           CPU LMEM 读写/RMW
1.5    RSP (branch)          响应输出路径
1.5.1  XD1 (leaf)            多 xd=1 乱序返回/tag
1.5.2  PRIO (leaf)           rsp_fifo 优先级
1.5.3  BP (leaf)             读/写/scalar/istb 反压
1.6    EXC (branch)          异常与中断
1.6.1  ILLEGAL (leaf)        非法编码/rd_csr/reserved
1.6.2  ADDR (leaf)           非 SPAD 地址/lmem-CIMC
1.6.3  INT (leaf)            中断现场/清除
1.6.4  BLOCK (leaf)          block_en 停止/恢复
1.7    CFG (branch)          配置/启动/CSR
1.7.1  START (leaf)          组件启动/cfg/pre 时序
1.7.2  COREREG (leaf)        cfg 信息存 core_reg
1.7.3  CSRCIMC (leaf)        CSR 默认值/icg/tile_rls/spad_excl/CIMC 2x2
1.8    DBGPERF (branch)      debug/性能可观测
1.8.1  DBG (leaf)            debug0/1/2 计数
1.8.2  PERF (leaf)           并行度/拥塞/窗口
1.9    LP (branch)           低功耗/复位
1.9.1  ICG (leaf)            IDLE/ICG 开关
1.9.2  RST (leaf)            中间复位/复位恢复
```

明细：`CMDSCHED_features.csv`（39 节点 = 1 root + 9 branch + 29 leaf）。

## 3. 测试点分解

| branch | 测试点数 | 说明 |
|---|---|---|
| CMD_IN | 8 | 握手、反压、解码、OST2 |
| SCHED | 13 | SH/DH、地址范围、乱序发射 |
| PAR | 6 | 2~5 组件、LS 并行、TMU 竞争 |
| MEM | 11 | tile/page/dram、共享 SPAD、释放、LMEM |
| RSP | 7 | xd=1、优先级、反压、返回类型 |
| EXC | 6 | 非法编码/地址、中断、block |
| CFG | 8 | 启动、core_reg、CSR/CIMC、spad_excl、done/rls |
| DBGPERF | 3 | debug/perf 计数 |
| LP | 4 | ICG、中间复位 |
| **合计** | **66** | 全部 `planned` |

测试点明细：`CMDSCHED_testpoints.csv`。

示例：

```text
TP_SCHED_DH_001  F-SCHED-DH × 数据形状
  stimulus: 构造 2~5 组件 RAW/WAW/WAR 依赖链
  expected: 依赖关系正确阻塞/放行
  contract: C-FUNC-DEP-006
  case_plan: TC_CMDSCHED_DEP_001
  status: planned
```

## 4. 契约候选

从 spec 和架构约束提取 42 条 spec 契约（`CMDSCHED_contracts.csv`）。其中 **40 条已以 `assume` 写入 `data/contract_matrix/`**，2 条（`C-IF-HS-001`、`C-FUNC-RSP-001`）与现有 active 契约合并。按类别：

| 类别 | 数量 | 示例 |
|---|---|---|
| 接口 | 4 | C-IF-HS-001、C-IF-START-001 |
| 功能 | 13 | C-FUNC-DEP-002/006、C-FUNC-ISSUE-001 |
| 数据 | 4 | C-DATA-TAG-001、C-DATA-RMW-001 |
| 性能/时序 | 4 | C-PERF-TMU-001、C-PERF-START-DONE-001 |
| 配置 | 4 | C-CFG-CSR-001、C-CFG-CIMC-001 |
| 资源 | 5 | C-RES-TILE-001、C-RES-RLS-001 |
| 异常 | 5 | C-EXC-ILLEGAL-001、C-EXC-INT-001 |
| 可观测 | 1 | C-DBG-REG-001 |
| 低功耗 | 2 | C-LP-IDLE-001、C-LP-RST-001 |

**注意**：40 条已按 13 列契约矩阵以 `assume` 入库，`check_artifact` 为占位（`spec_<class>_artifact`），`gate_matrix` 只校验 assumption；它们尚未转 `active`，因为还没有真实 case、检查产物和 URG 证据。2 条合并契约直接复用现有 active 契约。

## 5. Case 与批次计划

| case_plan | 批次 | 目标 |
|---|---|---|
| TC_CMDSCHED_BASIC_001 | 1 | 基础配置/启动/握手 |
| TC_CMDSCHED_ITYPE_001 | 2 | 指令类型/精度/组合 |
| TC_CMDSCHED_INSTB_001 | 3 | ins_buffer/乱序发射 |
| TC_CMDSCHED_DEP_001 | 4 | SHazard/DHazard |
| TC_CMDSCHED_HAZARD_001 | 5 | 2~5 组件依赖/第三条指令阻塞 |
| TC_CMDSCHED_PARALLEL_001 | 6 | 并行/TMU 竞争 |
| TC_CMDSCHED_MEM_001 | 7 | tile/page/dram/共享 SPAD |
| TC_CMDSCHED_RSP_001 | 8 | xd=1/优先级/反压 |
| TC_CMDSCHED_EXCP_001 | 9 | 异常/中断/block |
| TC_CMDSCHED_PERF_001 | 10 | 性能/拥塞/debug |
| TC_CMDSCHED_CSR_001 | P1 | CSR/ICG/复位 |
| TC_CMDSCHED_REL_001 | P1 | 可靠性/中间复位/长稳 |

以上 12 个 case 已落到 `docs/specs/cmdsched_cases.csv`（输出 `CMDSCHED_cases.csv` 与 `CMDSCHED_case_trace.md`），覆盖 42/42 契约和 66/66 TP；状态仍为 `planned`，不参与执行门禁。建议先跑通 `TC_CMDSCHED_RSP_001` 样板，再扩到 10 批次。

## 6. 覆盖率计划

### 6.1 Covergroup 候选

| CG | 目标 |
|---|---|
| CG_CMDSCHED_ITYPE | 指令类型、primitive、合法/非法编码 |
| CG_CMDSCHED_INSTB | ins_buffer 深度/链/发射路径 |
| CG_CMDSCHED_DEP | SHazard/DHazard 类型/粒度/范围 |
| CG_CMDSCHED_UNIT | master、slot、并行度、第三条指令、TMU |
| CG_CMDSCHED_ISSUE | 发射路径/优先级/start-done |
| CG_CMDSCHED_MEM | tile/page/dram、共享 SPAD、释放 |
| CG_CMDSCHED_RSP | 返回类型/数据/tag/优先级/反压/RMW |
| CG_CMDSCHED_EXCP | 中断类型/block/清除/现场 |
| CG_CMDSCHED_PERF | 并行度/拥塞/debug/perf |
| CG_CMDSCHED_CSR | CSR 默认值/ICG/tile_rls/spad_excl |

目标：CP 100%、cross 100%、illegal bin 0 命中；未覆盖项逐条评审/豁免。

### 6.2 代码/断言覆盖

- 代码覆盖：statement / branch / condition / toggle 均 100%。
- 功能覆盖：基于 Feature List 的 covergroup，>95% 且未覆盖项有豁免。
- 断言覆盖：所有植入断言至少触发一次。

## 7. 回归与种子

- 批次 1~10 逐级激活：BASIC → ITYPE → INSTB → DEP → HAZARD → PARALLEL → MEM → RSP → EXCP/PERF → RANDOM_MIX。
- 每批从 baseline 种子开始，稳定后进入 explore；平台期后归档 history。
- 回归目标：100% pass；失败必须定位到 case/contract/feature。
- 建议 nightly 全量、每周 explore、发布前 full + signoff。

## 8. 签核标准

1. 41 条 assume 契约（40 条 spec + `C-ENV-ROBUST-001`）逐条转 active，或继续 assume/exempt 并有明确理由；2 条合并契约确认绑定。
2. 66 个测试点全部转为 `covered` 或有 `exempt` 记录；`planned` 不得带入签核。
3. CP 100%、cross 100%、illegal 0；代码覆盖率 100%（或批准豁免）。
4. 断言覆盖率 100%；所有 SVA/Checker/SCB 均激活。
5. 回归 100% pass；种子可复现。
6. `reports/gate_report.json` 全绿；`reports/gate_report.xlsx` 评审通过。

## 9. 追溯关系

```text
spec 1.3/4/5/7/8/9/10
  → feature 树 (CMDSCHED_features.csv)
    → 测试点 (CMDSCHED_testpoints.csv)
      → 契约候选 (CMDSCHED_contracts.csv)
        → case_plan / 批次
          → 待实现的 UVM/urg 证据
            → 门禁/签核
```

| spec 章节 | 主要 feature |
|---|---|
| 1.3-1/2/3 | CFG/CSR、DECODE、EXC/ILLEGAL |
| 1.3-4/10 | MEM/SHARE、PAR/TMU |
| 1.3-5/6 | OST2、SCHED/SH、PAR/MST |
| 1.3-7 | SCHED/ISSUE |
| 1.3-8 | RSP/XD1、RSP/BP |
| 1.3-9/12/13 | MEM/TILE、MEM/RELEASE、SCHED/RANGE |
| 1.3-11 | CFG/COREREG |
| 4 | 全部功能 feature |
| 5/7 | 约束、非法/边界 TP |
| 6 | LP/ICG、LP/RST |
| 8 | EXC 全部 |
| 9/10 | PERF/CNT、签核口径 |

## 10. 风险与待决

| 风险 | 影响 | 处理 |
|---|---|---|
| 40 条 spec 契约仍为 assume | 未进入 active 门禁 | 补 case/检查产物/URG 证据后逐条转 active |
| 66 个 TP 全为 planned | 没有真实覆盖证据 | 先做 RSP 样板，再扩批次 |
| CP/cross 尚未落到 SV | 功能覆盖率不可测 | 把 CG/CP/cross 写成真实 covergroup |
| 真实 UVM/VCS/urg 未接 | case view/门禁仍是 target | 下一阶段补 sim/regression/evidence |
| NIU AXI ID / 跨 cluster noc 未决 | 依赖/性能验证范围不确定 | 架构评审关闭 |
| 代码覆盖率 100% 与功能 >95% 口径 | 签核标准冲突 | 项目层面固化 |

## 11. 与执行阶段的关系

- 执行层尚未接入；当前没有可执行仿真或证据。
- `CMDSCHED_*` 是真实 arch spec 的目标计划：42 条契约在 `data/contract_matrix/`（当前 8 active / 34 assume），66 个 TP、12 个 planned case 已建立；active 由 gate 依据 run 证据推进。
- 下一步：选 `TC_CMDSCHED_RSP_001` 做首个真实 UVM/VCS/URG 样板，补 SVA/Checker/SCB/coverage 资产并转 active；再复制到其余 11 个 planned case。
