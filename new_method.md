我认为，SignOffAI 这套架构的方法学可以概括为：

# 规格驱动、模型驱动、证据驱动的 AI 验证工程方法学

英文可以称为：

Specification-Driven, Model-Based and Evidence-Driven AI Verification Methodology

它不是简单的 Multi-Agent 方法，也不是传统的 UVM 自动化生成方法，而是把芯片验证从需求分析到工程签核组织成一个可执行、可追溯、可复现的闭环。

我把它分成六个层次。

## 1. Specification-Driven：规格驱动

第一层：验证依据

所有验证活动都应该从 IP Specification 出发。

例如 AXI DMA：

- 支持哪些传输模式？
- 描述符格式是什么？
- 地址和长度有什么约束？
- 4KB 边界如何处理？
- Backpressure 下应该有什么行为？
- 错误发生后状态如何变化？

核心思想：

不是让 Agent 自由生成测试，而是让 Agent 根据规格中的约束生成验证活动。

规格是验证依据，不能让模型凭经验补充不存在的功能。

## 2. Model-Based：模型驱动

第二层：形式化表达

将自然语言规格转换成机器可以处理的中间模型。

例如：

```
IP Specification
       |
       v
Requirement Model
       |
       v
Feature Model
       |
       v
Verification Model
       |
       v
UVM IR
```

以 DMA 为例，可以抽象出：

- Transaction Model
- Descriptor Model
- Address Model
- Protocol Model
- State Model
- Coverage Model

这样 Agent 不需要每次直接从自然语言生成 SystemVerilog，而是先生成结构化模型，再由 Generator 生成验证代码。

这也是 UVM IR 的重要价值。

## 3. Agent-Orchestrated：智能体协同

第三层：任务执行

Agent 不应该只是多个聊天机器人，而应该是有明确职责的工程执行单元。

例如：

| Agent / Executor    | 责任      |
| ------------------- | ------- |
| Spec Agent          | 规格解析    |
| Planning Agent      | 验证计划    |
| UVM Generator       | 环境与测试生成 |
| Stimulus Agent      | 激励生成    |
| Simulation Executor | 仿真执行    |
| Debug Agent         | 失败分析    |
| Coverage Agent      | 覆盖率分析   |
| Decision Agent      | 验证结论评估  |

这里有一个关键原则：

Agent 负责推理和决策，Executor 负责确定性执行。

例如仿真不能依赖 Agent 自己声称成功，必须以仿真工具实际返回的退出状态、日志和产物为依据。

## 4. Closed-Loop Verification：闭环验证

第四层：核心方法

我认为这是 SignOffAI 最应该建立的核心方法学。

传统自动化流程通常是：

```
Generate → Compile → Simulate → Report
```

SignOffAI 应该发展为：

```
Spec
 |
 v
Verification Planning
 |
 v
UVM / Stimulus Generation
 |
 v
Simulation
 |
 v
Failure Analysis
 |
 v
Coverage Analysis
 |
 v
Coverage Gap Identification
 |
 v
Targeted Stimulus Generation
 |
 +---------> Simulation
 |
 v
Verification Decision
```

这意味着：

- 测试失败，进入 Debug 分析；
- Coverage 不足，进入定向激励生成；
- 发现需求遗漏，回到验证计划；
- 产生新的证据，再重新评估验证状态。

不是每个问题都重新运行整个流程，而是通过任务依赖和产物关系，执行必要的局部闭环。

## 5. Evidence-Driven：证据驱动

第五层：可信度

这一层是 SignOffAI 与普通 AI 代码生成工具的重要区别。

每一次执行都应该留下：

- 输入规格及版本；
- RTL 版本和 Hash；
- 生成的 UVM 代码；
- 工具版本和配置；
- Random Seed；
- 仿真日志；
- Coverage 数据；
- Bug 分析结果；
- Decision 结果。

通过 RunContext、ArtifactStore、EventStore、Provenance DAG 和 Evidence，把这些信息关联起来。

最终要求：

任何一个验证结论，都能找到对应的执行过程和原始证据。

例如：

```
Decision: CONDITIONAL
    |
    +-- Coverage Report
    |
    +-- Simulation Results
    |
    +-- Uncovered Requirements
    |
    +-- Exclusion Records
    |
    +-- Run Manifest
```

不能仅仅因为 Agent 判断 PASS，就认为 IP 验证通过。

## 6. Quality-Gated Signoff：质量门禁与签核

第六层：工程决策

最后一层是验证质量门禁。

例如：

| 检查项目                | 结果          |
| ------------------- | ----------- |
| Requirement Mapping | PASS        |
| UVM Compilation     | PASS        |
| Regression          | PASS        |
| Functional Coverage | CONDITIONAL |
| Bug Analysis        | PASS        |
| Evidence Integrity  | PASS        |

