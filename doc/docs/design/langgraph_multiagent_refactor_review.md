# LangGraph 多 Agent 重构提案 —— 评估与修正方案

> 文档目的：对"按 Supervisor / Handoff / Subagents 模式重构为真正的多 Agent"这一提案做逐条评估，
> 并给出**与项目战略定位一致**的修正方案。
>
> 评估依据：静态通读 `src/layers/`、`src/agents/`、`src/cli/commands.py` 全部相关代码，
> 关键结论均带 `file:line` 证据。
>
> 日期：2026-10-08　　分支：`refactor/langgraph-migration`

---

## 一、结论摘要

| | |
|---|---|
| **提案的骨架判断** | ✅ 正确 —— Custom Workflow 为主骨架是对的 |
| **提案对现状的描述** | ❌ 错误 —— 它把项目**已经实现**的能力描述成"重构后才会有" |
| **提案的核心主张** | ❌ 危险 —— 「Agent 由 LLM 驱动决策」与 CLAUDE.md 战略定位正面对立 |
| **唯一真该做的事** | ✅ HITL（`interrupt()`）在 CLI 上的**断链修复**，且设施已存在，只差接线 |

**一句话**：提案的 70% 在描述你已有的图，30% 会伤害你的差异化。真正缺失的只有一件事，
而且它不是"多 Agent 模式"问题，是**一条执行路径没接上**的问题。

---

## 二、逐条评估

### 2.1 提案主张 vs 代码事实

| 提案要求 | 代码事实 | 证据 | 结论 |
|---|---|---|---|
| Custom Workflow 为主骨架 | 已有 `StateGraph(PipelineState)`，24 节点、8 处条件分支 | `graph.py:1650-1736`、`NODE_FUNCS` `graph.py:1632` | 已满足，不动 |
| 确定性节点嵌入 | 整个 L1 是零 AI 层；6/8 agent 零 LLM 调用 | `src/layers/l1_infrastructure/`；`agents/*/main.py` | 已满足，且要**加强** |
| 覆盖率反馈循环 | `decide → apply_directed_test / apply_expand_seeds / apply_relax → round_bump → ops → coverage → decide` | `graph.py:1718-1721`、`n_apply_directed_test` `:1404`、`n_apply_expand_seeds` `:1423` | **已存在** |
| 流程有真实分支和循环 | 8 处条件边；`round_bump` 注释自述「所有回边的汇合处」 | `graph.py:640-661`、`1671-1726` | **已存在** |
| Agent 间传递结构化上下文 | `_read_ctx` / `_write_ctx` + Context 黑板 + `PipelineState` 承载全部阶段产物 | `base.py:295/338`、`context.py:142/215`、`state.py:118-141` | **已存在** |
| Handoff 用 `Command(goto=...)` | 用条件边替代，功能等价 | `graph.py:1671-1726` | 功能等价，无需改写 |
| HITL 审批点 `interrupt()` | 设施齐全：`governance/approval.py`、`state.manual_gate`、`awaiting_approval`、`interrupted`、`interrupt()` | `graph.py:994`、`state.py:101/110/114` | ⚠️ **已实现但 CLI 不可达** |
| **Agent 由 LLM 驱动决策** | 现为规则引擎 + 可选 RL；`HARD_ACTIONS` 明确排除 RL | `decision_engine.py:75-201`、`:523-525` | ❌ **拒绝** |
| Supervisor 模式 | 已有中央 `decide` 节点承担路由决策 | `n_decide` `graph.py:862` | 换名不换实 |
| Async Subagents 并行 | 已有 `pipeline_scheduler` 做并发调度 | `execution.py:806`、`pipeline_scheduler.py` | 押后评估 |

### 2.2 冲突一：「Agent 由 LLM 驱动决策」与战略定位对立

**CLAUDE.md 原文**：

