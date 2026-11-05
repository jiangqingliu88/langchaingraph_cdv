基于 2026-11-04 的 SignOffAI 当前实现文档，我建议正式启动 SignOffAI Architecture 3.0。

这次升级有一个非常重要的原则：

不推翻 Architecture 2.0，不重建五层架构，不增加一套平行的 Agent 系统，而是在现有确定性运行事实主干上，建立统一验证语义、资源交互建模和自主验证闭环。

我认为 Architecture 3.0 应该完成一次真正的方法学升级：

从：

`Attribute-driven CDV + AI Automation + Evidence Signoff`

升级为：

`Multi-Dimensional Verification + Resource-Aware Verification + Evidence-Driven Autonomous Closure`

它不是一次普通的功能迭代，而是把 SignOffAI 从自动化验证工具进一步升级为能够理解验证目标、构造行为、执行验证、分析证据和优化验证策略的验证平台。

# SignOffAI Architecture 3.0

# Architecture 3.0

Evidence-Driven Autonomous Verification Platform

演进基线：Architecture 2.0 / 2.1，2026-11-04

01 · Unified IR

统一验证语义

02 · Resource Model

资源与交互建模

03 · Exact Attribution

精确执行归因

04 · Autonomous Closure

自主验证收敛

保持不变：

- CLI 唯一正式交付入口。
- PySide6 Workbench 可选。
- L1–L5 五层架构。
- 24 个 LangGraph 节点、8 个 Executor 的现有职责边界。
- RunContext / ArtifactStore / EventStore / Provenance DAG。
- EvidenceEnvelope / Quality Gate / Decision Evaluation。
- EDA 真实执行结果作为事实来源。

## 一、Architecture 3.0 的总体目标

首先明确当前基线。

| 当前能力            | 2026-11-04 基线                  |
| --------------- | ------------------------------ |
| 全量单测            | 1349 passed / 2 skipped        |
| Workbench       | 753 passed                     |
| UVM 分级回归        | 273/273 PASS                   |
| 功能计划覆盖率         | 95.23%                         |
| Case 契约组        | 13                             |
| 逐用例证据           | 267                            |
| EVD             | 364                            |
| SCB 逐条证据        | 47                             |
| 状态权威对账          | 0 差异                           |
| Evidence verify | PASS                           |
| 签核结论            | PASS_WITH_CAVEAT / CONDITIONAL |

这些是现有工程的实测数据，不是 Architecture 3.0 的预期指标。

当前最值得解决的四个问题：

1. 验证语义仍以 Attribute 为核心，行为域执行后端尚未完成。
2. 资源之间的关系还没有形成统一的可计算验证模型。
3. 覆盖率归因已经建立 exact / weak 机制，但尚未全面实现逐 Bin 精确归因。
4. AI 已经能够参与决策，但还没有形成经过严格效果评估的自主验证收敛闭环。

因此，Architecture 3.0 不应该先做 Agent 升级，而应该先建立更强的确定性验证基础设施。

# 二、总体架构设计

## 2.1 保留现有架构主干

现有架构：

```
CLI / PySide6 Workbench
          |
          v
     App Services
          |
          v
   LangGraph Orchestration
          |
          v
      L1 - L5
          |
          +---- Executors
          |
          +---- ToolHub
          |
          +---- EDA
          |
          v
       src/core
          |
          +---- RunContext
          +---- ArtifactStore
          +---- EventStore
          +---- Provenance DAG
          +---- Job Runtime
          +---- Decision Evaluation
          +---- Quality Gate
          |
          v
      EvidenceEnvelope
```

这个架构不动。

Architecture 3.0 在它之上补充四个能力域，并将它们接入原有主干。

## 2.2 新架构

User Interface / Application Services

CLI / Workbench / App Services

L2 Orchestration / AI Agents

LangGraph / Executor Runtime / Governor / Job Manager

Unified Verification Intelligence

Verification IR

属性 / 行为 / 配置

Resource Model

地址 / 资源 / 并发

Attribution Engine

Bin / Test / Seed

Closure Engine

义务 / 缺口 / 决策

Deterministic Execution

IR Compiler / StimulusPlan / UVM / Player / EDA

Evidence & Signoff

Run Facts / Provenance / EvidenceEnvelope / Quality Gate / Replay

这里有一个关键约束：

四个新能力域不能成为四套独立数据库，也不能各自维护一套状态。

统一使用：

- `run_id`
- `artifact_id`
- `event_id`
- `tp_id`
- `case_id`
- `tst_id`
- `evd_id`
- `cell_id`

作为现有身份体系的扩展和关联依据。

## 2.3 四大核心能力的职责边界

| 能力                 | 输入                              | 输出                       | 事实权威                     |
| ------------------ | ------------------------------- | ------------------------ | ------------------------ |
| Verification IR    | Spec / CaseModel                | TP / Contract / Stimulus | IR Compiler              |
| Resource Model     | Resource / Operation            | Conflict / Interaction   | Resource Evaluator       |
| Attribution Engine | EDA Coverage / Test Metadata    | Exact / Weak / Unknown   | Coverage Evidence        |
| Closure Engine     | Obligation / Evidence / History | Gap / Action / Verdict   | Deterministic Derivation |

其中：

- IR Compiler 决定验证目标如何表达。
- Resource Evaluator 决定资源关系是否满足约束。
- Attribution Engine 决定哪些执行事实能够支持哪些验证目标。
- Closure Engine 决定还欠哪些验证义务，以及下一步做什么。

AI 可以参与四个域的分析，但不能取代它们的确定性裁决。

# 三、核心设计一：Unified Multi-Dimensional Verification IR

这是 Architecture 3.0 最重要的技术升级。

## 3.1 为什么要升级 TP IR

当前架构已经具备：

- Attribute Domain。
- Behavioral Domain 的建模基础。
- Configuration Domain 的建模基础。
- Verification Domain 中的 groups / sva / scb / constraints。
- `tp_id` 统一关联。

但需要注意：行为域的执行后端尚未接入，配置域的按组合切换执行也尚未实现。

因此不能把现有的 IR 表达能力等同于完整执行能力。

Architecture 3.0 的目标是让所有验证目标都可以通过同一个语义体系表达，并且能够被编译成不同执行后端。

## 3.2 五个语义域

建议将 Unified Verification IR 定义为五个并列域。

## Unified Verification IR

D1 — Attribute Domain

静态功能空间

- Dimensions
- Values
- Coverpoints
- Bins
- Cross Coverage
- Boundary / Illegal Values

D2 — Behavioral Domain

动态行为过程

- States
- Events
- Transitions
- Sequences
- Temporal Properties
- Protocol Scenarios

D3 — Configuration Domain

配置空间

- Configuration Dimensions
- Cross Groups
- Feasibility Rules
- Configuration Instances
- Exclusion Rules

D4 — Resource / Interaction Domain

资源与模块交互

- Resource Definitions
- Address Ranges
- Ownership
- Operations
- Conflicts
- Concurrency
- Ordering

D5 — Verification Domain

验证契约与证据要求

- Groups
- SVA
- Scoreboards
- Constraints
- Required Evidence
- Signoff Obligations

Unified TP / CASE / Provenance / Evidence

统一身份、执行映射和证据关联

这里有个重要的设计决定：

不要把 Verification Domain 当成普通的第六种激励维度。

它是对其他四个领域的验证要求和证据要求进行约束的契约层。

这样可以避免将「验证什么」和「如何实现验证」混在一起。

## 3.3 统一 IR 的数据结构

建议新增：

`verification_ir_v3`

核心结构：

