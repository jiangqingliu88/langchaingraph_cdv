根据你目前提供的 SignOffAI Architecture 4.0 文档、11 月 13 日的迁移状态，以及刚才的 Architecture Guard 实现，你现在的系统已经不再是传统的 IC 验证自动化框架，也不只是 Claude Code + Skills。

它正在演进为：

# SignOffAI Architecture 4.0

## Agentic Design & Verification System

面向 IC 设计与验证的自主执行、确定性裁决和证据闭环系统

核心设计原则：

> Agent 负责理解、规划、生成、分析、提出修复；确定性 Engine 负责执行、检查、判定、签核。

本质上是：

概率性智能 + 确定性执行 + 结构化验证语义 + 可追溯证据。

先说明状态：以下是根据你提供的架构现状整理的逻辑架构，不代表我已经直接检查了你的最新仓库代码。

# 一、整体架构：八个核心平面

你的 Architecture 4.0 已经从原来的分层架构，演进成了八个职责平面。

# SignOffAI 4.0

## Interfaces Plane

CLI · Workbench · API · User Interaction

## Agent Plane

理解 · 规划 · 协作 · 分析 · 修复建议

## Orchestration Plane

任务分解 · 调度 · 状态机 · 闭环控制

Generation Plane

RTL / UVM / SVA / CModel 生成

Engine Plane

编译 / 仿真 / 检查 / 裁决

## IR Plane

统一验证语义和机器可执行契约

Intent IR

Execution IR

Evidence IR

Knowledge Plane

协议 / 规范 / IP知识 / 设计知识

Experience Plane

历史经验 / 失败案例 / 修复策略

Runtime Plane

进程管理 · 资源管理 · 权限 · 工作区 · EDA环境

注意：这张图是逻辑职责图，不是严格的 Python import 依赖图。八个平面之间并非简单的上下级关系。

# 二、八个平面分别负责什么？

## 1. Agent Plane：智能决策与专业能力

这是系统的 AI 核心。

它负责解决传统自动化工具无法直接解决的问题：理解模糊需求、分析设计意图、推导验证场景、诊断失败原因。

主要能力：

| Agent 类型       | 职责                  |
| -------------- | ------------------- |
| Intent Agent   | 理解验证需求              |
| Planning Agent | 生成验证计划              |
| RTL Agent      | 分析 RTL              |
| Protocol Agent | 分析 AXI、PCIe、DDR 等协议 |
| UVM Agent      | 生成 UVM 环境和测试        |
| SVA Agent      | 推导断言                |
| Debug Agent    | 分析仿真失败              |
| Coverage Agent | 分析覆盖率缺口             |
| Repair Agent   | 提出修复方案              |

这里有一个重要原则：

Agent 可以提出判断，但不能把自己的判断当作签核事实。

例如：

Agent 发现 DMA 读写地址冲突，提出修复建议。

但是否真的消除了冲突，必须由确定性检查器验证。

## 2. Orchestration Plane：自主任务编排

它解决的是：

多个专业 Agent 和执行模块如何协同完成一个完整验证任务？

它不是简单的 Agent 调用器。

它应该管理：

- Task Decomposition：任务分解。
- Agent Dispatch：Agent 调度。
- Workflow State：工作流状态。
- Dependency Management：任务依赖。
- Retry Policy：失败重试。
- Loop Control：闭环控制。
- Human Approval：人工审批。

例如：

```
验证 DMA
    |
    v
Intent Agent
    |
    v
Planning Agent
    |
    v
UVM Agent ---- SVA Agent
    |              |
    v              v
   Generation
       |
       v
     Engine
       |
       v
    Failure?
       |
   +---+---+
   |       |
  Yes      No
   |       |
 Debug   Evidence
   |       |
 Repair   Audit
   |       |
   +---> Re-run
```

它管理整个任务生命周期，而不是自己编译 RTL 或执行仿真。

## 3. Generation Plane：产物生成

这是 AI 与实际 IC 验证工程连接的重要位置。

主要负责生成：

