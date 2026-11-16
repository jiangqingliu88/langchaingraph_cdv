# 学习笔记：LangChain 与 Agents SDK 的原子性区别

> 以下为理解框架抽象的入门比喻，不代表可以省略工程治理。当前仓库
> `openai-agents==0.24.0` 是可创建的 SDK 运行时，旧 `specialists/` 和 LangGraph
> 阶段实施仍作为兼容入口并存。真正的当前组合与用量以
> [Agent Domain 布局](../architecture/AGENT_DOMAIN_LAYOUT.md) 为准。
> 模型 API 受配置与连接条件影响，工具需要明确定义，候选结论仍需要 SourceAnchor、
> Engine 或人工复核。

你问的“原子性区别”，我翻译成大白话就是：
这俩框架里，最小的“积木”分别是什么？谁更底层、谁更封装？

一、先给结论（一句人话版）

• LangChain 的原子单位 = Runnable（可运行组件）

  → 把“模型/工具/提示词/检索器”当成可拼接的零件
• OpenAI Agents 的原子单位 = Agent（会调工具的模型循环）

  → 把“一个带指令+工具+护栏的模型循环”当成最小智能体

一个在拼“零件”，一个在拼“演员”。

二、原子抽象对比

维度 LangChain openai-agents

最小原子 Runnable（LCEL 里一切皆 Runnable） Agent 对象

原子里装啥 prompt + model + output_parser + retriever instructions + model + tools + guardrails

控制流谁写 你用 \| 和图拼出来 模型在 Runner.run() 里自己循环

怎么调工具 Tool 是 Runnable 的一种 Tool 是 Agent 的能力，模型决定调不调

多 agent 怎么来 上层用 LangGraph 画节点 原生 handoff 把控制权交给另一个 Agent

状态 Runnable 无状态，状态靠外层传 Run 内有 context / session

耦合度 模型无关（OpenAI/Claude/本地都行） OpenAI 优先（可接 LiteLLM）

三、用代码看“原子”长啥样

LangChain 原子：Runnable

from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI

model = ChatOpenAI()
format_prompt = RunnableLambda(lambda x: f"回答：{x}")
chain = format_prompt | model        # 两个 Runnable 拼起来

chain.invoke("你好")

原子是“一段可执行的管道节点”，模型只是其中一个节点。

openai-agents 原子：Agent

from agents import Agent, Runner, function_tool

@function_tool
def search(q: str) -> str:
    return "查到的结果"

agent = Agent(
    name="助手",
    instructions="先检索再回答",
    tools=[search],
)

Runner.run_sync(agent, "杭州天气咋样")

原子是“一个会自己思考、自己调 tool 的循环体”，你不再拼管道。

四、本质区别（底层哲学）

LangChain：组合优先

• 哲学：“LLM 应用 = 组件组合”

• 原子是被动零件

• 你决定流程：prompt | model | parser

- 模型只是被调用的一个算子
• 优点：换模型/换检索器/换 parser 超灵活

• 缺点：抽象层多，流程复杂时像拼乐高拼到头晕

openai-agents：循环优先

• 哲学：“LLM 应用 = 一个会决策的 Agent”

- 原子是主动执行体
• 模型自己决定：调哪个 tool、转给谁、啥时候停

• Agent/Runner 之外，还需要配置模型、工具定义与参数边界、错误处理和审批；不能只靠两行代码宣称 Agent 已经工作。

• 优点：代码少、贴近“智能体”直觉

• 缺点：流程黑盒（模型驱动），复杂分支要外层再套图

五、原子性差异一句话总结

LangChain 原子 = 函数级零件（你控流程）

openai-agents 原子 = 智能体级循环（模型控流程）

再缩一层：
• LangChain：“我搭管道，模型是管道里的水”

• openai-agents：“我雇一个人，他自己决定怎么干活”

六、和你之前架构怎么对上

• 简单 RAG / 多模型切换 / 要 retriever 生态 → LangChain 当零件库

- 多 agent 分诊 / 转专家 / 要 guardrail → openai-agents 当执行体
• 长流程、要断点恢复、人工审核 → LangGraph 管图，里面节点调 agents

LangChain  : 零件（prompt/model/tool/retriever）
openai-agents: 演员（Agent + handoff）
LangGraph   : 剧本（谁先谁后、能不能回退）


七、防懵口诀

拼零件用 LangChain

雇人干活用 openai-agents

画流程图用 LangGraph

三者不打架，是三层

当前项目的实际入口、独立角色与兼容边界见 [Agent Domain 布局](../architecture/AGENT_DOMAIN_LAYOUT.md) 和 [文档总索引](../INDEX.md)。
