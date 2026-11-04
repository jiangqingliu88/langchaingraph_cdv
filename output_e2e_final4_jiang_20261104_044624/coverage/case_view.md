# Case 证据视图 —— output_e2e_final4_jiang_20261104_044624

## 覆盖率组总览（必须覆盖什么）

| 覆盖率组 | 功能点 | 覆盖类型 | 作用域（模块/逻辑） | 覆盖点 | 需求 | 必需证据层 | 执行证据 | CELL |
|---|---|---|---|---|---|---|---|---|
| CG-BEH_QUEUE | 队列水位迁移 | 场景序列 | — | — | — | functional | **无** | CELL-BEH_QUEUE-BEHAVIOR |
| CG-D_BARRIER | 硬件同步屏障 | 功能覆盖 | 多簇同步 | cp_barrier_type | REQ-NPU-012 | functional + timing + data | 有 | CELL-D_BARRIER-P3 |
| CG-D_CLUSTER | 簇 ID | 观测覆盖 | 多簇同步 | cp_cluster_id | REQ-NPU-007 | functional + timing + data | **无** | CELL-D_CLUSTER-P2 |
| CG-D_DECISION | 发射决策 | 观测覆盖 | 指令发射 | cp_issue_decision | REQ-NPU-006 | functional + timing + data | **无** | CELL-D_DECISION-P0 |
| CG-D_DEP | 数据依赖 | 观测覆盖 | 指令队列管理 | cp_dep_type | REQ-NPU-004 | functional + timing + data | **无** | CELL-D_DEP-P1 |
| CG-D_DTYPE | 数据类型 | 功能覆盖 | 指令发射 | cp_instr_dtype | REQ-NPU-003 | functional + timing + data | 有 | CELL-D_DTYPE-P0 |
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | cp_instr_opcode | REQ-NPU-008 | functional + timing + data | 有 | CELL-D_OPCODE-P2 |
| CG-D_PIPELINE | 流水重叠 | 场景序列 | 指令发射 | cp_pipeline_state | REQ-NPU-010 | functional + timing + data | 有 | CELL-D_PIPELINE-P3 |
| CG-D_PRIORITY | 优先级调度 | 功能覆盖 | 指令发射 | cp_op_priority | REQ-NPU-011 | functional + timing + data | 有 | CELL-D_PRIORITY-P3 |
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | cp_queue_level | REQ-NPU-001 | functional + timing + data | 有 | CELL-D_QUEUE-P1 |
| CG-D_SEQ | 指令序列模式 | 场景序列 | 指令队列管理 | cp_instr_seq | REQ-NPU-009 | functional + timing + data | 有 | CELL-D_SEQ-P3 |
| CG-D_TYPE | 指令类型 | 功能覆盖 | 指令发射 | cp_instr_type | REQ-NPU-002 | functional + timing + data | 有 | CELL-D_TYPE-P0 |
| CG-D_UNIT | 执行单元 | 观测覆盖 | 指令发射 | cp_issue_unit | REQ-NPU-005 | functional + timing + data | **无** | CELL-D_UNIT-P2 |

## 四集合证据（Groups / SVA / SCB / Constraints）

### Case: CASE-D_BARRIER　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_BARRIER | 硬件同步屏障 | 功能覆盖 | 多簇同步 | CELL-D_BARRIER-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-BARRIER_FLUSHES | barrier_flushes | `barrier_type != 2'd0 |-> issue_decision == 2'd3` | CELL-D_BARRIER-P3 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_BARRIER-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_BARRIER　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_BARRIER | 硬件同步屏障 | 功能覆盖 | 多簇同步 | CELL-D_BARRIER-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-BARRIER_FLUSHES | barrier_flushes | `barrier_type != 2'd0 |-> issue_decision == 2'd3` | CELL-D_BARRIER-P3 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_BARRIER-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_BARRIER　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_BARRIER | 硬件同步屏障 | 功能覆盖 | 多簇同步 | CELL-D_BARRIER-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-BARRIER_FLUSHES | barrier_flushes | `barrier_type != 2'd0 |-> issue_decision == 2'd3` | CELL-D_BARRIER-P3 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_BARRIER-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_BARRIER　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_BARRIER | 硬件同步屏障 | 功能覆盖 | 多簇同步 | CELL-D_BARRIER-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-BARRIER_FLUSHES | barrier_flushes | `barrier_type != 2'd0 |-> issue_decision == 2'd3` | CELL-D_BARRIER-P3 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_BARRIER-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_DTYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_DTYPE | 数据类型 | 功能覆盖 | 指令发射 | CELL-D_DTYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_DTYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b03_random | 是 | D_dtype | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_DTYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_DTYPE | 数据类型 | 功能覆盖 | 指令发射 | CELL-D_DTYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_DTYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b03_random | 是 | D_dtype | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_DTYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_DTYPE | 数据类型 | 功能覆盖 | 指令发射 | CELL-D_DTYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_DTYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b03_random | 是 | D_dtype | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_DTYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_DTYPE | 数据类型 | 功能覆盖 | 指令发射 | CELL-D_DTYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_DTYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b03_random | 是 | D_dtype | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_OPCODE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_OPCODE | 硬件指令操作码 | 功能覆盖 | 指令发射 | CELL-D_OPCODE-P2 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_OPCODE-P2 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b08_directed | 是 | D_opcode、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PIPELINE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PIPELINE | 流水重叠 | 场景序列 | 指令发射 | CELL-D_PIPELINE-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PIPELINE-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b10_random | 是 | D_pipeline | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PIPELINE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PIPELINE | 流水重叠 | 场景序列 | 指令发射 | CELL-D_PIPELINE-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PIPELINE-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b10_random | 是 | D_pipeline | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PIPELINE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PIPELINE | 流水重叠 | 场景序列 | 指令发射 | CELL-D_PIPELINE-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PIPELINE-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b10_random | 是 | D_pipeline | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PIPELINE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PIPELINE | 流水重叠 | 场景序列 | 指令发射 | CELL-D_PIPELINE-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PIPELINE-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b10_random | 是 | D_pipeline | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PIPELINE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PIPELINE | 流水重叠 | 场景序列 | 指令发射 | CELL-D_PIPELINE-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PIPELINE-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b10_random | 是 | D_pipeline | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PRIORITY　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PRIORITY | 优先级调度 | 功能覆盖 | 指令发射 | CELL-D_PRIORITY-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PRIORITY-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PRIORITY　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PRIORITY | 优先级调度 | 功能覆盖 | 指令发射 | CELL-D_PRIORITY-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PRIORITY-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PRIORITY　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PRIORITY | 优先级调度 | 功能覆盖 | 指令发射 | CELL-D_PRIORITY-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PRIORITY-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_PRIORITY　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_PRIORITY | 优先级调度 | 功能覆盖 | 指令发射 | CELL-D_PRIORITY-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_PRIORITY-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_QUEUE　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_QUEUE | 指令队列水位 | 状态后门 | 指令队列管理 | CELL-D_QUEUE-P1 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SVA（断言）**

