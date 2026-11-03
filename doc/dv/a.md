# NPU 指令调度器功能覆盖率计划文档

| 字段 | 内容 |
|---|---|
| 模块/IP | NPU Instruction Scheduler |
| 文档版本 | v1.0 |
| 验证负责人 | |
| 设计负责人 | |
| 最后更新 | |
| 关联需求文档 | |
| 关联验证计划 | |


## 1. 概述

### 1.1 目的

本文档定义 NPU 指令调度器（Instruction Scheduler）的功能覆盖率模型、配套约束设计及种子管理策略，建立**约束 → 激励 → 覆盖率 → 收敛**的完整闭环，确保验证完备性可度量、可追溯、可签核。

### 1.2 范围

覆盖 NPU 指令调度器的以下功能维度：

- 指令队列管理（水位、满/空）
- 指令类型调度（MAC/Vector/Scalar/DMA）
- 数据类型调度（INT8/FP16/BF16/FP32）
- 数据依赖处理（RAW/WAW/WAR）
- 执行单元分配与冲突
- 多簇调度
- 算子类型调度（Conv/MatMul/Activation/Pooling）
- 流水线控制（stall/flush/barrier）

### 1.3 术语

| 术语 | 含义 |
|---|---|
| MAC | Multiply-Accumulate，乘累加单元 |
| Vector | 向量处理单元 |
| Scalar | 标量处理单元 |
| DMA | Direct Memory Access，直接内存访问 |
| Tile | 张量分块，NPU 调度的基本数据单位 |
| Cluster | 多个 NPU Core 组成的簇 |
| Barrier | 同步屏障 |
| RAW | Read After Write，真数据依赖 |
| WAW | Write After Write，输出依赖 |
| WAR | Write After Read，反依赖 |
| CP | Coverpoint，功能覆盖点 |
| CG | Coverage Group，覆盖率组 |
| Bin | 覆盖点内的一个取值区间或条件 |
| Cross | 交叉覆盖 |
| 种子基线 | 回归时固定使用的随机种子集合 |
| 平台期 | 增加种子数覆盖率不再显著增长的拐点 |


## 2. 设计功能概述

### 2.1 调度器职责

NPU 指令调度器位于主控（CPU/固件）与执行单元之间，负责：

1. 接收来自主控的指令流，写入指令队列
2. 将指令分发到不同类型的执行单元
3. 检查数据依赖，决定发射顺序
4. 管理指令队列，处理满/空
5. 处理多簇的指令同步
6. 管理 DMA 与计算单元的内存访问
7. 响应屏障和冲刷请求

### 2.2 接口信号

| 信号 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 时钟 |
| rst_n | input | 1 | 异步复位，低有效 |
| instr_valid | input | 1 | 指令有效 |
| instr_opcode | input | 8 | 操作码 |
| instr_type | input | 3 | 指令类型 |
| instr_dtype | input | 3 | 数据类型 |
| instr_tile_id | input | 8 | Tile ID |
| instr_src_addr | input | 32 | 源地址 |
| instr_dst_addr | input | 32 | 目的地址 |
| issue_valid | output | 1 | 发射有效 |
| issue_unit | output | 3 | 执行单元 |
| issue_decision | output | 2 | 发射决策 |
| queue_level | internal | 6 | 队列水位 |
| dep_type | internal | 2 | 依赖类型 |
| cluster_id | internal | 2 | 簇 ID |


## 3. 功能覆盖率组与覆盖点

### 3.1 覆盖率组总览

按功能维度将覆盖点划分为 8 个覆盖率组（Coverage Group），每个组聚焦一类功能契约。

| CG ID | 覆盖率组名称 | 需求 ID | 覆盖点数 | 交叉数 | Bin 总数 | 目标 |
|---|---|---|---|---|---|---|
| CG_NPU_QUEUE | 队列管理覆盖组 | REQ-NPU-001 | 1 | 1 | 10 | 100% |
| CG_NPU_TYPE | 指令类型覆盖组 | REQ-NPU-002 | 1 | 1 | 8 | 100% |
| CG_NPU_DTYPE | 数据类型覆盖组 | REQ-NPU-003 | 1 | 1 | 8 | 100% |
| CG_NPU_DEP | 依赖处理覆盖组 | REQ-NPU-004 | 1 | 1 | 6 | 100% |
| CG_NPU_UNIT | 执行单元覆盖组 | REQ-NPU-005 | 1 | 1 | 16 | 100% |
| CG_NPU_DECISION | 发射决策覆盖组 | REQ-NPU-006 | 1 | 1 | 10 | 100% |
| CG_NPU_CLUSTER | 簇调度覆盖组 | REQ-NPU-007 | 1 | 0 | 4 | 100% |
| CG_NPU_OPCODE | 算子类型覆盖组 | REQ-NPU-008 | 1 | 0 | 8 | 100% |

**覆盖组之间的关系：**

```text
CG_NPU_QUEUE ──┐
CG_NPU_TYPE  ──┤
CG_NPU_DTYPE ──┼──→ 跨组交叉：X_NPU_TYPE_UNIT, X_NPU_DTYPE_UNIT
CG_NPU_UNIT  ──┤                  X_NPU_DEP_DEC, X_NPU_QUEUE_DEC
CG_NPU_DEP   ──┤                  X_NPU_UNIT_CLUSTER
CG_NPU_DECISION ─┘
```

**每个覆盖率组内包含：**
- 一个或多个覆盖点（coverpoint）
- 组内交叉（cross）
- 组内非法 bin 和忽略 bin


### 3.2 CG_NPU_QUEUE：队列管理覆盖组

#### 3.2.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_QUEUE |
| 需求 ID | REQ-NPU-001：调度器支持 0-32 条指令的队列深度 |
| 功能描述 | 覆盖指令队列从空到满的所有关键水位 |
| 采样信号 | `queue_level` |
| 采样事件 | `@(posedge clk) iff instr_valid \|\| issue_valid` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.2.2 覆盖点定义

##### CP_NPU_QUEUE_001：指令队列水位

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_QUEUE_001 |
| 覆盖点名称 | cp_queue_level |
| 采样信号 | `queue_level` |
| Bin 数 | 6 normal + 1 illegal |

```systemverilog
cp_queue_level: coverpoint queue_level {
  bins empty     = {0};
  bins low       = {[1:7]};
  bins mid       = {[8:15]};
  bins high      = {[16:24]};
  bins near_full = {[25:31]};
  bins full      = {32};
  illegal_bins illegal_over = {[33:$]};
}
```

##### Bin 说明

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| empty | normal | `queue_level == 0` | 空队列 |
| low | normal | `queue_level in [1:7]` | 低水位 |
| mid | normal | `queue_level in [8:15]` | 中水位 |
| high | normal | `queue_level in [16:24]` | 高水位 |
| near_full | normal | `queue_level in [25:31]` | 接近满 |
| full | normal | `queue_level == 32` | 满队列 |
| illegal_over | illegal | `queue_level > 32` | 非法超限 |

#### 3.2.3 组内交叉

