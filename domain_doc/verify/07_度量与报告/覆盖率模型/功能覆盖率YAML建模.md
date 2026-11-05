---
id: KB-DV-COV-002
title: 功能覆盖率 YAML 建模（schema 与示例）
type: 模板卡
domain: 度量与报告
subdomain: 覆盖率模型
tags: [覆盖率, CDV]
roles: [DV工程师, 架构师]
stages: [计划, 编码, 覆盖率]
summary: >
  把「功能契约 → 覆盖点 → 交叉 → 约束 → 批次 → 种子 → 追溯」写进一个机器可读的 YAML，
  让它同时驱动 SV 生成、回归脚本与签核审计。含指令调度器的完整示例。
applicable: |
  覆盖点已经从功能契约推导出来（见 KB-DV-COV-001），现在要决定**把它记成什么格式** ——
  要让工具读得懂、要能生成 SV、要能回答「这个约束是为了覆盖哪个 bin」。
not_applicable: |
  还没推导出覆盖点 —— 先去 KB-DV-COV-001 把覆盖点想清楚，格式救不了空模型；
  本仓库日常跑的是 case 属性模型（见文末「与本仓库 casemodel 格式的关系」）。
prerequisites: [KB-DV-COV-001 功能覆盖率建模]
references: [原稿 doc/dv/func/fun_cov_cmdsched_example.md（已并入本卡）]
related: [KB-DV-COV-001]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# 功能覆盖率 YAML 建模（schema 与示例）

> **一句话**：把「模块功能契约 → 覆盖点 → 交叉 → 约束 → 批次 → 种子 → 追溯」全部串在
> 一个文件里，做到机器可读、可生成、可校验。

> ⚠️ **先读这条**：本卡是一份**独立的覆盖模型 YAML 设计稿**，示例模块是指令调度器。
> 它**不是本仓库实际在跑的格式** —— 本仓库用的是 case 属性模型
> （L1 对象 / L2 子对象 / L3 维度 / L4 字段 / L5 方法 / L6 检查）。
> 两者的对照见文末。把本卡当作**设计参考**，不要当作使用手册。

## 用途

- 决定覆盖模型**用什么格式落地**（而不是散在若干 Word / Excel 里）
- 让「覆盖点 → SV → 回归脚本 → 追溯矩阵」由同一份文件生成，避免多文档脱节
- 评审时能回答：**这个约束是为哪个 bin 写的？这条需求被哪几个批次覆盖？**

## 不适用

| 你实际想干的事 | 该去哪 |
|---|---|
| 覆盖点还不知道怎么推 | `KB-DV-COV-001`（先有模型，再谈格式） |
| 想知道本仓库现在怎么建模 | `config/casemodel/examples/` + `src/tools/casemodel_tools/readme.md` |
| 覆盖率的收敛与签核标准 | `../../02_流程与签核/_index.md` |

---

## 一、五条设计取舍（本卡最值钱的部分）

### 1. 为什么 coverpoint 和 cross 分开

因为它们的生成语法不同，且交叉覆盖需要单独控制 bin 和排除项。分开后生成脚本更清晰。

### 2. 为什么约束要带 `targets`

这是这份 schema 的核心价值：**每个约束都必须声明它服务于哪个覆盖点的哪个 bin。** 没有 targets 的约束就是“孤儿约束”，应该在 review 时被质疑。

### 3. 为什么批次带 `seed_strategy`

种子策略不是全局统一的，每个批次独立确定。`baseline_length` 是筛选后的基线长度，`exploration_count` 是探索种子数。

### 4. 为什么 traceability 单独成节

需求追溯是签核的硬性要求。单独成节便于工具校验“是否有孤立需求”和“是否有孤立覆盖点”。

### 5. 为什么 tool_config 放在最后

工具配置因项目而异，放在最后便于替换。VCS 和 VSO.ai 的配置可以切换而不影响覆盖模型。

---

---

## 二、Schema 设计原则

| 原则 | 说明 |
|---|---|
| 一个文件描述一个模块 | 模块级建模，便于版本管理 |
| 覆盖点、交叉、约束、种子、批次同源 | 避免多文档脱节 |
| 每个 bin 可追溯到需求 | 支持签核审计 |
| 每个约束可追溯到目标 bin | 避免“写了约束不知道为什么” |
| YAML 可直接生成 SV 和回归脚本 | 减少手写错误 |

---

---

## 三、模板本体：指令调度器完整示例