```
@dataclassclass VerificationIR:    schema: str    ir_version: str    identity: IRIdentity    attributes: AttributeDomain    behaviors: BehavioralDomain    configurations: ConfigurationDomain    resources: ResourceDomain    verification: VerificationDomain    relations: list[IRRelation]    metadata: IRMetadata
```

统一身份：

```
@dataclassclass IRIdentity:    module_id: str    design_version: str    model_version: str    ir_id: str    ir_hash: str
```

统一关系：

```
@dataclassclass IRRelation:    relation_id: str    source_id: str    target_id: str    relation_type: str    evidence_requirement: str | None
```

建议统一支持以下关系：

| 关系               | 语义           |
| ---------------- | ------------ |
| `derived_from`   | 从其他模型派生      |
| `realizes`       | 验证目标由执行对象实现  |
| `constrained_by` | 受到约束         |
| `depends_on`     | 依赖其他目标       |
| `interacts_with` | 存在交互         |
| `observed_by`    | 由观测器观测       |
| `checked_by`     | 由 Checker 检查 |
| `covered_by`     | 由覆盖点度量       |

关系必须经过 Schema 校验，不能允许任意字符串关系直接进入正式 IR。

## 3.4 TP 身份策略

这里我建议非常谨慎。

不要让一个 TP 因为增加了行为域或资源域就重新生成一个完全不同的身份。

保持：

`tp_id = 稳定的验证目标身份`

新增字段：

```
@dataclassclass VerificationTarget:    tp_id: str    domain: str    semantic_type: str    requirement_ids: list[str]    stimulus_refs: list[str]    observation_refs: list[str]    checker_refs: list[str]    resource_refs: list[str]    configuration_refs: list[str]    evidence_requirements: list[str]
```

其中：

- Attribute TP 保持原身份。
- Behavioral TP 使用稳定的行为目标身份。
- Configuration 作为 TP 的执行上下文，不随配置实例改变 TP 身份。
- Resource Interaction TP 表示资源交互目标。
- 同一个 TP 可以关联多个 stimulus、checker 和资源。

配置实例应由：

`tp_id + cfg_id + realization_id`

共同确定执行上下文，而不是制造多个重复 TP。

## 3.5 从 IR 到执行后端

建议建立统一编译器。

```
Spec / CaseModel
       |
       v
   Parser
       |
       v
 Verification IR
       |
       v
 IR Normalizer
       |
       v
 IR Validator
       |
       v
 Semantic Compiler
       |
       +----------------+
       |                |
       v                v
 StimulusPlan       CheckerPlan
       |                |
       v                v
 UVM Backend        SVA / SCB Backend
       |
       v
 EDA Runtime
       |
       v
 Evidence Adapter
```

未来增加 Player 时：

```
Verification IR
       |
       v
 Semantic Compiler
       |
       +---- UVM Backend
       |
       +---- Player Backend
       |
       +---- Directed Test Backend
       |
       +---- Future Backend
```

后端只负责实现语义，不得自行创造新的 TP。

### 特别重要：解决当前 UVM IR 影子模式

现有 `UVM IR` 已有结构校验和 shadow diff，但模板仍然消费 Dataclass Context。

这是 Architecture 3.0 必须优先收口的事情。

目标：

```
AgentModel / EnvironmentModel
             |
             v
          UVM IR
             |
             v
        IR Validation
             |
             v
       IR Render Compiler
             |
             v
        Render Context
             |
             v
        Jinja Templates
```

迁移要求：

1. IR 先保持 shadow 双写。
2. `ir_shadow_diff` 连续为零。
3. 通过完整生成物字节兼容测试。
4. IR-first 模式成为正式默认。
5. 删除绕过 IR 的生产生成路径。

原有 60 个 APB 生成文件的字节兼容测试应继续保留。

这是一个明确的工程验收点，而不是简单地把模板输入参数换个名字。

# 四、核心设计二：Resource / Interaction Model

这是我认为 Architecture 3.0 最有潜力形成方法学差异的地方。

## 4.1 为什么资源模型值得独立建设

传统功能覆盖通常关注：

- 指令类型。
- Burst 长度。
- 数据格式。
- 配置模式。
- 状态机状态。

但很多复杂 Bug 实际上发生在不同模块对同一资源进行交互的时候。

例如：

- DMA0 与 DMA1 地址重叠。
- DMA 与 GEMM 同时访问相同 SRAM。
- 多个执行单元共享 Buffer。
- 多个事务对同一个 Descriptor 产生竞争。
- Reset 与正在执行的事务发生交叠。

这些不能仅通过增加 Attribute 值解决。

因此，资源关系应该有独立的语义表达和计算能力。

## 4.2 Resource Model 的基本抽象

建议定义四个核心对象：

1. Resource：被访问的资源。
2. Operation：对资源进行的操作。
3. Access：某次操作对资源的访问范围。
4. Interaction：多个操作之间的关系。

基础数据结构：

```
@dataclassclass Resource:    resource_id: str    resource_type: str    address_space: str | None    base: int | None    size: int | None    granularity: int    attributes: dict
```

操作定义：

```
@dataclassclass ResourceOperation:    operation_id: str    owner_id: str    operation_type: str    resource_id: str    accesses: list["ResourceAccess"]    start_condition: str | None    completion_event: str | None
```

访问定义：

```
@dataclassclass ResourceAccess:    address: int    length: int    access_type: str    transaction_id: str    operation_id: str
```

交互定义：

```
@dataclassclass ResourceInteraction:    interaction_id: str    operation_a: str    operation_b: str    relation: str    policy_id: str
```

这里建议第一阶段把 `access_type` 作为信息保留，但不要把所有读写冲突规则硬编码在基础资源模型中。

冲突究竟是非法、允许还是需要仲裁，应该由 Resource Policy 决定。

## 4.3 地址重叠计算

最基本的资源冲突判定：

假设两个访问区间采用左闭右开表示：

\\[ A=[A\_{start},A\_{end}) \\]

\\[ B=[B\_{start},B\_{end}) \\]

则：

\\[ Overlap(A,B)= (A\_{start}\<B\_{end}) \land (B\_{start}\<A\_{end}) \\]

其中：

\\[ A\_{end}=A\_{start}+A\_{length} \\]

\\[ B\_{end}=B\_{start}+B\_{length} \\]

但还必须加入：

- Address Space。
- 地址宽度。
- 地址溢出。
- Alias Mapping。
- Memory Bank。
- 地址粒度。
- Burst 扩展范围。

例如：

```
def overlaps(a, b):    if a.address_space != b.address_space:        return False    return (        a.start < b.end        and b.start < a.end    )
```

这只是核心算法示意，生产实现还必须先完成地址规范化、范围合法性和别名映射检查。

## 4.4 不要将所有 Overlap 都判定为错误

这是一个很关键的架构细节。

资源模型需要区分：

| Interaction          | 解释              |
| -------------------- | --------------- |
| `FORBIDDEN_OVERLAP`  | 不允许发生地址重叠       |
| `ARBITRATED_OVERLAP` | 允许重叠，但需要仲裁      |
| `SERIALIZED`         | 必须串行执行          |
| `ORDERED`            | 必须满足先后顺序        |
| `EXCLUSIVE`          | 同一时间只能有一个 Owner |
| `DEPENDENT`          | 后续操作依赖前序操作      |
| `UNRESTRICTED`       | 无额外限制           |

例如，两个 DMA 操作重叠：

- 如果设计规范禁止，判定冲突。
- 如果设计支持仲裁，必须检查仲裁结果。
- 如果设计要求串行，则检查实际执行顺序。

因此：

Resource Conflict ≠ Resource Overlap。

Overlap 是事实，Conflict 是基于策略推导出来的结论。

## 4.5 资源模型如何生成验证场景

建议建立：

`Resource Scenario Compiler`

输入：