##### X_NPU_QUEUE_DEC_001：队列水位 × 发射决策

| 项目 | 内容 |
|---|---|
| 交叉 ID | X_NPU_QUEUE_DEC_001 |
| 交叉对象 | `cp_queue_level` × `cp_issue_decision` |
| 目的 | 验证不同水位下调度器的发射决策是否正确 |
| Bin 数 | 4 |

```systemverilog
X_queue_decision: cross cp_queue_level, cp_issue_decision {
  bins full_blocked      = binsof(cp_queue_level.full)      && binsof(cp_issue_decision.blocked);
  bins near_full_stalled = binsof(cp_queue_level.near_full) && binsof(cp_issue_decision.stalled);
  bins empty_issued      = binsof(cp_queue_level.empty)     && binsof(cp_issue_decision.issued);
  bins low_issued        = binsof(cp_queue_level.low)       && binsof(cp_issue_decision.issued);
}
```

| 交叉 Bin | 条件 | 说明 |
|---|---|---|
| full_blocked | `full && blocked` | 满队列时阻塞 |
| near_full_stalled | `near_full && stalled` | 接近满时停顿 |
| empty_issued | `empty && issued` | 空队列时发射 |
| low_issued | `low && issued` | 低水位时发射 |

#### 3.2.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_full_queue` | `full_queue_seq` | full, full_blocked |
| `c_size` | `npu_stream` | low, mid, high |
| `c_queue_rate` | `npu_stream` | empty, low |


### 3.3 CG_NPU_TYPE：指令类型覆盖组

#### 3.3.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_TYPE |
| 需求 ID | REQ-NPU-002：调度器支持 MAC/Vector/Scalar/DMA 四类指令 |
| 功能描述 | 覆盖所有指令类型及其与执行单元的映射 |
| 采样信号 | `instr_type` |
| 采样事件 | `@(posedge clk) iff instr_valid` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.3.2 覆盖点定义

##### CP_NPU_TYPE_001：指令类型

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_TYPE_001 |
| 覆盖点名称 | cp_instr_type |
| 采样信号 | `instr_type` |
| Bin 数 | 4 normal |

```systemverilog
cp_instr_type: coverpoint instr_type {
  bins mac    = {MAC};
  bins vector = {VECTOR};
  bins scalar = {SCALAR};
  bins dma    = {DMA};
}
```

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| mac | normal | `instr_type == MAC` | 乘累加指令 |
| vector | normal | `instr_type == VECTOR` | 向量指令 |
| scalar | normal | `instr_type == SCALAR` | 标量指令 |
| dma | normal | `instr_type == DMA` | DMA 指令 |

#### 3.3.3 组内交叉

##### X_NPU_TYPE_UNIT_001：指令类型 × 执行单元

| 项目 | 内容 |
|---|---|
| 交叉 ID | X_NPU_TYPE_UNIT_001 |
| 交叉对象 | `cp_instr_type` × `cp_exec_unit` |
| 目的 | 验证每类指令正确路由到对应执行单元 |
| Bin 数 | 4 normal + 1 illegal |

```systemverilog
X_type_unit: cross cp_instr_type, cp_exec_unit {
  bins mac_to_mac       = binsof(cp_instr_type.mac)    && binsof(cp_exec_unit.mac);
  bins vec_to_vec       = binsof(cp_instr_type.vector) && binsof(cp_exec_unit.vector);
  bins scalar_to_scalar = binsof(cp_instr_type.scalar) && binsof(cp_exec_unit.scalar);
  bins dma_to_dma       = binsof(cp_instr_type.dma)    && binsof(cp_exec_unit.dma);
  illegal_bins mac_to_dma = binsof(cp_instr_type.mac) && binsof(cp_exec_unit.dma);
}
```

| 交叉 Bin | 条件 | 类型 | 说明 |
|---|---|---|---|
| mac_to_mac | `mac && mac` | normal | MAC 指令到 MAC 单元 |
| vec_to_vec | `vector && vector` | normal | 向量指令到向量单元 |
| scalar_to_scalar | `scalar && scalar` | normal | 标量指令到标量单元 |
| dma_to_dma | `dma && dma` | normal | DMA 指令到 DMA 单元 |
| mac_to_dma | `mac && dma` | illegal | MAC 指令不应到 DMA 单元 |

#### 3.3.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_type_dist` | `npu_instr` | mac, vector, scalar, dma |
| `c_dma_compute` | `dma_compute_seq` | dma_to_dma, mac_to_mac |


### 3.4 CG_NPU_DTYPE：数据类型覆盖组

#### 3.4.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_DTYPE |
| 需求 ID | REQ-NPU-003：调度器支持 INT8/FP16/BF16/FP32 四种数据类型 |
| 功能描述 | 覆盖所有数据类型及其与执行单元的组合 |
| 采样信号 | `instr_dtype` |
| 采样事件 | `@(posedge clk) iff instr_valid` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.4.2 覆盖点定义

##### CP_NPU_DTYPE_001：数据类型

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_DTYPE_001 |
| 覆盖点名称 | cp_dtype |
| 采样信号 | `instr_dtype` |
| Bin 数 | 4 normal |

```systemverilog
cp_dtype: coverpoint instr_dtype {
  bins int8 = {INT8};
  bins fp16 = {FP16};
  bins bf16 = {BF16};
  bins fp32 = {FP32};
}
```

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| int8 | normal | `instr_dtype == INT8` | 8位整数 |
| fp16 | normal | `instr_dtype == FP16` | 16位浮点 |
| bf16 | normal | `instr_dtype == BF16` | 16位脑浮点 |
| fp32 | normal | `instr_dtype == FP32` | 32位浮点 |

#### 3.4.3 组内交叉

##### X_NPU_DTYPE_UNIT_001：数据类型 × 执行单元

| 项目 | 内容 |
|---|---|
| 交叉 ID | X_NPU_DTYPE_UNIT_001 |
| 交叉对象 | `cp_dtype` × `cp_exec_unit` |
| 目的 | 验证每种数据类型在正确执行单元上处理 |
| Bin 数 | 4 normal + 1 illegal |

```systemverilog
X_dtype_unit: cross cp_dtype, cp_exec_unit {
  bins int8_mac    = binsof(cp_dtype.int8) && binsof(cp_exec_unit.mac);
  bins fp16_mac    = binsof(cp_dtype.fp16) && binsof(cp_exec_unit.mac);
  bins bf16_mac    = binsof(cp_dtype.bf16) && binsof(cp_exec_unit.mac);
  bins fp32_vector = binsof(cp_dtype.fp32) && binsof(cp_exec_unit.vector);
  illegal_bins int8_vector = binsof(cp_dtype.int8) && binsof(cp_exec_unit.vector);
}
```

| 交叉 Bin | 条件 | 类型 | 说明 |
|---|---|---|---|
| int8_mac | `int8 && mac` | normal | INT8 在 MAC 单元 |
| fp16_mac | `fp16 && mac` | normal | FP16 在 MAC 单元 |
| bf16_mac | `bf16 && mac` | normal | BF16 在 MAC 单元 |
| fp32_vector | `fp32 && vector` | normal | FP32 在向量单元 |
| int8_vector | `int8 && vector` | illegal | INT8 不应到向量单元 |

