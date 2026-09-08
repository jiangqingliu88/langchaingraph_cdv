好的，我帮你把你的项目目标拔高，写成一份可以直接放在 GitHub 或内部文档里的 **“项目愿景/目标”** 文档。

---

# SignOffAI（功能签核）——项目愿景与目标

> **开发准则**：本项目是个人级CLI工具，**禁止Web前端开发**。所有功能通过命令行接口（`python -m src.cli.commands`）交付，不开发、不维护、不优化任何 Web UI / Dashboard / SSE 推送 / 前端页面。精力集中在 CLI 体验、Agent 管道稳定性、Tool 工具链集成三件事上。

## 一、我们解决什么问题

IC 验证是芯片设计流程中时间最长、成本最高、最依赖经验的环节。当前行业普遍面临以下挑战：

**1. 验证流程是“手工作坊”，不是“工程平台”**
- 每个项目重复构建验证环境，缺乏标准化和可复用性
- 验证计划、覆盖率、回归、调试、签核各环节之间数据断裂
- 验证结果难以追溯、审计和复现

**2. 验证决策依赖“个人经验”，而不是“系统证据”**
- 签核依赖验证工程师的个人判断和口头沟通
- 缺乏系统化的证据链来支持签核决策
- 项目复盘时，无法回溯“为什么当时签了”

**3. AI 工具在 IC 验证领域缺乏“工程化落地”**
- 通用 AI 编程工具（Claude、Copilot、Cursor）无法真正集成 EDA 工具链
- 长链路可靠性不足，难以交付可信任的验证结果
- 缺少安全、审计、治理能力，难以在个人环境中落地

SignOffAI 的目标正是解决这些问题。

---

## 二、我们的长期目标

> **SignOffAI 的目标是：让 IC 验证从“手工作坊”演变为“可复现、可审计、可治理的工程平台”，让每一次签核决策都有完整的证据链支撑。**

这不是一个“辅助写代码”的 AI 工具，而是一个 **“验证流程平台”**——它把验证团队的核心工作流（规格分析 → UVM 生成 → 测试生成 → 回归 → 覆盖率分析 → 签核）变为 **可编程、可治理、可审计的工程系统**。

---

## 三、我们的核心价值主张

**我们承诺：每一位验证工程师和验证经理都能通过 SignOffAI 获得：**

| 价值 | 具体含义 |
|------|----------|
| **可复现** | 任意一步 Agent 动作都可以通过 `vagent dump` 命令，用同一份配置和脚本复现 |
| **可审计** | 每个阶段都输出 artifact manifest，包含 hash、输入、输出、执行日志 |
| **可治理** | 项目隔离、权限控制、Token 预算、人工审批机制 |
| **可交付** | 验证流程的最终产出不是“代码”，而是 **“签核证据包”**——一份包含所有证据、日志、决策依据的可审计文档 |

---

## 四、为什么我们能做到

通用 AI 编程工具做不到的事情，SignOffAI 做到了：

| 能力 | SignOffAI | Claude / Copilot |
|------|-----------|------------------|
| **集成真实 EDA 工具链** | ✅ 每个 Tool 都有独立脚本 + schema | ❌ 只能调 bash，无法管理 VCS/Questa 的复杂环境 |
| **输出可复现的 artifact** | ✅ 每步输出 manifest + hash | ❌ 只输出文本，无法复现 |
| **支持签核决策** | ✅ 自动生成签核证据包 | ❌ 只能辅助写代码 |
| **支持个人级治理** | ✅ 项目隔离、审计日志、人工审批 | ❌ 无 |
| **领域语义** | ✅ 理解 UVM、覆盖率、回归、VCS 命令行 | ❌ 通用模型，缺乏领域深度 |

---

## 五、我们的差异化壁垒

SignOffAI 的壁垒不在于“AI 有多聪明”，而在于：

**1. 领域知识的工程化**
- 我们不是把 LLM 当“万能生成器”用，而是把它嵌入到 **UVM 骨架 + Jinja2 渲染 + 契约校验** 的工程流程中
- LLM 只做“完形填空”，不决定整体结构