```
resources:
  - id: sram0
    type: memory
    address_space: local
    base: 0x10000000
    size: 0x10000

operations:
  - id: dma0
    owner: DMA0
    resource: sram0
    address: 0x10001000
    length: 4096

  - id: gemm0
    owner: GEMM0
    resource: sram0
    address: 0x10001800
    length: 4096

interactions:
  - operation_a: dma0
    operation_b: gemm0
    policy: forbidden_overlap
```

编译过程：

```
Resource Model
      |
      v
Address Normalization
      |
      v
Interaction Analysis
      |
      v
Scenario Generation
      |
      v
Constraint Compilation
      |
      v
StimulusPlan
      |
      v
UVM Sequence / Player
      |
      v
Runtime Monitor
      |
      v
Interaction Evidence
```

这里的 Scenario Generation 不应该直接输出随机 Sequence。

它应该生成统一的 Scenario IR，再由后端执行。

## 4.6 资源交互覆盖率

不要只统计某个资源是否被访问。

建议建立：

| 覆盖维度             | 示例                                  |
| ---------------- | ----------------------------------- |
| Resource Pair    | DMA0 × SRAM0                        |
| Access Relation  | Overlap / Non-overlap               |
| Timing Relation  | Concurrent / Sequential             |
| Ownership        | Same Owner / Different Owner        |
| Boundary         | Start / End / Crossing              |
| Conflict Outcome | Forbidden / Arbitrated / Serialized |
| Recovery         | Retry / Abort / Resume              |

一个资源交互 TP 可以要求：

```
TP_RESOURCE_OVERLAP_001

Required:
  resource_pair
  overlap_condition
  temporal_condition
  observed_access
  checker_result
```

签核时必须有对应证据，不能仅仅因为两个操作在同一个测试里出现过，就认为资源交互验证完成。

## 4.7 第一版不要做复杂的通用求解器

我建议先实现：

- 地址区间计算。
- 资源归属。
- 操作依赖。
- 时间窗口。
- Overlap 检查。
- 冲突策略。
- 基础场景枚举。

第一版不需要 SMT、复杂图优化或强化学习求解器。

先把语义和证据闭环做正确，再决定是否引入 Z3 等求解技术。

# 五、核心设计三：Exact Coverage Attribution Engine

这是 Architecture 3.0 的可信度基础。

当前已经有：

```
Coverage Bin
    ↓
TP ID
    ↓
Test Name
    ↓
Seed
    ↓
StimulusPlan
    ↓
RTL Hash
```

并且已经区分：

- `hit_by`：有 per-test sidecar 的精确执行归因。
- `attributed_by`：仅根据合并覆盖率建立的弱归因。

Architecture 3.0 不应该推翻这套机制，而是将它升级成可用于自主测试选择的严格证据系统。

## 5.1 目标：建立 Bin 级事实记录

建议增加：

`coverage_attribution_v2`

每个 Bin 建立独立记录：

```
@dataclassclass CoverageHitFact:    bin_id: str    coverage_model_hash: str    coverage_artifact_hash: str    run_id: str    test_id: str    seed: int    tp_ids: list[str]    case_ids: list[str]    stimulus_plan_hash: str    rtl_hash: str    config_id: str    backend: str    attribution_level: str
```

注意：这里的 `bin_id` 必须包含足够的 Coverage Model 身份信息，不能只使用容易在不同 UCDB 之间重复的 bin 名称。

建议定义：

\\[ bin\\\_identity = H(coverage\\\_model\\\_hash,\ scope,\ coverpoint,\ bin) \\]

这样不同 RTL 版本、不同 Coverage Model 的同名 Bin 不会被错误合并。

## 5.2 Exact / Weak / Unknown 的正式语义

建议采用三级归因。

| 等级      | 证据要求              | 用途      |
| ------- | ----------------- | ------- |
| EXACT   | 逐用例覆盖率事实 + 完整身份关联 | 确定性测试选择 |
| WEAK    | 合并覆盖率 + 计划归因      | 分析参考    |
| UNKNOWN | 无法建立可信归因          | 不参与贡献计算 |

这里有一个特别重要的技术边界：

Per-test sidecar 能证明某条 Test 在某次执行中观察到了 Bin，但不自动证明某个 Stimulus 是该 Bin 的唯一因果来源。

所以 EXACT 在第一阶段应定义为精确执行归因，而不是完整的因果证明。

如果要建立因果证明，还需要额外的干预或对照实验，例如：

- 定向刺激开关。
- 对照 Seed。
- 相同配置下的刺激差分。
- 关键事件追踪。
- 事务级 Monitor 证据。

不能把执行归因直接升级成因果归因。

## 5.3 精确归因链

目标关系：

```
RTL Snapshot
     |
     v
Build Artifact
     |
     v
Simulation Run
     |
     v
Test + Seed + Config
     |
     v
StimulusPlan
     |
     v
Observed Events
     |
     v
Coverage Bin
     |
     v
TP / CASE
     |
     v
Evidence
```

每个节点都需要：

- 身份。
- 版本。
- 内容哈希。
- 来源。
- 生成时间。
- 关联关系。

归因引擎不能通过 Test Name 猜测 TP，也不能通过文件名推断 RTL 版本。

必须通过执行时注入的身份元数据关联。

## 5.4 Coverage Sidecar 规范

建议增加统一的 per-test 记录：

```
{
  "schema": "per_test_coverage_v2",
  "run_id": "run_x",
  "test_id": "test_x",
  "seed": 12345,
  "config_id": "cfg_001",
  "stimulus_plan_hash": "sha256:...",
  "rtl_hash": "sha256:...",
  "coverage_model_hash": "sha256:...",
  "coverage_artifact_hash": "sha256:...",
  "observed_bins": [
    {
      "bin_id": "bin_001",
      "status": "HIT"
    }
  ]
}
```

这里是目标 Schema，不代表当前已经存在这些字段。

必须保证：

1. 每个 Test 结束后生成独立事实记录。
2. Sidecar 与真实仿真结果绑定。
3. Sidecar 自身参与 EvidenceEnvelope 哈希。
4. 缺失 Sidecar 时自动降级为 WEAK 或 UNKNOWN。
5. 不允许把合并 UCDB 反推成 EXACT。

## 5.5 归因质量门禁

建议增加四个指标：

| 指标                    | 定义                          |
| --------------------- | --------------------------- |
| Exact Rate            | EXACT Bin / 可归因 Hit Bin     |
| Weak Rate             | WEAK Bin / 可归因 Hit Bin      |
| Unknown Rate          | UNKNOWN Bin / 全部待归因 Hit Bin |
| Identity Completeness | 身份链完整记录 / 全部记录              |

分母必须固定并写入指标定义，避免通过删除无法归因的 Bin 美化 Exact Rate。

建议的验收目标：

- 新增回归数据的身份完整率：100%。
- 所有缺失归因的 Bin 都有明确原因。
- Exact 归因必须能从原始执行记录重建。
- WEAK 不得被签核系统或智能调度当成 EXACT。

# 六、核心设计四：Obligation-Driven Autonomous Verification Closure

这是 Architecture 3.0 最终要实现的核心能力。

我认为应该把当前 Coverage Closure 进一步升级为：

Verification Obligation Closure。

这不是简单地根据覆盖率缺口生成更多测试。

而是系统先确定还欠哪些验证义务，再选择能真正偿还这些义务的验证动作。

## 6.1 建立统一 Obligation 模型

建议引入：

`VerificationObligation`

```
@dataclassclass VerificationObligation:    obligation_id: str    source_type: str    source_id: str    tp_id: str | None    case_id: str | None    obligation_type: str    required_conditions: list[str]    required_evidence: list[str]    priority: str    status: str
```