#### 3.4.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_dtype_dist` | `npu_instr` | int8, fp16, bf16, fp32 |
| `c_dtype_mix` | `dtype_mix_seq` | 所有 dtype × unit |


### 3.5 CG_NPU_DEP：依赖处理覆盖组

#### 3.5.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_DEP |
| 需求 ID | REQ-NPU-004：调度器正确处理 RAW/WAW/WAR/无依赖 |
| 功能描述 | 覆盖所有依赖类型及其对应的调度决策 |
| 采样信号 | `dep_type` |
| 采样事件 | `@(posedge clk) iff instr_valid` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.5.2 覆盖点定义

##### CP_NPU_DEP_001：依赖类型

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_DEP_001 |
| 覆盖点名称 | cp_dep_type |
| 采样信号 | `dep_type` |
| Bin 数 | 4 normal |

```systemverilog
cp_dep_type: coverpoint dep_type {
  bins no_dep = {NONE};
  bins raw    = {RAW};
  bins waw    = {WAW};
  bins war    = {WAR};
}
```

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| no_dep | normal | `dep_type == NONE` | 无依赖 |
| raw | normal | `dep_type == RAW` | 读后写 |
| waw | normal | `dep_type == WAW` | 写后写 |
| war | normal | `dep_type == WAR` | 写后读 |

#### 3.5.3 组内交叉

##### X_NPU_DEP_DEC_001：依赖类型 × 发射决策

| 项目 | 内容 |
|---|---|
| 交叉 ID | X_NPU_DEP_DEC_001 |
| 交叉对象 | `cp_dep_type` × `cp_issue_decision` |
| 目的 | 验证每种依赖类型下调度器的决策是否正确 |
| Bin 数 | 6 normal |

```systemverilog
X_dep_decision: cross cp_dep_type, cp_issue_decision {
  bins raw_stalled    = binsof(cp_dep_type.raw)    && binsof(cp_issue_decision.stalled);
  bins raw_issued     = binsof(cp_dep_type.raw)    && binsof(cp_issue_decision.issued);
  bins waw_stalled    = binsof(cp_dep_type.waw)    && binsof(cp_issue_decision.stalled);
  bins war_stalled    = binsof(cp_dep_type.war)    && binsof(cp_issue_decision.stalled);
  bins no_dep_issued  = binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.issued);
  bins no_dep_blocked = binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.blocked);
}
```

| 交叉 Bin | 条件 | 说明 |
|---|---|---|
| raw_stalled | `raw && stalled` | RAW 依赖导致停顿 |
| raw_issued | `raw && issued` | RAW 依赖但成功发射 |
| waw_stalled | `waw && stalled` | WAW 依赖导致停顿 |
| war_stalled | `war && stalled` | WAR 依赖导致停顿 |
| no_dep_issued | `no_dep && issued` | 无依赖正常发射 |
| no_dep_blocked | `no_dep && blocked` | 无依赖但被结构冲突阻塞 |

#### 3.5.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_dep_dist` | `npu_instr` | no_dep, raw, waw, war |
| `c_raw` | `npu_stream` | raw_stalled, raw_issued |
| `c_waw` | `npu_stream` | waw_stalled |
| `c_war` | `npu_stream` | war_stalled |
| `c_raw_chain` | `raw_chain_seq` | raw_stalled |


### 3.6 CG_NPU_UNIT：执行单元覆盖组

#### 3.6.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_UNIT |
| 需求 ID | REQ-NPU-005：调度器支持 MAC/Vector/Scalar/DMA 四个执行单元 |
| 功能描述 | 覆盖所有执行单元及其与簇的组合 |
| 采样信号 | `issue_unit` |
| 采样事件 | `@(posedge clk) iff issue_valid` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.6.2 覆盖点定义

##### CP_NPU_UNIT_001：执行单元

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_UNIT_001 |
| 覆盖点名称 | cp_exec_unit |
| 采样信号 | `issue_unit` |
| Bin 数 | 4 normal |

```systemverilog
cp_exec_unit: coverpoint issue_unit {
  bins mac    = {MAC};
  bins vector = {VECTOR};
  bins scalar = {SCALAR};
  bins dma    = {DMA};
}
```

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| mac | normal | `issue_unit == MAC` | 乘累加单元 |
| vector | normal | `issue_unit == VECTOR` | 向量单元 |
| scalar | normal | `issue_unit == SCALAR` | 标量单元 |
| dma | normal | `issue_unit == DMA` | DMA 单元 |

#### 3.6.3 组内交叉

##### X_NPU_UNIT_CLUSTER_001：执行单元 × 簇

| 项目 | 内容 |
|---|---|
| 交叉 ID | X_NPU_UNIT_CLUSTER_001 |
| 交叉对象 | `cp_exec_unit` × `cp_cluster` |
| 目的 | 验证每个簇中的执行单元都被使用 |
| Bin 数 | 16 normal |

```systemverilog
X_unit_cluster: cross cp_exec_unit, cp_cluster;
```

| 交叉 Bin | 条件 |
|---|---|
| mac×c0, mac×c1, mac×c2, mac×c3 | MAC 单元在 4 个簇中 |
| vector×c0 ~ c3 | 向量单元在 4 个簇中 |
| scalar×c0 ~ c3 | 标量单元在 4 个簇中 |
| dma×c0 ~ c3 | DMA 单元在 4 个簇中 |

#### 3.6.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_type_dist` | `npu_instr` | mac, vector, scalar, dma |
| `c_multi_cluster` | `multi_cluster_seq` | 所有单元×簇 |


### 3.7 CG_NPU_DECISION：发射决策覆盖组

#### 3.7.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_DECISION |
| 需求 ID | REQ-NPU-006：调度器正确做出发射/停顿/阻塞/冲刷决策 |
| 功能描述 | 覆盖所有发射决策类型及其触发条件 |
| 采样信号 | `issue_decision` |
| 采样事件 | `@(posedge clk)` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.7.2 覆盖点定义

##### CP_NPU_DECISION_001：发射决策

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_DECISION_001 |
| 覆盖点名称 | cp_issue_decision |
| 采样信号 | `issue_decision` |
| Bin 数 | 4 normal |

```systemverilog
cp_issue_decision: coverpoint issue_decision {
  bins issued  = {ISSUED};
  bins stalled = {STALLED};
  bins blocked = {BLOCKED};
  bins flushed = {FLUSHED};
}
```

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| issued | normal | `issue_decision == ISSUED` | 成功发射 |
| stalled | normal | `issue_decision == STALLED` | 依赖停顿 |
| blocked | normal | `issue_decision == BLOCKED` | 结构冲突阻塞 |
| flushed | normal | `issue_decision == FLUSHED` | 被冲刷 |

#### 3.7.3 组内交叉

发射决策覆盖组不定义组内交叉，其交叉覆盖分布在其他组中：