```yaml
# ============================================================
# 模块功能覆盖率建模文件
# 模块: Instruction Scheduler
# 版本: v1.0
# ============================================================

module:
  name: instruction_scheduler
  display_name: "Instruction Scheduler"
  version: "1.0"
  owner: "verification_lead@example.com"
  designer: "design_lead@example.com"
  last_updated: "2025-01-15"
  requirements_doc: "spec/sched_req.md"
  verification_plan: "plan/sched_vplan.md"

# ============================================================
# 接口信号定义
# ============================================================
interface:
  clock: clk
  reset: rst_n
  reset_polarity: active_low

  inputs:
    - name: dec_valid
      width: 1
      desc: "译码指令有效"
    - name: dec_opcode
      width: 7
      desc: "操作码"
    - name: dec_rs1
      width: 5
      desc: "源寄存器1"
    - name: dec_rs2
      width: 5
      desc: "源寄存器2"
    - name: dec_rd
      width: 5
      desc: "目标寄存器"
    - name: dec_imm
      width: 32
      desc: "立即数"

  outputs:
    - name: issue_valid
      width: 1
      desc: "发射有效"
    - name: issue_port
      width: 2
      desc: "发射端口"
    - name: issue_exec_unit
      width: 3
      desc: "执行单元"
    - name: issue_decision
      width: 2
      desc: "发射决策"

  internal:
    - name: queue_level
      width: 5
      desc: "发射队列水位"
    - name: dep_type
      width: 2
      desc: "依赖类型"

# ============================================================
# 枚举定义
# ============================================================
enums:
  opcode:
    ADD:      7'b0110011
    SUB:      7'b0110011
    AND:      7'b0110011
    OR:       7'b0110011
    MUL:      7'b0110011
    DIV:      7'b0110011
    LW:       7'b0000011
    SW:       7'b0100011
    BEQ:      7'b1100011
    JAL:      7'b1101111
    FPU_ADD:  7'b1010011
    FPU_MUL:  7'b1010011

  exec_unit:
    ALU:    3'b000
    MUL:    3'b001
    LSU:    3'b010
    FPU:    3'b011
    BRANCH: 3'b100

  dep_type:
    NONE: 2'b00
    RAW:  2'b01
    WAW:  2'b10
    WAR:  2'b11

  issue_decision:
    ISSUED:  2'b00
    STALLED: 2'b01
    BLOCKED: 2'b10
    FLUSHED: 2'b11

# ============================================================
# 覆盖点定义
# ============================================================
coverpoints:

  - id: CP_SCHED_QUEUE_001
    name: cp_queue_level
    desc: "发射队列水位"
    requirement: REQ-SCHED-001
    signal: queue_level
    sample_event: "@(posedge clk) iff dec_valid || issue_valid"
    target: 100
    bins:
      - name: empty
        type: normal
        values: [0]
        desc: "空队列"
      - name: low
        type: normal
        ranges: [[1, 3]]
        desc: "低水位"
      - name: mid
        type: normal
        ranges: [[4, 7]]
        desc: "中水位"
      - name: high
        type: normal
        ranges: [[8, 14]]
        desc: "高水位"
      - name: full
        type: normal
        values: [15]
        desc: "满队列"
      - name: illegal_over
        type: illegal
        ranges: [[16, 31]]
        desc: "非法超限"

  - id: CP_SCHED_DEP_002
    name: cp_dep_type
    desc: "依赖类型"
    requirement: REQ-SCHED-002
    signal: dep_type
    sample_event: "@(posedge clk) iff dec_valid"
    target: 100
    bins:
      - name: no_dep
        type: normal
        values: [NONE]
      - name: raw
        type: normal
        values: [RAW]
      - name: waw
        type: normal
        values: [WAW]
      - name: war
        type: normal
        values: [WAR]

  - id: CP_SCHED_PORT_003
    name: cp_issue_port
    desc: "发射端口"
    requirement: REQ-SCHED-003
    signal: issue_port
    sample_event: "@(posedge clk) iff issue_valid"
    target: 100
    bins:
      - name: port0
        type: normal
        values: [0]
      - name: port1
        type: normal
        values: [1]
      - name: port2
        type: normal
        values: [2]
      - name: port3
        type: normal
        values: [3]

  - id: CP_SCHED_UNIT_004
    name: cp_exec_unit
    desc: "执行单元"
    requirement: REQ-SCHED-004
    signal: issue_exec_unit
    sample_event: "@(posedge clk) iff issue_valid"
    target: 100
    bins:
      - name: alu
        type: normal
        values: [ALU]
      - name: mul
        type: normal
        values: [MUL]
      - name: lsu
        type: normal
        values: [LSU]
      - name: fpu
        type: normal
        values: [FPU]
      - name: branch
        type: normal
        values: [BRANCH]

  - id: CP_SCHED_DECISION_005
    name: cp_issue_decision
    desc: "发射决策"
    requirement: REQ-SCHED-005
    signal: issue_decision
    sample_event: "@(posedge clk)"
    target: 100
    bins:
      - name: issued
        type: normal
        values: [ISSUED]
        desc: "成功发射"
      - name: stalled
        type: normal
        values: [STALLED]
        desc: "依赖停顿"
      - name: blocked
        type: normal
        values: [BLOCKED]
        desc: "结构冲突阻塞"
      - name: flushed
        type: normal
        values: [FLUSHED]
        desc: "被冲刷"

# ============================================================
# 交叉覆盖定义
# ============================================================
crosses:

  - id: X_SCHED_DEP_DEC_001
    name: X_dep_decision
    desc: "依赖类型 × 发射决策"
    requirement: [REQ-SCHED-002, REQ-SCHED-005]
    cross: [cp_dep_type, cp_issue_decision]
    target: 100
    bins:
      - name: raw_stalled
        expr: "binsof(cp_dep_type.raw) && binsof(cp_issue_decision.stalled)"
        desc: "RAW 依赖导致停顿"
      - name: raw_issued
        expr: "binsof(cp_dep_type.raw) && binsof(cp_issue_decision.issued)"
        desc: "RAW 依赖但成功发射"
      - name: waw_stalled
        expr: "binsof(cp_dep_type.waw) && binsof(cp_issue_decision.stalled)"
      - name: war_stalled
        expr: "binsof(cp_dep_type.war) && binsof(cp_issue_decision.stalled)"
      - name: no_dep_issued
        expr: "binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.issued)"
    excluded_bins:
      - "binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.stalled)"
      - "binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.blocked)"
      - "binsof(cp_dep_type.no_dep) && binsof(cp_issue_decision.flushed)"

  - id: X_SCHED_LEVEL_DEC_002
    name: X_level_decision
    desc: "队列水位 × 发射决策"
    requirement: [REQ-SCHED-001, REQ-SCHED-005]
    cross: [cp_queue_level, cp_issue_decision]
    target: 100
    bins:
      - name: full_blocked
        expr: "binsof(cp_queue_level.full) && binsof(cp_issue_decision.blocked)"
      - name: empty_issued
        expr: "binsof(cp_queue_level.empty) && binsof(cp_issue_decision.issued)"
      - name: low_issued
        expr: "binsof(cp_queue_level.low) && binsof(cp_issue_decision.issued)"

  - id: X_SCHED_UNIT_PORT_003
    name: X_unit_port
    desc: "执行单元 × 发射端口"
    requirement: [REQ-SCHED-003, REQ-SCHED-004]
    cross: [cp_exec_unit, cp_issue_port]
    target: 100
    # 全交叉，20 个 bin

# ============================================================
# 约束定义
# ============================================================
constraints:

  - id: C_OPCODE_DIST
    class: sched_instr
    name: c_opcode_dist
    desc: "操作码分布，控制执行单元覆盖"
    targets:
      - cp_exec_unit.alu
      - cp_exec_unit.mul
      - cp_exec_unit.lsu
      - cp_exec_unit.fpu
      - cp_exec_unit.branch
    code: |
      constraint c_opcode_dist {
        opcode dist {
          ADD  := 15, SUB := 15, AND := 10, OR := 10,
          MUL  := 10, DIV := 5,
          LW   := 15, SW  := 10,
          BEQ  := 10, JAL := 5,
          FPU_ADD := 5, FPU_MUL := 3
        };
      }

  - id: C_DEP_DIST
    class: sched_instr
    name: c_dep_dist
    desc: "依赖类型分布"
    targets:
      - cp_dep_type.no_dep
      - cp_dep_type.raw
      - cp_dep_type.waw
      - cp_dep_type.war
    code: |
      constraint c_dep_dist {
        dep_type dist {
          NONE := 40, RAW := 30, WAW := 15, WAR := 15
        };
      }

  - id: C_RAW
    class: sched_stream
    name: c_raw
    desc: "产生 RAW 依赖"
    targets:
      - X_dep_decision.raw_stalled
      - X_dep_decision.raw_issued
    code: |
      constraint c_raw {
        foreach (instrs[i]) {
          if (i > 0 && instrs[i].dep_type == RAW) {
            instrs[i].rs1 == instrs[i-1].rd;
          }
        }
      }

  - id: C_WAW
    class: sched_stream
    name: c_waw
    desc: "产生 WAW 依赖"
    targets:
      - X_dep_decision.waw_stalled
    code: |
      constraint c_waw {
        foreach (instrs[i]) {
          if (i > 1 && instrs[i].dep_type == WAW) {
            instrs[i].rd == instrs[i-2].rd;
          }
        }
      }

  - id: C_WAR
    class: sched_stream
    name: c_war
    desc: "产生 WAR 依赖"
    targets:
      - X_dep_decision.war_stalled
    code: |
      constraint c_war {
        foreach (instrs[i]) {
          if (i > 0 && instrs[i].dep_type == WAR) {
            instrs[i].rd == instrs[i-1].rs1;
          }
        }
      }

  - id: C_RAW_CHAIN
    class: raw_chain_seq
    name: c_raw_chain
    desc: "强制连续 RAW 依赖链，触发停顿"
    targets:
      - X_dep_decision.raw_stalled
    code: |
      constraint c_raw_chain {
        num_instr == 10;
        foreach (instrs[i]) {
          if (i > 0) {
            instrs[i].dep_type == RAW;
            instrs[i].rs1 == instrs[i-1].rd;
          }
        }
      }

  - id: C_FULL_QUEUE
    class: full_queue_issue_seq
    name: c_full_queue
    desc: "快速填满队列，制造满时阻塞"
    targets:
      - X_level_decision.full_blocked
      - cp_queue_level.full
    code: |
      constraint c_full_queue {
        num_instr == 20;
        foreach (instrs[i]) {
          if (i < 15) {
            instrs[i].dep_type == NONE;
            instrs[i].opcode inside {ADD, SUB, AND, OR};
          }
          if (i >= 15) {
            instrs[i].dep_type == RAW;
            instrs[i].rs1 == instrs[i-1].rd;
          }
        }
      }

  - id: C_CONTENTION
    class: port_contention_seq
    name: c_contention
    desc: "制造端口竞争"
    targets:
      - cp_issue_decision.blocked
      - X_SCHED_UNIT_PORT_003
    code: |
      constraint c_contention {
        num_instr == 10;
        foreach (instrs[i]) {
          instrs[i].opcode inside {ADD, SUB, AND, OR};
          instrs[i].dep_type == NONE;
        }
      }

  - id: C_FLUSH
    class: flush_seq
    name: c_flush
    desc: "制造冲刷场景"
    targets:
      - cp_issue_decision.flushed
    code: |
      constraint c_flush {
        num_instr == 10;
        instrs[4].opcode inside {BEQ, JAL};
        foreach (instrs[i]) {
          if (i > 4) instrs[i].dep_type == RAW;
        }
      }

  - id: C_FPU
    class: fpu_heavy_seq
    name: c_fpu
    desc: "高比例 FPU 指令，确保 FPU 覆盖"
    targets:
      - cp_exec_unit.fpu
    code: |
      constraint c_fpu {
        num_instr == 10;
        foreach (instrs[i]) {
          instrs[i].opcode dist {
            FPU_ADD := 40, FPU_MUL := 30, ADD := 15, LW := 15
          };
        }
      }

# ============================================================
# 测试批次定义
# ============================================================
batches:

  - id: BATCH_1
    name: sched_basic_test
    desc: "基础发射路径"
    constraints: [C_OPCODE_DIST]
    targets:
      - cp_issue_decision.issued
      - cp_exec_unit.alu
      - cp_issue_port.port0
    seed_strategy:
      type: fixed
      seeds: [1001]
      baseline_length: 1
      exploration_count: 0
    expected_coverage: 30

  - id: BATCH_2
    name: sched_dep_test
    desc: "依赖类型探索"
    constraints: [C_DEP_DIST, C_RAW, C_WAW, C_WAR]
    targets:
      - cp_dep_type
      - X_SCHED_DEP_DEC_001
    seed_strategy:
      type: random
      seed_range: [2001, 2300]
      baseline_length: 23
      exploration_count: 5
    expected_coverage: 60

  - id: BATCH_3
    name: sched_raw_stall_test
    desc: "RAW 停顿定向打击"
    constraints: [C_RAW_CHAIN]
    targets:
      - X_dep_decision.raw_stalled
    seed_strategy:
      type: random
      seed_range: [3001, 3200]
      baseline_length: 10
      exploration_count: 2
    expected_coverage: 75

  - id: BATCH_4
    name: sched_full_queue_test
    desc: "队列满压力"
    constraints: [C_FULL_QUEUE]
    targets:
      - X_level_decision.full_blocked
      - cp_queue_level.full
    seed_strategy:
      type: random
      seed_range: [4001, 4200]
      baseline_length: 15
      exploration_count: 3
    expected_coverage: 90

  - id: BATCH_5
    name: sched_port_contention_test
    desc: "端口竞争"
    constraints: [C_CONTENTION]
    targets:
      - cp_issue_decision.blocked
      - X_SCHED_UNIT_PORT_003
    seed_strategy:
      type: random
      seed_range: [5001, 5200]
      baseline_length: 12
      exploration_count: 2
    expected_coverage: 95

  - id: BATCH_6
    name: sched_flush_test
    desc: "冲刷场景"
    constraints: [C_FLUSH]
    targets:
      - cp_issue_decision.flushed
    seed_strategy:
      type: random
      seed_range: [6001, 6100]
      baseline_length: 8
      exploration_count: 2
    expected_coverage: 100

  - id: BATCH_7
    name: sched_random_mix_test
    desc: "随机混合回归，防过拟合"
    constraints: []
    targets:
      - all
    seed_strategy:
      type: random
      seed_range: [7001, 7500]
      baseline_length: 40
      exploration_count: 8
    expected_coverage: 100

# ============================================================
# 需求追溯矩阵
# ============================================================
traceability:

  - requirement: REQ-SCHED-001
    desc: "支持 0-15 队列深度"
    coverpoints: [CP_SCHED_QUEUE_001]
    crosses: [X_SCHED_LEVEL_DEC_002]
    constraints: [C_FULL_QUEUE]
    batches: [BATCH_1, BATCH_4]
    status: covered

  - requirement: REQ-SCHED-002
    desc: "正确处理 RAW/WAW/WAR"
    coverpoints: [CP_SCHED_DEP_002]
    crosses: [X_SCHED_DEP_DEC_001]
    constraints: [C_DEP_DIST, C_RAW, C_WAW, C_WAR, C_RAW_CHAIN]
    batches: [BATCH_2, BATCH_3]
    status: covered

  - requirement: REQ-SCHED-003
    desc: "支持 4 个发射端口"
    coverpoints: [CP_SCHED_PORT_003]
    crosses: [X_SCHED_UNIT_PORT_003]
    constraints: [C_CONTENTION]
    batches: [BATCH_5]
    status: covered

  - requirement: REQ-SCHED-004
    desc: "支持 5 类执行单元"
    coverpoints: [CP_SCHED_UNIT_004]
    crosses: [X_SCHED_UNIT_PORT_003]
    constraints: [C_OPCODE_DIST, C_FPU]
    batches: [BATCH_1, BATCH_2]
    status: covered

  - requirement: REQ-SCHED-005
    desc: "正确做出发射决策"
    coverpoints: [CP_SCHED_DECISION_005]
    crosses: [X_SCHED_DEP_DEC_001, X_SCHED_LEVEL_DEC_002]
    constraints: [C_RAW_CHAIN, C_FLUSH, C_CONTENTION]
    batches: [BATCH_3, BATCH_5, BATCH_6]
    status: covered

# ============================================================
# 覆盖率签核标准
# ============================================================
signoff:
  functional_coverage: 100
  cross_coverage: 100
  illegal_bins: 0
  ignore_bins_approved: true
  traceability_complete: true
  seed_baseline_established: true

  exemptions:
    - bin: illegal_over
      coverpoint: CP_SCHED_QUEUE_001
      reason: "架构上不可达"
      approver: "verification_lead@example.com"
      date: "2025-01-10"

# ============================================================
# 工具配置
# ============================================================
tool_config:
  simulator: vcs
  coverage_metrics:
    - line
    - cond
    - fsm
    - tgl
    - functional
  merge_command: "urg -dir *.vdb -cm merge -report ./report"
  grading_command: "urg -dir *.vdb -grade -metric group"
  ai_optimization:
    enabled: true
    tool: vso_ai
```

