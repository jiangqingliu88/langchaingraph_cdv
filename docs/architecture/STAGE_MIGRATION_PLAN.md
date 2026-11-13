# Stage Migration Plan (Architecture 4.0)

> 配套：`STAGE_OWNERSHIP.md`（归属）、`STAGE_DEPENDENCY_MATRIX.md`（依赖）。
> 原则：每次只迁移一个职责域；迁移后立即做 compileall + import sweep + guard。

## 1. 目标映射

| 旧路径 | 新路径 | 理由 |
|---|---|---|
| `src/engine/stages/front/{__init__,main}.py` | `src/engine/front/` | 输入解析是确定性 Engine |
| `src/engine/stages/front/vplan/` | `src/engine/front/vplan/` | 确定性 VPlan 校验/读取 |
| `src/engine/stages/front/dplan/` | `src/generation/planning/dplan/` | 调 LLM 抽 dplan/contract |
| `src/engine/stages/design/` | `src/generation/design/rtl/` | RTL 生成 |
| `src/engine/stages/model/` | `src/generation/design/cmodel/` | C Model 生成 |
| `src/engine/stages/verify/` | `src/generation/verification/` | UVM/SVA/testcase 生成 |
| `src/engine/stages/verify/{ir_artifacts,steps_dag,dut_checker}.py` | `src/engine/verify/` | 确定性 Verification IR |
| `src/engine/stages/ops/` | `src/engine/ops/` | EDA 执行 |
| `src/engine/stages/coverage/` | `src/engine/coverage/` | 覆盖率 |
| `src/engine/stages/audit/` | `src/engine/audit/` | 证据/签核 |
| `src/engine/stages/debug/main.py` | `src/agent/specialists/debug/` | LLM 根因/修复 |
| `src/engine/stages/debug/tools/` | `src/engine/diagnostics/` | 确定性日志/波形解析 |
| `src/engine/agents/supervisor/` | `src/engine/orchestration/supervisor/` | 确定性调度 |
| `src/engine/agents/runtime/nodes/pure/` | `src/engine/orchestration/nodes/pure/` | 确定性节点 |
| `src/engine/agents/runtime/nodes/agent/` | `src/agent/runtime/pipeline_nodes/` | Agentic 节点 |
| `src/engine/agents/runtime/{guards,markers}.py` | `src/engine/orchestration/` | 节点守卫 |
| `src/engine/agents/runtime/{tool_loop,stage_tools}.py` | `src/agent/runtime/` | LLM 工具循环 |
| `src/engine/agents/gates/` | `src/engine/audit/gates/` | 签核门 |
| `src/engine/agents/{design,verify,coverage,debug}/` | `src/agent/specialists/*` | 专家 Agent |
| `src/engine/agents/registry.py` | `src/engine/orchestration/registry.py` | AgentCard 能力表 |
| `src/engine/agents/stage_policy.py` | `src/engine/orchestration/stage_policy.py` | 阶段策略 |

迁移完成后 `src/engine/stages/` 与 `src/engine/agents/` 整个删除。

## 2. Import 兼容策略

- 一律改成**绝对导入**（`from src.<new> import ...`）。
- 不保留旧路径 shim：旧包会整目录删除，避免“两个名字指向同一实现”。
- 包内相对导入（`from .main import X`）随包移动自然生效；跨包相对导入显式改绝对。
- 注册点只有两处：
  - `src/layers/l2_orchestration/execution_helpers.py` 的 `_EXECUTOR_PATHS` 点路径表；
  - `src/interfaces/cli/commands.py` 的 `initialize()` 导入。
- 迁移后同步 `config/architecture_guard.py` 分区、`config/complexity_baseline.json`
  与 `config/architecture_budget.yaml` 的路径键。

## 3. 测试更新

不执行 pytest，但路径必须保持可导入：

| 测试/脚本 | 更新 |
|---|---|
| `tests/test_stages.py` | supervisor graph 新路径 |
| `tests/test_supervisor_graph.py` | supervisor/gates/design graph 新路径 |
| `tests/test_state_contracts.py` | guards 新路径 |
| `tests/test_agent_registry.py` | `engine.orchestration.registry` / `stage_policy` + `agent.runtime.stage_tools` |
| `tests/test_agent_tool_loop.py` / `test_debug_fake_eda.py` | `agent.runtime.tool_loop` |
| `tests/test_design_loop.py` | `agent.specialists.design` + supervisor routing |
| `tests/test_approval.py` / `test_manual_node_gate.py` | `engine.orchestration.nodes.pure.approval` |
| `tests/test_architecture_invariants.py` | 节点模块前缀断言改为 `src.engine.orchestration` / `src.agent` |
| `src/workbench/tests/test_pipeline_modules.py` | supervisor graph 新路径 |
| `src/ir/contract/tests/test_build.py` | `engine.ops.main` |

## 4. 迁移顺序

1. `engine/front` + `generation/planning/dplan`
2. `generation/design/{rtl,cmodel}`
3. `generation/verification` + `engine/verify`
4. `engine/ops`
5. `engine/diagnostics`（debug tools）
6. `engine/coverage`
7. `engine/audit` + `engine/audit/gates`
8. `engine/orchestration` + `agent/specialists` + `agent/runtime`

每步：移动 → 全仓替换 import → compileall → import sweep → guard。

## 5. 风险

| 风险 | 处理 |
|---|---|
| 生成模块被 `engine` 直接 import，边界反了 | 只允许 `engine/orchestration` 调用 `generation` Stage 执行器；`engine/front/ops/coverage/audit` 不 import generation |
| `engine/agents` 节点函数测试按模块前缀断言 | 同步更新断言；不依赖旧前缀 |
| 包内相对导入跨包失效 | 全模块 import sweep 兜底（805 模块） |
| 循环导入：agent ↔ generation ↔ engine | generation 只依赖 IR/tools；agent 依赖 engine/generation；engine 不依赖 agent |
| 复杂度基线路径漂移 | 迁移时同步改写 baseline 键 |
| 行为回归 | **本轮不跑 pytest**；结构/导入验证通过不等于行为回归通过 |

## 6. 完成判据（本轮）

- `src/engine/stages/` 与 `src/engine/agents/` 不再存在；
- 全模块 import sweep 0 failure；
- `python -m config.architecture_guard` OK；
- CLI 命令注册成功；
- 旧路径无残留引用（除历史文档/会话记录）。