| 交叉 ID | 交叉对象 | 所在组 |
|---|---|---|
| X_NPU_QUEUE_DEC_001 | 队列水位 × 发射决策 | CG_NPU_QUEUE |
| X_NPU_DEP_DEC_001 | 依赖类型 × 发射决策 | CG_NPU_DEP |

#### 3.7.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_raw_chain` | `raw_chain_seq` | stalled |
| `c_full_queue` | `full_queue_seq` | blocked |
| `c_contention` | `contention_seq` | blocked |
| `c_flush` | `flush_seq` | flushed |


### 3.8 CG_NPU_CLUSTER：簇调度覆盖组

#### 3.8.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_CLUSTER |
| 需求 ID | REQ-NPU-007：调度器支持 4 个簇 |
| 功能描述 | 覆盖所有簇的调度行为 |
| 采样信号 | `cluster_id` |
| 采样事件 | `@(posedge clk) iff issue_valid` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.8.2 覆盖点定义

##### CP_NPU_CLUSTER_001：簇 ID

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_CLUSTER_001 |
| 覆盖点名称 | cp_cluster |
| 采样信号 | `cluster_id` |
| Bin 数 | 4 normal |

```systemverilog
cp_cluster: coverpoint cluster_id {
  bins c0 = {0};
  bins c1 = {1};
  bins c2 = {2};
  bins c3 = {3};
}
```

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| c0 | normal | `cluster_id == 0` | 簇 0 |
| c1 | normal | `cluster_id == 1` | 簇 1 |
| c2 | normal | `cluster_id == 2` | 簇 2 |
| c3 | normal | `cluster_id == 3` | 簇 3 |

#### 3.8.3 组内交叉

簇调度覆盖组的交叉覆盖在 CG_NPU_UNIT 中定义（X_NPU_UNIT_CLUSTER_001）。

#### 3.8.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_cluster` | `npu_instr` | c0, c1, c2, c3 |
| `c_multi_cluster` | `multi_cluster_seq` | 所有簇×单元 |


### 3.9 CG_NPU_OPCODE：算子类型覆盖组

#### 3.9.1 覆盖组信息

| 项目 | 内容 |
|---|---|
| CG ID | CG_NPU_OPCODE |
| 需求 ID | REQ-NPU-008：调度器支持 Conv/MatMul/Activation/Pooling 等算子 |
| 功能描述 | 覆盖所有算子类型 |
| 采样信号 | `instr_opcode` |
| 采样事件 | `@(posedge clk) iff instr_valid` |
| 放置位置 | `npu_monitor` |
| 目标 | 100% |

#### 3.9.2 覆盖点定义

##### CP_NPU_OPCODE_001：算子类型

| 项目 | 内容 |
|---|---|
| 覆盖点 ID | CP_NPU_OPCODE_001 |
| 覆盖点名称 | cp_opcode |
| 采样信号 | `instr_opcode` |
| Bin 数 | 8 normal |

```systemverilog
cp_opcode: coverpoint instr_opcode {
  bins conv    = {CONV};
  bins matmul  = {MATMUL};
  bins relu    = {RELU};
  bins sigmoid = {SIGMOID};
  bins maxpool = {MAXPOOL};
  bins avgpool = {AVGPOOL};
  bins bn      = {BATCHNORM};
  bins add     = {ADD};
}
```

| Bin 名称 | 类型 | 条件 | 说明 |
|---|---|---|---|
| conv | normal | `instr_opcode == CONV` | 卷积 |
| matmul | normal | `instr_opcode == MATMUL` | 矩阵乘 |
| relu | normal | `instr_opcode == RELU` | ReLU 激活 |
| sigmoid | normal | `instr_opcode == SIGMOID` | Sigmoid 激活 |
| maxpool | normal | `instr_opcode == MAXPOOL` | 最大池化 |
| avgpool | normal | `instr_opcode == AVGPOOL` | 平均池化 |
| bn | normal | `instr_opcode == BATCHNORM` | 批归一化 |
| add | normal | `instr_opcode == ADD` | 逐元素加 |

#### 3.9.3 组内交叉

算子类型覆盖组不定义组内交叉，算子类型与其他维度的交叉在后续版本中按需扩展。

#### 3.9.4 覆盖组约束映射

| 约束 | 所属类 | 目标 Bin |
|---|---|---|
| `c_opcode_dist` | `npu_instr` | 所有算子（加权） |
| `c_opcode_cover` | `opcode_cover_seq` | 所有算子（定向） |


### 3.10 跨组交叉覆盖汇总

以下交叉覆盖跨越多个覆盖率组，统一在此汇总。

| 交叉 ID | 交叉对象 | 涉及覆盖组 | Bin 数 | 目标 |
|---|---|---|---|---|
| X_NPU_TYPE_UNIT_001 | 指令类型 × 执行单元 | CG_NPU_TYPE × CG_NPU_UNIT | 5 | 100% |
| X_NPU_DTYPE_UNIT_001 | 数据类型 × 执行单元 | CG_NPU_DTYPE × CG_NPU_UNIT | 5 | 100% |
| X_NPU_DEP_DEC_001 | 依赖类型 × 发射决策 | CG_NPU_DEP × CG_NPU_DECISION | 6 | 100% |
| X_NPU_QUEUE_DEC_001 | 队列水位 × 发射决策 | CG_NPU_QUEUE × CG_NPU_DECISION | 4 | 100% |
| X_NPU_UNIT_CLUSTER_001 | 执行单元 × 簇 | CG_NPU_UNIT × CG_NPU_CLUSTER | 16 | 100% |


### 3.11 覆盖率组与约束映射总表

| 覆盖率组 | 覆盖点 | 约束 | 目标 Bin |
|---|---|---|---|
| CG_NPU_QUEUE | cp_queue_level | c_full_queue, c_size | full, full_blocked |
| CG_NPU_TYPE | cp_instr_type | c_type_dist | mac, vector, scalar, dma |
| CG_NPU_DTYPE | cp_dtype | c_dtype_dist, c_dtype_mix | int8, fp16, bf16, fp32 |
| CG_NPU_DEP | cp_dep_type | c_dep_dist, c_raw, c_waw, c_war, c_raw_chain | no_dep, raw, waw, war |
| CG_NPU_UNIT | cp_exec_unit | c_type_dist, c_multi_cluster | mac, vector, scalar, dma |
| CG_NPU_DECISION | cp_issue_decision | c_raw_chain, c_full_queue, c_contention, c_flush | issued, stalled, blocked, flushed |
| CG_NPU_CLUSTER | cp_cluster | c_cluster, c_multi_cluster | c0, c1, c2, c3 |
| CG_NPU_OPCODE | cp_opcode | c_opcode_dist, c_opcode_cover | 所有算子 |


### 3.12 覆盖率组与批次映射