> 我们不是把 LLM 当"万能生成器"用，而是把它嵌入到 UVM 骨架 + Jinja2 渲染 + 契约校验的工程流程中。
> **LLM 只做"完形填空"，不决定整体结构。**

> 学术已经证明纯 LLM 收敛是红海且天花板低……**你真正的差异化不是"AI 更聪明"**，
> 而是可复现、可审计、可治理。

**代码中的刻意边界**：

- `HARD_ACTIONS = (FIX_COMPILE, FIX_MODEL)` —— 硬失败动作**永远走规则，RL 不参与**（`decision_engine.py:523`）
- 经验统计只提供"降级建议"，不直接拍板；注释明写「决策逻辑保持确定性，规则先行」（`decision_engine.py:243`）
- `TERMINAL_ACTIONS = ("CONVERGE",)` 不进 RL 动作空间（`decision_engine.py:525`）
- RL 只管 4 个软动作（`SOFT_ACTIONS`）

**为什么必须拒绝**：

| 若流程改为 LLM 驱动 | 后果 |
|---|---|
| 流程不确定 | **可复现崩掉** —— 同一份配置无法复现同一条路径，`vagent dump` 失去意义 |
| 决策不可回溯 | **可审计崩掉** —— 无法回答"为什么这一轮选了 EXPAND_SEEDS 而不是 RELAX_CONSTRAINT" |
| Token 成本不可预测 | **可治理崩掉** —— 预算模型失效 |
| 追学术红海 | CLAUDE.md 已判定：纯 LLM 收敛天花板低（Infineon 论文仅提升 10–20%） |

**这不是"保守"，这是把资源押在唯一可防守的高地上。**

### 2.3 冲突二：提案对现状的描述与代码不符

提案称「你之前的实现里，Agent 之间没有真正的通信和协作」。**已核验为事实错误**：

- **通信**：`_write_ctx` 把产出写回共享上下文（`base.py:667`），`_read_ctx` 读取（`base.py:569`）；
  Context 黑板有完整读写接口（`context.py:142 put` / `:215 get` / `:114 get_compressed`）
- **协作**：`PipelineState` 的 B 通道承载全部阶段产物（`spec` / `design_arch` / `model` / `tests` /
  `env` / `regression` / `debug` / `coverage` / `gaps`，`state.py:118-141`），并有 `PHASE_OWNERS`
  字段归属表在 import 期自检（`state.py:195-211`）
- **循环**：覆盖率不达标 → `decide` 产出动作 → `apply_*` 节点 → `round_bump` → 回到 `ops`，
  是完整的闭环（`graph.py:1718-1721`）

**结论：提案描述的"重构后架构"，就是当前的图。**

---

## 三、现有架构的真实能力清单

已具备（**不要重做**）：

- [x] LangGraph `StateGraph` 单一闭环图，24 节点、8 条件分支
- [x] Pydantic `State` + 自定义 reducer（`_add` / `operator.or_`）
- [x] 阶段间结构化上下文传递（Context 黑板 + PipelineState）
- [x] 覆盖率驱动的反馈循环（决策 → 动作 → 回边）
- [x] 规则引擎（硬编码优先级链 + 证据分类）与 RL 软决策并行
- [x] 五层领域证据链（`evidence/five_layer.py`、`manifest.py`、`file_audit.py`）
- [x] 治理设施（`governance/approval.py`、`governor.py`、`quality_guard.py`、`policy_pack.py`）
- [x] Checkpointer（`AsyncSqliteSaver`，落 `<output_root>/docs/checkpoints.sqlite`）
- [x] `interrupt()` / `Command(resume=)` 的完整实现

真正缺失（**这才是待办**）：

- [ ] **CLI 走不到 checkpoint / interrupt**（主命令用无 saver 的 `run_closed_loop`）
- [ ] `vagent approve/reject` 只写 `approval.json`，**不驱动图恢复**
- [ ] LangGraph 已装能力的 2/3 闲置（RetryPolicy / CachePolicy / Send / store / time travel）
- [ ] LLM 调用未收口（`LLMQueryEngine` 仅 1 个调用方，实际散落约 16 处）