- RTL
- UVM Agent
- UVM Environment
- UVM Sequence
- SystemVerilog Assertions
- CModel
- Testbench
- Constraints
- Verification Plan

这里可以调用 LLM API。

但有一个重要边界：

Generation 产生的是候选产物，不代表产物正确。

例如：

UVM Agent 生成了一个 AXI Driver。

必须经过编译、接口检查、仿真和相关验证，才能认为它可用。

这就是为什么 Generation 和 Engine 应该分开。

## 4. Engine Plane：确定性执行与裁决

系统的可信核心

这是 SignOffAI 最重要的工程基础。

它负责：

| Engine 子模块         | 职责            |
| ------------------ | ------------- |
| Front Engine       | 输入解析、验证任务前端处理 |
| Verify Engine      | 验证模型、规则和约束检查  |
| Ops Engine         | 编译、仿真、回归等执行   |
| Coverage Engine    | 覆盖率分析         |
| Audit Engine       | 证据检查和签核       |
| Diagnostics Engine | 确定性诊断与结果归类    |

这些也与你之前的主链：

```
front → verify → ops → coverage → audit
```

保持联系。

需要区分两个概念：

- Agent Debug：推测根因、提出修复。
- Engine Diagnostics：根据日志、退出码、规则和检查结果确定故障类别。

例如：

LLM 认为 DMA 的问题是地址冲突。

Engine 必须实际计算地址区间，检查是否发生 overlap。

不能因为 LLM 说修复成功，就认为验证通过。

## 5. IR Plane：统一验证语义

这是 Architecture 4.0 非常关键的一次升级。

IR 不应该只是 YAML 或 JSON 的包装。

它是 Agent、Generation、Engine 和 Evidence 之间的统一语义契约。

我建议把它理解为三个逻辑层次：

| IR           | 表达内容      |
| ------------ | --------- |
| Intent IR    | 人类想验证什么   |
| Execution IR | 机器具体执行什么  |
| Evidence IR  | 执行产生了什么事实 |

结合你之前确定的 Case IR：

```
Case IR
├── groups
├── sva
├── scb
├── constraints
└── waivers
```

它负责描述具体验证用例及其约束。

未来还可以进一步发展：

- Resource IR：资源及地址空间。
- Interaction IR：DMA、GEMM 等操作之间的交互。
- Coverage IR：验证目标与覆盖模型。
- Evidence IR：验证结果及其来源。

注意，这些是建议演进的语义类型，不代表目前都已经实现。

IR 的核心价值，是让不同 Agent 和 Engine 不再依赖彼此的内部实现，而是通过统一语义协作。

## 6. Knowledge Plane：专业知识

这是系统的知识来源。

例如：

- AXI 协议规范。
- PCIe 协议知识。
- DDR 时序知识。
- UVM 方法学。
- DMA 设计规范。
- RTL 编码规范。
- SoC 架构知识。

它回答：

> 这个设计和协议应该遵循什么规则？

它与 Agent 的区别是：

Knowledge 提供知识，Agent 使用知识完成推理。

## 7. Experience Plane：经验积累

Knowledge 和 Experience 不应该混为一谈。

例如：

Knowledge：

AXI burst 不能跨越某些规定的边界。

Experience：

某类 DMA RTL 在特定边界条件下曾经发生过 burst 长度计算错误，采用某种测试序列可以复现。

Experience 可以积累：

- 历史 Bug。
- 仿真失败案例。
- 修复记录。
- 回归经验。
- 覆盖率闭合策略。
- Agent 历史执行表现。

它的最终价值是让系统从每一次验证任务中积累可复用经验。

## 8. Runtime Plane：执行基础设施

它不负责验证业务逻辑，而是保障系统可靠运行。

例如：

- 进程启动和终止。
- EDA 工具调用。
- 工作区隔离。
- 文件和资源管理。
- 超时控制。
- 权限控制。
- 任务恢复。
- 执行环境管理。

例如 VCS、Questa、Verilator 等工具的调用和执行环境，应该通过适当的工具适配器与 Runtime 协同。

# 三、真正的核心：三个平面如何协同？

我认为只看八个平面还不够。