| 批次 | 测试名 | 激活的覆盖率组 | 目标覆盖率 |
|---|---|---|---|
| 1 | npu_basic_test | CG_NPU_DECISION | 25% |
| 2 | npu_type_test | CG_NPU_TYPE, CG_NPU_UNIT | 45% |
| 3 | npu_dtype_test | CG_NPU_DTYPE | 60% |
| 4 | npu_dep_test | CG_NPU_DEP | 75% |
| 5 | npu_raw_stall_test | CG_NPU_DEP, CG_NPU_DECISION | 82% |
| 6 | npu_full_queue_test | CG_NPU_QUEUE, CG_NPU_DECISION | 88% |
| 7 | npu_cluster_test | CG_NPU_CLUSTER, CG_NPU_UNIT | 93% |
| 8 | npu_opcode_test | CG_NPU_OPCODE | 97% |
| 9 | npu_dma_compute_test | CG_NPU_TYPE, CG_NPU_UNIT | 100% |
| 10 | npu_random_mix_test | 全部 | 防过拟合 |


### 3.13 覆盖率组签核标准

| 覆盖率组 | 覆盖点目标 | 交叉目标 | 非法 Bin | 豁免 |
|---|---|---|---|---|
| CG_NPU_QUEUE | 100% | 100% | 0 命中 | 需审批 |
| CG_NPU_TYPE | 100% | 100% | 0 命中 | 需审批 |
| CG_NPU_DTYPE | 100% | 100% | 0 命中 | 需审批 |
| CG_NPU_DEP | 100% | 100% | 0 命中 | 需审批 |
| CG_NPU_UNIT | 100% | 100% | 0 命中 | 需审批 |
| CG_NPU_DECISION | 100% | 100% | 0 命中 | 需审批 |
| CG_NPU_CLUSTER | 100% | 100% | 0 命中 | 需审批 |
| CG_NPU_OPCODE | 100% | — | 0 命中 | 需审批 |

**签核条件：所有覆盖率组达到 100%，或已通过正式豁免流程。**


## 4. 约束设计

### 4.1 约束层次结构

约束按三层组织，从宽到严逐层收紧：

```text
第 1 层：指令生成约束（单条指令的编码、类型、数据）
    ↓
第 2 层：序列依赖约束（指令之间的依赖关系）
    ↓
第 3 层：场景约束（针对特定覆盖率缺口的定向约束）
```

**核心原则：约束的设计必须与覆盖点一一对应。每个覆盖点的每个 bin，都要有对应的约束能生成命中它的激励。**

### 4.2 第 1 层：指令生成约束

**对应覆盖点**：`cp_instr_type`、`cp_dtype`、`cp_dep_type`、`cp_opcode`、`cp_cluster`

```systemverilog
class npu_instr extends uvm_sequence_item;
  rand opcode_e     opcode;
  rand instr_type_e instr_type;
  rand dtype_e      dtype;
  rand dep_type_e   dep_type;
  rand bit [7:0]    tile_id;
  rand bit [31:0]   src_addr, dst_addr;
  rand bit [1:0]    cluster_id;

  // 对应 cp_opcode
  constraint c_opcode_dist {
    opcode dist {
      CONV     := 15, MATMUL  := 15,
      RELU     := 10, SIGMOID := 5,
      MAXPOOL  := 10, AVGPOOL := 5,
      BATCHNORM:= 5,  ADD     := 10
    };
  }

  // 对应 cp_instr_type
  constraint c_type_dist {
    instr_type dist {
      MAC    := 40,
      VECTOR := 25,
      SCALAR := 20,
      DMA    := 15
    };
  }

  // 对应 cp_dtype
  constraint c_dtype_dist {
    dtype dist {
      INT8 := 40,
      FP16 := 30,
      BF16 := 20,
      FP32 := 10
    };
  }

  // 对应 cp_dep_type
  constraint c_dep_dist {
    dep_type dist {
      NONE := 40, RAW := 30, WAW := 15, WAR := 15
    };
  }

  // 对应 cp_cluster
  constraint c_cluster {
    cluster_id inside {[0:3]};
  }

  constraint c_addr {
    src_addr[3:0] == 0;  // 16字节对齐
    dst_addr[3:0] == 0;
  }
endclass
```

### 4.3 第 2 层：序列依赖约束

**对应覆盖点**：`X_NPU_DEP_DEC_001` 的各交叉 bin

```systemverilog
class npu_stream extends uvm_sequence #(npu_instr);
  rand int unsigned num_instr;
  rand npu_instr   instrs[];

  constraint c_size {
    num_instr inside {[5:50]};
    instrs.size() == num_instr;
  }

  // 对应 X_dep_decision.raw_stalled / raw_issued
  constraint c_raw {
    foreach (instrs[i]) {
      if (i > 0 && instrs[i].dep_type == RAW) {
        instrs[i].src_addr == instrs[i-1].dst_addr;
      }
    }
  }

  // 对应 X_dep_decision.waw_stalled
  constraint c_waw {
    foreach (instrs[i]) {
      if (i > 1 && instrs[i].dep_type == WAW) {
        instrs[i].dst_addr == instrs[i-2].dst_addr;
      }
    }
  }

  // 对应 X_dep_decision.war_stalled
  constraint c_war {
    foreach (instrs[i]) {
      if (i > 0 && instrs[i].dep_type == WAR) {
        instrs[i].dst_addr == instrs[i-1].src_addr;
      }
    }
  }

  // 对应 X_queue_decision.low_issued
  constraint c_queue_rate {
    foreach (instrs[i]) {
      if (i < 3) instrs[i].dep_type == NONE;
    }
  }
endclass
```

### 4.4 第 3 层：场景约束

#### 场景 1：队列满时阻塞

**目标覆盖点**：`X_NPU_QUEUE_DEC_001.full_blocked`、`cp_queue_level.full`

```systemverilog
class full_queue_seq extends npu_stream;
  constraint c_full_queue {
    num_instr == 40;
    foreach (instrs[i]) {
      if (i < 32) {
        instrs[i].dep_type == NONE;
        instrs[i].instr_type == MAC;
      }
      if (i >= 32) {
        instrs[i].dep_type == RAW;
      }
    }
  }
endclass
```

#### 场景 2：连续 RAW 依赖链

**目标覆盖点**：`X_NPU_DEP_DEC_001.raw_stalled`

```systemverilog
class raw_chain_seq extends npu_stream;
  constraint c_raw_chain {
    num_instr == 20;
    foreach (instrs[i]) {
      if (i > 0) {
        instrs[i].dep_type == RAW;
        instrs[i].src_addr == instrs[i-1].dst_addr;
      }
    }
  }
endclass
```

#### 场景 3：多簇并发

**目标覆盖点**：`X_NPU_UNIT_CLUSTER_001`

```systemverilog
class multi_cluster_seq extends npu_stream;
  constraint c_multi_cluster {
    num_instr == 16;
    foreach (instrs[i]) {
      instrs[i].cluster_id == i % 4;
      instrs[i].dep_type == NONE;
    }
  }
endclass
```

#### 场景 4：数据类型混合

**目标覆盖点**：`X_NPU_DTYPE_UNIT_001`

