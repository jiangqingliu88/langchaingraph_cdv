# NPU 指令调度器
<!--
  module: npu_sched
  level: BT
  data_width: 32
  requirements: [REQ-NPU-001, REQ-NPU-002, REQ-NPU-003, REQ-NPU-004, REQ-NPU-005,
                 REQ-NPU-006, REQ-NPU-007, REQ-NPU-008, REQ-NPU-009, REQ-NPU-010,
                 REQ-NPU-011, REQ-NPU-012]
-->

> 本文档覆盖 **NPU 硬件指令调度器**。算子（Conv/MatMul/ReLU 等）是软件/编译器
> 层面的概念，其调度验证属于软件栈验证，不在范围内 —— 硬件调度器直接调度的是
> **指令**。

## 1. 概述

接收来自主控的硬件指令流，按数据依赖决定发射顺序，把指令分发到不同类型的执行
单元，并管理队列水位、多簇归属、流水重叠与同步屏障。

**可覆盖性是本模块的设计约束之一**：12 个关键信号（队列水位、指令类型/数据类型、
依赖类型、执行单元、发射决策、簇 ID、操作码、指令序列、流水状态、优先级、屏障）
都在模块内按名字可见，供 `bind` 探针直接采样 —— 内部状态与输出端口**不需要**从
事务通道绕出去（那只看得到激励侧）。

## 2. 功能需求

### 指令队列管理
**级别**：P0
**描述**：支持 0-32 条指令的队列深度，处理满/空；越界水位为非法状态
**验收标准**：六档水位（empty/low/mid/high/near_full/full）100% 命中，无越界命中

### 指令类型调度
**级别**：P0
**描述**：支持 4 类指令（MAC / Vector / Scalar / DMA），分发到对应执行单元
**验收标准**：类型 × 执行单元的有意义组合 100% 命中，非法组合 0 命中

### 数据类型调度
**级别**：P0
**描述**：支持 4 种数据类型（INT8 / FP16 / BF16 / FP32）
**验收标准**：数据类型 × 执行单元的匹配组合 100% 命中

### 数据依赖处理
**级别**：P0
**描述**：正确处理 RAW（真依赖）/ WAW（输出依赖）/ WAR（反依赖），据此决定发射
**验收标准**：依赖类型 × 发射决策的组合 100% 命中

### 执行单元分配与冲突
**级别**：P0
**描述**：按指令类型把指令发到 MAC / Vector / Scalar / DMA 四个执行单元
**验收标准**：四个执行单元 100% 命中

### 发射决策
**级别**：P0
**描述**：正确做出 发射 / 停顿 / 阻塞 / 冲刷 四种决策
**验收标准**：四种决策 100% 命中；队列满时阻塞、有真依赖时停顿

### 多簇调度与同步
**级别**：P1
**描述**：支持 4 个簇的指令归属与同步；簇越界为非法状态
**验收标准**：簇 × 执行单元 100% 命中，无越界簇命中

### 硬件指令操作码覆盖
**级别**：P1
**描述**：支持 10 条硬件指令（MAC_INT8/FP16/BF16、VEC_ADD/MUL/RELU、LOAD、STORE、DMA_READ/WRITE）
**验收标准**：10 条指令 100% 命中

### 指令序列模式
**级别**：P1
**描述**：识别相邻两条指令的 opcode 组合模式
**验收标准**：6 种名义组合 100% 命中

### 指令流水重叠
**级别**：P2
**描述**：支持多条指令在时间上的并行执行
**验收标准**：5 种流水状态 100% 命中

### 优先级调度
**级别**：P2
**描述**：支持 HIGH_FIRST / LOW_FIRST / SAME_PRIO / ROUND_ROBIN 四种优先级策略
**验收标准**：四种策略 100% 命中

### 硬件同步屏障
**级别**：P2
**描述**：响应 TILE / OP / CLUSTER 三类同步屏障与冲刷请求
**验收标准**：四种屏障状态 100% 命中

## 3. 接口

| 信号 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 时钟 |
| rst_n | input | 1 | 异步复位，低有效 |
| instr_valid | input | 1 | 指令有效 |
| instr_opcode | input | 8 | 硬件指令操作码 |
| instr_type | input | 3 | 指令类型 |
| instr_dtype | input | 3 | 数据类型 |
| instr_tile_id | input | 8 | Tile ID（低位即簇 ID） |
| instr_src_addr | input | 32 | 源地址 |
| instr_dst_addr | input | 32 | 目的地址 |
| barrier_type | input | 2 | 同步屏障类型 |
| op_priority | input | 3 | 优先级策略 |
| issue_valid | output | 1 | 发射有效 |
| issue_unit | output | 3 | 执行单元 |
| issue_decision | output | 2 | 发射决策 |

**内部信号**（不在端口上，供 `bind` 探针采样）：`queue_level`(6)、`dep_type`(2)、
`cluster_id`(2)、`instr_seq`(8)、`pipeline_state`(3)。

## 4. 覆盖率与回归

功能覆盖率模型见 `casemodel.yaml`（12 个覆盖点 / 7 条交叉 / 含非法仓），
由 `casemodel_tools` 生成：

- **覆盖点与交叉** → `coverage/coverage_plan.yaml`
- **批次与种子管理** → 同上（11 个批次，共 195 次运行）
- **DUT 探针** → `coverage/dut_probe.sv`（`bind` 进本模块）
- **批次 test 类** → `env/tests/*_batch_test.sv`

**编码约定**：`instr_type` / `instr_dtype` / `dep_type` / `issue_unit` /
`issue_decision` 等按 **case 模型 `values:` 的顺序**编码（`MAC=0, VECTOR=1, …`）。
改顺序会改变 bin 的含义而**编译不报错** —— 见 RTL 文件头的说明。
