# SignOffAI Architecture 4.0

## Agentic Design & Verification System

> 目标架构，不是一次性物理搬迁清单。当前分支通过 **facade 包 + 真实文件映射**
> 先固化边界；实现仍留在原位置，逐步迁移。
>
> 关联文档：`ARCHITECTURE_CURRENT.md`（当前代码快照）、`ARCHITECTURE.md`（长篇说明）。

## 0. 四个平面

```text
Agent Plane                理解需求 / 规划 / 生成 / 分析 / 提出修复
      │  IR + Task Contract + Artifact Contract
      ▼
IR & Evidence              设计/验证语义、契约、产物、证据、决策
      │  候选产物 + 证据引用
      ▼
Deterministic Engine       lint / compile / formal / sim / regression / coverage
      │  事实 + 证据
      ▼
Evidence & Signoff Gate    证据关联 / 覆盖率裁决 / 人工审批 / 正式签核
```

不可越过的边界：

> **Agent 可以生成和修改设计，可以提出 PASS/FAIL 建议；只有确定性 Engine
> 和受控 Gate 才能形成正式验证结论。**

## 1. 目标目录（Architecture 4.0）

```text
src/
├── agent/                     # A. Agent Plane（长循环与专业角色）
│   ├── runtime/               # harness / loop / context / state / lifecycle
│   ├── supervisor/            # planner / scheduler / replan / router / termination
│   ├── specialists/           # spec / design / rtl / cmodel / uvm / sva / debug / coverage / review
│   ├── collaboration/         # subagent / delegation / contracts / result_merge
│   ├── memory/                # project / task / decision / working / facts
│   └── prompts/
│
├── generation/                # B. 设计与验证生成（概率性能力）
│   ├── design/                # rtl / cmodel / templates
│   ├── verification/          # uvm / sva / testcase / coverage_model
│   ├── repair/                # rtl / cmodel / verification repair
│   └── common/
│
├── ir/                        # C. 统一中间表示
│   ├── spec/                  # spec_ir / requirement
│   ├── design/                # design_ir / module_ir / resource_ir
│   ├── verification/          # case_ir / sva_ir / scb_ir / constraint_ir / waiver_ir
│   ├── execution/             # task_ir / resource_ir / dependency_ir
│   ├── contracts/             # artifact / task / verification / signoff
│   └── evidence/              # Evidence DAG / provenance / hashes
│
├── engine/                    # D. Deterministic Engine
│   ├── front/                 # rtl/spec parser / project loader
│   ├── design/                # lint / compile / formal / design_check
│   ├── verify/                # case_model / sva / uvm / testcase
│   ├── ops/                   # simulation / regression / formal / runtime
│   ├── coverage/              # functional / code / closure / attribution
│   ├── audit/                 # evidence / provenance / validator / decision / signoff_gate
│   └── executors/             # compile / formal / sim / regression / coverage
│
├── runtime/                   # E. 系统可靠性（不含 LLM 业务）
│   ├── task_store.py          # 任务状态、invocations、recovery
│   ├── job_manager.py         # 后台任务
│   ├── event_bus.py           # 事件流
│   ├── process_manager.py     # 子进程 / 进程树
│   ├── permission_gate.py     # 高风险审批
│   ├── workspace_manager.py   # main/staging/proposal/gate
│   ├── sandbox.py             # ScopedTools / 路径守卫
│   └── recovery.py            # 崩溃恢复 / 一致性检查
│
├── knowledge/                 # F. 知识系统
│   └── ic/                    # axi / dma / pcie / ddr / cache / uvm / systemverilog
│                              # （不用顶层 `skills/`，避免与 Claude Code skills 冲突）
├── experience/                # G. 经验沉淀（failure/repair patterns, weights）
├── interfaces/                # H. CLI / API / tool facades
└── workbench/                 # I. GUI 工作台（不动）

projects/                      # 用户项目
workspace/                     # Agent 工作空间（main/staging/proposals/gate）
artifacts/ evidence/ runs/     # 产物 / 证据 / 运行记录
tests/{unit,integration,e2e,fault_injection,security,architecture}
```

## 2. 真实文件映射（当前分支）

