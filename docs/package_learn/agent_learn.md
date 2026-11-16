# 学习笔记：AI 包按工程层次学习

> 本章是学习路径和选型建议，**不是这些包均已安装、均已接入或已完成生产级验证**。
> 本仓库实际使用 `openai-agents==0.24.0`，并保留原有 LangGraph/LangChain
> 兼容工作流。新 SDK Agent 入口不自动包含 Weaviate 检索、MongoDB、pymongo、
> LiteLLM 模型替代通道、Langfuse 或第三方评测平台。
>
> 以下出现“已有”时，指的是可导入的 client 包，不自动证明服务端已配置。
> 完整角色和 Agent/Runner 适配见 [Agent Domain 布局](../architecture/AGENT_DOMAIN_LAYOUT.md)，
> 安装版本见 [文档索引](../INDEX.md)。

AI 包现在不是“学越多越好”，而是按层学。给你一张“值得学 + 了解即可”的清单，按工程分层排，不堆名词。

一、Agent 编排框架（选 2 个深入，别全学）

包 定位 学不学

openai-agents OpenAI 原生、轻量、handoff/guardrail ✅ 必学（你已在用）

langgraph 状态图、断点恢复、人工审核 ✅ 必学（复杂流程）

langchain 组件库（retriever/prompt/tool） ✅ 会查文档就行，不必深抠

pydantic-ai 类型安全 Agent，Pydantic 原生 ⭐ 推荐学，写生产 API 很舒服

llama-index RAG 检索优先，数据连接器多 ✅ RAG 场景必看

crewai 角色制多 Agent 了解，做 demo 快

haystack 企业级 RAG pipeline 了解

autogen/semantic-kernel 微软系 了解，不新起

结论：openai-agents + langgraph + pydantic-ai 三选二组合最实用。

二、模型网关与接入（必学）

• litellm（本仓库已装 1.109.1）：可选的多模型路由层；具体 Provider、fallback、限流和成本统计需单独配置与核查，不等同于默认生产可用

- openai / anthropic / google-genai SDK：直接调也行
• portkey / helicone：网关层缓存+观测（可选）

模型接入应保留单一、可控的调用出口，而不是无条件加厂商转发。
本项目保留原预算/审计及统一 LLM 调用路径，再由 SDK Model 接口桥接既有决策。
LiteLLM 是可选适配层，安装它不代表自动替换了项目的模型通道。

三、RAG / 向量 / 记忆（核心层）

向量库

• weaviate-client（已安装）：可作为向量检索 client；是否需要及其检索质量须基于实际 schema、数据与服务端验证，不能由安装包推断

• qdrant-client ⭐ 轻量高性能，推荐备选

• pgvector：已有 Postgres 就直接用

• chroma：本地原型

• milvus：亿级再考虑，运维重

检索增强

• llama-index：切分/retriever/rerank

- sentence-transformers / bge-m3：embedding 模型
• ragas / deepeval：RAG 质量评测（后面讲）

记忆

• mem0 / letta / zep：长期记忆框架（了解）

- 短期记忆：上下文压缩+checkpoint，用 langgraph 自带就行

四、工具协议（2026 必须懂概念）

• MCP（Model Context Protocol） ✅ 工具/数据源统一协议，fastmcp 可写 server

• mcp 官方 SDK：让工具跨框架复用（agent 调同一个 MCP server）

大白话：MCP 是“Agent 的 USB-C”，不用每个框架写一遍工具适配。

五、可观测 / 追踪（生产必学）

- opentelemetry ✅ 你已有，标准埋点
• langfuse ⭐ 开源自部署，trace+成本+prompt 管理

• arize-phoenix：debug agent 轨迹强

- sentry-sdk ✅ 异常兜底
• logfire（pydantic 家）：OTel 原生，类型安全项目友好

框架会换，trace+eval 层是长期资产。

六、评测（最容易被忽略，但最值钱）

- deepeval ✅ pytest 风格，幻觉/相关度/忠实度
• ragas ✅ RAG 专用指标

• promptfoo：红队/回归测试，CI 友好

• llm-as-judge：用强模型当评委，但要校准 rubrics

- truLens：反馈函数式评估

改一次 prompt 不跑 eval = 盲飞。

七、安全 / 护栏（Guardrail）

• pydantic ✅ 输出结构校验（最基础护栏）

• guardrails-ai：输出校验+结构化生成

• nemo-guardrails：NVIDIA，对话/主题/注入防护

• lakera-guard：防 prompt injection

- presidio：PII 脱敏

最小闭环：输入过滤 + pydantic 输出校验 + 敏感工具人工确认

八、文档解析 / 多模态

• unstructured / docling：PDF/Word 解析

- pdfminer.six（你已有）
• pillow / opencv：图片预处理

• whisper / faster-whisper：语音转写

• vllm / ollama：本地模型推理（可选）

九、训练/微调（按需，不优先）

• unsloth ⭐ 微调快、省显存

• trl / peft：LoRA 微调

• datasets / tokenizers：数据准备

- 顺序：先 prompt+RAG 打到瓶颈，再考虑微调

十、学习优先级路线（给你排好）

阶段 1：先懂原理（不碰重框架）

• 手写 100 行 ReAct loop（模型+工具+循环）

• 搞懂：token、context、tool call、handoff、guardrail

阶段 2：搭能跑的

• openai-agents 单 agent

• 按实际项目接口与预算，有选择地接 LiteLLM / Weaviate；注释状态的 pymongo 不等于已启用数据库

- pydantic 做结构化输出

阶段 3：生产化

• langgraph 管流程

• otel + langfuse 埋点

• deepeval/ragas 写回归测试

• guardrail 接输入/输出

阶段 4：进阶

• MCP 写工具

• pydantic-ai 类型安全 agent

• 长期记忆（mem0/letta）

十一、不用学/别早碰

• AutoGen 新项目别起

• 各种“低代码 Agent 平台”（Dify/n8n）先看懂概念，不急上手

• 向量库别一上来选 Milvus

• 别追新框架，框架半衰期很短，eval+trace+tool 设计才保值

十二、一句话记牢

学 AI 工程化顺序：

先写裸 Agent 循环 → 再学 agents/langgraph → 再补 RAG/观测/评测/护栏

框架是壳，真正值钱的是：

工具边界设计 + 评估集 + trace + 成本控制

本仓库的可执行角色入口见 [Agent Domain 布局](../architecture/AGENT_DOMAIN_LAYOUT.md)，其余选型建议只有在明确接入和验证后才是项目能力。
