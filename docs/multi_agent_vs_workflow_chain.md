# Multi-Agent vs Workflow Chain 辨析

> 日期：2026-08-09  
> 核心问题：SignOffAI 自称"多 Agent 系统"，但实际是串行流水线。这两者有什么区别？当前架构属于哪一种？

---

## 1. 概念辨析

### 1.1 真正的 Multi-Agent System

```
                    ┌──────────┐   消息/协商   ┌──────────┐
                    │ Agent A  │ ←──────────→ │ Agent B  │
                    │ (设计)    │               │ (验证)    │
                    └─────┬────┘               └─────┬────┘
                          │    ┌──────────┐          │
                          └──→ │ Agent C  │ ←────────┘
                               │ (签核)    │
                               └──────────┘

特征:
  • 每个 Agent 是自治实体，有自己的目标/信念/决策逻辑
  • Agent 之间通过消息/协商通信，不是共享内存
  • 任务分配是动态的 — Agent 可以拒绝、委托、协商
  • 可以有并发 — 多个 Agent 同时工作
  • 行为是涌现的 — 整体行为不是任何单个 Agent 预先定义的
```

### 1.2 Workflow Chain（流水线链）

```
  输入 → [Step1] → [Step2] → [Step3] → ... → [StepN] → 输出
           ↑          ↑          ↑                  ↑
         Agent1     Agent2     Agent3            AgentN
         (LLM)      (LLM)      (LLM)             (LLM)

特征:
  • 每个 Step 只是流水线上的一个环节
  • 中央调度器决定顺序，Step 无权决定"下一步做什么"
  • 通信是单向的：上游输出 → 共享上下文 → 下游读取
  • 严格串行，无并发
  • 行为是确定的 — 流程在执行前就已完全定义
```

---

## 2. SignOffAI 的实际情况

### 2.1 核心执行循环（来自 `execution.py:333`）

```python
# ── 顺序执行所有阶段 ──
for p_tuple in phases:           # ← 硬编码的 17 个阶段列表
    name, role, ctx_key = p_tuple[0], p_tuple[1], p_tuple[2]

    agent = self.registry.get_agent_instance(role)
    if not agent:
        continue                  # ← 跳过，不能自主决定

    # 依赖检查
    executor = StepExecutor(name, agent, ctx, output_root, on_progress)
    missing = executor.check_dependencies()
    if missing:
        continue                  # ← 跳过，没有降级/替代方案

    # 构造输入（从 ctx 取上游数据）
    task_input = json.dumps(ctx_parts)

    # 执行 Agent（单一 LLM 调用 + 工具）
    step_result = await executor.execute(task_input)

    # 写回共享上下文
    results[name] = final_status
```

**这是一个经典的 ETL Pipeline 模式**：Extract（从 ctx 取数据）→ Transform（Agent 处理）→ Load（写回 ctx）。

### 2.2 "Agent" 到底是什么？

```python
class SpecAndTestPlanner(BaseAgent):
    consumes = []           # ← 声明：我消费什么数据
    produces = "spec"       # ← 声明：我生产什么数据

    async def execute_task(self, task):
        # 调用 LLM + 工具，返回结果
        return await self._executor.ainvoke({"input": task["input"]})
```

每个 "Agent" 实际上是：**一个 LangChain AgentExecutor（LLM + 工具集）+ consumes/produces 契约声明**。它自己不决定何时运行、不与其他 Agent 通信、不知道上游 Agent 是谁。

### 2.3 Agent 之间的"通信"方式

```
Agent A (spec_planner)     →    ctx.put("spec", {...})
                                ↓
Agent B (design_architect) ←    ctx.get("spec")

这是一种「生产者-消费者」模式，通过共享内存（ContextStore）传递数据，
不是 Agent 间的直接消息通信。
```

### 2.4 对比表