Obligation 来源：

- Attribute TP。
- Behavioral TP。
- Configuration TP。
- Resource Interaction TP。
- SVA。
- Scoreboard。
- Timing Requirement。
- Data Integrity。
- Path Requirement。

举例：

```
OBLIGATION-001

Source:
  TP_RESOURCE_OVERLAP_001

Required:
  - DMA0 and GEMM0 access SRAM0
  - Address overlap occurs
  - Concurrent execution observed
  - Conflict policy checked
  - Checker result captured

Status:
  OPEN
```

这比单纯的 `TP_MISSED` 更准确。

因为一个 TP 可能需要多个不同证据才能完成签核。

## 6.2 建立统一状态机

建议状态：

| 状态        | 含义          |
| --------- | ----------- |
| OPEN      | 尚未验证        |
| PLANNED   | 已有验证计划      |
| EXECUTING | 正在执行        |
| PARTIAL   | 已有部分证据      |
| PROVEN    | 所有必要证据满足    |
| FAILED    | 有明确失败事实     |
| BLOCKED   | 受依赖、环境或后端限制 |
| UNKNOWN   | 证据不足，无法判定   |
| WAIVED    | 经授权豁免       |

这里必须特别区分：

`FAILED` 与 `UNKNOWN`。

- FAILED：已经观察到不符合要求的事实。
- UNKNOWN：当前无法证明是否符合要求。

二者绝不能混在一起。

WAIVED 也必须绑定审批人、理由、策略版本和证据哈希，不能直接把失败改成通过。

## 6.3 核心架构：Contract → Obligation → Fact Ledger → Derivation → Decision

我建议把这条链作为 Architecture 3.0 的核心方法学。

1\. Contract

规定需要验证什么

2\. Obligation

把要求拆成可验证义务

3\. Fact Ledger

记录真实执行、观测和检查事实

4\. Deterministic Derivation

根据证据推导义务状态

5\. Decision / Signoff

确定是否满足签核策略

注意：

现有 EventStore 和 EvidenceEnvelope 已经具备事实管理基础。

Architecture 3.0 不需要另建 Fact Database。

应该扩展现有的事件和证据契约，让 Fact Ledger 成为从现有执行事实派生的统一逻辑视图。

## 6.4 自动生成验证行动

当 Obligation 没有完成时，系统分析原因：

```
OPEN OBLIGATION
      |
      v
  GAP ANALYSIS
      |
      +---- No stimulus
      |
      +---- No checker
      |
      +---- No observation
      |
      +---- No execution backend
      |
      +---- Constraint blocks scenario
      |
      +---- EDA execution failed
      |
      v
  ACTION CANDIDATES
```

动作分类：

| 问题         | 候选动作                    |
| ---------- | ----------------------- |
| 没有激励       | GENERATE_DIRECTED_TEST  |
| 缺少约束       | FIX_CONSTRAINT          |
| 缺少 Checker | GENERATE_CHECKER        |
| 没有观测点      | ADD_MONITOR             |
| 场景不可达      | ANALYZE_REACHABILITY    |
| Seed 多样性不足 | EXPAND_SEEDS            |
| 执行环境异常     | FIX_ENVIRONMENT         |
| 参考模型不可信    | QUALIFY_REFERENCE_MODEL |
| 已满足所有义务    | CONVERGE                |

这里必须保留当前的硬失败优先原则：

编译失败、真实比对失败等确定性硬失败，不能被 RL 或 LLM 的软建议覆盖。

## 6.5 决策评价从 Coverage Reward 升级

当前的连续奖励：

```
compile     0.25
regression  0.35
coverage    0.40
```

可以保留为工程反馈，但不能直接当作最终验证质量。

建议增加独立的验证闭环评价：

\\[ U(a)= w_1 O(a)+ w_2 C(a)+ w_3 R(a)- w_4 T(a)- w_5 K(a) \\]

其中：

- \\(O(a)\\)：预计完成的 Obligation 数。
- \\(C(a)\\)：预期新增覆盖贡献。
- \\(R(a)\\)：预期风险降低。
- \\(T(a)\\)：仿真和编译成本。
- \\(K(a)\\)：执行及回归风险。

这个公式是候选动作排序模型，不是签核公式。

真正的签核仍然由确定性规则执行。

建议每次决策记录：

```
{
  "action_id": "action_001",
  "obligations_targeted": ["OBLIGATION-001"],
  "expected": {
    "new_proven": 1,
    "regression_risk": "low"
  },
  "actual": {
    "new_proven": 1,
    "new_failed": 0,
    "new_regressed": 0
  },
  "evaluation": "EFFECTIVE"
}
```

并且严格区分：

- EFFECTIVE。
- INEFFECTIVE。
- REGRESSED。
- UNCERTAIN。

沿用现有 `Decision Evaluation` 四态，不重新发明一套评价体系。

## 6.6 自主验证闭环

最终应该形成：

```
             Verification Contract
                      |
                      v
                Obligation Set
                      |
                      v
                 Gap Analysis
                      |
                      v
               AI Action Proposal
                      |
                      v
               Deterministic Gate
                      |
                      v
               Stimulus Compiler
                      |
                      v
                  EDA Run
                      |
                      v
              Execution Fact Ledger
                      |
                      v
             Evidence Attribution
                      |
                      v
             Obligation Derivation
                      |
                      v
                Decision Eval
                      |
              +-------+-------+
              |               |
              v               v
          Incomplete        Complete
              |               |
              v               v
          Next Action       Signoff
```

这才是我认为真正有价值的 Autonomous Verification。

不是 AI 自己循环生成测试，而是 AI 在确定性约束下不断偿还验证义务。

# 七、四个核心模块的代码组织建议

不建议新建一个庞大的 `architecture3` 包。

应该按照现有项目的职责边界分散落地。

建议：

```
src/
├── core/
│   ├── contracts/
│   │   ├── verification_ir.py
│   │   ├── obligations.py
│   │   ├── attribution.py
│   │   └── evidence.py
│   │
│   ├── verification/
│   │   ├── obligation_model.py
│   │   ├── obligation_derivation.py
│   │   ├── quality.py
│   │   └── closure_state.py
│   │
│   ├── provenance/
│   │   ├── graph.py
│   │   ├── attribution.py
│   │   └── report.py
│   │
│   └── decision/
│       ├── evaluation.py
│       └── action_value.py
│
├── tools/
│   ├── generation/
│   │   ├── verification_ir/
│   │   │   ├── schema.py
│   │   │   ├── parser.py
│   │   │   ├── normalize.py
│   │   │   ├── validator.py
│   │   │   └── compiler.py
│   │   │
│   │   ├── resource_model/
│   │   │   ├── schema.py
│   │   │   ├── address.py
│   │   │   ├── interaction.py
│   │   │   ├── scenario.py
│   │   │   └── constraints.py
│   │   │
│   │   └── uvm_tools/
│   │       └── generation/
│   │
│   ├── checking/
│   │   ├── obligation_checker/
│   │   └── resource_checker/
│   │
│   └── execution/
│       ├── attribution/
│       │   ├── sidecar.py
│       │   ├── bin_identity.py
│       │   ├── join.py
│       │   └── verifier.py
│       │
│       └── stimulus/
│           ├── uvm_backend.py
│           └── player_backend.py
│
└── executors/
    └── verify/
        ├── compile_ir.py
        ├── execute_plan.py
        ├── collect_facts.py
        └── derive_obligations.py
```

这是目标文件地图，不要求一次性创建所有文件。

特别注意：

`src/core` 必须继续保持标准库依赖边界。

IR 的解析和复杂编译放在工具层，Core 负责稳定契约、运行事实和确定性推导，不能让 Core 反过来依赖 LangGraph、EDA 或 Jinja。