```systemverilog
class dtype_mix_seq extends npu_stream;
  constraint c_dtype_mix {
    num_instr == 20;
    foreach (instrs[i]) {
      instrs[i].dtype dist {
        INT8 := 25, FP16 := 25, BF16 := 25, FP32 := 25
      };
    }
  }
endclass
```

#### 场景 5：算子覆盖

**目标覆盖点**：`cp_opcode` 所有 bin

```systemverilog
class opcode_cover_seq extends npu_stream;
  constraint c_opcode_cover {
    num_instr == 16;
    instrs[0].opcode == CONV;
    instrs[1].opcode == MATMUL;
    instrs[2].opcode == RELU;
    instrs[3].opcode == SIGMOID;
    instrs[4].opcode == MAXPOOL;
    instrs[5].opcode == AVGPOOL;
    instrs[6].opcode == BATCHNORM;
    instrs[7].opcode == ADD;
  }
endclass
```

#### 场景 6：DMA 与计算并发

**目标覆盖点**：`X_NPU_TYPE_UNIT_001`

```systemverilog
class dma_compute_seq extends npu_stream;
  constraint c_dma_compute {
    num_instr == 20;
    foreach (instrs[i]) {
      if (i % 3 == 0) {
        instrs[i].instr_type == DMA;
      } else {
        instrs[i].instr_type inside {MAC, VECTOR};
      }
    }
  }
endclass
```

#### 场景 7：冲刷

**目标覆盖点**：`cp_issue_decision.flushed`

```systemverilog
class flush_seq extends npu_stream;
  constraint c_flush {
    num_instr == 16;
    instrs[8].opcode inside {CONV, MATMUL};
    foreach (instrs[i]) {
      if (i > 8) instrs[i].dep_type == RAW;
    }
  }
endclass
```

### 4.5 约束与覆盖点映射表

| 约束 | 所属类 | 目标覆盖点 | 目标 Bin |
|---|---|---|---|
| `c_opcode_dist` | `npu_instr` | `cp_opcode` | 所有算子 |
| `c_type_dist` | `npu_instr` | `cp_instr_type` | mac/vector/scalar/dma |
| `c_dtype_dist` | `npu_instr` | `cp_dtype` | int8/fp16/bf16/fp32 |
| `c_dep_dist` | `npu_instr` | `cp_dep_type` | no_dep/raw/waw/war |
| `c_cluster` | `npu_instr` | `cp_cluster` | c0/c1/c2/c3 |
| `c_raw` | `npu_stream` | `X_NPU_DEP_DEC_001` | raw_stalled/raw_issued |
| `c_waw` | `npu_stream` | `X_NPU_DEP_DEC_001` | waw_stalled |
| `c_war` | `npu_stream` | `X_NPU_DEP_DEC_001` | war_stalled |
| `c_queue_rate` | `npu_stream` | `X_NPU_QUEUE_DEC_001` | low_issued |
| `c_full_queue` | `full_queue_seq` | `X_NPU_QUEUE_DEC_001` | full_blocked |
| `c_raw_chain` | `raw_chain_seq` | `X_NPU_DEP_DEC_001` | raw_stalled |
| `c_multi_cluster` | `multi_cluster_seq` | `X_NPU_UNIT_CLUSTER_001` | 所有簇×单元 |
| `c_dtype_mix` | `dtype_mix_seq` | `X_NPU_DTYPE_UNIT_001` | 所有 dtype×unit |
| `c_opcode_cover` | `opcode_cover_seq` | `cp_opcode` | 所有算子 |
| `c_dma_compute` | `dma_compute_seq` | `X_NPU_TYPE_UNIT_001` | dma×dma, mac×mac |
| `c_flush` | `flush_seq` | `cp_issue_decision` | flushed |


## 5. 批次设计与覆盖率演进

### 5.1 批次规划

| 批次 | 测试名 | 约束 | 目标覆盖点 | 种子数 | 预期覆盖率 |
|---|---|---|---|---|---|
| 1 | npu_basic_test | 基础约束 | cp_issue_decision.issued | 5 | 25% |
| 2 | npu_type_test | c_type_dist | cp_instr_type 全部 | 30 | 45% |
| 3 | npu_dtype_test | c_dtype_dist | cp_dtype 全部 | 30 | 60% |
| 4 | npu_dep_test | c_dep_dist + c_raw/c_waw/c_war | cp_dep_type + X_NPU_DEP_DEC | 50 | 75% |
| 5 | npu_raw_stall_test | c_raw_chain | X_NPU_DEP_DEC.raw_stalled | 20 | 82% |
| 6 | npu_full_queue_test | c_full_queue | X_NPU_QUEUE_DEC.full_blocked | 30 | 88% |
| 7 | npu_cluster_test | c_multi_cluster | X_NPU_UNIT_CLUSTER | 20 | 93% |
| 8 | npu_opcode_test | c_opcode_cover | cp_opcode 全部 | 20 | 97% |
| 9 | npu_dma_compute_test | c_dma_compute | X_NPU_TYPE_UNIT | 20 | 100% |
| 10 | npu_random_mix_test | 宽松混合 | 探索性 | 100 | 防过拟合 |

### 5.2 批次演进逻辑

```text
批次 1：基础发射
  → 25%，缺口：类型未覆盖
批次 2：指令类型
  → 45%，缺口：数据类型未覆盖
批次 3：数据类型
  → 60%，缺口：依赖未覆盖
批次 4：依赖探索
  → 75%，缺口：RAW stall未命中
批次 5：RAW停顿
  → 82%，缺口：队列满阻塞未命中
批次 6：队列压力
  → 88%，缺口：多簇并发未覆盖
批次 7：多簇并发
  → 93%，缺口：算子类型未全覆盖
批次 8：算子覆盖
  → 97%，缺口：DMA与计算并发未覆盖
批次 9：DMA并发
  → 100%
批次 10：随机混合
  → 防过拟合
```

### 5.3 覆盖率缺口与约束变化对应

| 缺口 | 根因分析 | 约束变化 | 新增/修改类 |
|---|---|---|---|
| `raw_stalled` 未命中 | 约束未强制 RAW 链 | 增加 `c_raw_chain` | `raw_chain_seq` |
| `full_blocked` 未命中 | 队列未满，随机难度大 | 增加 `c_full_queue` | `full_queue_seq` |
| `flushed` 未命中 | 未制造冲刷场景 | 增加 `c_flush` | `flush_seq` |
| `int8_vector` 命中 | 约束未限制 dtype×unit | 增加 illegal 约束 | `npu_instr` |
| `cluster×unit` 未全覆盖 | 未强制多簇 | 增加 `c_multi_cluster` | `multi_cluster_seq` |
| `opcode` 未全覆盖 | 随机分布不均 | 增加 `c_opcode_cover` | `opcode_cover_seq` |


## 6. 种子管理

### 6.1 种子基线建立流程

```text
第 1 步：每个测试跑 200-500 个种子
第 2 步：记录每个种子的覆盖率贡献、运行时间、pass/fail
第 3 步：按覆盖率贡献排名
第 4 步：找覆盖率平台期
第 5 步：从高贡献种子里选出基线种子
第 6 步：纳入回归，固定使用
第 7 步：定期维护（设计变更后重新评估）
```