真正决定 Architecture 4.0 水平的是三种责任能否分开。

## 三层责任模型

Intent Layer — 意图层

人类想验证什么？

Agent 理解需求、制定计划、提出验证策略。

Execution Layer — 执行层

机器具体执行什么？

IR 定义执行契约，Generation 产生候选产物，Engine 执行验证。

Evidence Layer — 证据层

如何证明验证真的完成？

Evidence 记录事实，Audit 检查证据，Engine 作出签核判定。

三层之间通过 IR、任务契约和证据关联，而不是直接共享内部状态。

这三个层次实际上是你的 Verification Compilation Methodology 的工程化表达。

它不是简单地把人类需求翻译成代码，而是：

```
Human Intent
     |
     v
Machine-Readable Intent
     |
     v
Execution Contract
     |
     v
EDA Execution
     |
     v
Evidence Collection
     |
     v
Deterministic Signoff
```

# 四、一次真实的 DMA 验证任务如何运行？

我们用你之前讨论过的 DMA 与 GEMM 地址冲突场景举例。

## DMA / GEMM 冲突验证闭环

1. 用户提出需求

   DMA 和 GEMM 两个操作只要地址区间 overlap 就算冲突，不区分读写。
2. Intent Agent

   提取操作类型、地址、长度、冲突规则。
3. Planning Agent

   规划无冲突、完全重叠、部分重叠、边界相邻等测试场景。
4. IR

   形成资源描述、操作描述、冲突约束和验证目标。
5. Generation

   生成 SystemVerilog constraint、UVM Sequence 和必要的 Checker。
6. Engine

   执行随机化、编译、仿真和冲突规则检查。
7. Diagnostics Agent

   分析失败现象，提出约束或测试修复方案。
8. Re-verification

   重新生成或修改候选产物，重新执行完整检查。
9. Evidence + Audit

   保存随机种子、配置、代码版本、日志、检查结果和覆盖率证据。

最终只有 Engine 根据预定规则和完整证据作出通过或失败判定。

这就是一个真正的自主验证闭环。

# 五、工程目录应该如何理解？

当前代码已按 **8 个职责平面 + workbench** 收敛，旧 `layers/`、`core/`、`tools/`、`utils/`、`modes/`、`interfaces/`、`workspace/` 均已并入平面，不再作为顶层目录存在：

```text
src/
├── agent_plane/              # 理解、规划、专家、协作、记忆
│   ├── runtime/              # harness / loop / context / state
│   ├── planner/              # task planner / DAG / replan / acceptance
│   ├── specialists/          # design / verify / coverage / debug
│   ├── collaboration/        # subagent / delegation / contracts
│   └── memory/
│
├── orchestration_plane/      # 任务编排与状态机
│   ├── supervisor/           # graph / routing / state
│   ├── nodes/pure/           # 确定性流程节点
│   ├── gates/                # 人工审批 / 审计门
│   ├── registry.py           # AgentCard 能力表
│   ├── guards.py / markers.py
│   └── l2/                   # 原 l2_orchestration
│
├── generation_plane/         # 候选工件生成（可调 LLM）
│   ├── design/{rtl,cmodel}/
│   ├── verification/         # UVM / SVA / testcase
│   ├── planning/dplan/
│   └── {uvm,cmodel,isa_ir}_tools/
│
├── engine_plane/             # 确定性执行与裁决（不调 LLM）
│   ├── front/ verify/ ops/ coverage/ audit/
│   ├── diagnostics/          # 日志 / 波形 / 失败提取
│   └── __init__.py           # facade（惰性转发）
│
├── ir_plane/                 # 统一验证语义
│   ├── vplan/ contract/ proposal/
│   └── decision/             # 原 l3_decision
│
├── knowledge_plane/          # 协议 / IP / 设计知识
├── experience_plane/         # 历史失败 / 修复 / 覆盖率闭合策略
│
├── runtime_plane/            # 执行基础设施
│   ├── core/                 # 原 core
│   ├── infrastructure/       # 原 l1_infrastructure
│   ├── tools/                # 原 tools
│   ├── utils/
│   └── {task_store,session,job_manager,sandbox,...}.py
│
└── workbench/                # Interfaces Plane：CLI + API + GUI
    ├── cli/                  # 原 interfaces/cli
    ├── api/                  # 原 interfaces/api
    ├── modes/                # 原 modes
    └── ui/                   # PySide6 工作台
```