---

## 四、修正方案

### 4.1 骨架：保持 Custom Workflow（不变）

**不引入** Supervisor / Handoff / Subagents 的重写。理由：

- Supervisor 的职责已由图中的中央 `decide` + `governor` 节点承担
- Handoff 的语义已由条件边 + PipelineState 等价实现，改成 `Command(goto=)` 是**纯形式改动**，
  但会让重入/checkpoint 语义变复杂（`Command` 与 `conditional_edges` 混用需额外小心）
- 价值不在换模式名，在补齐真实缺口

### 4.2 唯一结构性改动：修 HITL 断链（P0）

**问题**：`interrupt()` 只在有 checkpointer 时触发（`graph.py:1086`，条件 `rt.interrupt_mode`），
而 `interrupt_mode = saver is not None`（`execution.py:649`）。saver 只在
`run_closed_loop_streaming` 传入（`execution.py:651`），该函数**唯一调用者是 GUI 的
`RunService`**（`run_service.py:467`）。

结果：

| 入口 | 命令 | checkpoint | interrupt |
|---|---|---|---|
| A `run_closed_loop` | `vagent run` / `ci verify` / `multi` / REPL | ❌ | ❌ 阻塞式 gate |
| B `run_closed_loop_streaming` | GUI / RunService | ✅ | ✅ |

**修法**：

1. `run_closed_loop`（`execution.py:488-573`）也构造并传入 `_safe_checkpointer`
2. `vagent approve/reject`（`commands.py:4117-4150`）改为调用
   `run_closed_loop(..., resume=<payload>)`，走 `Command(resume=)` 真恢复
3. 合并 A/B 两个入口的输入装配逻辑（`execution.py:526-545` vs `:670-704` 是两份重复实现，
   `--rtl` 曾因只改一处而被 CLI 忽略）

**收益**：一次性兑现 CLAUDE.md 的「可复现」（可从中间态重放）与「可治理」（审批真能暂停/恢复）。

### 4.3 概念清理：「Agent」降级为「Stage」（P2，非紧急但方向明确）

**依据**：8/8 agent 覆写 `execute_task`；7/8 的 `_get_prompt_template()` 返回 `None`；
6/8 零 LLM 调用；`direct_chain` 分支死；`_offline_result` 两个调用点几乎不可达；
`AgentExecutor` 唯一用户是 `debug`（`debug/main.py:366` 调 `super().execute_task()`）。

即：**`BaseAgent` + LLM executor 的抽象，真实服务场景是 1/8。**

**改法**：把 Agent 从"会思考的实体"重定义为"声明式阶段执行器"：

```python
class Stage(Protocol):
    name: str
    requires_llm: bool        # 显式声明 —— 6/8 为 False
    risk: ToolRisk            # 显式分级 —— 治理的输入
    produces: list[str]       # 产出哪些证据 —— 证据链的输入

    def run(self, s: StageInput) -> StageOutput: ...
```

**收益**：`requires_llm` / `risk` / `produces` 从散落的 if 分支变成**声明**，
可自动生成 token 预算扣减、风险门控、证据清单；顺带删掉
`AgentExecutor` / `langchain_classic` / `_lc_tool_compat` / `tool_system.py`（与 `tool_hub` 重复）。

### 4.4 用足已装 LangGraph 能力（P2）

| 能力 | 替代对象 | 收益 |
|---|---|---|
| `RetryPolicy` | 手写的 `compile_retries` / `governor_retry` 节点 | 少两个节点，重试语义标准化 |
| `get_state_history`（time travel） | 无 | **直接支撑 `vagent dump` 的"任意一步可复现"** |
| `Send` API | 外挂的 `pipeline_scheduler` | 多模块并发进图，状态不再割裂 |
| `store` | `graph.py:1650` 空挂的形参 | 跨 run 长记忆（接 L4） |
| `exclusive` reducer | `state.py:39` 定义但**未挂载** | 让"单写者纪律"从静态表变成运行时保障 |