### 6.2 种子基线表

| 测试名 | 类型 | 种子基线 | 基线长度 | 探索种子 | 总运行次数 |
|---|---|---|---|---|---|
| npu_basic_test | 定向 | {1001} | 1 | 0 | 1 |
| npu_type_test | 随机 | {2001, 2005, ...} | 15 | 3 | 18 |
| npu_dtype_test | 随机 | {3001, 3005, ...} | 15 | 3 | 18 |
| npu_dep_test | 随机 | {4001, 4005, ...} | 25 | 5 | 30 |
| npu_raw_stall_test | 定向 | {5001, 5003, ...} | 10 | 2 | 12 |
| npu_full_queue_test | 随机 | {6001, 6005, ...} | 15 | 3 | 18 |
| npu_cluster_test | 随机 | {7001, 7003, ...} | 10 | 2 | 12 |
| npu_opcode_test | 定向 | {8001, 8002, ...} | 8 | 2 | 10 |
| npu_dma_compute_test | 随机 | {9001, 9003, ...} | 12 | 2 | 14 |
| npu_random_mix_test | 随机 | {10001, 10012, ...} | 40 | 8 | 48 |

### 6.3 种子筛选示例

以 `npu_dep_test` 为例：

| 种子范围 | 数量 | 覆盖率贡献 | 保留数 |
|---|---|---|---|
| 4001-4100 | 100 | 贡献 50% | 15 |
| 4101-4200 | 100 | 贡献 30% | 7 |
| 4201-4300 | 100 | 贡献 20% | 3 |

**最终种子基线：25 个。**

### 6.4 种子管理工具

| 工具 | 能力 |
|---|---|
| VCS `urg -grade` | 基于功能覆盖率对种子分级 |
| VSO.ai | AI 驱动的种子优化，减少 10 倍种子数 |
| 覆盖率合并 | `urg -dir *.vdb -cm merge` |


## 7. 覆盖率采样实现

### 7.1 Covergroup 定义

```systemverilog
class npu_sched_coverage extends uvm_subscriber #(npu_item);
  `uvm_component_utils(npu_sched_coverage)

  covergroup npu_sched_cg @(posedge clk);
    option.per_instance = 1;

    // ============ CG_NPU_QUEUE ============
    cp_queue_level: coverpoint queue_level {
      bins empty     = {0};
      bins low       = {[1:7]};
      bins mid       = {[8:15]};
      bins high      = {[16:24]};
      bins near_full = {[25:31]};
      bins full      = {32};
      illegal_bins illegal_over = {[33:$]};
    }

    // ============ CG_NPU_TYPE ============
    cp_instr_type: coverpoint instr_type {
      bins mac    = {MAC};
      bins vector = {VECTOR};
      bins scalar = {SCALAR};
      bins dma    = {DMA};
    }

    // ============ CG_NPU_DTYPE ============
    cp_dtype: coverpoint instr_dtype {
      bins int8 = {INT8};
      bins fp16 = {FP16};
      bins bf16 = {BF16};
      bins fp32 = {FP32};
    }

    // ============ CG_NPU_DEP ============
    cp_dep_type: coverpoint dep_type {
      bins no_dep = {NONE};
      bins raw    = {RAW};
      bins waw    = {WAW};
      bins war    = {WAR};
    }

    // ============ CG_NPU_UNIT ============
    cp_exec_unit: coverpoint issue_unit {
      bins mac    = {MAC};
      bins vector = {VECTOR};
      bins scalar = {SCALAR};
      bins dma    = {DMA};
    }

    // ============ CG_NPU_DECISION ============
    cp_issue_decision: coverpoint issue_decision {
      bins issued  = {ISSUED};
      bins stalled = {STALLED};
      bins blocked = {BLOCKED};
      bins flushed = {FLUSHED};
    }

    // ============ CG_NPU_CLUSTER ============
    cp_cluster: coverpoint cluster_id {
      bins c0 = {0};
      bins c1 = {1};
      bins c2 = {2};
      bins c3 = {3};
    }

    // ============ CG_NPU_OPCODE ============
    cp_opcode: coverpoint instr_opcode {
      bins conv    = {CONV};
      bins matmul  = {MATMUL};
      bins relu    = {RELU};
      bins sigmoid = {SIGMOID};
      bins maxpool = {MAXPOOL};
      bins avgpool = {AVGPOOL};
      bins bn      = {BATCHNORM};
      bins add     = {ADD};
    }

    // ============ 跨组交叉 ============
    X_type_unit: cross cp_instr_type, cp_exec_unit {
      bins mac_to_mac       = binsof(cp_instr_type.mac)    && binsof(cp_exec_unit.mac);
      bins vec_to_vec       = binsof(cp_instr_type.vector) && binsof(cp_exec_unit.vector);
      bins scalar_to_scalar = binsof(cp_instr_type.scalar) && binsof(cp_exec_unit.scalar);
      bins dma_to_dma       = binsof(cp_instr_type.dma)    && binsof(cp_exec_unit.dma);
      illegal_bins mac_to_dma = binsof(cp_instr_type.mac) && binsof(cp_exec_unit.dma);
    }

    X_dtype_unit: cross cp_dtype, cp_exec_unit {
      bins int8_mac    = binsof(cp_dtype.int8) && binsof(cp_exec_unit.mac);
      bins fp16_mac    = binsof(cp_dtype.fp16) && binsof(cp_exec_unit.mac);
      bins bf16_mac    = binsof(cp_dtype.bf16) && binsof(cp_exec_unit.mac);
      bins fp32_vector = binsof(cp_dtype.fp32) && binsof(cp_exec_unit.vector);
      illegal_bins int8_vector = binsof(cp_dtype.int8) && binsof(cp_exec_unit.vector);
    }

    X_dep_decision: cross cp_dep_type, cp_issue_decision {
      bins raw_stalled    = binsof(cp_dep_type.raw)    && binsof(cp_issue_decision.stalled);
      bins raw_issued     = binsof(cp_dep_type.raw)    && binsof(cp_issue_decision.issued);
      bins waw_stalled    = binsof(cp_dep_type.waw)    && binsof(cp_issue_decision.stalled);
      bins war_stalled    = binsof(cp_dep_type.war)    && binsof(cp_issue_decision.stalled);
      bins no_dep_issued  = binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.issued);
      bins no_dep_blocked = binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.blocked);
    }

    X_queue_decision: cross cp_queue_level, cp_issue_decision {
      bins full_blocked      = binsof(cp_queue_level.full)      && binsof(cp_issue_decision.blocked);
      bins near_full_stalled = binsof(cp_queue_level.near_full) && binsof(cp_issue_decision.stalled);
      bins empty_issued      = binsof(cp_queue_level.empty)     && binsof(cp_issue_decision.issued);
      bins low_issued        = binsof(cp_queue_level.low)       && binsof(cp_issue_decision.issued);
    }

    X_unit_cluster: cross cp_exec_unit, cp_cluster;
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    npu_sched_cg = new();
  endfunction

  function void write(npu_item t);
    queue_level    = t.queue_level;
    instr_type     = t.instr_type;
    instr_dtype    = t.instr_dtype;
    dep_type       = t.dep_type;
    issue_unit     = t.issue_unit;
    issue_decision = t.issue_decision;
    cluster_id     = t.cluster_id;
    instr_opcode   = t.instr_opcode;
    npu_sched_cg.sample();
  endfunction