最终 Decision 可能是：

- PASS
- PASS_WITH_CAVEAT
- CONDITIONAL
- FAIL

这些状态必须由规则、实际结果和证据共同决定，而不是由 LLM 自由生成。

## 7. 六层方法学与 SignOffAI 当前架构的映射

## SignOffAI Methodology

Specification-Driven

Requirement / Feature / Verification Model

Model-Based

IR / UVM IR / StimulusPlan / Coverage Model

Agent-Orchestrated

LangGraph / Agent / Executor / ToolHub

Closed-Loop Verification

Simulation / Debug / Coverage Closure

Evidence-Driven

RunContext / ArtifactStore / Provenance / Evidence

Quality-Gated Signoff

Decision Evaluation / Verification Quality Gate

这六层是我对你现有架构的方法学归纳，不是说仓库已经存在一个正式命名的六层方法学模块。

## 8. 这套方法学与传统验证方法有什么区别？

| 对比               | 传统 UVM 验证   | SignOffAI 方法学                  |
| ---------------- | ----------- | ------------------------------ |
| 验证依据             | Spec + 人工分析 | Spec 驱动的结构化模型                  |
| 验证计划             | 人工制定        | Agent 辅助生成                     |
| 环境生成             | 人工编写为主      | IR 驱动生成                        |
| 激励               | 人工 + 随机约束   | 模型约束 + AI 定向生成                 |
| Debug            | 人工定位为主      | Agent 辅助分析                     |
| Coverage Closure | 人工迭代        | 分析、生成、仿真闭环                     |
| 执行管理             | 脚本和 EDA 工具  | Job Runtime + Executor         |
| 结果可信度            | 日志、报告、人工审查  | Provenance + Evidence + Replay |
| 签核               | 人工综合判断      | 质量门禁辅助决策                       |

需要强调：AI 不替代验证工程师，也不替代仿真器、形式验证工具或签核责任人。它改变的是工程活动的组织方式和自动化程度。

## 9. 我的一个关键建议

如果你要把 SignOffAI 发展成长期产品，我建议把方法学固定为：

SDM-EV Methodology

- S：Specification-Driven
- D：Data/Model-Driven
- M：Multi-Agent Orchestration
- E：Evidence-Driven
- V：Verification Closure

其中 Closed-Loop Verification 和 Quality Gate 是贯穿整个流程的机制。

这套名称是一个建议的产品方法学命名，并非行业已有标准。

我认为最重要的战略定位是：

SignOffAI 不应该只是 AI UVM Generator，而应该是一个面向 IP Verification 的 Evidence-Driven Autonomous Verification Platform。

这才是你目前架构真正值得坚持的方向。





走得通，但必须缩小目标、分阶段验证。我认为 SignOffAI 这条路线有现实可行性，值得继续投入；不过，它能否成为商业化的 AI 验证平台，目前还不能下定论。

我不想只给你一个鼓励性的答案。站在 IC 验证工程和产品商业化两个角度，我的判断是：

- 技术路线：可行。
- 工程架构：方向合理。
- IP 验证切入点：可行，而且比直接做 SoC 更现实。
- 全自动 Sign-Off：短期不现实。
- 商业化：有机会，但必须用真实项目证明价值。

## 1. 为什么我认为这条路走得通？

核心原因是：你不是试图让 AI 直接替代仿真器，而是在自动化传统验证工程中大量依赖人工的环节。

传统 IP 验证有几个明显的工作量来源：

1. 阅读 Spec，整理验证需求。
2. 制定验证计划和测试场景。
3. 编写 UVM 环境和 Sequence。
4. 编译、仿真和回归。
5. 分析失败日志。
6. 追踪 Coverage 缺口。
7. 反复生成测试、运行仿真、收敛 Coverage。
8. 整理交付报告和验证证据。

这些工作具有结构化、重复性和工具化的特点，适合 AI 辅助自动化。

而你的架构已经考虑了模型、执行、产物、追溯和质量门禁，不是单纯把 LLM 接到代码生成器上。

## 2. 真正的难点在哪里？

我认为有五个难点，其中三个决定项目能不能成功。

| 难点               | 风险               | 我的判断 |
| ---------------- | ---------------- | ---- |
| Spec 理解与需求提取     | AI 漏掉约束、误解时序     | 高    |
| UVM 自动生成         | 代码能编译，但验证行为不正确   | 高    |
| 激励有效性            | 测试数量很多，却触发不了关键场景 | 高    |
| Coverage Closure | 能找到缺口，却不能有效补齐    | 很高   |
| Debug 自动分析       | 把环境问题误判为 DUT Bug | 高    |

