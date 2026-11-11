# Verification Agentic System 1.0

`src/vas/` 是 IC 验证的自主执行系统。核心原则：

> **Agent 负责理解、规划、生成、分析、提出修复；确定性 Engine 负责执行、检查、判定、签核。**

LLM 可以参与验证工作，但不能自行宣布验证通过。

## 六层

```text
L6 Experience      CLI / Workbench / Human Review / Signoff Dashboard
L5 Agentic         Planner / Router / Runtime / 10 个验证角色
L4 Verification IR Intent / Design / Resource / Execution / Evidence
L3 Engine          Compile / Simulate / Regression / Coverage / Analyze
L1 Evidence        ArtifactStore / Provenance / Hash Chain / Policy / Approval
```

只有 L5 是 Agentic 层；其余是数据、执行、治理基础设施。

## 包结构

```text
src/vas/
├── contracts.py          TaskContract / TaskResult
├── ir/models.py          五类 IR + trace_errors()
├── evidence/
│   ├── store.py          ArtifactStore + Provenance 哈希链
│   └── policy.py         GatePolicy（确定性裁决）
├── engine/protocols.py   VerificationEngine / NullEngine / CallableEngine
├── runtime/
│   ├── registry.py       10 个 AgentSpec
│   ├── permissions.py    agent→task 授权
│   ├── llm.py            LLMAdapter / NullLLM
│   ├── context.py        AgentContext
│   └── runtime.py        生命周期/重试/预算/trace
├── agents/handlers.py    10 个角色 handler
└── orchestration/
    ├── state.py          状态机
    └── orchestrator.py   闭环编排
```

## 十个角色

| Agent | 任务 | 输出 |
|---|---|---|
| Requirement | `requirement_extraction` | Intent IR |
| Architecture | `architecture_analysis` | Design IR |
| Planning | `planning` | objectives / scenarios |
| UVM | `uvm_generation` | Execution IR tests |
| Formal | `formal_generation` | SVA tests |
| Regression | `regression` | runs |
| Debug | `debug` | diagnosis |
| Coverage | `coverage_analysis` | coverage / gaps |
| Repair | `repair` | repair proposals |
| Signoff | `signoff` | signoff request |

## 数据流

```text
spec/RTL
  → Requirement Agent → Intent IR
  → Architecture Agent → Design IR
  → Planning Agent → objectives/scenarios
  → UVM/Formal Agent → Execution IR
  → Regression Agent → Engine → Evidence IR
  → Coverage Agent → gaps
  → Repair Agent（可选）→ 下一轮
  → GatePolicy → Signoff
```

每条关系都可校验：

```text
Requirement → Objective → Test → Run → Evidence → Decision
```

`VerificationIR.trace_errors()` 会拒绝悬空引用和没有 run 证据的 test。

## 确定性 Gate

`GatePolicy` 检查：

- IR trace 完整；
- 每个 test 都有 run 证据；
- 没有未解释的 failed/blocked；
- 每个 objective 覆盖率达到 target；
- 证据文件哈希一致；
- 有授权的人工/自动批准记录。

任何一项不满足 → `blocked`，不会因为 Agent 说“完成”而通过。

## Engine

`NullEngine` 在没有 EDA 时显式返回：

```text
blocked: EDA_MISSING
```

`CallableEngine` 用于接入真实 compile/run/coverage 后端；Agent 不直接跑 EDA。

## CLI

```bash
python -m src.cli.commands vas run <spec.md> \
  --design-top <dut_top> \
  --workspace output_vas \
  --target 95 \
  --json
```

无 EDA 时输出 `blocked` + `EDA_MISSING`，不伪造 passed。

## 扩展

新增一个角色：

1. `runtime/registry.py` 加 `AgentSpec`；
2. `agents/handlers.py` 加 handler；
3. `orchestration/orchestrator.py` 加任务；
4. 加测试：权限、IR 追踪、gate 阻断。

新增一个 IR 字段：

1. `ir/models.py` 加模型/字段；
2. `trace_errors()` 加语义校验；
3. GatePolicy 加确定性检查；
4. 加测试。
