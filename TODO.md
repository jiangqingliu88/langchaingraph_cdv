● src/layers/（五层）和 src/agents/（七 Agent）是两种不同的切分维度，不是并列关系，而是**「平台」与「执行者」**的关系。
     
  一句话关系
     
  ▎ layers 是「横切的能力平台」（引擎），agents 是「纵向的领域角色」（驾驶员）。

  横切 —— layers 五层能力（所有 Agent 共享的引擎）
    L5 进化（蒸馏）      ────────────────────────────────
    L4 记忆（经验库）    ────────────────────────────────
    L3 决策（决策引擎）  ────────────────────────────────
    L2 调度（编排+通信） ────────────────────────────────
    L1 基础设施（EDA）   ────────────────────────────────
         │      │      │      │      │      │      │
      design model verify  ops  coverage debug audit   ← 纵向七 Agent（领域角色）

  两者的调用方向（从实际 import 看到的）

  ① L2 编排 agents（layers → agents）：

  # src/layers/l2_orchestration/execution.py
  from src.agents.design import DesignAgent
  from src.agents.model import ModelAgent
  ...  # 七 Agent 全部被 L2 的 execution.py import 并编排成闭环

  ② agents 依赖 layers 的能力（agents → layers）：

  # agents 里实际 import 的 layers：
  from src.layers.l2_orchestration.agents.base import BaseAgent   # 继承 L2 基类
  from src.layers.l2_orchestration.agents.registry import register_agent  # L2 注册
  from src.layers.l1_infrastructure.output_config import make_output_root  # 调 L1
  from src.layers.l1_infrastructure.coverage_backend import ...  # 调 L1
  from src.layers.l2_orchestration.communication.tool_subprocess import ...  # 走 MCP
  from src.layers.l4_memory.debug_experience import ...  # 读写 L4 经验
  from src.layers.l5_evolution.growth import ...  # 受益 L5 蒸馏

  具体映射：每个 Agent 用哪些层

  ┌──────────┬───────────────────────────────────┬──────────────────────────────────┐
  │  Agent   │             横跨的层              │               说明               │
  ├──────────┼───────────────────────────────────┼──────────────────────────────────┤
  │ design   │ L1(output_config) + L2(base)      │ 继承 BaseAgent，用输出目录       │
  ├──────────┼───────────────────────────────────┼──────────────────────────────────┤
  │ ops      │ L1 + L2(tool_subprocess)          │ 通过 MCP 调 L1 的回归            │
  ├──────────┼───────────────────────────────────┼──────────────────────────────────┤
  │ coverage │ L1(coverage_backend) + L2 + L4    │ 收集覆盖率（L1）+ 归因校准（L4） │
  ├──────────┼───────────────────────────────────┼──────────────────────────────────┤
  │ debug    │ L4(debug_experience) + L5(growth) │ 读写调试经验 + 受益蒸馏          │
  ├──────────┼───────────────────────────────────┼──────────────────────────────────┤
  │ verify   │ L2(policy_pack)                   │ 按策略包加载领域知识             │
  └──────────┴───────────────────────────────────┴──────────────────────────────────┘

  为什么这样分（设计意图）

  ┌────────────┬──────────────────────────────────────────────┬────────────────────────────────────────────────────────┐
  │    维度    │                layers（五层）                │                    agents（七角色）                    │
  ├────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
  │ 切分方向   │ 横切（能力/引擎）                            │ 纵向（领域/角色）                                      │
  ├────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
  │ 回答的问题 │ 「怎么做」——基础设施、调度、决策、记忆、进化 │ 「谁来做」——设计、模型、验证、运维、覆盖率、调试、审计 │
  ├────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
  │ 稳定性     │ 与 DUT 类型无关，稳定                        │ 与验证领域相关，可扩展                                 │
  ├────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
  │ 复用性     │ 跨项目复用（引擎）                           │ 每个验证项目都需要这七个角色                           │
  └────────────┴──────────────────────────────────────────────┴────────────────────────────────────────────────────────┘

  一句话总结

  ▎ layers 是「发动机、变速箱、导航、油箱」这套引擎，agents 是「设计工程师、验证工程师、调试工程师」这七位驾驶员——引擎（layers）是
  ▎ 横切的、可复用的，驾驶员（agents）是纵向的、干具体活的；L2 的 execution.py
  ▎ 负责「安排七个驾驶员按闭环流程干活」，每个驾驶员干到哪一步就调用对应层的引擎能力。

  这个结构的好处是：如果要加「性能 Agent」或换「VCS 后端」，只需要在 agents 加一个角色、或在 L1
  加一个后端，不用动五层引擎——职责分离清晰。




$env:ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
$env:ANTHROPIC_AUTH_TOKEN="sk-你的DeepSeekKey"
$env:ANTHROPIC_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
$env:CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"
$env:CLAUDE_CODE_EFFORT_LEVEL="max"
claude