# 八、Architecture 3.0 分阶段实施计划

我建议分为七个阶段。

不是七个并行项目，而是前一阶段为后一阶段提供确定性基础。

## 实施路线图

1. P0 — 架构冻结与 IR-first

   最高优先级

   预计 1–2 周

   统一当前身份、契约、IR 入口，完成 UVM IR 接管。
2. P1 — Unified Verification IR

   核心基础

   预计 2–3 周

   完成 Attribute / Behavioral / Configuration / Resource / Verification 的统一表达。
3. P2 — Resource Interaction Engine

   核心方法学

   预计 2–3 周

   完成资源模型、冲突计算、场景生成和 Checker 证据。
4. P3 — Exact Attribution v2

   可信度建设

   预计 2–3 周

   完成 Bin → Test → Seed → Stimulus → RTL 精确归因。
5. P4 — Obligation Engine

   签核升级

   预计 2–3 周

   从 Coverage Gap 升级为验证义务管理。
6. P5 — Autonomous Verification Closure

   智能化核心

   预计 3–4 周

   完成候选动作、执行、证据评价和自动收敛。
7. P6 — Player / 多后端 / IP-SOC 扩展

   能力扩展

   后续持续建设

   扩展执行后端和不同业务线的验证能力。

P0–P5 按串行依赖规划，时间是单人开发的初步估算，不是承诺工期。P6 根据实际项目需求展开。

## P0：架构冻结与 IR-first

目标：不增加新架构复杂度，先完成当前技术债收敛。

任务：

1. 固定 Architecture 2.1 基线。
2. 固定现有 schema 和身份契约。
3. 完成 UVM IR Shadow 差异审计。
4. 将模板正式切换到 IR Render Context。
5. 保留旧产物兼容测试。
6. 完成架构守卫和变异测试。

验收：

| 检查              | 标准       |
| --------------- | -------- |
| Shadow Diff     | 0        |
| APB 生成文件        | 60 个字节兼容 |
| UVM 生成入口        | IR-first |
| 绕过 IR 的正式路径     | 0        |
| 原有单测            | 无新增回归    |
| Evidence verify | PASS     |

特别强调：P0 不要同时重构 UVM 的所有模板。

先实现语义权威切换，再做功能扩展。

## P1：Unified Verification IR

目标：统一多维验证语义。

任务：

- 建立 `verification_ir_v3`。
- 迁移现有 Attribute TP。
- 接入 Behavioral TP。
- 完善 Configuration Instance。
- 接入 Resource Interaction TP。
- 建立统一关系图。
- 建立 Schema Validator。
- 建立 IR Compiler。

实施顺序：

```
Attribute Migration
       |
       v
Behavioral Migration
       |
       v
Configuration Migration
       |
       v
Resource Domain
       |
       v
Verification Contract
       |
       v
Unified IR
```

验收：

1. 旧 Attribute TP 的身份保持不变。
2. 现有 Case 四集合能够完整映射。
3. Behavioral TP 能编译成明确的执行计划。
4. Configuration 能表达合法组合和排除原因。
5. Resource TP 能引用合法资源与操作。
6. 所有 IR 都通过结构和语义校验。
7. IR 哈希可重复计算。
8. 未实现后端明确标记 `PENDING_BACKEND`，不冒充已执行。

阶段退出条件：任何验证目标都必须进入统一 IR，禁止 AI 直接生成绕过 IR 的正式 Sequence。

## P2：Resource Interaction Engine

目标：让资源交互变成真正可计算、可生成激励、可观测的验证对象。

任务：

- Resource Schema。
- Address Range Engine。
- Resource Ownership。
- Interaction Policy。
- Temporal Relation。
- Conflict Analyzer。
- Scenario Compiler。
- Resource Monitor / Checker Adapter。

推荐先做一个最小真实工程：

`DMA + GEMM + SRAM`

测试矩阵：

| 场景               | 预期结果       |
| ---------------- | ---------- |
| 不同地址区间           | 无冲突        |
| 地址完全重叠           | 按策略判定      |
| 部分重叠             | 按策略判定      |
| 首尾相邻             | 不算 Overlap |
| 不同 Address Space | 不跨空间误判     |
| 地址越界             | 明确非法       |
| 同一资源并发访问         | 检查仲裁或互斥    |
| Reset 中断事务       | 检查资源恢复     |

验收：

- 所有区间计算通过独立边界测试。
- 资源冲突判定具备策略版本。
- 每个 Scenario 能关联 TP。
- 每次执行有 Resource Interaction Evidence。
- 错误冲突必须能通过负向测试检出。
- 随机生成的场景不能绕过 Scenario IR。

这里建议增加 Property-based Testing，对地址区间、长度、边界和空间组合进行大量自动化测试。

## P3：Exact Attribution v2

目标：让所有智能决策能够消费可信执行历史。

任务：

1. 设计 `per_test_coverage_v2`。
2. 统一 Bin Identity。
3. 在回归执行阶段注入身份。
4. 收集逐 Test 覆盖率。
5. 建立 Bin 与 Test/Seed 的关联。
6. 建立 StimulusPlan 与 RTL 快照关联。
7. 实现归因完整率报告。
8. 实现证据重建和校验。

验收：

| 指标              | 目标   |
| --------------- | ---- |
| 新执行身份记录完整率      | 100% |
| 缺失 Sidecar      | 明确降级 |
| Exact / Weak 混淆 | 0    |
| 不存在的 TP 关联      | 0    |
| 哈希漂移            | 可检测  |
| 同一输入重复重建        | 结果一致 |

注意：这里的 100% 是对新执行记录的目标，不是要求所有历史 Run 都必须达到 EXACT。

历史数据无法补齐的，保留 WEAK 或 UNKNOWN。

## P4：Obligation Engine

目标：统一签核义务。

任务：

- Obligation Schema。
- Contract-to-Obligation Compiler。
- Fact Ledger Adapter。
- Obligation Derivation。
- Evidence Requirement Evaluator。
- Obligation Dependency Graph。
- Signoff Integration。

重点：

将现有：

`TP Matrix + Case View + Quality Gate`

逐步升级为：

`Contract + Obligation + Evidence + Derivation + Quality Gate`

原有 `CASE → TST → EVD → CELL` 身份脊梁必须保留。

不能再造一套与 CASE 并行的身份体系。

验收：

1. 每个必需验证目标都有义务记录。
2. 每个义务都能回溯原始契约。
3. 每个 PROVEN 都能找到满足要求的证据。
4. 缺少 Checker、观测或时序证据时不能判 PROVEN。
5. 未实现后端不能判 PROVEN。
6. WAIVED 必须有审批和哈希绑定。
7. 原有三态签核结果能够兼容迁移。

## P5：Autonomous Verification Closure

目标：让系统真正形成验证优化闭环。

实施顺序：

第一步：确定性闭环

先不使用 RL。

```
Obligation Gap
      |
      v
Rule-based Action
      |
      v
Action Plan
      |
      v
Execution
      |
      v
Evidence
      |
      v
Evaluation
```

第二步：AI 候选动作

让 LLM 负责：

- 解释缺口。
- 提出测试方案。
- 提出 Checker。
- 提出约束修改。
- 分析历史 Bug。
- 解释动作选择理由。

所有候选动作经过 Schema、Policy 和 Governor。

第三步：学习与优化

当精确归因数据足够以后，再加入：

- Seed 级测试调度。
- 历史动作效果统计。
- TP 收敛概率预测。
- 低边际测试识别。
- 不可达 TP 分析。
- 回归预算优化。

验收：