旧 L1–L5 的分层守卫已删除，职责边界改由 `config/architecture_guard.py` 的平面分区检查。

# 六、Workbench 在哪里？

Workbench 不属于 Agent Plane，也不属于 Engine Plane。

它属于 Interfaces Plane。

它的角色是整个系统的可视化操作入口。

结合你之前提供的 PySide6 Workbench 架构：

## Workbench

Project

项目、SoC、IP 管理

Agent

任务、计划、状态

Verification

Case IR、SVA、SCB

Execution

编译、仿真、回归

Coverage

覆盖率与缺口分析

Evidence

证据、审计、签核

Workbench 通过模块注册、Bridge 和工具接口访问业务能力，不拥有独立验证引擎。

你之前明确过一个重要原则：CLI 是正式入口，Workbench 是可选桌面外壳。

我认为应该继续保留。

# 七、Architecture 4.0 到底先进在哪里？

我不想简单告诉你它很先进。真正值得评价的是架构解决了什么问题。

| 传统验证自动化      | SignOffAI 4.0 目标       |
| ------------ | ---------------------- |
| 固定脚本         | 自主任务规划                 |
| 人工编写 UVM     | Agent 辅助生成             |
| 人工分析日志       | Agent 辅助诊断             |
| 独立工具运行       | 统一 Engine 执行           |
| YAML/JSON 配置 | 结构化验证 IR               |
| 手动维护验证经验     | Knowledge + Experience |
| 人工判断结果       | Evidence 驱动的确定性裁决      |
| 人工串联流程       | 自主闭环编排                 |

但必须区分三个成熟度：

- 架构设计成熟度：已经建立八平面和职责分离的方向。
- 工程实现成熟度：需要用实际代码、测试和依赖检查验证。
- 自主验证成熟度：需要通过真实 RTL、UVM、EDA 回归任务证明。

目录迁移完成，不等于自主验证能力完成。

# 八、我认为现在的架构还缺少什么？

这里是我对 Architecture 4.0 的进一步判断。

有三个关键能力值得重点检查。

1\. Resource & Interaction Model

目前 IR 的重点是验证 Case，但 IC 验证真正复杂的地方往往是资源和操作之间的关系。

例如：

- DMA 与 GEMM 的地址重叠。
- 多个 Master 的访问冲突。
- 多个指令之间的依赖。
- Buffer 生命周期。
- 共享资源竞争。

建议把 Resource IR 和 Interaction IR 作为下一轮 IR 演进重点。

2\. Provenance DAG

需要知道每个最终结果从哪里来：

```
Verification Intent
       |
       v
Verification Plan
       |
       v
Generated UVM
       |
       v
Compile Result
       |
       v
Simulation Result
       |
       v
Coverage Result
       |
       v
Signoff Decision
```

任何一项失败，都应该能反向追溯到具体输入、代码版本、工具版本、执行配置和证据。

3\. Autonomous Recovery

真正的 Agentic System 不应该停留在：

```
发现问题 → 输出建议
```

而应该做到：

```
发现问题
   ↓
分析原因
   ↓
提出修复
   ↓
受控修改
   ↓
重新执行
   ↓
验证修复
   ↓
记录经验
```

同时必须设置重试上限、权限边界和人工审批机制，避免 Agent 无限修改。

# 九、现在这套架构的最终定位

我把它总结成一句话：

# SignOffAI

An Evidence-Driven Autonomous IC Verification System

一个由专业 Agent 驱动、由确定性 Engine 执行和裁决、由统一 IR 连接、由 Evidence 保证可追溯性的自主 IC 设计验证系统。

核心公式

\\[ \text{Agent} + \text{IR} + \text{Engine} + \text{Evidence} \\]

\\[ \Downarrow \\]

## Autonomous Verification Closure