**2. 工具链的深度集成**
- 不是“调一下 VCS”，而是把 VCS 封装成一个 **独立可复现的 Tool**
- 每个 Tool 都有 schema 契约、输入输出验证、风险分级

**3. 证据链的系统化**
- 每个阶段都输出 artifact manifest，构成一条从规格到签核的完整证据链
- 证据链本身是可审计、可追溯的

**4. 个人级治理架构**
- 项目隔离、RBAC、审计日志、Token 预算、人工审批
- 这是个人场景可以落地的前提

---

## 六、我们的产品路线图

| 阶段 | 目标 | 预计时间 |
|------|------|----------|
| **Phase 1: 可复现的验证工具链** | 每个 Tool 独立可执行，支持 `vagent dump` 复现 | 2026 Q3 |
| **Phase 2: 证据驱动平台** | 每个阶段输出 artifact manifest，支持自动签核证据包生成 | 2026 Q4 |
| **Phase 3: 个人级治理** | 项目隔离、审计日志、Token 预算、人工审批 | 2027 Q1 |
| **Phase 4: 签核决策引擎** | AI 辅助签核决策、风险评分、gap 分析 | 2027 Q2 |

---

## 七、我们的成功标准

- **工程师可以**：在任何时间、任何机器上，用 `vagent dump` 复现任意一步 Agent 动作
- **验证经理可以**：在 SignOffAI 平台上完成一次完整的签核决策，并获得一份可审计的证据包
- **个人可以**：在多项目、多团队环境中部署 SignOffAI，并确保所有验证活动可追溯、可治理
- **行业可以**：将 SignOffAI 作为 IC 验证 AI 化的参考范式，推动整个行业从“手工作坊”向“工程平台”演进

---

## 八、我们最终希望实现什么

> **SignOffAI 不是“一个 AI 工具”，它是 IC 验证行业向“工程平台化”演进的一个标志性产品。**

我们相信，IC 验证的未来不是“每个人都有一个 AI 助手”，而是 **“每个验证团队都有一个统一的、可治理的、可追溯的验证平台”**。

SignOffAI 就是那个平台。

---

**如果你愿意，我可以帮你把这版文档变成你 GitHub 的 `README.md`、项目官网的 `About` 页面、或者内部立项的 `Vision Document`。**
## 九、竞品分析