尤其要注意一个问题：

生成代码成功，不代表验证成功；Coverage 达标，也不代表没有 Bug。

真正困难的是建立可靠的验证依据和结果判定机制。

因此，AI 生成的每个测试都应该能够追溯到需求、功能场景和覆盖目标；仿真结果必须由真实 EDA 工具提供；最终签核仍然需要工程规则和人工责任边界。

## 3. 我认为最合理的产品发展路线

不要一开始就把目标定为全自动芯片 Sign-Off。

## SignOffAI 产品发展路线

1. 第一阶段：AI-Assisted IP Verification

   近期目标

   Spec 分析、验证计划、UVM 生成、回归执行、Debug 辅助和 Evidence 交付。

   目标：让工程师更快完成 IP 验证。
2. 第二阶段：Closed-Loop IP Verification

   核心突破

   Coverage 缺口分析、定向激励生成、仿真反馈、自动迭代。

   目标：证明系统能够自主推进验证收敛。
3. 第三阶段：Evidence-Driven IP Sign-Off

   质量门禁、证据链、Replay、验证结果审查。

   目标：让客户信任系统产生的工程结论。
4. 第四阶段：SoC Verification Extension

   多 IP 协同、系统级数据流、共享资源竞争、Firmware 协同。

   目标：在 IP 验证能力成熟后扩展系统级验证。

这四个阶段不是必须全部完成才能商业化。第一阶段如果能产生明确 ROI，就可以开始交付。

## 4. 怎么证明它真的走得通？

我建议不要再用内部单元测试数量来判断项目是否成功，而是做一个真实的 AXI DMA Benchmark。

设置两组：

- A 组：传统 UVM 工程师开发和验证。
- B 组：工程师使用 SignOffAI 辅助完成验证。

使用相同的 RTL、Spec、EDA 工具和功能目标。

重点测量：

| 指标           | 要回答的问题         |
| ------------ | -------------- |
| 环境开发时间       | 是否明显缩短？        |
| 测试开发时间       | 是否减少人工工作？      |
| Bug 检出率      | 是否保留传统流程的检测能力？ |
| Coverage     | 是否达到相同目标？      |
| Debug 时间     | 是否更快定位问题？      |
| Replay 成功率   | 失败是否能够可靠复现？    |
| Evidence 完整性 | 客户能否审查整个验证过程？  |

特别建议注入一批已知 RTL Bug，建立 Bug 检出基准。

第一轮可以使用 20 个左右的缺陷作为实验目标，但要覆盖不同类别，并记录每个缺陷的可检测条件。不要只统计发现数量，还要检查误报、漏报和 Bug 定位准确性。

## 5. 什么结果说明应该继续投入？

我会采用下面的判断标准：

| 实验结果                        | 决策                      |
| --------------------------- | ----------------------- |
| 时间明显缩短，Bug 检出和 Coverage 不退化 | 强烈建议继续                  |
| 时间缩短，但需要大量人工修正              | 继续优化生成和审查机制             |
| 代码生成快，但测试无效                 | 暂停扩展 Agent，解决验证模型问题     |
| Coverage 能分析，不能有效收敛         | 集中突破 StimulusPlan 和反馈闭环 |
| 结果不能复现                      | 优先修复 Runtime 和 Evidence |

这里不建议提前规定一个漂亮的百分比作为成功标准。先用人工基线测出真实成本，再确定客户愿意接受的改善幅度。

## 6. 最后，我对这个项目的真实判断

我认为 SignOffAI 有机会成为一个有价值的垂直工程产品。

但它最有价值的定位不是：

“AI 自动写 UVM。”

而是：

AI 能否组织并推进一项真实的 IP 验证任务，从规格理解、环境构建、仿真执行到 Coverage 收敛和证据交付。

这是一个比代码生成难得多、但也更有价值的方向。

还有一点我想强调：你现在的架构已经覆盖了不少基础设施，不应该继续以增加 Agent、增加模块、增加 GUI 页面作为主要进度指标。接下来应该以真实验证效果作为研发指标。

我的建议

# 值得继续做

但下一阶段把范围锁定在一个 AXI DMA IP Benchmark，先证明三个能力：

1. 能稳定生成可运行的验证环境。
2. 能检测真实注入的 RTL 缺陷。
3. 能根据 Coverage 缺口产生有效的定向测试。

这三项成功之后，再扩大 IP 类型和商业交付范围。

如果这三项能在真实 DUT 上跑通，SignOffAI 就不只是一个有架构设计的 AI 工具，而是开始具备真正的工程产品竞争力。&#x20;