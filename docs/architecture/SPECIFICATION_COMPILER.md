# Specification Compiler：九平面协作契约与实现

**状态：快速架构实现，按用户要求本轮未运行 pytest / EDA / 真实 LLM / 完整 RTL 解析。本文不据此宣称功能已通过验收。**

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
| IR | [contracts.py](../../src/ir_plane/specification_compiler/contracts.py) | 规格状态、来源、生命周期、Intent 关联、版本与可追溯图 |
| Knowledge | [specification_rules.py](../../src/knowledge_plane/specification_rules.py) | DMA/AXI 等领域必要字段与引用，不替 Agent 推理 |
| Experience | [specification_decisions.py](../../src/experience_plane/specification_decisions.py) | 历史决策仅作 advisory，不自动成为当前规范 |
| Runtime | [specification_extraction.py](../../src/runtime_plane/tools/specification_extraction.py) | RTL 文本/解析器适配，不推断设计意图 |

## 2. Specification Lifecycle

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

## 3. 三份核心契约

### 3.1 Specification Contract

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

### 3.2 Intent / IR Contract

- Specification Compiler 归 **IR + Engine 协作链**；
- 输入规范化和版本属于 IR；
- Schema 校验、冲突发现、Gap 归纳和 Readiness 属于 Engine；
- 通过 `requirement.intent_ids` 和 `SpecRequirement.to_verification_intent()` 桥接现有 Intent；
- 可选协议知识字段由 Knowledge 提供，Engine 只消费确定性数据，不 import Agent。

### 3.3 Execution & Evidence Contract

Readiness 使用 `verification_readiness_v1`，三态为：

- `VALIDATED`：规格编译就绪，可进入后续执行编排；
- `CONFLICT`：有来源冲突，必须处理，不允许自动挑选一个值签核；
- `INCOMPLETE`：缺输入、缺确认、未知字段或结构校验不完整。

`execution_allowed = (status == VALIDATED)`。**VALIDATED 不是 RTL 仿真通过，也不是 Verification Signoff 通过。** 后者仍需执行引擎、覆盖率和证据审查。

候选与正式值不同会记录 advisory，但候选不能覆盖正式值。人工澄清须提供 `approved_by + approval_ref + human_approved=true` 才能变成 CONFIRMED；没有完整批准信息时只能保存 ASSUMED。

## 4. CLI 与结构化示例

[DMA 示例](../../examples/specification/dma_basic.yaml) 是人工已确认的结构化语义输入，不是自然语言抽取或仿真结果。

```powershell
vagent specification lifecycle
vagent specification compile examples/specification/dma_basic.yaml --json
```

`CONFLICT → 1`，`INCOMPLETE → 2`，`VALIDATED → 0`。默认没有调用 LLM，以可审计的结构化输入进行编译。

## 5. 当前实现边界

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