我的建议是：暂时不要设计 Architecture 5.0。

下一阶段应该围绕三个目标：

1. Architecture Guard 2.0：保证架构不会失控。
2. Resource / Interaction IR：让系统真正理解复杂芯片资源交互。
3. DMA Autonomous Verification：完成第一个从需求到签核的真实自主验证闭环。

这三件事比继续增加 Agent 类型、继续拆目录、继续增加抽象层更有价值。

因为最终要证明的不是 SignOffAI 有多少个模块，而是它能不能真正替工程师完成一项复杂的 IC 验证任务。

> 全量单测：**1249 passed**（2026-11-13，14 skipped）。

## 相关文档与边界

- 8 个职责平面是整体架构；Agent Plane、Deterministic Engine、IR & Evidence、Evidence & Signoff Gate 是核心可信协作体系（不是第二套“四平面架构”）。
- 归属与迁移：`docs/architecture/STAGE_OWNERSHIP.md`、`STAGE_MIGRATION_PLAN.md`、`STAGE_DEPENDENCY_MATRIX.md`。
- 预算与债务：`docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md`（Guard 2.0）。
- C Model 是 Candidate Reference Model：编译通过不等于 Golden，需经过 VALIDATED / APPROVED_GOLDEN。

## 已知边界（与 `config/known_limitations.py` 同步）

> 不是 TODO：每条都是当前承诺的边界；实现后改 status 并从文档移除。

- `unreachable_declaration`（open）：不可达声明未实现
- `verified_ref_model`（open）：没有 verified TLM 1.0 参考模型
- `single_backend_template`（open）：只有 Questa 后端模板完整
- `plusargs_source`（open）：测试语义 plusargs 还没有生成源
- `single_machine_regression`（by_design）：单机串行回归
- `no_web_ui`（by_design）：不开发 Web UI
- `coarse_reward`（by_design）：奖励信号是“粗连续”
- `kg_is_query_only`（by_design）：知识图是查询层，不是推理层
- `player_runtime`（open）：player 的 SV 包已实现，但 stimulus_plan/verify 主链尚未接线
- `provenance_sandbox_lifecycle`（open）：产物级 provenance DAG
- `cmd_allowlist_monitor`（by_design）：命令白名单默认 EDA enforce、其他 monitor
- `uvm_ir_migration`（open）：UVM 生成器尚未迁到统一 IR
- `incremental_dependency_heuristic`（by_design）：增量依赖映射由文件级启发式自动生成
- `incremental_compile`（open）：增量编译尚未实现
- `optimize_seed_order`（open）：回归优化的种子级重排未实现
- `soc_evidence_not_v2`（open）：SoC 证据包不是 v2 三态签核
- `ip_cdv_not_measured`（open）：IP 级覆盖率尚未测量（独立 IP TB 待 M2）
- `e203_c_path_boundary`（open）：E203 C 路径的边界
- `optional_auth_api`（by_design）：auth.py 是可选 API 面
- `long_output_path`（by_design）：输出目录过长会撞 Windows MAX_PATH（coverstore 打不开 → vsim-7）

## 十、当前里程碑（2026-11-13）

| 项 | 状态 |
|---|---|
| M0 Architecture Guard 2.1 | ✅ 8 平面全覆盖、unzoned/cycle/lazy-debt、dependency matrix |
| M1 Resource / Interaction IR | ✅ `vagent resource verify` + SoC 主链 preflight；intent → 重叠事实 → 场景 → 三态结论 → 证据包 |
| M2 Evidence v2 | ✅ `evidence audit`（完整性/有效性/可信度）+ `evidence stale`（输入 hash 失效） |
| M3 DMA Autonomous Verification | ◐ 资源冲突四类场景已可确定性验证；自然语言→生成→执行→签核主链待接 |
| M4 Autonomous Recovery | ◐ 受控 staging + 保护路径 + Engine 复验标记已落地；自动修复闭环待接 |

Guard 2.1 的规则：新平面不被静默跳过；新增逆向 import / import 环直接失败；
延迟 import 债务已登记、只允许缩小。
