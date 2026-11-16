# 学习笔记：Agents SDK 与生态包

> 学习材料，不是本项目的联网验收报告。当前仓库实际安装并固定
> `openai-agents==0.24.0`；**Python 导入名是 `agents`**，SDK 的 `Agent`、
> `Runner`、`FunctionTool` 与审批边界已经接入本项目角色入口。
> 本项目使用 `ProjectBudgetedModel` 保留统一模型预算/审计，不承诺任意
> Provider、原生流式输出、handoff 或每个 SDK 高级特性都已完成适配。
> 实际入口与已接入能力见 [Agent Domain 布局](../architecture/AGENT_DOMAIN_LAYOUT.md)。

下文保留 Python/TypeScript 生态入门和历史背景；具体版本、依赖与本仓库状态以本页说明、[文档索引](../INDEX.md)及 `requirements.txt` 为准。安装包不能代替有效模型密钥或真实 Provider 连接。

先理一下你问的三件事：OpenAI 官方包叫啥、还有哪些开源同类型包、啥时候发布的。

一、OpenAI 官方 Agents 包（开源）

Python

• 包名：openai-agents（不是 openai-agent，单数）

• 安装：pip install openai-agents

• 仓库：github.com/openai/openai-agents-python

• 协议：MIT 开源

• 定位：以 Agent / Tool / Handoff / Guardrail / Tracing 为核心的 Agent 运行时；它不是零依赖库。

- 最小用法：
from agents import Agent, Runner

agent = Agent(name="assistant", instructions="你是个助手")
result = Runner.run_sync(agent, "写个递归的俳句")
print(result.final_output)


TypeScript

• 包名：@openai/agents（npm）

发布时间线

• 2024-10：OpenAI 先发实验性 Swarm（只教学用，不维护）

- 2025-03-11：正式发布 Agents SDK（Python 版，生产可用，接 Responses API）
• 2025 后续：TS 版跟进

• 2026 持续迭代：sandbox、session、MCP v2、guardrail 增强

你之前 site-packages 里看到的 openai_agent 文件夹，大概率是早期残留/截断名，正规包就是 openai-agents。

二、同生态“还有啥开源包”（Agent 框架横评）

1. OpenAI 系

• openai-agents（官方，轻量 runtime）

• 已废弃：swarm（实验品，被 Agents SDK 取代）

2. LangChain 系（你环境里已经有一堆）

- langchain / langchain-core
• langgraph（图编排，生产级，有 checkpoint / 人机协同）

• langchain-community / langchain-openai

3. 微软系

• autogen（AG2，多 agent 对话；新项目转向 Microsoft Agent Framework）

• semantic-kernel（.NET/Python 企业向）

4. 其他主流开源

• crewai：角色制多 agent（研究员/写手/评审），上手快

• haystack：RAG 向

• mastra / vercel ai sdk：TS 向

5. 观测/辅助层（你环境里也有影子）

• opentelemetry-*：Agents SDK 内置 tracing 走 OTLP

• litellm：接 100+ 模型，Agents SDK 可借它接非 OpenAI 模型

三、怎么选（一句话）

• 想紧跟 OpenAI 官方、轻量多 agent 交接 → openai-agents

• 想复杂状态图、可恢复、审计轨迹 → langgraph

- 想角色扮演式快速搭 demo → crewai
• 想纯研究多轮辩论 → autogen（老项目别新起）

• 想不装 MongoDB 那种本地文档库 → 跟 agent 框架无关，用 TinyDB/TinyMongo

四、和你之前那个环境对一下

你之前目录里：
• langchain* + langgraph → 编排层

• openai + litellm → 模型层

• weaviate-client → 可用的向量库客户端，不代表服务端已连通；项目记忆与业务存储仍以实际配置的 SQLite/工作区为准，原注释的 pymongo 未启用

• opentelemetry → agent tracing

• 本项目已确认安装 openai-agents==0.24.0，导入名是 agents；它可与既有 LangGraph 兼容工作流并存。新角色通过 SDK Agent/Runner 执行，原 specialist 及模型调用接口按兼容适配层保留

实际的 SDK 组合与角色分工见 [Agent Domain 布局](../architecture/AGENT_DOMAIN_LAYOUT.md)；学习材料与工程验收的区分见 [文档总索引](../INDEX.md)。