| 现有实现 | 4.0 归属 | 本阶段处理 |
|---|---|---|
| `src/workspace/harness/harness.py` | `src/agent/runtime/harness.py` | 保留实现；`src/agent` facade 已暴露 |
| `src/workspace/harness/{state,session,context}.py` | `src/agent/runtime/` + `src/runtime/` | 保留；session/recovery 后续拆到 runtime |
| `src/workspace/harness/memory/` | `src/agent/memory/` + `src/runtime/task_store.py` | 保留；TaskStore 已在 `src/runtime` facade 暴露 |
| `src/workspace/harness/planner/` | `src/agent/supervisor/` | 保留；DAG/replan 已实现 |
| `src/workspace/harness/subagents/` | `src/agent/collaboration/` | 保留；contract/manager/isolation 已实现 |
| `src/workspace/harness/{jobs,permissions,write_audit}.py` | `src/runtime/` | 保留；`src/runtime` facade 已暴露 |
| `src/workspace/zones.py` / `resources.py` | `src/runtime/workspace_manager.py` / `sandbox.py` | 保留；路径守卫/直接模式已实现 |
| `src/modes/agent_mode.py` | `src/agent/` 入口 | 已实现；`vagent work` 统一入口 |
| `src/agents/`（supervisor + 专家子图） | `src/engine/verify` / `src/engine/ops` | 保留为确定性编排内核 |
| `src/stages/`（8 个 stage executor） | `src/engine/{front,design,verify,ops,coverage,audit}` + `src/generation` | 保留；后续按职责拆分 |
| `src/layers/l1_infrastructure/` | `src/engine/executors/` | 保留（EDA/回归/原子写） |
| `src/layers/l2_orchestration/regression_tools/` | `src/engine/ops/regression/` | 保留 |
| `src/layers/l3_decision/vplan/` | `src/ir/{spec,verification,contracts,evidence}` + `src/engine/verify` | 保留；契约/evidence 语义已存在 |
| `src/layers/l3_decision/contract/` | `src/ir/contracts/` | 保留 |
| `src/workspace/proposal/schema.py` | `src/ir/contracts/task_contract.py` | 保留 |
| `src/layers/l4_memory/` | `src/knowledge/` | 保留 |
| `src/layers/l5_evolution/` | `src/experience/` | 保留 |
| `src/tools/generation/uvm_tools/` | `src/generation/` | 保留；UVM/SVA 模板 |
| `src/tools/checking/` / `humanview/` / `common/` | `src/engine/audit` / `src/runtime` | 保留 |
| `src/app/services/verify_service.py` / `soc_service.py` | `src/engine/` facade | 保留；`src/engine` 已暴露 |
| `src/app/services/agent_mode_service.py` | `src/agent/` facade | 保留；已改名 |
| `src/cli/` | `src/interfaces/cli/` | 保留；`commands.py` 只做参数解析 |
| `src/workbench/` | `src/workbench/` | 不动 |

## 3. 已落地的 4.0 边界（本阶段）

新增 facade 包（不搬实现，只稳定名字）：

```text
src/agent/__init__.py      # Harness / TaskStore / Planner / Subagents / run_goal
src/engine/__init__.py     # run_verify / VPlan evaluate / SoC / run_goal
src/ir/__init__.py         # VPlan IR / contracts / Proposal / evidence
src/runtime/__init__.py    # TaskStore / jobs / permissions / workspace / subagent manager
src/generation/            # 目标命名空间（生成器仍留在 tools/stages）
src/knowledge/             # 目标命名空间（知识仍在 l4_memory / playbooks）
src/experience/            # 目标命名空间（经验仍在 l5_evolution）
src/interfaces/            # 目标命名空间（CLI 仍在 src/cli）
```

`config/architecture_guard.py` 已把上述前缀映射为 `iface`，facade 可以合法
引用 app/workspace/layers；实现仍受原有五层依赖约束。

## 4. 三个核心对象

| 对象 | 解决 | 当前落点 |
|---|---|---|
| **Design IR** | 机器如何理解芯片设计 | `src/layers/l3_decision/vplan` + dplan（目标 `src/ir/design`） |
| **Verification IR** | 机器如何理解验证意图 | `src/layers/l3_decision/vplan/runtime` + case IR（目标 `src/ir/verification`） |
| **Evidence DAG** | 如何证明结论可信 | VPlan evidence + `contract/vplan_map.json` + SVA/gate（目标 `src/ir/evidence`） |

Evidence DAG 的关键规则：**输入版本变化 → 下游证据失效**。RTL 改动后，
compile/formal/sim/coverage/signoff 证据必须重新评估，不能复用旧结论。

## 5. 实施顺序

| 阶段 | 工作 | 验收 |
|---|---|---|
| **P0 边界固化（当前）** | facade 包 + 真实文件映射 + guard 前缀；CLI 双模式 | 无越权裁决；Agent/Engine/IR/Runtime 名字稳定 |
| P1 生成体系 | RTL / C Model / UVM / SVA / testcase 生成器归位到 `generation/` | 产物可编译、可追溯、可复现 |
| P2 设计验证闭环 | Design IR / Verification IR / Differential check | RTL 与 C Model 独立验证；Debug-Repair-Rerun |
| P3 自主签核 | Evidence DAG / Coverage closure / Signoff gate | 证据完整、失效传播正确、人工审批可追溯 |

物理迁移只在 P1/P2 进行；P0 **不移动运行中的文件**，避免当前链路失稳。

## 6. 不可放松的边界

1. **Agent 不拥有裁决权**：可以生成/修改/建议，不能自行宣布 PASS、不能激活契约。
2. **Engine 不调用 LLM**：lint/compile/formal/sim/regression/coverage 是确定性执行。
3. **Runtime 不含业务**：TaskStore、进程、超时、权限、恢复、workspace 与 LLM 解耦。
4. **IR 是唯一语义桥**：Spec/Design/Verification/Execution IR + contracts，
   避免 Agent 与 Engine 直接拼字符串。
5. **Evidence 是签核依据**：每个结论有输入/产物 hash、工具版本、运行结果与依赖。
6. **C Model 初期只是 Candidate Reference Model**：编译通过不等于 Golden。
