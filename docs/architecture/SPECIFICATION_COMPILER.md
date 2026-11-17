# Specification Compiler：九平面协作契约与实现

**状态：快速架构实现，按用户要求本轮未运行 pytest / EDA / 真实 LLM / 完整 RTL 解析。本文不据此宣称功能已通过验收。**

> **实现更新（2026-11-14）**：已增加一个可运行的 [AXI4-Stream 有限时序闭环](INTERFACE_TIMING_SLICE.md)。它在上述九平面内实现 Temporal IR、原文/端口绑定、原 Specification 工作流桥接和 Monitor/Runtime 接口；Temporal IR 通过原 `specification_contract_v1` 元数据中的 `temporal_interfaces` 与 `interface_binding_reports` 进入主链。测试替身和真实仿真被严格区分；本机没有 RTL 仿真器，因此该项仍为 INCOMPLETE，不扩展为所有接口已完成。

## 1. 不增加第十个 Plane

系统是九个逻辑 Plane：**Interfaces + Agent + Orchestration + Generation + Engine + IR + Knowledge + Experience + Runtime**。

仓库中仍以八个 `src/*_plane` 目录承载后八项；Interfaces 由既有 `src/workbench` 承载。`Specification Intelligence` 与 `Specification Lifecycle` 都是跨平面业务能力，`specification_compiler` 不是一个新的顶层职责平面。

| Plane | 本实现的接口/位置 | 责任边界 |
|---|---|---|
| Interfaces | [cmd_specification.py](../../src/workbench/cli/cmd_specification.py) | `specification compile / lifecycle` 入口，不裁决 |
| Agent | [analysis.py](../../src/agent_plane/specification/analysis.py) | 注入现有 Agent analyzer，提取与发现问题，只产生 `DERIVED` |
| Orchestration | [specification_workflow.py](../../src/orchestration_plane/specification_workflow.py) | 组织生命周期、候选合并与澄清，不批准规格 |
| Generation | [candidates.py](../../src/generation_plane/specification/candidates.py) | 候选 Requirement 生成，不能自我确认设计意图 |
| Engine | [compiler.py](../../src/engine_plane/specification_compiler/compiler.py) | 确定性 Schema、来源、Gap、Conflict、Readiness 校验 |
| IR | [contracts.py](../../src/mental_ir_plane/specification_compiler/contracts.py) | 规格状态、来源、生命周期、Intent 关联、版本与可追溯图 |
| Knowledge | [specification_rules.py](../../src/knowledge_plane/specification_rules.py) | DMA/AXI 等领域必要字段与引用，不替 Agent 推理 |
| Experience | [specification_decisions.py](../../src/experience_plane/specification_decisions.py) | 历史决策仅作 advisory，不自动成为当前规范 |
| Runtime | [specification_extraction.py](../../src/runtime_plane/tools/specification_extraction.py) | RTL 文本/解析器适配，不推断设计意图 |

## 2. 运行产物的工作区

原始产物先进入 `Archive/<run_id>/`，再按项目映射为 `mental_model_agent/`、`rtl_generation/`、`uvm_agent/`、`simulation_agent/` 和覆盖率/调试目录；系统级用 `artifacts.sqlite` 索引运行和文件哈希。它们来自实际运行，不是 LLM 自述完成。

该布局仍属于 Runtime 的持久化职责，不是第十个 Plane，也不是 Cadence 协议/数据库接管。未执行能力写 NOT_RUN 状态。结构、SQLite 指针、legacy 兼容与查询方式见 [ChipStack 风格产物工作区](CHIPSTACK_ARTIFACT_WORKSPACE.md)。

## 3. Specification Lifecycle

九个阶段统一由 IR 中的 `LifecycleStage` 定义。编排器按顺序登记，允许进入澄清再返回检查；事件记录不代表清单中的业务问题已经证明。

```text
01 ingestion
02 extraction
03 reconciliation
04 gap_analysis
05 clarification
06 synthesis
07 ir_compilation
08 validation
09 evolution
```