---

---

## 四、YAML → SystemVerilog 生成规则

这套 YAML 可以直接驱动脚本生成 SV 代码。对应关系如下：

| YAML 字段 | SV 生成结果 |
|---|---|
| `coverpoints[].name` | `coverpoint` 的标签名 |
| `coverpoints[].signal` | `coverpoint <signal>` |
| `coverpoints[].bins[].values` | `bins <name> = {<values>}` |
| `coverpoints[].bins[].ranges` | `bins <name> = {[<lo>:<hi>]}` |
| `coverpoints[].bins[].type: illegal` | `illegal_bins <name>` |
| `coverpoints[].bins[].type: ignore` | `ignore_bins <name>` |
| `crosses[].cross` | `cross <cp1>, <cp2>` |
| `crosses[].bins[].expr` | `bins <name> = <expr>` |
| `crosses[].excluded_bins` | `binsof(...) && !binsof(...)` |
| `constraints[].code` | 直接插入 constraint 块 |

---

---

## 五、YAML → 回归脚本

```python
import yaml

with open("sched_coverage.yaml") as f:
    cfg = yaml.safe_load(f)

# 生成回归脚本
with open("regress.sh", "w") as f:
    f.write("#!/bin/bash\n")
    for batch in cfg["batches"]:
        name = batch["name"]
        seeds = batch["seed_strategy"].get("seeds", [])
        seed_range = batch["seed_strategy"].get("seed_range", [])
        baseline = batch["seed_strategy"]["baseline_length"]
        explore = batch["seed_strategy"]["exploration_count"]

        if seeds:
            seed_list = seeds
        else:
            # 从 seed_range 中取 baseline + explore 个种子
            seed_list = list(range(seed_range[0], seed_range[0] + baseline + explore))

        for s in seed_list:
            f.write(f"simv +ntb_random_seed={s} +UVM_TESTNAME={name} \\\n")
            f.write(f"     -cm line+cond+fsm+tgl+functional -cm_dir ./cov_{name}_{s}.vdb\n")

    f.write("urg -dir ./cov_*.vdb -cm merge -report ./report\n")
```