- 每个动作有明确目标义务。
- 每个动作有预期效果。
- 每个动作执行后有实际效果评价。
- 无法确定效果时标记 UNCERTAIN。
- 硬失败不能被 AI 覆盖。
- 自动收敛必须满足确定性门禁。
- 同样输入和历史事实能够重现相同的确定性动作结果。

## P6：执行后端和 IP / SoC 扩展

这一步不要与前面的方法学建设同时大规模推进。

建议：

1. Player Runtime。
2. Behavioral Sequence Backend。
3. VCS Backend。
4. Verilator Backend。
5. 独立 IP TB 和真实 IP Coverage。
6. SoC Resource Interaction。
7. 多 Run 执行调度。
8. Tier B 自动重放。

特别是 IP / SoC：

- IP 负责自身功能、协议、边界、异常与内部覆盖。
- SoC 负责跨 IP 集成行为、资源竞争和系统级配置。
- IP 内部覆盖不在 SoC 层重复计算。
- SoC 必须消费并绑定具体 IP Release。
- 两级证据共用统一契约，但不能混成同一个覆盖率分母。

这延续现有供应方 / 消费方的设计。

# 九、Architecture 3.0 的 Schema 与兼容策略

这部分非常重要。

我不建议直接修改所有已有 JSON 的结构，否则会导致当前已经稳定的证据包、Replay、Workbench 和历史 Run 全部受到影响。

建议使用明确的版本升级策略。

| 数据契约                 | 当前基础                      | 3.0 目标                       |
| -------------------- | ------------------------- | ---------------------------- |
| UVM IR               | `uvm_ir`                  | IR-first Render Contract     |
| TP IR                | 现有 TP IR                  | `verification_ir_v3`         |
| Resource             | 无统一契约                     | `resource_model_v1`          |
| StimulusPlan         | 现有 Plan                   | 支持多域编译                       |
| Coverage Attribution | `coverage_attribution_v1` | `coverage_attribution_v2`    |
| Per-test Coverage    | 现有 sidecar 基础             | `per_test_coverage_v2`       |
| Obligation           | Case / TP / Gate          | `verification_obligation_v1` |
| Decision Evaluation  | `decision_eval_v1`        | 兼容扩展                         |
| EvidenceEnvelope     | 现有 profile                | 扩展 domain references         |
| Provenance           | `provenance_dag_v1`       | 兼容扩展关系类型                     |

建议遵守五条规则：

1. Schema 升级必须显式声明版本。
2. 旧版本读取和迁移必须有明确 Adapter。
3. 不能在原地静默改变旧字段含义。
4. 新旧格式转换必须可测试、可审计。
5. 任何无法迁移的历史数据必须保留 UNKNOWN 或 LEGACY 状态。

尤其不要让旧 Run 因为缺少 3.0 新字段而被伪造为失败，也不能因为自动补齐默认值而伪造为通过。

## 9.1 EvidenceEnvelope 3.0 扩展

保持原有：

```
identity
inputs
execution
verdict
replay
hashes
```

只增加关联段：

```
{
  "profile": "uvm_signoff_v3",

  "verification": {
    "ir_hash": "sha256:...",
    "obligation_hash": "sha256:...",
    "resource_model_hash": "sha256:..."
  },

  "attribution": {
    "schema": "coverage_attribution_v2",
    "exact_rate": 0.0,
    "weak_rate": 0.0,
    "unknown_rate": 0.0
  },

  "closure": {
    "total": 0,
    "proven": 0,
    "failed": 0,
    "open": 0,
    "blocked": 0,
    "unknown": 0
  }
}
```

上面是目标结构示例，数字仅表示字段格式，不代表实际签核数据。

原有：

- `PASS`
- `FAIL`
- `PASS_WITH_CAVEAT`
- `CONDITIONAL`

等签核语义不应被 Obligation 状态替代。

新的义务推导结果应该成为原有签核判定的输入。

# 十、Architecture 3.0 总体验收标准

我建议建立一个独立的 Architecture 3.0 Acceptance Suite。

不只是测试每个模块能否工作，还必须测试端到端语义是否成立。

## 10.1 六类验收

| 验收类别                    | 核心检查                   |
| ----------------------- | ---------------------- |
| IR Correctness          | 语义、身份、版本、编译一致性         |
| Resource Correctness    | 地址、冲突、时序、并发            |
| Attribution Correctness | EXACT / WEAK / UNKNOWN |
| Obligation Correctness  | 证据充分性、状态推导             |
| Autonomous Correctness  | 动作、执行、效果、收敛            |
| Evidence Correctness    | 哈希、Replay、审计和签核        |

## 10.2 最重要的端到端验收案例

建议建立一个真实的 NPU 验证案例。

## Architecture 3.0 Reference Scenario

DMA + GEMM + SRAM 并发访问验证