`EVOLUTION` 当前仅保存本次编排器中的前驱 hash/status。跨 Run 的 DAG 失效传播、历史 Signoff 失效与恢复，仍是 M2 的独立工作，不在这里伪装为已完成。

## 4. 三份核心契约

### 4.1 Specification Contract

`Schema = specification_contract_v1`，主要内容：

- `sources`：来源 ID、类型、定位、可选 SHA-256、产生者；
- `requirements`：字段、值、状态、来源与已有 `VerificationIntent` 的连接；
- `gaps`：未知与待补充事实，保留 OPEN/RESOLVED/ASSUMED；
- `conflicts`：同字段多来源冲突及对应值和来源；
- `lifecycle`：阶段的顺序、状态与重入记录；
- `version`：澄清发生修改时递增。

状态约束：

| 状态 | 含义 |
|---|---|
| CONFIRMED | 正式规范来源，或者明确人工批准 |
| DERIVED | Agent/Generation 推导，尚未确认 |
| ASSUMED | 假设登记，不能当成正式要求 |
| UNKNOWN | 未知，进入缺口处理 |
| CONFLICT | 有冲突，不得宣称完整 |

**Agent/Generation/Experience 类型的来源，未经人工批准不能支撑 CONFIRMED。** 复用已有 `VerificationIntent` 的 CANDIDATE/CONFIRMED 状态，而不是另写一套意图模型。

### 4.2 Intent / IR Contract

- Specification Compiler 归 **IR + Engine 协作链**；
- 输入规范化和版本属于 IR；
- Schema 校验、冲突发现、Gap 归纳和 Readiness 属于 Engine；
- 通过 `requirement.intent_ids` 和 `SpecRequirement.to_verification_intent()` 桥接现有 Intent；
- 可选协议知识字段由 Knowledge 提供，Engine 只消费确定性数据，不 import Agent。

### 4.3 Execution & Evidence Contract

Readiness 使用 `verification_readiness_v1`，三态为：

- `VALIDATED`：规格编译就绪，可进入后续执行编排；
- `CONFLICT`：有来源冲突，必须处理，不允许自动挑选一个值签核；
- `INCOMPLETE`：缺输入、缺确认、未知字段或结构校验不完整。

`execution_allowed = (status == VALIDATED)`。**VALIDATED 不是 RTL 仿真通过，也不是 Verification Signoff 通过。** 后者仍需执行引擎、覆盖率和证据审查。

候选与正式值不同会记录 advisory，但候选不能覆盖正式值。人工澄清须提供 `approved_by + approval_ref + human_approved=true` 才能变成 CONFIRMED；没有完整批准信息时只能保存 ASSUMED。

## 5. CLI 与结构化示例

[DMA 示例](../../examples/specification/dma_basic.yaml) 是人工已确认的结构化语义输入，不是自然语言抽取或仿真结果。

```powershell
vagent specification lifecycle
vagent specification compile examples/specification/dma_basic.yaml --json
```

`CONFLICT → 1`，`INCOMPLETE → 2`，`VALIDATED → 0`。默认没有调用 LLM，以可审计的结构化输入进行编译。

## 6. 完整端到端所必需的接口时序语义（当前未完成）

**不能把给 LLM 阅读 Spec 等同于它可靠地理解了每个接口时序。** 当前 Compiler 没有把自然语言、信号关系或波形自动提升成已证明的接口语义。要达到完整端到端，必须补充以下接口级 `interface_timing_v1` 契约（这是下一阶段要实现的契约，不表示本轮已经实现）：

```yaml
interface_id: axi_stream_ingress
protocol: axi4_stream
version: 1
clocks:
  - {name: aclk, period_ps: 1000, reset: aresetn, reset_active_high: false}
signals:
  - {name: s_axis_tvalid, role: VALID, clock: aclk, width: 1,
     binding_status: CONFIRMED}
  - {name: s_axis_tready, role: READY, clock: aclk, width: 1,
     binding_status: CONFIRMED}
rules:
  - {rule_id: R-HANDSHAKE, kind: HANDSHAKE,
     valid: s_axis_tvalid, ready: s_axis_tready,
     stable_signals: [s_axis_tvalid], clock: aclk, status: CONFIRMED}
unknowns: []
```