| 维度 | 真正 Multi-Agent | SignOffAI "Agent" |
|------|:---:|:---:|
| **谁决定执行什么** | Agent 自己决定 | `run_pipeline()` 的 `for` 循环决定 |
| **Agent 间通信** | 直接消息/协商 | `ContextStore` 共享字典 |
| **并发能力** | 可以同时运行 | 严格串行，一个等一个 |
| **任务分配** | 协商/招标/委托 | 硬编码 `FULL_PHASES` 列表 |
| **运行时可替代** | Agent 可以拒绝任务，其他 Agent 补上 | 依赖缺失 → `skip`，固定角色 |
| **协作解决问题** | 多 Agent 同时分析同一问题 | 每个阶段独立，无交叉 |
| **流程自适应** | 根据中间结果动态调整流程 | 阶段列表在执行前就确定了 |
| **失败处理** | 自动路由到其他 Agent | `StepExecutor` 同 Agent 重试最多 2 次 |
| **分布式智能** | 智能分散在每个 Agent 中 | 智能在 LLM 单次调用中，Agent 只是容器 |

---

## 3. 架构本质：LLM-Powered Sequential Pipeline

### 3.1 真实架构图

```
                    PipelineExecutionService (中央调度器)
                              │
          ┌───────────────────┼───────────────────────┐
          │                   │                       │
          ▼                   ▼                       ▼
     ┌─────────┐        ┌─────────┐            ┌─────────┐
     │ Phase 1 │   →    │ Phase 2 │    → ... → │ Phase N │
     │ spec    │        │ design  │            │ report  │
     └────┬────┘        └────┬────┘            └────┬────┘
          │                  │                      │
          ▼                  ▼                      ▼
     ┌─────────┐        ┌─────────┐            ┌─────────┐
     │  LLM    │        │  LLM    │            │  LLM    │
     │ + tools │        │ + tools │            │ + tools │
     └─────────┘        └─────────┘            └─────────┘
          │                  │                      │
          ▼                  ▼                      ▼
     ┌──────────────────────────────────────────────────┐
     │              ContextStore (共享字典)               │
     │  spec: {...}  design_arch: {...}  env: {...}      │
     └──────────────────────────────────────────────────┘
```

**正确的名称应该是：LLM-Powered Sequential Verification Pipeline。**

### 3.2 为什么容易混淆

系统有一些"看起来像"多 Agent 的设计：

| 设计元素 | 看起来像 Multi-Agent | 实际作用 |
|----------|:---:|------|
| 11 个 Agent 类 | ✅ 多个独立 Agent | 只是 11 个不同的 LLM prompt 模板 + 工具集 |
| `consumes/produces` | ✅ Agent 间契约 | 只是 `ctx.get()` / `ctx.put()` 的类型标注 |
| `AgentRegistry` | ✅ Agent 注册中心 | 只是一个 `Dict[str, object]` |
| `ContextStore` | ✅ 共享上下文 | 只是一个带溯源标记的 `Dict[str, Any]` |
| `StepExecutor` | ✅ 阶段执行器 | 只是 `agent.execute_task()` + 重试循环 |

**这些都是命名上的"Agent 化"，底层实现是常规的 Pipeline 模式。**

---

## 4. 这个设计合理吗？

### 4.1 对于当前项目阶段：**合理，且正确的选择**

```
为什么 Pipeline 模式比 Multi-Agent 更适合当前阶段：

1. 可预测性 — IC 验证流程本身就是顺序的（spec→design→verify→signoff），
   Pipeline 精确建模了这个顺序。

2. 可调试性 — 每个阶段的输入/输出清晰可见，出问题定位到具体阶段。

3. 可观测性 — 17 个阶段的 score/time/status 一目了然。

4. LLM 的不确定性已经足够大 — 不需要再用 Agent 自治来增加不确定性。

5. 重放性 — 相同的输入 + 相同的阶段序列 → 相近的输出，这对签核场景至关重要。

6. CI 友好 — Pipeline 模式天然适合 CI/CD 集成。
```

### 4.2 什么时候需要真正的 Multi-Agent？

```
Multi-Agent 模式有价值的场景：

1. 并发探索 — "同时用 3 种策略生成测试用例，投票选最优"
   → 当前 Pipeline 做不到，因为每个 phase 只有一个 Agent

2. 动态分工 — "覆盖率有 5 个缺口，自动分配给 3 个测试工程师 Agent"
   → 当前做不到，因为 phase 角色是固定的

3. 协商决策 — "设计 Agent 和验证 Agent 对接口定义有分歧，协商达成一致"
   → 当前做不到，Agent 之间不通信

4. 自愈 — "Assertion Engineer 失败了，Debug Engineer 自动顶上"
   → 当前做不到，fail 就 skip
```