---

## 五、落地路线

### P0 —— 修断链（支撑最硬的两个支柱）

1. `run_closed_loop` 传 checkpointer
2. `approve` / `reject` 走 `Command(resume=)` 真恢复
3. 合并 A/B 入口的输入装配

### P1 —— 去重复与依赖炸弹

4. 删 `langchain_classic` 隐性依赖（`base.py:12` 顶层 import，**未在 requirements 声明**）：
   把 `debug` Phase 6 改成直连 chain（约 10 行），删掉 `AgentExecutor` 整条路径
5. 删 `tool_system.py`（与 `tool_hub.py` 重复：两套注册表 / 三处 schema 校验 / 两个同名 `wrap_agent_tools`）
6. 删 `_tools_old.py`（1753 行）/ `src/core/`（import 即 ImportError）/ `scmodel_tools/`（空目录）
7. LLM 调用收口到 `LLMQueryEngine`（或明确废弃）

### P2 —— 结构治理

8. 拆 `commands.py`（5061 行）/ `graph.py`（1741 行，建图仅占约 90 行）
9. **Stage 概念重构**（4.3）
10. 用足 LangGraph 能力（4.4）
11. 加依赖方向测试（现有 3 处反向依赖靠函数内延迟 import 遮掩）

### P3 —— 契约收口

12. 工具返回值统一为 dict（现 dict / JSON 字符串混用，靠 workbench bridge 兜底）
13. 补全 `ToolRisk` 标注（46 处 `@tool` 仅 3 处标注）

---

## 六、与提案的差异总表

| 提案建议 | 本方案 | 差异理由 |
|---|---|---|
| Custom Workflow 为主骨架 | **采纳** | 已有，保持 |
| 确定性节点嵌入 | **采纳并加强** | 已有，是壁垒 |
| 覆盖率反馈循环 | **采纳，修数据 bug** | 已有；`staged-regression-tag-filter` 未结 bug 在此链上 |
| HITL `interrupt()` 审批点 | **采纳，列为 P0** | 设施已有，但 CLI 断链；这是真缺口 |
| Handoff 用 `Command(goto=)` | **不改** | 条件边功能等价，改写会复杂化 checkpoint 语义 |
| Supervisor 模式 | **不改** | 中央 `decide` + `governor` 已承担该职责 |
| Async Subagents | **押后** | 有 `pipeline_scheduler`；收益需先评估 |
| **Agent 由 LLM 驱动决策** | **拒绝** | 与 CLAUDE.md 正面对立，摧毁可复现/可审计/可治理 |

---

## 七、对提案中"伪多 Agent"论断的回应

提案称当前实现是"伪多 Agent"，因为 Agent 由写死的 if-else 驱动、彼此不通信。

**准确的说法是**：当前实现**不是多 Agent 系统，而是确定性阶段管线** ——
这是一个**有意的设计选择**，不是缺陷。

- 它不是"伪多 Agent"，它是"真确定性管线"
- "多 Agent"要解决的问题（让 LLM 自主分解任务、自主选择协作者），
  在这个领域恰恰是 CLAUDE.md 判定为红海且天花板低的方向
- 项目的差异化在**证据链 + 治理**，不在 Agent 自主性

**如果一定要用"Agent"这个词**，那么调整方向应该是**让这个词名实相符**（4.3 的 Stage 重定义），
而不是**让实现去追赶这个词**。

---

*本文档所有结论基于对当前分支代码的静态阅读。建议在动手前用现有测试套件
（`tests/` 75 个文件 8.2k 行）做一次基线回归，确认对"哪些路径实际执行"的判断。*
