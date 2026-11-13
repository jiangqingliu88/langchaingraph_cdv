# SignOffAI Long-Horizon Runtime — 代码审查包

> 分支：`refactor/langgraph-migration` · 快照：2026-11-13
> 这是当前代码副本（非生成物）。`ARCHITECTURE_CURRENT.md` 是同期架构快照。

## 目标架构

- `ARCHITECTURE_4.0.md` — Agent / Engine / IR / Runtime 四平面目标架构与真实文件映射。

## 第一轮要求的 8 个文件

| 文件 | 覆盖内容 |
|---|---|
| `harness.py` | 主循环、状态机、C0–C4 注入、TaskStore 同步、自动 replan、恢复检查 |
| `context.py` | token 估算、压缩、tool-result pruner、压缩审计钩子 |
| `task_store.py` | goal/plan/todo/decisions/blockers/facts、version、events、幂等与一致性检查 |
| `manager.py` | subagent 派发、进程/线程模式、并发、超时、幂等回收、结果校验 |
| `isolation.py` | 独立 workspace、ScopedTools 工具/写路径白名单 |
| `contract.py` | SubagentContract / SubagentResult / 状态 |
| `session.py` | 会话消息、持久化、恢复 |
| `test_long_horizon_runtime.py` | 现有长任务/子 Agent 测试覆盖（非新增） |

## 额外文件

| 文件 | 作用 |
|---|---|
| `factory.py` | 6 个 Agent Type 定义 + 角色专用 prompt |
| `runner.py` | 进程级子 Agent 入口（独立 Harness/session/TaskStore/workspace） |
| `validator.py` | 结果可信度：交付物 + finding 的 file/line/signal 核对 |
| `dag.py` | Task DAG 校验、并行分层、下游失效 |
| `facts.py` | Immutable Facts（只追加，压缩不丢） |
| `llm_factory.py` / `llm_call.py` | LLM client 创建与唯一调用出口 |
| `permissions.py` | 直接模式高风险操作审批（删除/破坏性 shell/RTL/UVM/契约矩阵） |
| `write_audit.py` | 写入前后 hash + unified diff 审计 |
| `tools.py` | 工具白名单/schema（含 `allow_rerun`） |
| `modes/` | Agent Mode / Verify Mode facade + router（`vagent work` 统一入口） |
| `cmd_work.py` | `vagent work <goal> [--mode agent|verify]` |
| `agent_mode_service.py` | Agent Mode 的服务实现 facade |

## 真实数据样本（`samples/`）

- `samples/subagents/demo/result.json` — 子 Agent 结构化结果
- `samples/subagents/demo/events.jsonl` — 子任务事件
- `samples/sessions/*.json` / `*.events.jsonl` — Session 与事件
- `samples/task/*/` — goal/plan/todo/blockers/facts/completion/project_context

## 本轮代码改动（未新增测试）

- Immutable Facts + 压缩审计（`facts.py`、`task_store.py`、`context.py`）
- Task DAG（`dag.py`，子目标 `depends_on`，未满足依赖不执行）
- 进程级子 Agent（`runner.py`，真实 LLM 默认独立进程）
- 子任务幂等回收（同 `task_id+objective` 已完成直接返回）
- 结果证据核对（`validator.py`：file/line/signal 必须真实存在）
- TaskStore version/event log/一致性检查（恢复前检查坏 JSON/悬空依赖/空版本）
- 工具调用账本：`invocations.jsonl` 记录 RUNNING/COMPLETED/FAILED/UNKNOWN；
  恢复时把 RUNNING 标 UNKNOWN；非幂等工具需显式 `allow_rerun=true`
- 进程树清理：子 Agent 超时用 taskkill /T 或 killpg 清整棵树（runner + shell + EDA）
- 子任务 fingerprint：task_id + objective + scope + project revision + 输入文件 hash
- 直接模式写入审计与审批：`writes.jsonl` 记录 before/after hash + diff；
  删除/破坏性 shell/改 RTL/UVM/契约矩阵走审批
- 双模式入口：`src/modes/`（Agent Mode / Verify Mode）+ `vagent work`；
  Agent 仍是统一入口，Engine 是可调用的确定性内核

## 待代码级审批时重点看

1. `manager.run_contract`：进程 vs 线程的判定、超时、幂等键。
2. `runner.py`：子进程的写边界、LLM 环境传递、结果落盘。
3. `task_store.py`：`_bump`、`append_event`、`consistency` 与并发写。
4. `context.Compactor`：压缩审计是否保留 fact ids，是否可能删事实。
5. `validator._check_finding`：file/line/signal 核对是否足够。
6. `harness._observe_tool_result/_auto_replan`：失败触发与去重。
7. `task_store.begin_invocation/finish_invocation/recover_invocations`：RUNNING→UNKNOWN 与 allow_rerun 门。
8. `manager._fingerprint`：project revision + 输入 hash 是否覆盖陈旧结果复用风险。
9. `manager._kill_process_tree`：Windows taskkill /T 与 POSIX killpg。
10. `permissions.decide` + `write_audit.record_write`：高风险写审批与可回滚审计。