endclass
```

### 7.2 采样位置原则

| 原则 | 说明 |
|---|---|
| 在 monitor 采样 | 不在 sequence 采样，保证垂直复用 |
| 联合采样激励和结果 | 区分"场景发生"和"场景正确处理" |
| 用 `iff` 限定有效周期 | 复位和无效周期不采样 |
| 非法 bin 用 `illegal_bins` | 命中即报错 |


## 8. 需求追溯矩阵

| 需求 ID | 需求描述 | 覆盖点 | 交叉覆盖 | 约束 | 测试用例 | 状态 |
|---|---|---|---|---|---|---|
| REQ-NPU-001 | 支持0-32队列深度 | CP_NPU_QUEUE_001 | X_NPU_QUEUE_DEC_001 | c_full_queue | npu_full_queue_test | 已覆盖 |
| REQ-NPU-002 | 支持4类指令 | CP_NPU_TYPE_001 | X_NPU_TYPE_UNIT_001 | c_type_dist | npu_type_test | 已覆盖 |
| REQ-NPU-003 | 支持4种数据类型 | CP_NPU_DTYPE_001 | X_NPU_DTYPE_UNIT_001 | c_dtype_dist | npu_dtype_test | 已覆盖 |
| REQ-NPU-004 | 正确处理依赖 | CP_NPU_DEP_001 | X_NPU_DEP_DEC_001 | c_raw/c_waw/c_war | npu_dep_test | 已覆盖 |
| REQ-NPU-005 | 支持4个执行单元 | CP_NPU_UNIT_001 | X_NPU_UNIT_CLUSTER_001 | c_type_dist | npu_type_test | 已覆盖 |
| REQ-NPU-006 | 正确做出发射决策 | CP_NPU_DECISION_001 | X_NPU_DEP_DEC_001 | c_full_queue | npu_full_queue_test | 已覆盖 |
| REQ-NPU-007 | 支持4个簇 | CP_NPU_CLUSTER_001 | X_NPU_UNIT_CLUSTER_001 | c_multi_cluster | npu_cluster_test | 已覆盖 |
| REQ-NPU-008 | 支持8种算子 | CP_NPU_OPCODE_001 | — | c_opcode_cover | npu_opcode_test | 已覆盖 |

**要求：不能有孤立需求，也不能有孤立覆盖点。**


## 9. 覆盖率收敛签核标准

### 9.1 签核条件

| 条件 | 标准 |
|---|---|
| 功能覆盖点 | 100% bin 命中 |
| 交叉覆盖 | 100% 有意义组合命中 |
| 非法 bin | 0 命中 |
| 忽略 bin | 已审批并记录理由 |
| 需求追溯 | 无孤立需求，无孤立覆盖点 |
| 种子基线 | 已建立并纳入回归 |
| 豁免项 | 有理由、有审批人、有记录 |
| 回归稳定性 | 固定回归集覆盖率稳定 |

### 9.2 豁免流程

```text
发现未覆盖 bin
    ↓
分析原因
    ├─ 约束可覆盖但种子没抽到 → 加种子 / 调约束
    ├─ 约束覆盖不到 → 补约束 / 写定向 case
    ├─ 架构不可达 → 申请豁免
    └─ 命中了但结果错 → DUT bug，进 debug
    ↓
豁免申请 → 验证负责人审批 → 记录理由和审批人
```

### 9.3 豁免记录表

| Bin | 所属覆盖点 | 豁免理由 | 审批人 | 日期 |
|---|---|---|---|---|
| | | | | |


## 10. 附录

### 10.1 批次执行命令示例

```bash
# 批次5：RAW stall测试
for seed in 5001 5003 5007 5012 5015; do
  simv +ntb_random_seed=$seed +UVM_TESTNAME=npu_raw_stall_test \
       -cm line+cond+fsm+tgl+functional -cm_dir ./cov_$seed.vdb
done

# 合并覆盖率
urg -dir cov_*.vdb -cm merge -report ./report_batch5

# 种子分级
urg -dir cov_*.vdb -grade -metric group
```

### 10.2 覆盖率组速查卡

```text
┌──────────────────────────────────────────────┐
│  CG_NPU_QUEUE    → cp_queue_level            │
│                     + X_queue_decision        │
├──────────────────────────────────────────────┤
│  CG_NPU_TYPE     → cp_instr_type             │
│                     + X_type_unit             │
├──────────────────────────────────────────────┤
│  CG_NPU_DTYPE    → cp_dtype                  │
│                     + X_dtype_unit            │
├──────────────────────────────────────────────┤
│  CG_NPU_DEP      → cp_dep_type               │
│                     + X_dep_decision          │
├──────────────────────────────────────────────┤
│  CG_NPU_UNIT     → cp_exec_unit              │
│                     + X_unit_cluster          │
├──────────────────────────────────────────────┤
│  CG_NPU_DECISION → cp_issue_decision         │
├──────────────────────────────────────────────┤
│  CG_NPU_CLUSTER  → cp_cluster                │
├──────────────────────────────────────────────┤
│  CG_NPU_OPCODE   → cp_opcode                 │
└──────────────────────────────────────────────┘
```

### 10.3 常见坑清单

| 坑 | 后果 | 避免方式 |
|---|---|---|
| 只采激励不采结果 | 无法区分"场景发生"和"正确处理" | 联合采样 |
| 交叉覆盖爆炸 | bin数量失控 | 只交叉有意义的组合 |
| 约束与覆盖点脱节 | 覆盖率上不去 | 建立约束-覆盖点映射 |
| 数据类型未全覆盖 | 遗漏精度相关bug | 强制覆盖所有dtype |
| 算子类型遗漏 | 遗漏特定算子bug | 定向覆盖所有opcode |
| 多簇并发未覆盖 | 遗漏跨簇竞争bug | 增加多簇并发场景 |
| 忽略bin滥用 | 掩盖真实缺口 | 豁免需审批 |
| 采样时机不对 | 覆盖率虚高或漏采 | 用 `iff` 限定有效周期 |


## 11. 文档变更记录

| 版本 | 日期 | 修改人 | 修改内容 |
|---|---|---|---|
| v1.0 | | | 初始版本 |


**本文档的核心思想：NPU 指令调度器的功能覆盖率，按功能维度划分为 8 个覆盖率组，每组聚焦一类功能契约。每个约束对准一个覆盖点的 bin，每个测试的种子基线由覆盖率平台期决定，每个批次由上一批的缺口驱动。约束、覆盖点、测试用例、种子基线四者形成闭环。**