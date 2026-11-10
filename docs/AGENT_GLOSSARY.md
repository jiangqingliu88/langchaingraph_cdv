# AGENT GLOSSARY

本文件固定 agentic 架构的术语。目录叫 `src/skills/` 后，代码里仍有
`BaseExecutor` / `ExecutorRegistry` 等历史符号；这里明确它们的关系。

| 术语 | 含义 | 代码落点 |
|---|---|---|
| **Supervisor** | 只读状态、只写路由字段的主控节点；不调 LLM、不跑 EDA | `src/agents/supervisor/graph.py` |
| **Agent / Expert** | 有循环、有工具、有预算的专家；不直接操作 EDA | `src/agents/{design,verify,debug,coverage}/` |
| **Subgraph** | 挂载在主图上的专家图；内部可有环形边 | `src/agents/*/graph.py` |
| **Skill** | 一个阶段的完整能力包（原 executor） | `src/skills/<role>/main.py` |
| **Executor** | **Skill 的实现基类/历史注册名**，不是旧架构 | `src/layers/l2_orchestration/skills/base.py`、`.../registry.py` |
| **Tool** | 原子动作，经 ToolHub 白名单/schema 校验 | `src/tools/`、`src/agents/runtime/skill_tools.py` |
| **Gate** | 纯代码门禁，不接受 LLM 汇报 | `src/agents/gates/` |
| **SupervisorView** | 主图只读投影，避免看到专家内部字段 | `src/agents/supervisor/state.py` |
| **AgentCard** | 工牌：skills / tools / 重试上限 / 写范围 | `src/agents/registry.py` |
| **SkillTool** | 把 skill 包成 agent 可调用的“技能工具” | `src/agents/runtime/skill_tools.py` |

## 命名约定

- 目录/agent 侧：用 **skill**；
- 实现类：暂时保留 **Executor**（`BaseExecutor`、`DesignExecutor`），
  因为它是稳定的代码接口，改名会破坏外部 import；下一轮可做别名迁移。
- 看到 `Executor` 时，理解为“Skill 的实现类”，不是“旧 24 节点架构”。