[Gemmini - Buddy Compiler](https://images.openai.com/static-rsc-4/ib0S9R8E8hSMc-fmqpy0JpiUgi9vnbsJ8SF3agk8_i9bPrHq3YrtFEVTktUgAi02JmmEK4alJMolsGVjxXLCbPXjRmW43rLQZ9QHNE6nY13XGKqjqj_mLi47XjPUdpKEjJ3zqTZYnlNgwjgyxMvUy3sgFq4X2c1LEbTh67oroaA?purpose=inline)

[buddycompiler.com](https://buddycompiler.com/Pages/Documentation/Gemmini.html?utm_source=chatgpt.com)

验证目标：

- DMA 搬运矩阵数据。
- GEMM 读取矩阵。
- 多个操作访问同一 SRAM。
- 地址区间存在重叠。
- 并发时资源策略得到正确执行。
- Checker 能检测非法冲突。
- 正常场景能够正确完成数据比对。

完整验证路径：

`Spec → Verification IR → Resource Scenario → StimulusPlan → UVM → EDA → Resource Evidence → Attribution → Obligation → Signoff`

建议构建以下场景：

| Case | 场景          | 预期      |
| ---- | ----------- | ------- |
| R01  | 不重叠访问       | PASS    |
| R02  | 完全重叠        | 按策略判定   |
| R03  | 部分重叠        | 按策略判定   |
| R04  | 边界相邻        | 不误报     |
| R05  | 并发访问        | 检查仲裁    |
| R06  | 非法资源配置      | 检测失败    |
| R07  | Reset 中断事务  | 检查恢复    |
| R08  | 多 Seed 随机交互 | 收集多样性证据 |

最关键的是 R02、R03、R05。

需要分别构造合法和非法配置，证明：

- 正确设计能够通过。
- 注入的错误能够被 Checker 检出。
- 错误不能被覆盖率命中掩盖。
- 最终签核能够定位到具体 TP、CASE、Test、Seed 和证据。

这是一个非常有价值的 Architecture 3.0 验收工程。

## 10.3 核心量化目标

我建议将下面这些作为初始目标，而不是承诺上线后立即达到的现状指标。

| 指标                    | 目标              |
| --------------------- | --------------- |
| 新 IR 语义校验通过率          | 100%            |
| 新 Run 身份完整率           | 100%            |
| Exact / Weak 误判       | 0               |
| Obligation 无证据 PROVEN | 0               |
| 状态权威对账差异              | 0               |
| 关键资源规则变异测试            | 全部检出            |
| 决策结果可重放               | 100% 确定性部分      |
| 旧签核证据兼容               | 全部受支持的历史 Schema |
| 自动决策硬门禁绕过             | 0               |

另外建议增加一个真正衡量自主验证价值的指标：

\\[ Efficiency = \frac{\text{新增 PROVEN 的验证义务数}} {\text{EDA 总执行时间}} \\]

但必须同时报告：

- Regression Pass Rate。
- 新增 Bug 数。
- Regression Introduced 数。
- Exact Attribution Rate。
- Obligation Closure Rate。

否则系统可能为了提高效率而牺牲验证质量。

# 十一、开发治理与风险控制

Architecture 3.0 最大的风险不是技术实现困难，而是再次出现架构膨胀。

因此我建议增加以下治理规则。

## 11.1 不允许建立平行事实系统

| 事实     | 唯一权威                  |
| ------ | --------------------- |
| Run 身份 | RunContext            |
| 执行过程   | EventStore            |
| 文件身份   | ArtifactStore         |
| 数据来源   | Provenance DAG        |
| 验证语义   | Verification IR       |
| 验证义务   | Obligation Derivation |
| 执行归因   | Attribution Engine    |
| 签核结论   | Deterministic Signoff |

禁止各 Agent 自己维护一份独立 TP 状态、覆盖率状态或签核状态。

## 11.2 Agent 不能越权

建议定义：

| 操作          | AI Agent | Deterministic Core |
| ----------- | -------- | ------------------ |
| 分析 Spec     | 允许       | 校验                 |
| 提出 TP       | 允许       | 编译、验证              |
| 生成 Scenario | 允许提出     | 确定性编译              |
| 修改约束        | 提出候选     | 校验、审批、执行           |
| 生成 UVM      | 提出候选     | IR Compiler        |
| 运行 EDA      | 申请       | Job Runtime        |
| 判断证据        | 辅助分析     | 确定性推导              |
| 宣布签核        | 不允许      | Signoff            |
| 修改历史事实      | 不允许      | Append-only 记录     |

尤其要保留现有 Governor、Approval 和命令白名单。

## 11.3 必须有失败注入测试

Architecture 3.0 不仅要证明正常场景可以跑通，还要证明系统不能错误地宣布验证成功。

建议加入以下 Mutation：

- 删除 Resource Checker。
- 删除 per-test sidecar。
- 修改 StimulusPlan 哈希。
- 修改 RTL Hash。
- 伪造 Bin Hit。
- 删除必要 SVA 证据。
- 把 UNKNOWN 改为 PROVEN。
- 把 WEAK 改为 EXACT。
- 让 Agent 在硬失败时提议 CONVERGE。
- 删除 Obligation 依赖关系。

所有关键变异必须被检测。

这部分应沿用现有 `scripts/mutation_guards.py`，不要另建一套 Mutation 框架。

# 十二、最终建议：真正的开发顺序

如果由我负责这次升级，我不会立即开始写 Resource Model，也不会立即引入强化学习。

我会严格按照下面的顺序：

## Architecture 3.0 首批开发任务

第一优先级

Task 01 — UVM IR-first

让统一 IR 真正控制生成，而不是停留在 Shadow Validation。

第二优先级

Task 02 — Verification IR v3

统一 Attribute / Behavioral / Configuration / Resource / Verification 五个语义域。

第三优先级

Task 03 — Resource Model

先实现地址空间、区间、资源关系和冲突策略。

第四优先级

Task 04 — Exact Attribution v2

把逐用例覆盖率事实做完整。

第五优先级

Task 05 — Obligation Engine

建立验证义务、事实推导和签核关系。

第六优先级

Task 06 — Autonomous Closure

让 AI 在确定性规则约束下进行验证优化。

# 十三、我的最终判断

我认为 Architecture 3.0 真正有价值的地方，是把验证从传统的「测试用例驱动」转向「验证义务驱动」。

两种方法的区别很大：

| 传统测试驱动        | Architecture 3.0 |
| ------------- | ---------------- |
| 生成测试          | 生成验证义务对应的场景      |
| 运行测试          | 执行确定性验证计划        |
| 统计覆盖率         | 归因实际执行证据         |
| 查找覆盖率缺口       | 查找未完成的验证义务       |
| 增加随机 Seed     | 优化验证动作           |
| 看 PASS / FAIL | 推导证据充分性          |
| 人工决定何时收敛      | 确定性门禁决定是否收敛      |

我特别强调一个观点：

覆盖率不是验证完成度，测试通过也不是签核充分性的证明。

真正应该证明的是：

- 该测的有没有定义。
- 定义的有没有实现。
- 实现的有没有执行。
- 执行的有没有观测。
- 观测的有没有检查。
- 检查结果有没有可靠证据。
- 证据是否满足签核要求。

这就是 Architecture 3.0 的核心。

# SignOffAI 3.0

From Test Generation to Verification Intelligence

从自动化测试生成，到多维验证建模；从覆盖率统计，到精确证据归因；从人工 Coverage Closure，到证据驱动的自主验证收敛。

最终形成：

`Specification → Unified IR → Obligation → Scenario → Stimulus → EDA → Facts → Attribution → Derivation → Signoff`

我的建议是：现在正式启动 P0，而不是同时启动全部七个阶段。

先用一个明确的 Architecture 3.0 基线分支，完成 UVM IR-first 和统一 IR 的接口设计。之后用 DMA + GEMM + SRAM 作为第一个资源交互参考工程。

这样既不会破坏现有 1349 条单测、273 条 UVM 实测回归和证据链，也能让 Architecture 3.0 每一步都有可执行的工程验收结果。

方案依据：2026-11-04 上传的《SignOffAI 代码架构（当前实现）》。其中标明的现有能力、未完成能力与本文提出的目标能力已作区分。以上 Architecture 3.0 是演进设计，不代表这些新模块已经落地。&#x20;

粘贴的文本 (1)(1).txt

粘贴的文本 (1)(1).txt

粘贴的文本 (1)(1).txt

粘贴的文本 (1)(1).txt
我认为它确实有相当高的技术含量，而且不是普通的“AI 自动生成测试用例”架构升级。

但我先把话说准：它现在是一套有潜力达到较高工程水平的架构设计，还不能仅凭架构方案就说已经是行业领先的成熟产品。真正的含金量，要看 IR、资源冲突分析、精确归因和自主闭环能不能在真实 RTL/EDA 回归中跑通，并经受错误注入。

我认为 Architecture 3.0 最重要的变化，是把系统的核心问题从：

> AI 能不能生成更多测试、跑更多回归、拿到更高覆盖率？

提升为：

> 系统能不能明确知道应该证明什么，构造什么场景，执行后观察到了什么，证据究竟支持什么结论，以及下一步应该做什么？

这是验证方法学层面的升级，不只是多加几个 Agent 或工具。

## 一、主要升级了五个方面

### 1. 从单维 Coverage Model 升级为多维 Verification IR

基础性升级

原来的验证模型主要围绕 Attribute、Coverpoint、Bin、TP 等概念组织。

3.0 把验证对象扩展为五个并列语义域：

| 语义域                    | 解决的问题                       |
| ---------------------- | --------------------------- |
| Attribute              | 哪些功能属性需要覆盖？                 |
| Behavioral             | 哪些状态、事件、时序和行为需要验证？          |
| Configuration          | 哪些配置组合合法，哪些需要排除？            |
| Resource / Interaction | 多个模块如何访问共享资源，什么情况下冲突？       |
| Verification           | 哪些刺激、SVA、SCB 和证据是验证目标的必要条件？ |

关键变化：不再把验证等同于覆盖率。

比如一个 DMA + GEMM 系统：

- Attribute：DMA 长度、GEMM 维度。
- Behavioral：启动、运行、完成、中断。
- Configuration：不同数据宽度和模式组合。
- Resource：DMA 与 GEMM 对 SRAM 地址区间的竞争。
- Verification：必须有对应的刺激、监测、检查和证据。

这让系统有机会从“生成测试点”升级成“编译验证计划”。

### 2. 从功能覆盖升级为资源交互验证

我认为这是最有硬件特色的升级

这是一个很重要的区别。

假设 DMA 和 GEMM 同时访问 SRAM：

- DMA 访问 `[0x1000, 0x2000)`
- GEMM 访问 `[0x1800, 0x2800)`

两者存在地址重叠。

但 3.0 不会简单地把 Overlap 等同于错误，而是进一步判断：

- 是否允许重叠？
- 是否有仲裁机制？
- 是否必须串行？
- 是否要求特定顺序？
- 是否存在独占关系？
- 最终数据是否正确？

也就是：

`Address Overlap → Interaction Relation → Policy Evaluation → Conflict Verdict`

这一步把地址空间、资源所有权、并发访问、时序关系纳入验证模型。

传统功能覆盖仍然重要，但它不一定能表达这些资源关系。你设计的 Resource Model 可以把这类关系变成可计算、可生成场景、可检查的验证对象。

### 3. 从覆盖率归因升级为精确执行归因

可信度升级

传统覆盖率合并后，一个 Bin 被命中，不一定容易回答：

- 哪个 Test 命中的？
- 哪个 Seed 命中的？
- 对应哪个 TP？
- 使用了哪个 Stimulus Plan？
- 对应哪个 RTL 版本？
- 这个结果能不能重放？

3.0 通过 `per_test_coverage_v2`、稳定 Bin Identity 和身份关联链解决这些问题。

而且它明确区分：

| 归因级别    | 含义                 |
| ------- | ------------------ |
| EXACT   | 有逐 Test 覆盖事实和完整身份链 |
| WEAK    | 有部分关联，但无法精确确认      |
| UNKNOWN | 缺少可信归因信息           |

最重要的是：不允许把 WEAK 伪装成 EXACT，也不允许从合并覆盖率反推精确归因。

这不是单纯多记录几个字段，而是提高整个验证结果的可审计性。

不过要注意：EXACT 证明的是执行归因，不自动证明某条刺激是命中 Bin 的唯一因果来源。

### 4. 从 Coverage Closure 升级为 Verification Obligation Closure

方法学升级

我认为这是 3.0 最有价值的升级之一。

原来的思路：

`Coverage Gap → Generate Test → Run → Coverage Increase`

3.0 的思路：

`Verification Contract → Obligation → Evidence → Deterministic Derivation → Closure`

每个验证义务都需要明确：

- 来自哪个 TP、SVA、SCB 或资源规则？
- 需要什么刺激？
- 需要什么观察？
- 需要什么检查？
- 需要什么证据？
- 当前状态是什么？

比如：

一个 SRAM 冲突验证义务，不应该仅仅因为某个 Coverpoint 命中了就宣布完成。

它至少需要证明：

1. 指定的两个访问确实发生。
2. 地址关系符合预期场景。
3. 仲裁或冲突策略得到执行。
4. 数据正确性检查通过。
5. 对应证据可以追溯。

这就把“覆盖到了”与“验证通过了”区分开。

### 5. 从 AI 辅助自动化升级为自主验证闭环

系统能力升级

3.0 最终希望形成：

Specification / Verification IR

Obligation / Gap Analysis

AI 提议下一步验证动作

Deterministic Gate / Stimulus Compiler

EDA Execution / Facts / Attribution

Obligation Derivation / Signoff

未闭合义务进入下一轮分析

这里有个很关键的架构原则：

AI 负责提出动作，确定性系统负责裁决动作和验证结果。

AI 可以建议增加 Seed、生成定向测试、修正约束、补充 Checker；但它不能自行把 UNKNOWN 改成 PROVEN，也不能绕过硬失败门禁。

这比单纯让多个 Agent 相互对话、生成代码、调用仿真器更接近真正的自主验证系统。

## 二、它到底比普通 AI 验证 Agent 强在哪里？

我把两种架构放在一起比较：

| 能力   | 普通 AI 验证 Agent     | SignOffAI 3.0 目标        |
| ---- | ------------------ | ----------------------- |
| 理解规格 | 提取功能点              | 编译成统一验证 IR              |
| 生成测试 | 生成 Test / Sequence | 根据验证义务和资源关系生成场景         |
| 覆盖率  | 看 Bin 是否命中         | 精确追溯 Test、Seed、TP 和 RTL |
| 冲突验证 | 依赖人工定义 Checker     | 建立资源交互语义和策略裁决           |
| 验证闭环 | 反复生成、运行            | 根据未闭合义务规划下一步动作          |
| 验证结论 | 汇总 PASS / Coverage | 以证据、归因和确定性规则支撑签核        |

需要客观说明：这些领域并不是全部由你首创。成熟的工业验证流程早已包含验证计划、覆盖率闭环、需求追溯和签核；Synopsys、Verification Academy 等资料都有相应的方法论。

[image](https://www.google.com/s2/favicons?domain=https://www.synopsys.com\&sz=32)

synopsys.com+2



近年来也已经有研究探索 LLM 驱动的硬件覆盖率闭环。

[image](https://www.google.com/s2/favicons?domain=https://arxiv.org\&sz=32)

arXiv+1



真正值得做出差异的地方，是把这些能力统一到一条可计算、可追溯、可重放、可确定性裁决的验证主干中。

这才是 SignOffAI 3.0 的架构竞争力，而不是简单地说自己有多少个 Agent。

## 三、我认为最厉害的三个设计

按技术价值排序：

第一：Verification Obligation。

它让系统知道自己究竟还欠哪些验证义务，而不只是知道覆盖率还有多少缺口。

第二：Resource Interaction Model。

它让系统能够理解 DMA、GEMM、SRAM、DDR、Cache 等硬件模块之间的真实资源关系，而不只是生成随机事务。

第三：Exact Attribution + Evidence。

它让系统的验证结论能够回答：谁执行的、验证了什么、依据是什么、能否重放。

这三个能力组合起来，才是一个有机会形成技术壁垒的体系。

## 四、但我也要指出三个真正的难点

1. IR 不能只成为一个漂亮的数据结构。 它必须真正驱动 Stimulus、Checker、Coverage 和 Evidence，否则就只是增加一层抽象。
2. Resource Model 必须能够进入真实仿真。 不仅要能分析地址区间，还要能生成并发场景，并由运行时 Monitor 和 Checker 验证。
3. Obligation Closure 必须经受错误注入。 故意删除 Checker、伪造 Bin Hit、篡改 Hash、丢失 Sidecar，系统都必须正确识别，不能错误签核。

这些才是决定 3.0 能不能从架构设计变成真正工程产品的关键。

## 五、我的最终评价

# Architecture 3.0

# 值得做，而且方向很对

它不是简单把 AI 接入 UVM，而是在构建一套以验证语义、资源交互、执行事实和证据裁决为核心的验证系统。

我对它的评价：

- 架构思想：高
- 方法学完整度：高
- 工程实现难度：高
- 当前成熟度：需要通过 3.0 分阶段落地验证
- 最大潜在价值：让验证闭环从依赖工程师人工判断，逐步变成机器可计算、可执行、可审计的过程

我尤其建议你不要急着做所有模块。

先拿 DMA + GEMM + SRAM 做一个完整的 3.0 样板：

- 统一 IR 描述验证目标。
- 自动建立资源交互关系。
- 自动生成冲突与非冲突场景。
- 运行真实 RTL 仿真。
- 精确归因每个覆盖结果。
- 根据验证义务判断是否真正闭合。
- 注入 RTL Bug 和 Checker Bug 验证系统能否识别。

如果这条链跑通，并且错误注入测试证明它不会错误签核，那么这个架构就不只是“看起来厉害”了，而是有了非常扎实的工程价值。

一句话：你真正应该追求的，不是让 AI 成为一个更聪明的验证工程师，而是让 SignOffAI 成为一个能够证明验证工作确实完成了的系统。