这只是结构化字段示意。要真正覆盖每个接口，还需满足：

| 必须回答的问题 | 不能接受的替代物 |
|---|---|
| 接口与端口清单是否完整？ | 只覆盖 AI 挑出来的几个接口 |
| 信号与角色、方向、位宽、层级绑定是否确定？ | 按名字猜测 `valid/ready` |
| 时钟域、边沿、复位极性与恢复条件是否明确？ | 默认一种时钟、默认复位有效电平 |
| 握手、payload 稳定性、顺序、依赖、延迟边界是什么？ | 一句自然语言“接口正常通信” |
| 每条规则如何被编译成可执行 checker/monitor？ | 只输出一个时序解释或 Markdown 报告 |
| 实际周期/采样相位、seed、工具版本、原始波形和 checker 结果能否追溯？ | Agent 宣称“仿真看起来没问题” |
| 不理解、缺失或冲突如何回到澄清与重验？ | 让模型自行补一个最可能的含义 |

Engine 不能只校验文本格式：必须检查信号绑定、时钟引用、规则参数、未知项、冲突以及执行所需证据。Generation 只能生成候选 monitor/checker；Runtime/Engine 必须提供实际运行期 trace 和三态结论。**静态语义 PASS、运行时接口 PASS、Verification Signoff PASS 仍然是三个不同级别。**

因此，本轮 Specification Compiler 是横向契约框架，不是“已保证 AI 正确理解所有接口时序”的完成品。完整端到端还需要接口时序 schema、各协议规则包、真实 Testbench/Checker 运行和相应测试验收，不能靠一次快速代码生成替代。

### 与当前协议元数据真源的关系

当前 `_vplan_uvm_spec()` 与 `find_spec_yaml` 已把 `port.protocol` 保留为端口语义（pulse/config/valid_ready…），用 `interface_group` 单独承载 Agent 边界，driver 也优先按协议字段驱动。这个既有链路是重要基础，后续接口时序契约必须**复用同一份协议元数据**，不能再让 AI 根据端口名另造一套解释。

但仍须区分：

- **协议元数据一致**：后续生成器拿到的字段没有丢；
- **协议语义得到实现**：模板确实完成对应脉冲/握手/稳定性行为；
- **接口时序被证明**：真实 checker/monitor 在输入、配置和波形上证明了规则。

三者不能相互替代。对 LLM 或命名约定的回退推断，时序契约应额外记录 `provenance` 与 `binding_status`，没有正式来源或人工确认的绑定不能作为端到端 Guaranteed Understanding直接进入签核。已有 NPU_SCHED 的回归证据可以证明其中的特定场景，但不能外推成所有接口、任意时序语义均已覆盖。

## 7. 当前实现边界

已完成的是可嵌入的本地业务骨架：IR、确定性编译器、澄清操作、生命周期编排、九平面适配和 CLI。

尚未完成或尚未验证：

1. 本轮没有运行功能测试、集成测试或架构回归；
2. analyzer/generator 需要接入现有 Agent/LLM 工艺，不会自行完成自然语言提取；
3. Runtime 的端口扫描只覆盖单行常见声明，不是完整 SystemVerilog 解析器；复杂设计必须注入既有 parser；
4. 领域字段来自最小 DMA/AXI 注册表，尚不是完整协议规范库；
5. 这里验证来源声明和确认纪律，未替代完整 Evidence 包可信校验；
6. 生命周期保存在结果里，还没有跨 Run 持久化 DAG、自动失效传播或 UI 工作台；
7. 这是一项规格编译能力，不会扩大为 Architecture 5.0，也不会新增独立 Agent 或 Plane。

下一轮应先做现有 Agent 的实际 adapter 接线、针对性契约测试和 DMA 缺失/冲突案例验收，再考虑扩展协议和生命周期界面。