---

---

## 六、多模块的组织方式

如果项目有多个模块，建议按目录组织：

```text
coverage/
├── schema/
│   └── coverage_schema.yaml       # schema 定义
├── modules/
│   ├── instruction_scheduler.yaml  # 调度器
│   ├── fifo.yaml                   # FIFO
│   ├── axi_master.yaml             # AXI 主
│   ├── cache.yaml                  # Cache
│   └── dma.yaml                    # DMA
├── scripts/
│   ├── gen_sv.py                   # YAML → SV
│   ├── gen_regress.py              # YAML → 回归脚本
│   └── check_traceability.py       # 校验追溯完整性
└── reports/
    └── merged/
```

每个模块一个 YAML，统一 schema，统一生成流程。

---

---

## 七、与本仓库 casemodel 格式的关系

**这是两套不同的东西，别混用。**

| | 本卡描述的 schema | 本仓库 casemodel |
|---|---|---|
| 顶层 | `module` / `interface` / `enums` | `tests:` → `object` |
| 结构化方式 | `coverpoints` / `crosses` / `constraints` / `batches` | L1 对象 → L2 子对象 → L3 维度 → L4 字段 → L5 方法 → L6 检查 |
| 覆盖点来源 | 手写 coverpoint + signal | 维度 → covergroup、字段 → coverpoint、取值 → bin |
| 能生成什么 | SV covergroup、回归脚本 | case、SV covergroup（`vagent case-model covergroups`） |
| 现状 | 设计稿 | 已实现，有 CLI 与工作台页 |

**判据**：本卡的价值在**那五条取舍**（尤其是「约束必须声明 `targets`，否则是孤儿约束」），
不在 YAML 字段名 —— 字段名跟着工具走，取舍不跟。

## 八、坑

| 坑 | 说明 |
|---|---|
| 把设计稿当手册用 | 本卡的 YAML 本仓库**不解析**。照抄它会得到一份没人读的文件 |
| 约束不写 `targets` | 立刻退化成孤儿约束 —— 没人知道它为什么存在，也没人敢删 |
| 只写 `coverpoints` 不写 `traceability` | 签核时回答不了「哪条需求没被覆盖」，追溯矩阵才是签核的硬通货 |
| 批次不带 `seed_strategy` | 复现不了。种子策略是「这次覆盖率是怎么来的」的答案 |
| 全交叉 | 见 KB-DV-COV-001：交叉爆炸会让覆盖率数字失去意义 |