---

## 5. 如何演进到真正的 Multi-Agent

### 5.1 不需要改（当前 Pipeline 已经够用）

```
Pipeline 模式适用于:
  ✅ 完整的 spec→signoff 流程               → vagent verify --workflow full
  ✅ CI 集成中的一次性验证                     → jenkins/gitlab-ci 调用
  ✅ 确定性签核报告                           → vagent signoff
```

### 5.2 可以在特定场景引入 Multi-Agent

```bash
# 场景 1: 并发测试生成
vagent test generate --strategy multi-agent --agents 3
# → 3 个 TestEngineer Agent 并发工作，投票选最优

# 场景 2: 覆盖率缺口自动分配
vagent cover close --mode multi-agent
# → CoverageManager 发现缺口 → 自动分发给多个 Agent 补充测试

# 场景 3: 根因分析协商
vagent debug diagnose --mode multi-agent
# → DebugEngineer + DesignArchitect + ModelAgent 协商分析
```

### 5.3 实现 Multi-Agent 需要的架构改造

```
当前:                              改造后:
                                    
Pipeline (单链)                    Orchestrator (调度器)
  │                                  │
  ├─ Phase 1 (spec)                  ├─ Agent Pool (多个 Agent 实例)
  ├─ Phase 2 (design)                │   ├─ spec_planner × 1
  ├─ ...                             │   ├─ test_engineer × 3  ← 可并行
  └─ Phase N (report)                │   └─ debug_engineer × 2 ← 可协商
                                     │
需要新增:                            ├─ Message Bus (Agent 间通信)
  • Agent 自治循环 (while not done)   │   ├─ TaskAnnounce
  • 任务招标 (Contract Net Protocol)   │   ├─ TaskBid
  • 消息总线 (Agent-to-Agent message) │   ├─ TaskAward
  • 并发执行器 (asyncio.gather)        │   └─ ResultPublish
  • 协商协议 (negotiation protocol)   │
                                     └─ Shared Blackboard (替代 ContextStore)
```

**结论：在引擎尚未全部跑通之前，不需要做这个改造。Pipeline 模式对当前阶段是正确的。**

---

## 6. 建议：正名 + 定位

### 6.1 推荐命名

| 现状 | 问题 | 建议 |
|------|------|------|
| "多 Agent 系统" | 误导，暗示 Agent 自治/并发/协商 | **"LLM 驱动的验证流水线"** |
| "Agent" | 暗示自治智能体 | **"Stage Processor"** 或保留 Agent 但明确其定位 |
| "Multi-Agent" | 学术术语，与实际不符 | **"Multi-Stage Pipeline"** |
| `consumes/produces` | 借用了 Agent 术语 | 保留——这是好的设计模式，不管叫什么 |

### 6.2 架构文档中应该写

```
SignOffAI 的架构是 LLM-Powered Sequential Pipeline：

  每个 Stage 封装了一个 LLM Agent（LangChain AgentExecutor + 领域工具集），
  Stage 之间通过 ContextStore（带溯源的数据通道）传递结构化数据。
  中央调度器按预定顺序串行执行所有 Stage，支持依赖检查、重试和回滚。

  这不是一个分布式 Multi-Agent 系统——没有 Agent 间直接通信、并发执行
  或协商决策。这是有意为之：IC 验证流程本身是顺序的，Pipeline 模式提供
  了验证签核场景所需的可预测性、可审计性和确定性的执行轨迹。
```

---

## 7. 一句话总结

> **SignOffAI 不是 Multi-Agent 系统，而是 LLM-Powered Sequential Pipeline。每个"Agent"只是流水线上的一个带 LLM + 工具集的阶段处理器。这个设计对当前阶段是正确的——IC 验证流程天然串行，Pipeline 的可预测性和可审计性比 Agent 自治更重要。不要把 Pipeline 叫成 Multi-Agent，也不要为了"真正的多 Agent"而强行改造一个已经够用的架构。**
