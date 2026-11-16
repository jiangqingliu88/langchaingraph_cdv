# Agent Domain 与 ten-role ReAct layout

## 1. 范围与保持不变的约束

本次按用户给的十个角色组织 Agent，使用已安装的 **openai-agents 0.24.0**。每个角色都有独立目录、Agent 类、契约和受限工具集合；真正的循环为 SDK 的 `Agent -> Runner -> tools/observe -> subsequent model turns`，而不是 `generate -> store`。

五个 Domain 是 `src/agent_plane/` 内部的**功能分组**，不是新增架构职责 Plane。原八个 `src/*_plane` 与 Workbench Interfaces 的逻辑关系不变，既有 specialist 实现、Supervisor 子图及团队协作契约也未因新目录整体迁移。

**真实 SDK 与适配而不是“每类写一遍模型循环”**：
- [SDK-facing core](../../src/agent_plane/reaction/core.py)：直接构造 `agents.Agent`，再交给 `Runner.run`。
- [Model bridge](../../src/agent_plane/reaction/sdk_model.py)：保留原项目 LLM 出口、JSON 决策校验和预算，把旧决策映射成真正的 `ModelResponse`/`ResponseFunctionToolCall`。
- [Tool bridge](../../src/agent_plane/reaction/sdk_tools.py)：把 LangChain/旧工具的 `[name, description]` 转成真正的 SDK FunctionTool，不复制方言或重复包装已转换的 SDK Tool。
- [角色注册](../../src/agent_plane/reaction/registry.py)：十个角色类及其兼容别名入口；在 [编排卡片注册](../../src/orchestration_plane/registry.py) 独立暴露 `SPECIALIST_CARDS`。

### 循环边界

- `Runner.run(..., max_turns=role.max_steps)` 提供真正的迭代能力与有限步数。
- 最终的 tool 决策只有在注册工具表中的名字才能变成 `ResponseFunctionToolCall`。
- 仅靠模型自己声明“已经读过/运行过”是不够的：正常候选结论需要真实工具输出；`final` 前没有工具输出、或工具返回 NOT_RUN/INCOMPLETE/错误，均限制为 INCOMPLETE。
- 原始 source anchor、文件路径、line range 与哈希均来自实际读取，不自动扩大到磁盘其他区域。
- 已注册不可达/不可用后端可以出现在责任说明里，但入参不会因此变成执行结果。

## 2. 实际目录

```text
src/agent_plane/
├── reaction/
│   ├── core.py                 # SDK Agent / Runner 面向各角色的统一入口
│   ├── sdk_model.py            # ProjectBudgetedModel → SDK Model/Response
│   ├── sdk_tools.py            # Legacy/LangChain tool → SDK FunctionTool
│   ├── adapters.py             # 旧生成器的参数白名单与显式输出约束
│   ├── tools.py                # 受限文本读取与目录范围
│   └── registry.py             # 十个角色注册与旧 alias
├── design_understanding/
│   └── mental_model_agent/     # MentalModelAgent + existing Mental IR adapter
├── design_verification/
│   └── simulation_agent/       # SimulationAgent (unit-testing)
├── design_signoff/
│   └── lint_autofix/           # LintAutoFixAgent
├── design_generation/
│   ├── rtl_upgrade_agent/      # RTLUpgradeAgent
│   └── rtl_early_estimation_agent/ # RTLEarlyEstimationAgent
└── verification/
    ├── formal_agent/
    ├── functional_coverage_agent/
    ├── test_plan_agent/
    ├── uvm_coding_agent/
    └── dv_debug_agent/
```

每个角色目录都至少有 `agent.py` 与 `__init__.py`。专用工具需要额外文件时单独放 `tools.py`，而不是把所有生成器复制进这些新目录。

**目录架构注册表**：五个 Domain 与 ChipStack R-020 固定产物子目录的映射在
[`src/agent_plane/domains.py`](../../src/agent_plane/domains.py)，由
[`project_layout.py`](../../src/runtime_plane/core/project_layout.py) 的
`AGENT_ARTIFACT_DIRS` 约束。`ReActAgent.artifact_root` 直接派生自它；GUI 的
「工程目录」页与 `vagent workspace agents` 都从这里取表。详见
[CHIPSTACK_PROJECT_LAYOUT.md](CHIPSTACK_PROJECT_LAYOUT.md)。

原 `specialists/` 已退休：生成器/工具/子图已迁入对应 Domain（例如
`verification/formal_agent/main.py`、`design_generation/rtl_upgrade_agent/design_tools.py`），
九个对话入口迁到 `src/workbench/modes/chats/`。完整映射见
[SPECIALIST_AGENTS.md](SPECIALIST_AGENTS.md)。

## 3. 十个角色的真实能力与边界