| id | 名称 | 规则 | cell | fail | cover_property_hit | status |
|---|---|---|---|---|---|---|
| SVA-QUEUE_LEVEL_WITHIN_DEPTH | queue_level_within_depth | `queue_level <= 6'd32` | CELL-D_QUEUE-P1 | 0 | None | MISSING |
| SVA-ISSUED_NEEDS_NO_BLOCKER | issued_needs_no_blocker | `issue_decision == 2'd0 |-> queue_level != 6'd0 && barrier_type == 2'd0 && dep_type != 2'd1` | CELL-D_QUEUE-P1 | 0 | None | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_QUEUE-P1 | 220 | 220 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b06_special | **否（空骨架）** | D_queue、D_decision | 维度不可驱动：没有 `stimulus.field`，也没有 `realization.values` 场景序列 —— apply() 落 default 分支 |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_SEQ　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_SEQ | 指令序列模式 | 场景序列 | 指令队列管理 | CELL-D_SEQ-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_SEQ-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_SEQ　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_SEQ | 指令序列模式 | 场景序列 | 指令队列管理 | CELL-D_SEQ-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_SEQ-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_SEQ　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_SEQ | 指令序列模式 | 场景序列 | 指令队列管理 | CELL-D_SEQ-P3 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_SEQ-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_SEQ　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_SEQ | 指令序列模式 | 场景序列 | 指令队列管理 | CELL-D_SEQ-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_SEQ-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_SEQ　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_SEQ | 指令序列模式 | 场景序列 | 指令队列管理 | CELL-D_SEQ-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_SEQ-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_SEQ　`case_status=NOT_VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_SEQ | 指令序列模式 | 场景序列 | 指令队列管理 | CELL-D_SEQ-P3 | MISSING | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | MISSING |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_SEQ-P3 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_TYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_TYPE | 指令类型 | 功能覆盖 | 指令发射 | CELL-D_TYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_TYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b02_random | 是 | D_type | 1 条字段赋值（模型可驱动） |
| p_th_b09_random | 是 | D_type、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_TYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_TYPE | 指令类型 | 功能覆盖 | 指令发射 | CELL-D_TYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_TYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b02_random | 是 | D_type | 1 条字段赋值（模型可驱动） |
| p_th_b09_random | 是 | D_type、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_TYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_TYPE | 指令类型 | 功能覆盖 | 指令发射 | CELL-D_TYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_TYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b02_random | 是 | D_type | 1 条字段赋值（模型可驱动） |
| p_th_b09_random | 是 | D_type、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

### Case: CASE-D_TYPE　`case_status=VERIFIED`

**Groups**

| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|---|---|---|
| CG-D_TYPE | 指令类型 | 功能覆盖 | 指令发射 | CELL-D_TYPE-P0 | PROVEN | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | PROVEN |

**SCB（比对）**

| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|---|---|---|
| SB-NPU-DUT | NPU 调度器 in-order 比对 | env DUT 检查收口；匹配 CHECK-FUNC 的测试点都归到这条 SB | per_scb | CELL-D_TYPE-P0 | 120 | 120 | 0 | PROVEN |

**Constraints（约束）**

| id | backed | 维度 | 说明 |
|---|---|---|---|
| p_th_b02_random | 是 | D_type | 1 条字段赋值（模型可驱动） |
| p_th_b09_random | 是 | D_type、D_unit | 1 条字段赋值（模型可驱动） |
| p_th_b11_random | 是 | D_queue、D_type、D_dtype、D_dep、D_unit、D_decision、D_cluster、D_opcode、D_seq、D_pipeline、D_priority、D_barrier | 7 条字段赋值（模型可驱动） |

## 视图1：用例 × 证据层（23 个逻辑用例 / 267 次执行）

| 逻辑用例 | 类型 | 执行 | 功能覆盖 | SVA | Scoreboard | PATH | 结论 |
|---|---|---|---|---|---|---|---|
| CASE-D_BARRIER | 用例 | ×4 | 🟢 通过 | 🔴 缺失 | 🟢 通过 | — 不适用 | 证据链不完整（SVA） |
| CASE-D_DTYPE | 用例 | ×4 | 🟢 通过 | — 不适用 | 🟢 通过 | — 不适用 | 不适用 |
| CASE-D_OPCODE | 用例 | ×10 | 🟢 通过 | — 不适用 | 🟢 通过 | — 不适用 | 不适用 |
| CASE-D_PIPELINE | 用例 | ×5 | 🔴 缺失 | — 不适用 | 🟢 通过 | — 不适用 | 证据链不完整（功能覆盖） |
| CASE-D_PRIORITY | 用例 | ×4 | 🟢 通过 | — 不适用 | 🟢 通过 | — 不适用 | 不适用 |
| CASE-D_QUEUE | 用例 | ×10 | 🟢 通过 | 🔴 缺失 | 🟢 通过 | — 不适用 | 证据链不完整（SVA） |
| CASE-D_SEQ | 用例 | ×6 | 🔴 缺失 | — 不适用 | 🟢 通过 | — 不适用 | 证据链不完整（功能覆盖） |
| CASE-D_TYPE | 用例 | ×4 | 🟢 通过 | — 不适用 | 🟢 通过 | — 不适用 | 不适用 |
| npu_basic_test | 批次 | ×1 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_cluster_test | 批次 | ×12 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_dep_test | 批次 | ×30 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_dma_compute_test | 批次 | ×14 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_dtype_test | 批次 | ×18 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_full_queue_test | 批次 | ×18 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_opcode_test | 批次 | ×10 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_pipeline_test | 批次 | ×14 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_random_mix_test | 批次 | ×48 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_raw_stall_test | 批次 | ×12 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_sched_env_directed_test | 批次 | ×22 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_sched_env_gen_test | 批次 | ×1 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |
| npu_sched_in_loopback_test | 批次 | ×1 | — 不适用 | 🟡 部分 | 🟡 部分 | — 不适用 | 待补（SVA、Scoreboard） |
| npu_sched_out_loopback_test | 批次 | ×1 | — 不适用 | 🟡 部分 | 🟡 部分 | — 不适用 | 待补（SVA、Scoreboard） |
| npu_type_test | 批次 | ×18 | — 不适用 | 🟡 部分 | 🟢 通过 | — 不适用 | 待补（SVA） |

## 视图2：功能契约 × 证据层

| Feat | 描述 | 功能覆盖 | SVA | Scoreboard | PATH | 状态 |
|---|---|---|---|---|---|---|
| REQ-NPU-001 | 指令队列水位 | ? | ? | ? | — | 待补（） |
| REQ-NPU-002 | 指令类型 | ? | ? | ? | — | 待补（） |
| REQ-NPU-003 | 数据类型 | ? | ? | ? | — | 待补（） |
| REQ-NPU-004 | 数据依赖 | ? | ? | ? | — | 证据链不完整 |
| REQ-NPU-005 | 执行单元 | ? | ? | ? | — | 待补（） |
| REQ-NPU-006 | 发射决策 | ? | ? | ? | — | 证据链不完整 |
| REQ-NPU-007 | 簇 ID | ? | ? | ? | — | 待补（） |
| REQ-NPU-008 | 硬件指令操作码 | ? | ? | ? | — | 待补（） |
| REQ-NPU-009 | 指令序列模式 | ? | ? | ? | — | 待补（） |
| REQ-NPU-010 | 流水重叠 | ? | ? | ? | — | 待补（） |
| REQ-NPU-011 | 优先级调度 | ? | ? | ? | — | 待补（） |
| REQ-NPU-012 | 硬件同步屏障 | ? | ? | ? | — | 待补（） |
| dim:队列水位迁移 | 队列水位迁移 | ? | ? | ? | — | 待补（） |

## 视图3：功能组 × 生命周期路径

| 路径 | 优先级调度 | 发射决策 | 执行单元 | 指令序列模式 | 指令类型 | 指令队列水位 | 数据依赖 | 数据类型 | 流水重叠 | 硬件同步屏障 | 硬件指令操作码 | 簇 ID |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| （未声明 PATH 组） | 🟢 | 🟡 | 🟡 | 🟢 | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 | 🟢 | 🟢 | 🟡 |

## 视图4：缺口与豁免

| 类型 | 项 | 根因 | 补齐动作 | 责任人 | 状态 |
|---|---|---|---|---|---|
| CELL 部分证据 | CELL-BEH_QUEUE-BEHAVIOR | TP-NPUSCH-BEH_QUEUE-TR_EMPTY_ENQ: PENDING_BACKEND；TP-NPUSCH-BEH_QUEUE-TR_LOW_ENQ: PENDING_BACKEND；TP-NPUSCH-BEH_QUEUE-TR_HIGH_ENQ: PENDING_BACKEND… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_BARRIER-P3 | TP-NPUSCH-D_BARRIER-NONE: PARTIAL；TP-NPUSCH-D_BARRIER-TILE_BARRIER: PARTIAL；TP-NPUSCH-D_BARRIER-OP_BARRIER: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_CLUSTER-P2 | TP-NPUSCH-D_CLUSTER-0: PARTIAL；TP-NPUSCH-D_CLUSTER-1: PARTIAL；TP-NPUSCH-D_CLUSTER-2: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 未签核 | CELL-D_DECISION-P0 | TP-NPUSCH-D_DECISION-BLOCKED: NOT_VERIFIED | 补缺失证据（同一条用例 + 同一种子） | 待分配 | 未开始 |
| CELL 未签核 | CELL-D_DEP-P1 | TP-NPUSCH-D_DEP-WAR: NOT_VERIFIED | 补缺失证据（同一条用例 + 同一种子） | 待分配 | 未开始 |
| CELL 部分证据 | CELL-D_DTYPE-P0 | TP-NPUSCH-D_DTYPE-INT8: PARTIAL；TP-NPUSCH-D_DTYPE-FP16: PARTIAL；TP-NPUSCH-D_DTYPE-BF16: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_OPCODE-P2 | TP-NPUSCH-D_OPCODE-MAC_INT8: PARTIAL；TP-NPUSCH-D_OPCODE-MAC_FP16: PARTIAL；TP-NPUSCH-D_OPCODE-MAC_BF16: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_PIPELINE-P3 | TP-NPUSCH-D_PIPELINE-NONE: PARTIAL；TP-NPUSCH-D_PIPELINE-MAC_MAC: PARTIAL；TP-NPUSCH-D_PIPELINE-MAC_DMA: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_PRIORITY-P3 | TP-NPUSCH-D_PRIORITY-HIGH_FIRST: PARTIAL；TP-NPUSCH-D_PRIORITY-LOW_FIRST: PARTIAL；TP-NPUSCH-D_PRIORITY-SAME_PRIO: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_QUEUE-P1 | TP-NPUSCH-D_QUEUE-0: PARTIAL；TP-NPUSCH-D_QUEUE-1: PARTIAL；TP-NPUSCH-D_QUEUE-7: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_SEQ-P3 | TP-NPUSCH-D_SEQ-MAC_MAC: PARTIAL；TP-NPUSCH-D_SEQ-LOAD_MAC: PARTIAL；TP-NPUSCH-D_SEQ-MAC_STORE: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_TYPE-P0 | TP-NPUSCH-D_TYPE-MAC: PARTIAL；TP-NPUSCH-D_TYPE-VECTOR: PARTIAL；TP-NPUSCH-D_TYPE-SCALAR: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| CELL 部分证据 | CELL-D_UNIT-P2 | TP-NPUSCH-D_UNIT-MAC: PARTIAL；TP-NPUSCH-D_UNIT-VECTOR: PARTIAL；TP-NPUSCH-D_UNIT-SCALAR: PARTIAL… | 补齐未签核 TP 的执行证据 / 接后端 | 待分配 | 进行中 |
| 证据缺失 | TP-NPUSCH-D_DEP-WAR 功能覆盖 | 未完整证明 | 补定向激励/覆盖仓，或修 monitor 采样条件 | 待分配 | 未开始 |
| 证据缺失 | TP-NPUSCH-D_DECISION-BLOCKED 功能覆盖 | 未完整证明 | 补定向激励/覆盖仓，或修 monitor 采样条件 | 待分配 | 未开始 |

## 视图5：Case 分类树

| 分类 | 名称 | 父级 | 用例数 | 测试数 | 来源 |
|---|---|---|---|---|---|
| CCAT-ROOT | 根 | — | 13 | 0 | declared |
| CCAT-OBJ-01 | 指令队列管理 | CCAT-ROOT | 0 | 0 | declared |
| CCAT-OBJ-02 | 指令发射 | CCAT-ROOT | 0 | 0 | declared |
| CCAT-OBJ-03 | 多簇同步 | CCAT-ROOT | 0 | 0 | declared |

## 视图6：Case × CELL

| CELL | CG | P | 颜色 | TP 数 | 声明用例 | 实际用例 |
|---|---|---|---|---|---|---|
| CELL-BEH_QUEUE-BEHAVIOR | BEH_QUEUE | behavior | 🟡 | 7 | CASE-BEH_QUEUE | — |
| CELL-D_BARRIER-P3 | D_barrier | p3 | 🟡 | 4 | CASE-D_BARRIER | CASE-D_BARRIER |
| CELL-D_CLUSTER-P2 | D_cluster | p2 | 🟡 | 4 | CASE-D_CLUSTER | — |
| CELL-D_DECISION-P0 | D_decision | p0 | 🔴 | 4 | CASE-D_DECISION | — |
| CELL-D_DEP-P1 | D_dep | p1 | 🔴 | 4 | CASE-D_DEP | — |
| CELL-D_DTYPE-P0 | D_dtype | p0 | 🟡 | 4 | CASE-D_DTYPE | CASE-D_DTYPE |
| CELL-D_OPCODE-P2 | D_opcode | p2 | 🟡 | 10 | CASE-D_OPCODE | CASE-D_OPCODE |
| CELL-D_PIPELINE-P3 | D_pipeline | p3 | 🟡 | 5 | CASE-D_PIPELINE | CASE-D_PIPELINE |
| CELL-D_PRIORITY-P3 | D_priority | p3 | 🟡 | 4 | CASE-D_PRIORITY | CASE-D_PRIORITY |
| CELL-D_QUEUE-P1 | D_queue | p1 | 🟡 | 10 | CASE-D_QUEUE | CASE-D_QUEUE |
| CELL-D_SEQ-P3 | D_seq | p3 | 🟡 | 6 | CASE-D_SEQ | CASE-D_SEQ |
| CELL-D_TYPE-P0 | D_type | p0 | 🟡 | 4 | CASE-D_TYPE | CASE-D_TYPE |
| CELL-D_UNIT-P2 | D_unit | p2 | 🟡 | 4 | CASE-D_UNIT | — |

## 视图7：执行证据（EVD）

| EVD | CASE | TST | 测试 | seed | 阶段 | 波形 | legacy |
|---|---|---|---|---|---|---|---|
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_BASIC_TEST@1001 | — | TST-NPU_BASIC_TEST@1001 | npu_basic_test | 1001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_basic_test_seed_1001/waves/npu_basic_test.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7001 | — | TST-NPU_CLUSTER_TEST@7001 | npu_cluster_test | 7001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_1_seed_7001/waves/npu_cluster_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7002 | — | TST-NPU_CLUSTER_TEST@7002 | npu_cluster_test | 7002 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_2_seed_7002/waves/npu_cluster_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7003 | — | TST-NPU_CLUSTER_TEST@7003 | npu_cluster_test | 7003 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_3_seed_7003/waves/npu_cluster_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7004 | — | TST-NPU_CLUSTER_TEST@7004 | npu_cluster_test | 7004 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_4_seed_7004/waves/npu_cluster_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7005 | — | TST-NPU_CLUSTER_TEST@7005 | npu_cluster_test | 7005 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_5_seed_7005/waves/npu_cluster_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7006 | — | TST-NPU_CLUSTER_TEST@7006 | npu_cluster_test | 7006 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_6_seed_7006/waves/npu_cluster_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7007 | — | TST-NPU_CLUSTER_TEST@7007 | npu_cluster_test | 7007 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_7_seed_7007/waves/npu_cluster_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7008 | — | TST-NPU_CLUSTER_TEST@7008 | npu_cluster_test | 7008 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_8_seed_7008/waves/npu_cluster_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7009 | — | TST-NPU_CLUSTER_TEST@7009 | npu_cluster_test | 7009 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_9_seed_7009/waves/npu_cluster_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7010 | — | TST-NPU_CLUSTER_TEST@7010 | npu_cluster_test | 7010 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_10_seed_7010/waves/npu_cluster_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7011 | — | TST-NPU_CLUSTER_TEST@7011 | npu_cluster_test | 7011 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_11_seed_7011/waves/npu_cluster_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_CLUSTER_TEST@7012 | — | TST-NPU_CLUSTER_TEST@7012 | npu_cluster_test | 7012 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_cluster_test_run_12_seed_7012/waves/npu_cluster_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4001 | — | TST-NPU_DEP_TEST@4001 | npu_dep_test | 4001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_1_seed_4001/waves/npu_dep_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4002 | — | TST-NPU_DEP_TEST@4002 | npu_dep_test | 4002 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_2_seed_4002/waves/npu_dep_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4003 | — | TST-NPU_DEP_TEST@4003 | npu_dep_test | 4003 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_3_seed_4003/waves/npu_dep_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4004 | — | TST-NPU_DEP_TEST@4004 | npu_dep_test | 4004 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_4_seed_4004/waves/npu_dep_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4005 | — | TST-NPU_DEP_TEST@4005 | npu_dep_test | 4005 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_5_seed_4005/waves/npu_dep_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4006 | — | TST-NPU_DEP_TEST@4006 | npu_dep_test | 4006 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_6_seed_4006/waves/npu_dep_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4007 | — | TST-NPU_DEP_TEST@4007 | npu_dep_test | 4007 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_7_seed_4007/waves/npu_dep_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4008 | — | TST-NPU_DEP_TEST@4008 | npu_dep_test | 4008 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_8_seed_4008/waves/npu_dep_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4009 | — | TST-NPU_DEP_TEST@4009 | npu_dep_test | 4009 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_9_seed_4009/waves/npu_dep_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4010 | — | TST-NPU_DEP_TEST@4010 | npu_dep_test | 4010 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_10_seed_4010/waves/npu_dep_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4011 | — | TST-NPU_DEP_TEST@4011 | npu_dep_test | 4011 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_11_seed_4011/waves/npu_dep_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4012 | — | TST-NPU_DEP_TEST@4012 | npu_dep_test | 4012 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_12_seed_4012/waves/npu_dep_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4013 | — | TST-NPU_DEP_TEST@4013 | npu_dep_test | 4013 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_13_seed_4013/waves/npu_dep_test_run_13.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4014 | — | TST-NPU_DEP_TEST@4014 | npu_dep_test | 4014 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_14_seed_4014/waves/npu_dep_test_run_14.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4015 | — | TST-NPU_DEP_TEST@4015 | npu_dep_test | 4015 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_15_seed_4015/waves/npu_dep_test_run_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4016 | — | TST-NPU_DEP_TEST@4016 | npu_dep_test | 4016 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_16_seed_4016/waves/npu_dep_test_run_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4017 | — | TST-NPU_DEP_TEST@4017 | npu_dep_test | 4017 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_17_seed_4017/waves/npu_dep_test_run_17.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4018 | — | TST-NPU_DEP_TEST@4018 | npu_dep_test | 4018 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_18_seed_4018/waves/npu_dep_test_run_18.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4019 | — | TST-NPU_DEP_TEST@4019 | npu_dep_test | 4019 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_19_seed_4019/waves/npu_dep_test_run_19.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4020 | — | TST-NPU_DEP_TEST@4020 | npu_dep_test | 4020 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_20_seed_4020/waves/npu_dep_test_run_20.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4021 | — | TST-NPU_DEP_TEST@4021 | npu_dep_test | 4021 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_21_seed_4021/waves/npu_dep_test_run_21.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4022 | — | TST-NPU_DEP_TEST@4022 | npu_dep_test | 4022 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_22_seed_4022/waves/npu_dep_test_run_22.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4023 | — | TST-NPU_DEP_TEST@4023 | npu_dep_test | 4023 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_23_seed_4023/waves/npu_dep_test_run_23.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4024 | — | TST-NPU_DEP_TEST@4024 | npu_dep_test | 4024 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_24_seed_4024/waves/npu_dep_test_run_24.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4025 | — | TST-NPU_DEP_TEST@4025 | npu_dep_test | 4025 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_25_seed_4025/waves/npu_dep_test_run_25.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4026 | — | TST-NPU_DEP_TEST@4026 | npu_dep_test | 4026 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_26_seed_4026/waves/npu_dep_test_run_26.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4027 | — | TST-NPU_DEP_TEST@4027 | npu_dep_test | 4027 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_27_seed_4027/waves/npu_dep_test_run_27.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4028 | — | TST-NPU_DEP_TEST@4028 | npu_dep_test | 4028 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_28_seed_4028/waves/npu_dep_test_run_28.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4029 | — | TST-NPU_DEP_TEST@4029 | npu_dep_test | 4029 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_29_seed_4029/waves/npu_dep_test_run_29.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DEP_TEST@4030 | — | TST-NPU_DEP_TEST@4030 | npu_dep_test | 4030 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_dep_test_run_30_seed_4030/waves/npu_dep_test_run_30.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9001 | — | TST-NPU_DMA_COMPUTE_TEST@9001 | npu_dma_compute_test | 9001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_1_seed_9001/waves/npu_dma_compute_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9002 | — | TST-NPU_DMA_COMPUTE_TEST@9002 | npu_dma_compute_test | 9002 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_2_seed_9002/waves/npu_dma_compute_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9003 | — | TST-NPU_DMA_COMPUTE_TEST@9003 | npu_dma_compute_test | 9003 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_3_seed_9003/waves/npu_dma_compute_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9004 | — | TST-NPU_DMA_COMPUTE_TEST@9004 | npu_dma_compute_test | 9004 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_4_seed_9004/waves/npu_dma_compute_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9005 | — | TST-NPU_DMA_COMPUTE_TEST@9005 | npu_dma_compute_test | 9005 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_5_seed_9005/waves/npu_dma_compute_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9006 | — | TST-NPU_DMA_COMPUTE_TEST@9006 | npu_dma_compute_test | 9006 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_6_seed_9006/waves/npu_dma_compute_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9007 | — | TST-NPU_DMA_COMPUTE_TEST@9007 | npu_dma_compute_test | 9007 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_7_seed_9007/waves/npu_dma_compute_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9008 | — | TST-NPU_DMA_COMPUTE_TEST@9008 | npu_dma_compute_test | 9008 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_8_seed_9008/waves/npu_dma_compute_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9009 | — | TST-NPU_DMA_COMPUTE_TEST@9009 | npu_dma_compute_test | 9009 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_9_seed_9009/waves/npu_dma_compute_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9010 | — | TST-NPU_DMA_COMPUTE_TEST@9010 | npu_dma_compute_test | 9010 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_10_seed_9010/waves/npu_dma_compute_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9011 | — | TST-NPU_DMA_COMPUTE_TEST@9011 | npu_dma_compute_test | 9011 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_11_seed_9011/waves/npu_dma_compute_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9012 | — | TST-NPU_DMA_COMPUTE_TEST@9012 | npu_dma_compute_test | 9012 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_12_seed_9012/waves/npu_dma_compute_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9013 | — | TST-NPU_DMA_COMPUTE_TEST@9013 | npu_dma_compute_test | 9013 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_13_seed_9013/waves/npu_dma_compute_test_run_13.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DMA_COMPUTE_TEST@9014 | — | TST-NPU_DMA_COMPUTE_TEST@9014 | npu_dma_compute_test | 9014 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_dma_compute_test_run_14_seed_9014/waves/npu_dma_compute_test_run_14.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3001 | — | TST-NPU_DTYPE_TEST@3001 | npu_dtype_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_1_seed_3001/waves/npu_dtype_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3002 | — | TST-NPU_DTYPE_TEST@3002 | npu_dtype_test | 3002 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_2_seed_3002/waves/npu_dtype_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3003 | — | TST-NPU_DTYPE_TEST@3003 | npu_dtype_test | 3003 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_3_seed_3003/waves/npu_dtype_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3004 | — | TST-NPU_DTYPE_TEST@3004 | npu_dtype_test | 3004 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_4_seed_3004/waves/npu_dtype_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3005 | — | TST-NPU_DTYPE_TEST@3005 | npu_dtype_test | 3005 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_5_seed_3005/waves/npu_dtype_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3006 | — | TST-NPU_DTYPE_TEST@3006 | npu_dtype_test | 3006 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_6_seed_3006/waves/npu_dtype_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3007 | — | TST-NPU_DTYPE_TEST@3007 | npu_dtype_test | 3007 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_7_seed_3007/waves/npu_dtype_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3008 | — | TST-NPU_DTYPE_TEST@3008 | npu_dtype_test | 3008 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_8_seed_3008/waves/npu_dtype_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3009 | — | TST-NPU_DTYPE_TEST@3009 | npu_dtype_test | 3009 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_9_seed_3009/waves/npu_dtype_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3010 | — | TST-NPU_DTYPE_TEST@3010 | npu_dtype_test | 3010 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_10_seed_3010/waves/npu_dtype_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3011 | — | TST-NPU_DTYPE_TEST@3011 | npu_dtype_test | 3011 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_11_seed_3011/waves/npu_dtype_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3012 | — | TST-NPU_DTYPE_TEST@3012 | npu_dtype_test | 3012 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_12_seed_3012/waves/npu_dtype_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3013 | — | TST-NPU_DTYPE_TEST@3013 | npu_dtype_test | 3013 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_13_seed_3013/waves/npu_dtype_test_run_13.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3014 | — | TST-NPU_DTYPE_TEST@3014 | npu_dtype_test | 3014 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_14_seed_3014/waves/npu_dtype_test_run_14.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3015 | — | TST-NPU_DTYPE_TEST@3015 | npu_dtype_test | 3015 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_15_seed_3015/waves/npu_dtype_test_run_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3016 | — | TST-NPU_DTYPE_TEST@3016 | npu_dtype_test | 3016 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_16_seed_3016/waves/npu_dtype_test_run_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3017 | — | TST-NPU_DTYPE_TEST@3017 | npu_dtype_test | 3017 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_17_seed_3017/waves/npu_dtype_test_run_17.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_DTYPE_TEST@3018 | — | TST-NPU_DTYPE_TEST@3018 | npu_dtype_test | 3018 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_dtype_test_run_18_seed_3018/waves/npu_dtype_test_run_18.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6001 | — | TST-NPU_FULL_QUEUE_TEST@6001 | npu_full_queue_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_1_seed_6001/waves/npu_full_queue_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6002 | — | TST-NPU_FULL_QUEUE_TEST@6002 | npu_full_queue_test | 6002 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_2_seed_6002/waves/npu_full_queue_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6003 | — | TST-NPU_FULL_QUEUE_TEST@6003 | npu_full_queue_test | 6003 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_3_seed_6003/waves/npu_full_queue_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6004 | — | TST-NPU_FULL_QUEUE_TEST@6004 | npu_full_queue_test | 6004 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_4_seed_6004/waves/npu_full_queue_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6005 | — | TST-NPU_FULL_QUEUE_TEST@6005 | npu_full_queue_test | 6005 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_5_seed_6005/waves/npu_full_queue_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6006 | — | TST-NPU_FULL_QUEUE_TEST@6006 | npu_full_queue_test | 6006 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_6_seed_6006/waves/npu_full_queue_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6007 | — | TST-NPU_FULL_QUEUE_TEST@6007 | npu_full_queue_test | 6007 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_7_seed_6007/waves/npu_full_queue_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6008 | — | TST-NPU_FULL_QUEUE_TEST@6008 | npu_full_queue_test | 6008 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_8_seed_6008/waves/npu_full_queue_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6009 | — | TST-NPU_FULL_QUEUE_TEST@6009 | npu_full_queue_test | 6009 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_9_seed_6009/waves/npu_full_queue_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6010 | — | TST-NPU_FULL_QUEUE_TEST@6010 | npu_full_queue_test | 6010 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_10_seed_6010/waves/npu_full_queue_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6011 | — | TST-NPU_FULL_QUEUE_TEST@6011 | npu_full_queue_test | 6011 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_11_seed_6011/waves/npu_full_queue_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6012 | — | TST-NPU_FULL_QUEUE_TEST@6012 | npu_full_queue_test | 6012 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_12_seed_6012/waves/npu_full_queue_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6013 | — | TST-NPU_FULL_QUEUE_TEST@6013 | npu_full_queue_test | 6013 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_13_seed_6013/waves/npu_full_queue_test_run_13.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6014 | — | TST-NPU_FULL_QUEUE_TEST@6014 | npu_full_queue_test | 6014 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_14_seed_6014/waves/npu_full_queue_test_run_14.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6015 | — | TST-NPU_FULL_QUEUE_TEST@6015 | npu_full_queue_test | 6015 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_15_seed_6015/waves/npu_full_queue_test_run_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6016 | — | TST-NPU_FULL_QUEUE_TEST@6016 | npu_full_queue_test | 6016 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_16_seed_6016/waves/npu_full_queue_test_run_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6017 | — | TST-NPU_FULL_QUEUE_TEST@6017 | npu_full_queue_test | 6017 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_17_seed_6017/waves/npu_full_queue_test_run_17.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_FULL_QUEUE_TEST@6018 | — | TST-NPU_FULL_QUEUE_TEST@6018 | npu_full_queue_test | 6018 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_full_queue_test_run_18_seed_6018/waves/npu_full_queue_test_run_18.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8001 | — | TST-NPU_OPCODE_TEST@8001 | npu_opcode_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_1_seed_8001/waves/npu_opcode_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8002 | — | TST-NPU_OPCODE_TEST@8002 | npu_opcode_test | 8002 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_2_seed_8002/waves/npu_opcode_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8003 | — | TST-NPU_OPCODE_TEST@8003 | npu_opcode_test | 8003 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_3_seed_8003/waves/npu_opcode_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8004 | — | TST-NPU_OPCODE_TEST@8004 | npu_opcode_test | 8004 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_4_seed_8004/waves/npu_opcode_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8005 | — | TST-NPU_OPCODE_TEST@8005 | npu_opcode_test | 8005 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_5_seed_8005/waves/npu_opcode_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8006 | — | TST-NPU_OPCODE_TEST@8006 | npu_opcode_test | 8006 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_6_seed_8006/waves/npu_opcode_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8007 | — | TST-NPU_OPCODE_TEST@8007 | npu_opcode_test | 8007 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_7_seed_8007/waves/npu_opcode_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8008 | — | TST-NPU_OPCODE_TEST@8008 | npu_opcode_test | 8008 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_8_seed_8008/waves/npu_opcode_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8009 | — | TST-NPU_OPCODE_TEST@8009 | npu_opcode_test | 8009 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_9_seed_8009/waves/npu_opcode_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_OPCODE_TEST@8010 | — | TST-NPU_OPCODE_TEST@8010 | npu_opcode_test | 8010 | p2 | regression_run/p2/build_build_npu_sched_dut/test_npu_opcode_test_run_10_seed_8010/waves/npu_opcode_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9501 | — | TST-NPU_PIPELINE_TEST@9501 | npu_pipeline_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_1_seed_9501/waves/npu_pipeline_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9502 | — | TST-NPU_PIPELINE_TEST@9502 | npu_pipeline_test | 9502 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_2_seed_9502/waves/npu_pipeline_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9503 | — | TST-NPU_PIPELINE_TEST@9503 | npu_pipeline_test | 9503 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_3_seed_9503/waves/npu_pipeline_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9504 | — | TST-NPU_PIPELINE_TEST@9504 | npu_pipeline_test | 9504 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_4_seed_9504/waves/npu_pipeline_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9505 | — | TST-NPU_PIPELINE_TEST@9505 | npu_pipeline_test | 9505 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_5_seed_9505/waves/npu_pipeline_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9506 | — | TST-NPU_PIPELINE_TEST@9506 | npu_pipeline_test | 9506 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_6_seed_9506/waves/npu_pipeline_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9507 | — | TST-NPU_PIPELINE_TEST@9507 | npu_pipeline_test | 9507 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_7_seed_9507/waves/npu_pipeline_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9508 | — | TST-NPU_PIPELINE_TEST@9508 | npu_pipeline_test | 9508 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_8_seed_9508/waves/npu_pipeline_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9509 | — | TST-NPU_PIPELINE_TEST@9509 | npu_pipeline_test | 9509 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_9_seed_9509/waves/npu_pipeline_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9510 | — | TST-NPU_PIPELINE_TEST@9510 | npu_pipeline_test | 9510 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_10_seed_9510/waves/npu_pipeline_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9511 | — | TST-NPU_PIPELINE_TEST@9511 | npu_pipeline_test | 9511 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_11_seed_9511/waves/npu_pipeline_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9512 | — | TST-NPU_PIPELINE_TEST@9512 | npu_pipeline_test | 9512 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_12_seed_9512/waves/npu_pipeline_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9513 | — | TST-NPU_PIPELINE_TEST@9513 | npu_pipeline_test | 9513 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_13_seed_9513/waves/npu_pipeline_test_run_13.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_PIPELINE_TEST@9514 | — | TST-NPU_PIPELINE_TEST@9514 | npu_pipeline_test | 9514 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_pipeline_test_run_14_seed_9514/waves/npu_pipeline_test_run_14.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10001 | — | TST-NPU_RANDOM_MIX_TEST@10001 | npu_random_mix_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_1_seed_10001/waves/npu_random_mix_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10002 | — | TST-NPU_RANDOM_MIX_TEST@10002 | npu_random_mix_test | 10002 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_2_seed_10002/waves/npu_random_mix_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10003 | — | TST-NPU_RANDOM_MIX_TEST@10003 | npu_random_mix_test | 10003 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_3_seed_10003/waves/npu_random_mix_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10004 | — | TST-NPU_RANDOM_MIX_TEST@10004 | npu_random_mix_test | 10004 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_4_seed_10004/waves/npu_random_mix_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10005 | — | TST-NPU_RANDOM_MIX_TEST@10005 | npu_random_mix_test | 10005 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_5_seed_10005/waves/npu_random_mix_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10006 | — | TST-NPU_RANDOM_MIX_TEST@10006 | npu_random_mix_test | 10006 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_6_seed_10006/waves/npu_random_mix_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10007 | — | TST-NPU_RANDOM_MIX_TEST@10007 | npu_random_mix_test | 10007 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_7_seed_10007/waves/npu_random_mix_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10008 | — | TST-NPU_RANDOM_MIX_TEST@10008 | npu_random_mix_test | 10008 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_8_seed_10008/waves/npu_random_mix_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10009 | — | TST-NPU_RANDOM_MIX_TEST@10009 | npu_random_mix_test | 10009 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_9_seed_10009/waves/npu_random_mix_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10010 | — | TST-NPU_RANDOM_MIX_TEST@10010 | npu_random_mix_test | 10010 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_10_seed_10010/waves/npu_random_mix_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10011 | — | TST-NPU_RANDOM_MIX_TEST@10011 | npu_random_mix_test | 10011 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_11_seed_10011/waves/npu_random_mix_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10012 | — | TST-NPU_RANDOM_MIX_TEST@10012 | npu_random_mix_test | 10012 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_12_seed_10012/waves/npu_random_mix_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10013 | — | TST-NPU_RANDOM_MIX_TEST@10013 | npu_random_mix_test | 10013 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_13_seed_10013/waves/npu_random_mix_test_run_13.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10014 | — | TST-NPU_RANDOM_MIX_TEST@10014 | npu_random_mix_test | 10014 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_14_seed_10014/waves/npu_random_mix_test_run_14.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10015 | — | TST-NPU_RANDOM_MIX_TEST@10015 | npu_random_mix_test | 10015 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_15_seed_10015/waves/npu_random_mix_test_run_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10016 | — | TST-NPU_RANDOM_MIX_TEST@10016 | npu_random_mix_test | 10016 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_16_seed_10016/waves/npu_random_mix_test_run_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10017 | — | TST-NPU_RANDOM_MIX_TEST@10017 | npu_random_mix_test | 10017 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_17_seed_10017/waves/npu_random_mix_test_run_17.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10018 | — | TST-NPU_RANDOM_MIX_TEST@10018 | npu_random_mix_test | 10018 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_18_seed_10018/waves/npu_random_mix_test_run_18.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10019 | — | TST-NPU_RANDOM_MIX_TEST@10019 | npu_random_mix_test | 10019 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_19_seed_10019/waves/npu_random_mix_test_run_19.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10020 | — | TST-NPU_RANDOM_MIX_TEST@10020 | npu_random_mix_test | 10020 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_20_seed_10020/waves/npu_random_mix_test_run_20.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10021 | — | TST-NPU_RANDOM_MIX_TEST@10021 | npu_random_mix_test | 10021 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_21_seed_10021/waves/npu_random_mix_test_run_21.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10022 | — | TST-NPU_RANDOM_MIX_TEST@10022 | npu_random_mix_test | 10022 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_22_seed_10022/waves/npu_random_mix_test_run_22.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10023 | — | TST-NPU_RANDOM_MIX_TEST@10023 | npu_random_mix_test | 10023 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_23_seed_10023/waves/npu_random_mix_test_run_23.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10024 | — | TST-NPU_RANDOM_MIX_TEST@10024 | npu_random_mix_test | 10024 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_24_seed_10024/waves/npu_random_mix_test_run_24.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10025 | — | TST-NPU_RANDOM_MIX_TEST@10025 | npu_random_mix_test | 10025 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_25_seed_10025/waves/npu_random_mix_test_run_25.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10026 | — | TST-NPU_RANDOM_MIX_TEST@10026 | npu_random_mix_test | 10026 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_26_seed_10026/waves/npu_random_mix_test_run_26.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10027 | — | TST-NPU_RANDOM_MIX_TEST@10027 | npu_random_mix_test | 10027 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_27_seed_10027/waves/npu_random_mix_test_run_27.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10028 | — | TST-NPU_RANDOM_MIX_TEST@10028 | npu_random_mix_test | 10028 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_28_seed_10028/waves/npu_random_mix_test_run_28.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10029 | — | TST-NPU_RANDOM_MIX_TEST@10029 | npu_random_mix_test | 10029 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_29_seed_10029/waves/npu_random_mix_test_run_29.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10030 | — | TST-NPU_RANDOM_MIX_TEST@10030 | npu_random_mix_test | 10030 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_30_seed_10030/waves/npu_random_mix_test_run_30.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10031 | — | TST-NPU_RANDOM_MIX_TEST@10031 | npu_random_mix_test | 10031 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_31_seed_10031/waves/npu_random_mix_test_run_31.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10032 | — | TST-NPU_RANDOM_MIX_TEST@10032 | npu_random_mix_test | 10032 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_32_seed_10032/waves/npu_random_mix_test_run_32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10033 | — | TST-NPU_RANDOM_MIX_TEST@10033 | npu_random_mix_test | 10033 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_33_seed_10033/waves/npu_random_mix_test_run_33.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10034 | — | TST-NPU_RANDOM_MIX_TEST@10034 | npu_random_mix_test | 10034 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_34_seed_10034/waves/npu_random_mix_test_run_34.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10035 | — | TST-NPU_RANDOM_MIX_TEST@10035 | npu_random_mix_test | 10035 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_35_seed_10035/waves/npu_random_mix_test_run_35.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10036 | — | TST-NPU_RANDOM_MIX_TEST@10036 | npu_random_mix_test | 10036 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_36_seed_10036/waves/npu_random_mix_test_run_36.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10037 | — | TST-NPU_RANDOM_MIX_TEST@10037 | npu_random_mix_test | 10037 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_37_seed_10037/waves/npu_random_mix_test_run_37.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10038 | — | TST-NPU_RANDOM_MIX_TEST@10038 | npu_random_mix_test | 10038 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_38_seed_10038/waves/npu_random_mix_test_run_38.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10039 | — | TST-NPU_RANDOM_MIX_TEST@10039 | npu_random_mix_test | 10039 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_39_seed_10039/waves/npu_random_mix_test_run_39.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10040 | — | TST-NPU_RANDOM_MIX_TEST@10040 | npu_random_mix_test | 10040 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_40_seed_10040/waves/npu_random_mix_test_run_40.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10041 | — | TST-NPU_RANDOM_MIX_TEST@10041 | npu_random_mix_test | 10041 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_41_seed_10041/waves/npu_random_mix_test_run_41.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10042 | — | TST-NPU_RANDOM_MIX_TEST@10042 | npu_random_mix_test | 10042 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_42_seed_10042/waves/npu_random_mix_test_run_42.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10043 | — | TST-NPU_RANDOM_MIX_TEST@10043 | npu_random_mix_test | 10043 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_43_seed_10043/waves/npu_random_mix_test_run_43.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10044 | — | TST-NPU_RANDOM_MIX_TEST@10044 | npu_random_mix_test | 10044 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_44_seed_10044/waves/npu_random_mix_test_run_44.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10045 | — | TST-NPU_RANDOM_MIX_TEST@10045 | npu_random_mix_test | 10045 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_45_seed_10045/waves/npu_random_mix_test_run_45.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10046 | — | TST-NPU_RANDOM_MIX_TEST@10046 | npu_random_mix_test | 10046 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_46_seed_10046/waves/npu_random_mix_test_run_46.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10047 | — | TST-NPU_RANDOM_MIX_TEST@10047 | npu_random_mix_test | 10047 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_47_seed_10047/waves/npu_random_mix_test_run_47.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RANDOM_MIX_TEST@10048 | — | TST-NPU_RANDOM_MIX_TEST@10048 | npu_random_mix_test | 10048 | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_random_mix_test_run_48_seed_10048/waves/npu_random_mix_test_run_48.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5001 | — | TST-NPU_RAW_STALL_TEST@5001 | npu_raw_stall_test | 5001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_1_seed_5001/waves/npu_raw_stall_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5002 | — | TST-NPU_RAW_STALL_TEST@5002 | npu_raw_stall_test | 5002 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_2_seed_5002/waves/npu_raw_stall_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5003 | — | TST-NPU_RAW_STALL_TEST@5003 | npu_raw_stall_test | 5003 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_3_seed_5003/waves/npu_raw_stall_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5004 | — | TST-NPU_RAW_STALL_TEST@5004 | npu_raw_stall_test | 5004 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_4_seed_5004/waves/npu_raw_stall_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5005 | — | TST-NPU_RAW_STALL_TEST@5005 | npu_raw_stall_test | 5005 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_5_seed_5005/waves/npu_raw_stall_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5006 | — | TST-NPU_RAW_STALL_TEST@5006 | npu_raw_stall_test | 5006 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_6_seed_5006/waves/npu_raw_stall_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5007 | — | TST-NPU_RAW_STALL_TEST@5007 | npu_raw_stall_test | 5007 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_7_seed_5007/waves/npu_raw_stall_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5008 | — | TST-NPU_RAW_STALL_TEST@5008 | npu_raw_stall_test | 5008 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_8_seed_5008/waves/npu_raw_stall_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5009 | — | TST-NPU_RAW_STALL_TEST@5009 | npu_raw_stall_test | 5009 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_9_seed_5009/waves/npu_raw_stall_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5010 | — | TST-NPU_RAW_STALL_TEST@5010 | npu_raw_stall_test | 5010 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_10_seed_5010/waves/npu_raw_stall_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5011 | — | TST-NPU_RAW_STALL_TEST@5011 | npu_raw_stall_test | 5011 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_11_seed_5011/waves/npu_raw_stall_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_RAW_STALL_TEST@5012 | — | TST-NPU_RAW_STALL_TEST@5012 | npu_raw_stall_test | 5012 | p1 | regression_run/p1/build_build_npu_sched_dut/test_npu_raw_stall_test_run_12_seed_5012/waves/npu_raw_stall_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_DIRECTED_TEST | — | TST-NPU_SCHED_ENV_DIRECTED_TEST | npu_sched_env_directed_test | None | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_sched_D_ADDR_0/waves/npu_sched_D_ADDR_0.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001 | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pCLUSTER_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_cluster_barrier_seed_10001/waves/tp_npusch_d_barrier_cluster_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001#group:CG-D_BARRIER | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pCLUSTER_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_cluster_barrier_seed_10001/waves/tp_npusch_d_barrier_cluster_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001#scb:SB-NPU-DUT | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pCLUSTER_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_cluster_barrier_seed_10001/waves/tp_npusch_d_barrier_cluster_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001#sva:SVA-BARRIER_FLUSHES | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PCLUSTER_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pCLUSTER_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_cluster_barrier_seed_10001/waves/tp_npusch_d_barrier_cluster_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001 | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001 | npu_sched_env_d_barrier_pNONE_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_none_seed_10001/waves/tp_npusch_d_barrier_none.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001#group:CG-D_BARRIER | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001 | npu_sched_env_d_barrier_pNONE_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_none_seed_10001/waves/tp_npusch_d_barrier_none.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001#scb:SB-NPU-DUT | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001 | npu_sched_env_d_barrier_pNONE_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_none_seed_10001/waves/tp_npusch_d_barrier_none.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001#sva:SVA-BARRIER_FLUSHES | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PNONE_TEST@10001 | npu_sched_env_d_barrier_pNONE_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_none_seed_10001/waves/tp_npusch_d_barrier_none.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001 | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pOP_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_op_barrier_seed_10001/waves/tp_npusch_d_barrier_op_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001#group:CG-D_BARRIER | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pOP_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_op_barrier_seed_10001/waves/tp_npusch_d_barrier_op_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001#scb:SB-NPU-DUT | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pOP_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_op_barrier_seed_10001/waves/tp_npusch_d_barrier_op_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001#sva:SVA-BARRIER_FLUSHES | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_POP_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pOP_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_op_barrier_seed_10001/waves/tp_npusch_d_barrier_op_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001 | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pTILE_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_tile_barrier_seed_10001/waves/tp_npusch_d_barrier_tile_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001#group:CG-D_BARRIER | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pTILE_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_tile_barrier_seed_10001/waves/tp_npusch_d_barrier_tile_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001#scb:SB-NPU-DUT | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pTILE_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_tile_barrier_seed_10001/waves/tp_npusch_d_barrier_tile_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001#sva:SVA-BARRIER_FLUSHES | CASE-D_BARRIER | TST-NPU_SCHED_ENV_D_BARRIER_PTILE_BARRIER_TEST@10001 | npu_sched_env_d_barrier_pTILE_BARRIER_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_barrier_tile_barrier_seed_10001/waves/tp_npusch_d_barrier_tile_barrier.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PBF16_TEST@3001 | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PBF16_TEST@3001 | npu_sched_env_d_dtype_pBF16_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_bf16_seed_3001/waves/tp_npusch_d_dtype_bf16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PBF16_TEST@3001#group:CG-D_DTYPE | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PBF16_TEST@3001 | npu_sched_env_d_dtype_pBF16_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_bf16_seed_3001/waves/tp_npusch_d_dtype_bf16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PBF16_TEST@3001#scb:SB-NPU-DUT | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PBF16_TEST@3001 | npu_sched_env_d_dtype_pBF16_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_bf16_seed_3001/waves/tp_npusch_d_dtype_bf16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PFP16_TEST@3001 | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PFP16_TEST@3001 | npu_sched_env_d_dtype_pFP16_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_fp16_seed_3001/waves/tp_npusch_d_dtype_fp16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PFP16_TEST@3001#group:CG-D_DTYPE | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PFP16_TEST@3001 | npu_sched_env_d_dtype_pFP16_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_fp16_seed_3001/waves/tp_npusch_d_dtype_fp16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PFP16_TEST@3001#scb:SB-NPU-DUT | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PFP16_TEST@3001 | npu_sched_env_d_dtype_pFP16_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_fp16_seed_3001/waves/tp_npusch_d_dtype_fp16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PFP32_TEST@3001 | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PFP32_TEST@3001 | npu_sched_env_d_dtype_pFP32_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_fp32_seed_3001/waves/tp_npusch_d_dtype_fp32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PFP32_TEST@3001#group:CG-D_DTYPE | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PFP32_TEST@3001 | npu_sched_env_d_dtype_pFP32_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_fp32_seed_3001/waves/tp_npusch_d_dtype_fp32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PFP32_TEST@3001#scb:SB-NPU-DUT | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PFP32_TEST@3001 | npu_sched_env_d_dtype_pFP32_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_fp32_seed_3001/waves/tp_npusch_d_dtype_fp32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PINT8_TEST@3001 | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PINT8_TEST@3001 | npu_sched_env_d_dtype_pINT8_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_int8_seed_3001/waves/tp_npusch_d_dtype_int8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PINT8_TEST@3001#group:CG-D_DTYPE | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PINT8_TEST@3001 | npu_sched_env_d_dtype_pINT8_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_int8_seed_3001/waves/tp_npusch_d_dtype_int8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_DTYPE_PINT8_TEST@3001#scb:SB-NPU-DUT | CASE-D_DTYPE | TST-NPU_SCHED_ENV_D_DTYPE_PINT8_TEST@3001 | npu_sched_env_d_dtype_pINT8_test | 3001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_dtype_int8_seed_3001/waves/tp_npusch_d_dtype_int8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PDMA_READ_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PDMA_READ_TEST@8001 | npu_sched_env_d_opcode_pDMA_READ_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/waves/tp_npusch_d_opcode_dma_read.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PDMA_READ_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PDMA_READ_TEST@8001 | npu_sched_env_d_opcode_pDMA_READ_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/waves/tp_npusch_d_opcode_dma_read.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PDMA_READ_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PDMA_READ_TEST@8001 | npu_sched_env_d_opcode_pDMA_READ_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/waves/tp_npusch_d_opcode_dma_read.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PDMA_WRITE_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PDMA_WRITE_TEST@8001 | npu_sched_env_d_opcode_pDMA_WRITE_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_write_seed_8001/waves/tp_npusch_d_opcode_dma_write.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PDMA_WRITE_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PDMA_WRITE_TEST@8001 | npu_sched_env_d_opcode_pDMA_WRITE_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_write_seed_8001/waves/tp_npusch_d_opcode_dma_write.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PDMA_WRITE_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PDMA_WRITE_TEST@8001 | npu_sched_env_d_opcode_pDMA_WRITE_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_write_seed_8001/waves/tp_npusch_d_opcode_dma_write.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PLOAD_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PLOAD_TEST@8001 | npu_sched_env_d_opcode_pLOAD_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_load_seed_8001/waves/tp_npusch_d_opcode_load.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PLOAD_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PLOAD_TEST@8001 | npu_sched_env_d_opcode_pLOAD_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_load_seed_8001/waves/tp_npusch_d_opcode_load.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PLOAD_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PLOAD_TEST@8001 | npu_sched_env_d_opcode_pLOAD_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_load_seed_8001/waves/tp_npusch_d_opcode_load.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_BF16_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_BF16_TEST@8001 | npu_sched_env_d_opcode_pMAC_BF16_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_bf16_seed_8001/waves/tp_npusch_d_opcode_mac_bf16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_BF16_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_BF16_TEST@8001 | npu_sched_env_d_opcode_pMAC_BF16_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_bf16_seed_8001/waves/tp_npusch_d_opcode_mac_bf16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_BF16_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_BF16_TEST@8001 | npu_sched_env_d_opcode_pMAC_BF16_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_bf16_seed_8001/waves/tp_npusch_d_opcode_mac_bf16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_FP16_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_FP16_TEST@8001 | npu_sched_env_d_opcode_pMAC_FP16_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_fp16_seed_8001/waves/tp_npusch_d_opcode_mac_fp16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_FP16_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_FP16_TEST@8001 | npu_sched_env_d_opcode_pMAC_FP16_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_fp16_seed_8001/waves/tp_npusch_d_opcode_mac_fp16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_FP16_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_FP16_TEST@8001 | npu_sched_env_d_opcode_pMAC_FP16_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_fp16_seed_8001/waves/tp_npusch_d_opcode_mac_fp16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_INT8_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_INT8_TEST@8001 | npu_sched_env_d_opcode_pMAC_INT8_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_int8_seed_8001/waves/tp_npusch_d_opcode_mac_int8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_INT8_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_INT8_TEST@8001 | npu_sched_env_d_opcode_pMAC_INT8_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_int8_seed_8001/waves/tp_npusch_d_opcode_mac_int8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PMAC_INT8_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PMAC_INT8_TEST@8001 | npu_sched_env_d_opcode_pMAC_INT8_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_mac_int8_seed_8001/waves/tp_npusch_d_opcode_mac_int8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PSTORE_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PSTORE_TEST@8001 | npu_sched_env_d_opcode_pSTORE_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_store_seed_8001/waves/tp_npusch_d_opcode_store.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PSTORE_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PSTORE_TEST@8001 | npu_sched_env_d_opcode_pSTORE_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_store_seed_8001/waves/tp_npusch_d_opcode_store.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PSTORE_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PSTORE_TEST@8001 | npu_sched_env_d_opcode_pSTORE_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_store_seed_8001/waves/tp_npusch_d_opcode_store.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_ADD_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_ADD_TEST@8001 | npu_sched_env_d_opcode_pVEC_ADD_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_add_seed_8001/waves/tp_npusch_d_opcode_vec_add.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_ADD_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_ADD_TEST@8001 | npu_sched_env_d_opcode_pVEC_ADD_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_add_seed_8001/waves/tp_npusch_d_opcode_vec_add.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_ADD_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_ADD_TEST@8001 | npu_sched_env_d_opcode_pVEC_ADD_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_add_seed_8001/waves/tp_npusch_d_opcode_vec_add.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_MUL_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_MUL_TEST@8001 | npu_sched_env_d_opcode_pVEC_MUL_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_mul_seed_8001/waves/tp_npusch_d_opcode_vec_mul.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_MUL_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_MUL_TEST@8001 | npu_sched_env_d_opcode_pVEC_MUL_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_mul_seed_8001/waves/tp_npusch_d_opcode_vec_mul.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_MUL_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_MUL_TEST@8001 | npu_sched_env_d_opcode_pVEC_MUL_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_mul_seed_8001/waves/tp_npusch_d_opcode_vec_mul.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_RELU_TEST@8001 | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_RELU_TEST@8001 | npu_sched_env_d_opcode_pVEC_RELU_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_relu_seed_8001/waves/tp_npusch_d_opcode_vec_relu.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_RELU_TEST@8001#group:CG-D_OPCODE | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_RELU_TEST@8001 | npu_sched_env_d_opcode_pVEC_RELU_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_relu_seed_8001/waves/tp_npusch_d_opcode_vec_relu.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_OPCODE_PVEC_RELU_TEST@8001#scb:SB-NPU-DUT | CASE-D_OPCODE | TST-NPU_SCHED_ENV_D_OPCODE_PVEC_RELU_TEST@8001 | npu_sched_env_d_opcode_pVEC_RELU_test | 8001 | p2 | regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_vec_relu_seed_8001/waves/tp_npusch_d_opcode_vec_relu.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_DMA_TEST@9501 | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_DMA_TEST@9501 | npu_sched_env_d_pipeline_pMAC_DMA_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_mac_dma_seed_9501/waves/tp_npusch_d_pipeline_mac_dma.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_DMA_TEST@9501#group:CG-D_PIPELINE | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_DMA_TEST@9501 | npu_sched_env_d_pipeline_pMAC_DMA_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_mac_dma_seed_9501/waves/tp_npusch_d_pipeline_mac_dma.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_DMA_TEST@9501#scb:SB-NPU-DUT | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_DMA_TEST@9501 | npu_sched_env_d_pipeline_pMAC_DMA_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_mac_dma_seed_9501/waves/tp_npusch_d_pipeline_mac_dma.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_MAC_TEST@9501 | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_MAC_TEST@9501 | npu_sched_env_d_pipeline_pMAC_MAC_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_mac_mac_seed_9501/waves/tp_npusch_d_pipeline_mac_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_MAC_TEST@9501#group:CG-D_PIPELINE | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_MAC_TEST@9501 | npu_sched_env_d_pipeline_pMAC_MAC_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_mac_mac_seed_9501/waves/tp_npusch_d_pipeline_mac_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_MAC_TEST@9501#scb:SB-NPU-DUT | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMAC_MAC_TEST@9501 | npu_sched_env_d_pipeline_pMAC_MAC_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_mac_mac_seed_9501/waves/tp_npusch_d_pipeline_mac_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMULTI_OP_TEST@9501 | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMULTI_OP_TEST@9501 | npu_sched_env_d_pipeline_pMULTI_OP_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_multi_op_seed_9501/waves/tp_npusch_d_pipeline_multi_op.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMULTI_OP_TEST@9501#group:CG-D_PIPELINE | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMULTI_OP_TEST@9501 | npu_sched_env_d_pipeline_pMULTI_OP_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_multi_op_seed_9501/waves/tp_npusch_d_pipeline_multi_op.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PMULTI_OP_TEST@9501#scb:SB-NPU-DUT | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PMULTI_OP_TEST@9501 | npu_sched_env_d_pipeline_pMULTI_OP_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_multi_op_seed_9501/waves/tp_npusch_d_pipeline_multi_op.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PNONE_TEST@9501 | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PNONE_TEST@9501 | npu_sched_env_d_pipeline_pNONE_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_none_seed_9501/waves/tp_npusch_d_pipeline_none.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PNONE_TEST@9501#group:CG-D_PIPELINE | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PNONE_TEST@9501 | npu_sched_env_d_pipeline_pNONE_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_none_seed_9501/waves/tp_npusch_d_pipeline_none.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PNONE_TEST@9501#scb:SB-NPU-DUT | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PNONE_TEST@9501 | npu_sched_env_d_pipeline_pNONE_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_none_seed_9501/waves/tp_npusch_d_pipeline_none.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PVEC_MAC_TEST@9501 | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PVEC_MAC_TEST@9501 | npu_sched_env_d_pipeline_pVEC_MAC_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_vec_mac_seed_9501/waves/tp_npusch_d_pipeline_vec_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PVEC_MAC_TEST@9501#group:CG-D_PIPELINE | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PVEC_MAC_TEST@9501 | npu_sched_env_d_pipeline_pVEC_MAC_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_vec_mac_seed_9501/waves/tp_npusch_d_pipeline_vec_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PIPELINE_PVEC_MAC_TEST@9501#scb:SB-NPU-DUT | CASE-D_PIPELINE | TST-NPU_SCHED_ENV_D_PIPELINE_PVEC_MAC_TEST@9501 | npu_sched_env_d_pipeline_pVEC_MAC_test | 9501 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_pipeline_vec_mac_seed_9501/waves/tp_npusch_d_pipeline_vec_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PHIGH_FIRST_TEST@10001 | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PHIGH_FIRST_TEST@10001 | npu_sched_env_d_priority_pHIGH_FIRST_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_high_first_seed_10001/waves/tp_npusch_d_priority_high_first.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PHIGH_FIRST_TEST@10001#group:CG-D_PRIORITY | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PHIGH_FIRST_TEST@10001 | npu_sched_env_d_priority_pHIGH_FIRST_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_high_first_seed_10001/waves/tp_npusch_d_priority_high_first.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PHIGH_FIRST_TEST@10001#scb:SB-NPU-DUT | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PHIGH_FIRST_TEST@10001 | npu_sched_env_d_priority_pHIGH_FIRST_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_high_first_seed_10001/waves/tp_npusch_d_priority_high_first.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PLOW_FIRST_TEST@10001 | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PLOW_FIRST_TEST@10001 | npu_sched_env_d_priority_pLOW_FIRST_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_low_first_seed_10001/waves/tp_npusch_d_priority_low_first.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PLOW_FIRST_TEST@10001#group:CG-D_PRIORITY | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PLOW_FIRST_TEST@10001 | npu_sched_env_d_priority_pLOW_FIRST_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_low_first_seed_10001/waves/tp_npusch_d_priority_low_first.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PLOW_FIRST_TEST@10001#scb:SB-NPU-DUT | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PLOW_FIRST_TEST@10001 | npu_sched_env_d_priority_pLOW_FIRST_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_low_first_seed_10001/waves/tp_npusch_d_priority_low_first.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PROUND_ROBIN_TEST@10001 | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PROUND_ROBIN_TEST@10001 | npu_sched_env_d_priority_pROUND_ROBIN_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_round_robin_seed_10001/waves/tp_npusch_d_priority_round_robin.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PROUND_ROBIN_TEST@10001#group:CG-D_PRIORITY | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PROUND_ROBIN_TEST@10001 | npu_sched_env_d_priority_pROUND_ROBIN_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_round_robin_seed_10001/waves/tp_npusch_d_priority_round_robin.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PROUND_ROBIN_TEST@10001#scb:SB-NPU-DUT | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PROUND_ROBIN_TEST@10001 | npu_sched_env_d_priority_pROUND_ROBIN_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_round_robin_seed_10001/waves/tp_npusch_d_priority_round_robin.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PSAME_PRIO_TEST@10001 | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PSAME_PRIO_TEST@10001 | npu_sched_env_d_priority_pSAME_PRIO_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_same_prio_seed_10001/waves/tp_npusch_d_priority_same_prio.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PSAME_PRIO_TEST@10001#group:CG-D_PRIORITY | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PSAME_PRIO_TEST@10001 | npu_sched_env_d_priority_pSAME_PRIO_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_same_prio_seed_10001/waves/tp_npusch_d_priority_same_prio.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_PRIORITY_PSAME_PRIO_TEST@10001#scb:SB-NPU-DUT | CASE-D_PRIORITY | TST-NPU_SCHED_ENV_D_PRIORITY_PSAME_PRIO_TEST@10001 | npu_sched_env_d_priority_pSAME_PRIO_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_priority_same_prio_seed_10001/waves/tp_npusch_d_priority_same_prio.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001 | npu_sched_env_d_queue_p0_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_0_seed_6001/waves/tp_npusch_d_queue_0.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001 | npu_sched_env_d_queue_p0_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_0_seed_6001/waves/tp_npusch_d_queue_0.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001 | npu_sched_env_d_queue_p0_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_0_seed_6001/waves/tp_npusch_d_queue_0.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001 | npu_sched_env_d_queue_p0_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_0_seed_6001/waves/tp_npusch_d_queue_0.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P0_TEST@6001 | npu_sched_env_d_queue_p0_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_0_seed_6001/waves/tp_npusch_d_queue_0.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001 | npu_sched_env_d_queue_p15_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_15_seed_6001/waves/tp_npusch_d_queue_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001 | npu_sched_env_d_queue_p15_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_15_seed_6001/waves/tp_npusch_d_queue_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001 | npu_sched_env_d_queue_p15_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_15_seed_6001/waves/tp_npusch_d_queue_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001 | npu_sched_env_d_queue_p15_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_15_seed_6001/waves/tp_npusch_d_queue_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P15_TEST@6001 | npu_sched_env_d_queue_p15_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_15_seed_6001/waves/tp_npusch_d_queue_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001 | npu_sched_env_d_queue_p16_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_16_seed_6001/waves/tp_npusch_d_queue_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001 | npu_sched_env_d_queue_p16_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_16_seed_6001/waves/tp_npusch_d_queue_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001 | npu_sched_env_d_queue_p16_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_16_seed_6001/waves/tp_npusch_d_queue_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001 | npu_sched_env_d_queue_p16_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_16_seed_6001/waves/tp_npusch_d_queue_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P16_TEST@6001 | npu_sched_env_d_queue_p16_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_16_seed_6001/waves/tp_npusch_d_queue_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001 | npu_sched_env_d_queue_p1_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_1_seed_6001/waves/tp_npusch_d_queue_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001 | npu_sched_env_d_queue_p1_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_1_seed_6001/waves/tp_npusch_d_queue_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001 | npu_sched_env_d_queue_p1_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_1_seed_6001/waves/tp_npusch_d_queue_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001 | npu_sched_env_d_queue_p1_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_1_seed_6001/waves/tp_npusch_d_queue_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P1_TEST@6001 | npu_sched_env_d_queue_p1_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_1_seed_6001/waves/tp_npusch_d_queue_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001 | npu_sched_env_d_queue_p24_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_24_seed_6001/waves/tp_npusch_d_queue_24.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001 | npu_sched_env_d_queue_p24_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_24_seed_6001/waves/tp_npusch_d_queue_24.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001 | npu_sched_env_d_queue_p24_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_24_seed_6001/waves/tp_npusch_d_queue_24.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001 | npu_sched_env_d_queue_p24_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_24_seed_6001/waves/tp_npusch_d_queue_24.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P24_TEST@6001 | npu_sched_env_d_queue_p24_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_24_seed_6001/waves/tp_npusch_d_queue_24.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001 | npu_sched_env_d_queue_p25_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_25_seed_6001/waves/tp_npusch_d_queue_25.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001 | npu_sched_env_d_queue_p25_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_25_seed_6001/waves/tp_npusch_d_queue_25.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001 | npu_sched_env_d_queue_p25_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_25_seed_6001/waves/tp_npusch_d_queue_25.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001 | npu_sched_env_d_queue_p25_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_25_seed_6001/waves/tp_npusch_d_queue_25.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P25_TEST@6001 | npu_sched_env_d_queue_p25_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_25_seed_6001/waves/tp_npusch_d_queue_25.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001 | npu_sched_env_d_queue_p31_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_31_seed_6001/waves/tp_npusch_d_queue_31.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001 | npu_sched_env_d_queue_p31_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_31_seed_6001/waves/tp_npusch_d_queue_31.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001 | npu_sched_env_d_queue_p31_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_31_seed_6001/waves/tp_npusch_d_queue_31.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001 | npu_sched_env_d_queue_p31_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_31_seed_6001/waves/tp_npusch_d_queue_31.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P31_TEST@6001 | npu_sched_env_d_queue_p31_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_31_seed_6001/waves/tp_npusch_d_queue_31.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001 | npu_sched_env_d_queue_p32_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_32_seed_6001/waves/tp_npusch_d_queue_32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001 | npu_sched_env_d_queue_p32_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_32_seed_6001/waves/tp_npusch_d_queue_32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001 | npu_sched_env_d_queue_p32_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_32_seed_6001/waves/tp_npusch_d_queue_32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001 | npu_sched_env_d_queue_p32_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_32_seed_6001/waves/tp_npusch_d_queue_32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P32_TEST@6001 | npu_sched_env_d_queue_p32_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_32_seed_6001/waves/tp_npusch_d_queue_32.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001 | npu_sched_env_d_queue_p7_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_7_seed_6001/waves/tp_npusch_d_queue_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001 | npu_sched_env_d_queue_p7_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_7_seed_6001/waves/tp_npusch_d_queue_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001 | npu_sched_env_d_queue_p7_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_7_seed_6001/waves/tp_npusch_d_queue_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001 | npu_sched_env_d_queue_p7_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_7_seed_6001/waves/tp_npusch_d_queue_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P7_TEST@6001 | npu_sched_env_d_queue_p7_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_7_seed_6001/waves/tp_npusch_d_queue_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001 | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001 | npu_sched_env_d_queue_p8_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_8_seed_6001/waves/tp_npusch_d_queue_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001#group:CG-D_QUEUE | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001 | npu_sched_env_d_queue_p8_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_8_seed_6001/waves/tp_npusch_d_queue_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001#scb:SB-NPU-DUT | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001 | npu_sched_env_d_queue_p8_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_8_seed_6001/waves/tp_npusch_d_queue_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001#sva:SVA-ISSUED_NEEDS_NO_BLOCKER | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001 | npu_sched_env_d_queue_p8_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_8_seed_6001/waves/tp_npusch_d_queue_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001#sva:SVA-QUEUE_LEVEL_WITHIN_DEPTH | CASE-D_QUEUE | TST-NPU_SCHED_ENV_D_QUEUE_P8_TEST@6001 | npu_sched_env_d_queue_p8_test | 6001 | p1 | regression_run/p1/build_build_npu_sched_dut/test_tp_npusch_d_queue_8_seed_6001/waves/tp_npusch_d_queue_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PDMA_MAC_TEST@10001 | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PDMA_MAC_TEST@10001 | npu_sched_env_d_seq_pDMA_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_dma_mac_seed_10001/waves/tp_npusch_d_seq_dma_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PDMA_MAC_TEST@10001#group:CG-D_SEQ | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PDMA_MAC_TEST@10001 | npu_sched_env_d_seq_pDMA_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_dma_mac_seed_10001/waves/tp_npusch_d_seq_dma_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PDMA_MAC_TEST@10001#scb:SB-NPU-DUT | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PDMA_MAC_TEST@10001 | npu_sched_env_d_seq_pDMA_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_dma_mac_seed_10001/waves/tp_npusch_d_seq_dma_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PLOAD_MAC_TEST@10001 | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PLOAD_MAC_TEST@10001 | npu_sched_env_d_seq_pLOAD_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_load_mac_seed_10001/waves/tp_npusch_d_seq_load_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PLOAD_MAC_TEST@10001#group:CG-D_SEQ | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PLOAD_MAC_TEST@10001 | npu_sched_env_d_seq_pLOAD_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_load_mac_seed_10001/waves/tp_npusch_d_seq_load_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PLOAD_MAC_TEST@10001#scb:SB-NPU-DUT | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PLOAD_MAC_TEST@10001 | npu_sched_env_d_seq_pLOAD_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_load_mac_seed_10001/waves/tp_npusch_d_seq_load_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PMAC_MAC_TEST@10001 | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PMAC_MAC_TEST@10001 | npu_sched_env_d_seq_pMAC_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_mac_mac_seed_10001/waves/tp_npusch_d_seq_mac_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PMAC_MAC_TEST@10001#group:CG-D_SEQ | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PMAC_MAC_TEST@10001 | npu_sched_env_d_seq_pMAC_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_mac_mac_seed_10001/waves/tp_npusch_d_seq_mac_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PMAC_MAC_TEST@10001#scb:SB-NPU-DUT | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PMAC_MAC_TEST@10001 | npu_sched_env_d_seq_pMAC_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_mac_mac_seed_10001/waves/tp_npusch_d_seq_mac_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PMAC_STORE_TEST@10001 | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PMAC_STORE_TEST@10001 | npu_sched_env_d_seq_pMAC_STORE_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_mac_store_seed_10001/waves/tp_npusch_d_seq_mac_store.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PMAC_STORE_TEST@10001#group:CG-D_SEQ | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PMAC_STORE_TEST@10001 | npu_sched_env_d_seq_pMAC_STORE_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_mac_store_seed_10001/waves/tp_npusch_d_seq_mac_store.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PMAC_STORE_TEST@10001#scb:SB-NPU-DUT | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PMAC_STORE_TEST@10001 | npu_sched_env_d_seq_pMAC_STORE_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_mac_store_seed_10001/waves/tp_npusch_d_seq_mac_store.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PSCALAR_MAC_TEST@10001 | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PSCALAR_MAC_TEST@10001 | npu_sched_env_d_seq_pSCALAR_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_scalar_mac_seed_10001/waves/tp_npusch_d_seq_scalar_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PSCALAR_MAC_TEST@10001#group:CG-D_SEQ | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PSCALAR_MAC_TEST@10001 | npu_sched_env_d_seq_pSCALAR_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_scalar_mac_seed_10001/waves/tp_npusch_d_seq_scalar_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PSCALAR_MAC_TEST@10001#scb:SB-NPU-DUT | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PSCALAR_MAC_TEST@10001 | npu_sched_env_d_seq_pSCALAR_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_scalar_mac_seed_10001/waves/tp_npusch_d_seq_scalar_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PVEC_MAC_TEST@10001 | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PVEC_MAC_TEST@10001 | npu_sched_env_d_seq_pVEC_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_vec_mac_seed_10001/waves/tp_npusch_d_seq_vec_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PVEC_MAC_TEST@10001#group:CG-D_SEQ | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PVEC_MAC_TEST@10001 | npu_sched_env_d_seq_pVEC_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_vec_mac_seed_10001/waves/tp_npusch_d_seq_vec_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_SEQ_PVEC_MAC_TEST@10001#scb:SB-NPU-DUT | CASE-D_SEQ | TST-NPU_SCHED_ENV_D_SEQ_PVEC_MAC_TEST@10001 | npu_sched_env_d_seq_pVEC_MAC_test | 10001 | p3 | regression_run/p3/build_build_npu_sched_dut/test_tp_npusch_d_seq_vec_mac_seed_10001/waves/tp_npusch_d_seq_vec_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PDMA_TEST@2001 | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PDMA_TEST@2001 | npu_sched_env_d_type_pDMA_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_dma_seed_2001/waves/tp_npusch_d_type_dma.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PDMA_TEST@2001#group:CG-D_TYPE | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PDMA_TEST@2001 | npu_sched_env_d_type_pDMA_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_dma_seed_2001/waves/tp_npusch_d_type_dma.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PDMA_TEST@2001#scb:SB-NPU-DUT | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PDMA_TEST@2001 | npu_sched_env_d_type_pDMA_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_dma_seed_2001/waves/tp_npusch_d_type_dma.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PMAC_TEST@2001 | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PMAC_TEST@2001 | npu_sched_env_d_type_pMAC_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_mac_seed_2001/waves/tp_npusch_d_type_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PMAC_TEST@2001#group:CG-D_TYPE | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PMAC_TEST@2001 | npu_sched_env_d_type_pMAC_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_mac_seed_2001/waves/tp_npusch_d_type_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PMAC_TEST@2001#scb:SB-NPU-DUT | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PMAC_TEST@2001 | npu_sched_env_d_type_pMAC_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_mac_seed_2001/waves/tp_npusch_d_type_mac.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PSCALAR_TEST@2001 | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PSCALAR_TEST@2001 | npu_sched_env_d_type_pSCALAR_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_scalar_seed_2001/waves/tp_npusch_d_type_scalar.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PSCALAR_TEST@2001#group:CG-D_TYPE | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PSCALAR_TEST@2001 | npu_sched_env_d_type_pSCALAR_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_scalar_seed_2001/waves/tp_npusch_d_type_scalar.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PSCALAR_TEST@2001#scb:SB-NPU-DUT | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PSCALAR_TEST@2001 | npu_sched_env_d_type_pSCALAR_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_scalar_seed_2001/waves/tp_npusch_d_type_scalar.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PVECTOR_TEST@2001 | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PVECTOR_TEST@2001 | npu_sched_env_d_type_pVECTOR_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_vector_seed_2001/waves/tp_npusch_d_type_vector.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PVECTOR_TEST@2001#group:CG-D_TYPE | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PVECTOR_TEST@2001 | npu_sched_env_d_type_pVECTOR_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_vector_seed_2001/waves/tp_npusch_d_type_vector.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_D_TYPE_PVECTOR_TEST@2001#scb:SB-NPU-DUT | CASE-D_TYPE | TST-NPU_SCHED_ENV_D_TYPE_PVECTOR_TEST@2001 | npu_sched_env_d_type_pVECTOR_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_tp_npusch_d_type_vector_seed_2001/waves/tp_npusch_d_type_vector.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_ENV_GEN_TEST | — | TST-NPU_SCHED_ENV_GEN_TEST | npu_sched_env_gen_test | None | p3 | regression_run/p3/build_build_npu_sched_dut/test_npu_sched_gen_stimulus/waves/npu_sched_gen_stimulus.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_IN_LOOPBACK_TEST | — | TST-NPU_SCHED_IN_LOOPBACK_TEST | npu_sched_in_loopback_test | None | loopback | regression_run/loopback/build_build_npu_sched_npu_sched_in_loopback/test_test_npu_sched_in_loopback/waves/test_npu_sched_in_loopback.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_SCHED_OUT_LOOPBACK_TEST | — | TST-NPU_SCHED_OUT_LOOPBACK_TEST | npu_sched_out_loopback_test | None | loopback | regression_run/loopback/build_build_npu_sched_npu_sched_out_loopback/test_test_npu_sched_out_loopback/waves/test_npu_sched_out_loopback.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2001 | — | TST-NPU_TYPE_TEST@2001 | npu_type_test | 2001 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_1_seed_2001/waves/npu_type_test_run_1.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2002 | — | TST-NPU_TYPE_TEST@2002 | npu_type_test | 2002 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_2_seed_2002/waves/npu_type_test_run_2.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2003 | — | TST-NPU_TYPE_TEST@2003 | npu_type_test | 2003 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_3_seed_2003/waves/npu_type_test_run_3.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2004 | — | TST-NPU_TYPE_TEST@2004 | npu_type_test | 2004 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_4_seed_2004/waves/npu_type_test_run_4.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2005 | — | TST-NPU_TYPE_TEST@2005 | npu_type_test | 2005 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_5_seed_2005/waves/npu_type_test_run_5.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2006 | — | TST-NPU_TYPE_TEST@2006 | npu_type_test | 2006 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_6_seed_2006/waves/npu_type_test_run_6.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2007 | — | TST-NPU_TYPE_TEST@2007 | npu_type_test | 2007 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_7_seed_2007/waves/npu_type_test_run_7.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2008 | — | TST-NPU_TYPE_TEST@2008 | npu_type_test | 2008 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_8_seed_2008/waves/npu_type_test_run_8.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2009 | — | TST-NPU_TYPE_TEST@2009 | npu_type_test | 2009 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_9_seed_2009/waves/npu_type_test_run_9.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2010 | — | TST-NPU_TYPE_TEST@2010 | npu_type_test | 2010 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_10_seed_2010/waves/npu_type_test_run_10.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2011 | — | TST-NPU_TYPE_TEST@2011 | npu_type_test | 2011 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_11_seed_2011/waves/npu_type_test_run_11.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2012 | — | TST-NPU_TYPE_TEST@2012 | npu_type_test | 2012 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_12_seed_2012/waves/npu_type_test_run_12.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2013 | — | TST-NPU_TYPE_TEST@2013 | npu_type_test | 2013 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_13_seed_2013/waves/npu_type_test_run_13.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2014 | — | TST-NPU_TYPE_TEST@2014 | npu_type_test | 2014 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_14_seed_2014/waves/npu_type_test_run_14.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2015 | — | TST-NPU_TYPE_TEST@2015 | npu_type_test | 2015 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_15_seed_2015/waves/npu_type_test_run_15.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2016 | — | TST-NPU_TYPE_TEST@2016 | npu_type_test | 2016 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_16_seed_2016/waves/npu_type_test_run_16.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2017 | — | TST-NPU_TYPE_TEST@2017 | npu_type_test | 2017 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_17_seed_2017/waves/npu_type_test_run_17.db | 否 |
| EVD-output_e2e_final4_jiang_20261104_044624-TST-NPU_TYPE_TEST@2018 | — | TST-NPU_TYPE_TEST@2018 | npu_type_test | 2018 | p0 | regression_run/p0/build_build_npu_sched_dut/test_npu_type_test_run_18_seed_2018/waves/npu_type_test_run_18.db | 否 |