正面硬刚西门子/Synopsys/Cadence 没有领先机会；但在「可复现·可审计·可治理 + 个人/小团队 + 
  开源工具链」这个楔子上，有真实且可防守的领先机会。 下面分三层说清。
   
  一、坏消息：巨头已经在你这条赛道上，且比你深
     
  2026 年三大 EDA 巨头已全部下场做「agentic 验证」，方向和你几乎一致：

  - 西门子 Questa One Agentic Toolkit（2026/02）：5 个专用 Agent（RTL Code / Lint / CDC / Verification Plan / Debug），明确用 MCP + 
  goal-driven agents + context-aware——和你 tool_protocol.py / jsonrpc.py 的 ITool/MCP + 决策层是同一套思路。2026/07 又与 NVIDIA
  推「自校验」工作流，把 AI 决策回打到 Calibre/Questa 做确定性签核——这正是你的「铁律一：EDA 是唯一真理」。
  - Cadence ChipStack AI Super Agent（2026/02）：自主生成 RTL + testbench + 验证计划，Tenstorrent 实测验证时间 4x。
  - Synopsys AgentEngineer + 自主验证 Agent（DAC 2026/07）：编排整个验证周期（测试计划→覆盖率收敛→调试），号称 50x 加速、覆盖率 
  +20%，L2→L5 自主度路线图。

  关键点：这三家拥有仿真器本体、license、波形/ucdb/形式验证引擎、以及 Altera/NVIDIA/Qualcomm/Tenstorrent 级的数据与算力，78%
  市场份额。你现在是在他们的工具外面包一层 agent 壳，而他们正在把同样的壳原生做进工具里。这个位面没有领先机会，追就是陪跑。

  二、好消息：学术界刚证明「你押的方向是对的」

  2026 年有两篇论文直接命中你架构的核心判断：

  - Agentic AI for Chip Design Verification: Failure Modes, Metrics, and Coverage Closure
  (https://ieeexplore.ieee.org/document/11534779/authors#authors) 的结论是 LLM 对验证「Last
  Mile（覆盖率收敛）」根本性不足（时序推理、状态空间、开环幻觉），必须转向 Agentic AI + 递归推理 + 工具执行——这正是你 closed_loop.py +
  decision_engine.py 在做的。
  - Agentic AI-based Coverage Closure for Formal Verification
  (https://arxivlens.com/paperview/details/agentic-ai-based-coverage-closure-for-formal-verification-1974-b745cf2e)（Infineon）用
  CoverageHoleAnalyzer + SVAPropertyGenerator 做迭代收敛，只提升 10–20%——说明「覆盖率闭环」天花板不高，纯靠 AI 收敛撑不起护城河。

  这反过来印证了：你真正的差异化不是"AI 更聪明"（巨头和学术都证明这不够），而是你 CLAUDE.md
  里反复强调、但巨头没说透的三件事——可复现、可审计、可治理。

  三、三个真实可领先的楔子（按可行性排序）

  楔子: ① 签核证据链 + 治理
  为什么巨头不碰: 巨头讲"50x 快"，不讲"可证明、可审计、可追责"；行业签核回溯至今靠人工
  你的现成优势: file_audit.py（git
    diff+理由+哈希链）、evidence.py（五层领域证据）、manifest.py（证据包）、quality_guard.py（三层兜底+人工升级）
  领先条件: 这是唯一能和大厂差异化且大厂短期不会认真做的点，建议全力押注
  ────────────────────────────────────────
  楔子: ② 个人/小团队 + 开源工具链
  为什么巨头不碰: 巨头只服务 Altera/NVIDIA 级企业，个人、初创、教学是被忽略市场
  你的现成优势: 你「个人级 CLI」定位 + Verilator/open-source UVM 可跑
  领先条件: 别追 Questa 深度集成，改打「无需 license 的 agentic 验证」
  ────────────────────────────────────────
  楔子: ③ 工具无关的开源 agentic 层
  为什么巨头不碰: 巨头各自锁死自家工具
  你的现成优势: 你的 ToolHub/ITool 协议天然可接任意后端
  领先条件: 开源社区 digital-chip-design-agents、UCAgent 已证明有需求，但都没有证据链+治理

  我的建议（一句话）

  放弃"和巨头拼覆盖率收敛速度"的念头，把「签核证据链 + 个人级治理」做成第一定位，开源工具链做第二定位。 这不是退而求其次——学术已经证明纯
  LLM 收敛是红海且天花板低，而「可证明的签核」恰恰是巨头这套 agentic 叙事里唯一还没被占领、且和你的架构天然重合的高地。

  领先的窗口不取决于你代码写多快，而取决于你能否在巨头把「审计/治理」也收编进自家工具之前，把「可复现·可审计·可治理的签核」做成这个细分领
  域的默认答案。

  ---
  Sources:
  - Siemens Questa One Agentic Toolkit (https://www.embedded.com/siemens-agentic-toolkit-automates-chip-verification-workflows)
  - Siemens Fuse EDA AI Agent (GTC 2026)
  (https://agentmarketcap.ai/blog/2026/06/27/siemens-fuse-eda-ai-agent-industrial-hardware-design-automation)
  - Synopsys 自主芯片代理 50x 验证
  (https://www.edgen.tech/zh-tw/news/post/synopsys-launches-autonomous-chip-agents-with-50x-faster-verification)
  - Agentic AI for Chip Design Verification: Failure Modes, Metrics, Coverage Closure (IEEE)
  (https://ieeexplore.ieee.org/document/11534779/authors#authors)
  - Agentic AI Coverage Closure for Formal Verification (Infineon)
  (https://arxivlens.com/paperview/details/agentic-ai-based-coverage-closure-for-formal-verification-1974-b745cf2e)
  - digital-chip-design-agents (开源) (https://github.com/hdl-tools/digital-chip-design-agents)
  - UCAgent (开源) (https://github.com/XS-MLVP/UCAgent)