| Domain / Agent | 新入口 | 已接上的实际工具 | 尚未声称完成的能力 |
|---|---|---|---|
| Design Understanding — Mental Model Agent | `design_understanding/mental_model_agent` | 读取来源/结构；复用旧 `generate_mental_ir`；MentalIR 类型验证与容器内的 storage | RTL/Spec 全芯片自动理解、绝对一致性认证 |
| Design Verification — Unit Testing (simulation-agent) | `design_verification/simulation_agent` | 复用纯 SV `generate_tb` 以产生 testbench 文本候选 | `run_unit_test`：真实编译/仿真本阶段不启用 |
| Design Signoff — Lint AutoFix | `design_signoff/lint_autofix` | 受限源读取与模型驱动的观察循环 | Jasper SuperLint、修复代码落盘和违规消除验真 |
| Design Generation — RTL Upgrade | `design_generation/rtl_upgrade_agent` | 复用既有限域 `BuildDesignTools` 的 `read_file/list_rtl/check_rtl` | 按未经确认的 ECN/需求修改生产 RTL；写入工具未默认放行 |
| Design Generation — RTL Early Estimation | `design_generation/rtl_early_estimation_agent` | 受限源读取与明确的 PPA 未接入状态 | Joules PPA 分析、PPA 数值与工艺角实验 |
| Verification — Formal Agent | `verification/formal_agent` | 复用 `generate_formal_plan`；FormalPlan 原模型验证与容器内 storage | Jasper/formal 引擎、actual proof、coverage proof；engine.ran 保持 false |
| Verification — Functional Coverage Agent | `verification/functional_coverage_agent` | `ReadCoverageTool`、`ListCoverageFilesTool`，读取实际报告 | 不通过无证明的形式剔除、闭合率自动提升或可达性证明 |
| Verification — Test Plan Agent | `verification/test_plan_agent` | 受限 SourceAnchor/文本读取及“必须有 spec”的角色契约 | 实际 TP 生成 API 尚需接入现有唯一 VPlan 编译链；NOT_RUN 而非用其它角色冒充 TP |
| Verification — UVM Coding Agent | `verification/uvm_coding_agent` | 复用 `find_spec_yaml`、`jinja_render`、`check_static`、`read_file`、`write_file` | 未配置 output_root 则工具 NOT_RUN；写入及渲染需要 SDK 审批；编译/EDA 验证不是自动结论 |
| Verification — DV Debug Agent | `verification/dv_debug_agent` | 旧 DebugTools 中的 `collect_sim_log`、`collect_compile_log`、`fingerprint_error` | 任意 xcelium failure DB 接入、自动 RC 修复与自动签核 |

其中 **FormalPlan/SVA/Testbench/mental IR 是生成候选物**；它们存在并不自动获得验证 PASS、模型正确性或可综合保证。必须看原 Engine 的绑定、检查与真正的执行数据。

## 4. ReAct 与模型调用的连接

当前两半协同保留：

1. **选型与决定谁来生成**——原项目的预算/缓存/审计中的统一 LLM 调用继续选择受限工具；旧 `tool/final/needs_input` 决策被翻译为 SDK 所需的类型。
2. **实际循环与工具生命周期**——OpenAI Agents 的 `Runner` 决定如何进行 FunctionTool、工具观察和下一轮的推理；SDK 处理工具调用和文本输出。

`ProjectBudgetedModel` 在最终消息时复核：有 sdk tool-output 才考虑 CANDIDATE，而状态为 NOT_RUN/INCOMPLETE/明显错误的结果不能触发正常的最终候选回复。`PENDING_HUMAN` 保留给 SDK 的审批中断；缺规格或缺执行后端保留 INCOMPLETE。

此适配目前不另行宣称原生流式 token 响应、structured-output 或 handoff 支持。相关分支会以 INCOMPLETE 返回，而不假装支持。

## 5. 权限与写入

- [读取器](../../src/agent_plane/reaction/tools.py) 越过 workspace 拒绝，限制公开项目目录与文本类型；`.git`、私有会话与 Python 虚拟环境文件不能被当成可读源文档。
- [生成器适配](../../src/agent_plane/reaction/adapters.py) 用真实函数签名过滤 kwargs；缺 `output_dir` 时不允许借用相对路径将产物写去任意目录。
- workspace/output_root 边界分开处理，构造时明确指定输出工作区，运行时不能通过 prompt 提升权限。
- 支持存储的角色将写工具标记为 `requires_approval`，接入 SDK 的 `needs_approval`，使写入可被审批暂停而不是自动改写生产代码。
- 尚缺 actual backend 的编外 capability 以 NOT_RUN 明文返回；不生成虚假的 PPA 数值、Jasper proof 或 SuperLint 报告。

## 6. 入口与兼容

```python
from agents import Runner
from src.agent_plane.reaction.registry import create_agent

role = create_agent("formal_agent", workspace_root=".")
assert role.workflow.name == "Formal Agent"
assert type(role.workflow.model).__name__ == "ProjectBudgetedModel"

# role.workflow 是真正的 agents.Agent，可以直接交给 SDK：
# result = Runner.run_sync(role.workflow, "读取已给定的规格并生成 FormalPlan 候选", max_turns=6)
```

也可使用 `from src.agent_plane import create_react_agent, react_agent_metadata`。工厂入口不会自动启动 Provider、EBUS 或 EDA。只有真正执行 `ainvoke/invoke/run_sync` 时，才会进入模型和工具调用；缺模型密钥的情况沿用原项目错误/INCOMPLETE 边界。

`card("formal")`、`card("mental")`、`card("unit_test")` 等旧查询继续使用对应 canonical role；flow controllers `supervisor/design/verify/debug/coverage` 与六类协作 contract 也没有被并发改名。不要从原始卡的个数推导新指定 Agent 的总数：注册中维护了执行管理卡、兼容卡以及十个新角色卡。

## 7. 此阶段验证限制

- 十个 Domain Agent 已完成独立目录、类与 SDK Agent 构造核对。
- 已验证 ModelResponse 类型与 FunctionTool 参数封装，以及角色卡片注册和 alias。
- **不运行 EDA，不跑仿真或全量测试**。本阶段不是“所有能力已被真实模型和真实硬件执行验证”的结论。
- 当前 SDK model adapter 的 Provider 真实连通与端到端工具循环，需要此后在有效模型配置下验收；静态构型验证不能替代这一轮运行验证。
- 本地 SDK 版本和 API 仅在 `openai-agents 0.24.0` 上核对；沿升级 SDK 时应重新检查 `Model.get_response` 的完整签名，而不是猜新版本参数。
