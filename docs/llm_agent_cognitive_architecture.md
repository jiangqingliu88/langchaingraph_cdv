# SignOffAI Agent 认知架构 —— 从"LLM 在干什么活"重新命名

> **核心命题**：Agent 的名字应该回答一个问题——"这个 Agent 里，LLM 到底在干什么认知活？"
>
> 旧名字（`spec_planner`、`regression_manager`）描述的是**产出物或角色**，不是 LLM 的认知动作。新名字用动词/动名词直接标注 LLM 的认知工作类型。
>
> 日期：2026-08-10

---

## 一、命名原则

| 旧命名法（角色导向） | 新命名法（认知导向） | 规则 |
|:---:|:---:|------|
| `spec_planner` | `intent_extractor` | **动词-er**：LLM 在提取什么？ |
| `write_rtl` | `logic_composer` | **名词-composer**：LLM 在组合什么？ |
| `coverage_manager` | `gap_interpreter` | **名词-interpreter**：LLM 在解释什么？ |

**三条命名规则：**
1. 名字必须包含一个**认知动词**（extract / decompose / infer / trace / interpret / cluster / compose / synthesize / review / model / design）
2. 名字必须能回答"输入 → 认知动作 → 输出"（比如 `intent_extractor`：spec 文本 → **提取意图** → 测试点列表）
3. 一看名字就知道**这部分能不能用传统工具替代**（`gap_interpreter` 一看就是 LLM 的活；`failure_clusterer` 一看就应该是 dvsim API 为主 LLM 为辅）

---

## 二、12 Agent 重命名总表

| # | 旧名 | 新名 | LLM 在干什么活 | 一句话 |
|:---:|------|------|---------------|--------|
| 1 | `spec_planner` | **`intent_extractor`** | 从自然语言 spec 中**提取**设计意图、隐含约束、corner case | "这个 spec 到底在说什么？哪里容易出 bug？" |
| 2 | `design_architect` | **`module_decomposer`** | 将功能描述**分解**为模块层次、寄存器字段语义 | "这个功能应该拆成几个模块？每个寄存器管什么？" |
| 3 | `verify_architect` | **`testbench_orchestrator`** | **编排**验证环境结构——几个 agent、scoreboard 怎么比、reference model 怎么接 | "这个 DUT 的验证环境长什么样？" |
| 4 | `model_agent` | **`behavior_modeler`** | 从功能描述**建模**算法行为，翻译成 C++ | "这个功能的算法行为怎么描述？怎么翻译成 C++？" |
| 5 | `write_rtl` | **`logic_composer`** | 从接口契约 + 功能描述**组合**出可综合 RTL 逻辑 | "在这个接口约束下，内部逻辑怎么写？" |
| 6 | `test_engineer` | **`scenario_designer`** | 从测试点**设计**测试场景和随机约束策略 | "怎么测才能抓到 bug？约束怎么设？" |
| 7 | `assertion_engineer` | **`property_inferrer`** | 从设计意图**推理**时序属性和断言条件 | "这个信号在时序上应该满足什么性质？" |
| 8 | `coverage_manager` | **`gap_interpreter`** | **解释**覆盖率缺口的语义原因，建议补测方向 | "这 15% 为什么没覆盖？语义上缺什么？" |
| 9 | `regression_manager` | **`failure_clusterer`** | **聚类**失败测试，识别共同根因模式 | "这 50 个失败其实是同一个根因吗？" |
| 10 | `debug_engineer` | **`root_cause_tracer`** | 从故障现象**追踪**根本原因——多跳因果推理 | "这个 FAIL 的真正根因是什么？在哪一层？" |
| 11 | `quality_assurance` | **`semantic_reviewer`** | **审查**代码的语义正确性和设计意图一致性 | "这段代码真的实现了 spec 要求的功能吗？" |
| 12 | `report_generator` | **`conclusion_synthesizer`** | **合成**自然语言签核结论——数据→决策叙述 | "综合所有证据，本次能不能签？风险多大？" |

---

## 三、按认知类型分组：5 类 LLM 认知工作

12 个 Agent 的认知工作可以归纳为 5 大类。同一类共享相同的认知模式、相同的难度特征、相同的迭代策略。

### 3.1 语义理解类 —— "从自然语言中提取结构化语义"

| Agent | LLM 认知动作 | 输入 | 输出 |
|-------|-------------|------|------|
| **`intent_extractor`** | 意图提取 + 隐含约束识别 | 自然语言 Spec 文档 | 结构化测试点 + corner case 列表 |
| **`gap_interpreter`** | 覆盖率缺口语义解释 | 覆盖率数字 + 缺口列表 | 自然语言补测建议 |
| **`semantic_reviewer`** | 设计意图一致性检查 | RTL 代码 + spec | "这段代码和 spec 意图一致吗？" |

**共同的认知特征：**
- 核心能力是**自然语言理解**，这是 LLM 的核心优势，传统工具完全做不到
- 输入永远有**歧义和不完整**——spec 不会写清楚所有 edge case；覆盖率数字背后的语义原因需要推理
- **LLM 占比都是 60-90%**，传统工具只做格式校验/数据预处理

**共同的难度与迭代需求：**

```
intent_extractor（🟡🟡🟡🟡 高难度，需要迭代）:
  → 为什么难：反馈信号极度稀疏。漏了一个测试点，要等到 coverage 阶段才发现
  → 迭代机制：多阶段交叉验证（spec × design × assert × cover）

gap_interpreter（🟢🟢 低难度，无需迭代）:
  → 为什么简单：输入已经有覆盖率数字，LLM 只需要"翻译"成自然语言
  → 单次调用即可，不需要迭代

semantic_reviewer（🟢🟢 低难度，无需迭代）:
  → 为什么简单：lint 已经过滤了机械问题，LLM 只看语义
  → 单次调用即可，不需要迭代
```

---

### 3.2 结构分解类 —— "把整体拆成部分，定义部分之间的关系"

| Agent | LLM 认知动作 | 输入 | 输出 |
|-------|-------------|------|------|
| **`module_decomposer`** | 功能模块划分 + 寄存器语义设计 | 功能描述 + 接口列表 | 模块层次 + 寄存器表 |
| **`testbench_orchestrator`** | 验证环境拓扑设计 | DUT 接口 + 功能描述 | 组件列表 + 连接拓扑 + 比对策略 |

**共同的认知特征：**
- 核心能力是**结构化分解**——把一个复杂系统拆成合理的子系统
- **没有唯一正确答案**——同一个功能可以有多种模块划分方式
- 考验的是 LLM 对**内聚性、耦合度、接口复杂度**的判断

**共同的难度与迭代需求：**

```
module_decomposer（🟢🟢 低难度，无需迭代）:
  → 为什么简单：架构好坏主要靠人 review，1-2 轮调整就收敛
  → 不需要独立迭代循环

testbench_orchestrator（🟡🟡🟡 中等难度，需要迭代）:
  → 为什么难：编译反馈循环——架构决定代码结构，代码编译不过说明架构有问题
  → 迭代机制：架构描述→Jinja2渲染→编译→编译失败→修架构/修模板参数→再渲染
  → 注意：代码渲染是 Jinja2 的活，不是 LLM 的活
```

---

### 3.3 代码生成类 —— "从结构化描述翻译成可执行代码"

| Agent | LLM 认知动作 | 输入 | 输出 |
|-------|-------------|------|------|
| **`behavior_modeler`** | 功能描述 → 算法行为翻译 | 功能 spec + 接口契约 | C++ 参考模型 |
| **`logic_composer`** | 接口契约 + 功能 → 可综合逻辑 | 接口契约 + 寄存器表 + 时序描述 | 可综合 RTL |
| **`scenario_designer`** | 测试点 → 测试场景 + 随机约束 | 测试点列表 + UVM 环境 | sequence + 约束 + 定向 test |

**共同的认知特征：**
- 核心能力是**"翻译+填空"**——输入是结构化的（契约、测试点），LLM 在约束框架内做填空题
- **正确性不能靠 LLM 保证**——需要编译器/仿真器/综合器反馈
- 这是 SignOffAI "LLM 做填空题" 设计理念的核心体现

**共同的难度与迭代需求：**

```
behavior_modeler（🟢🟡 中低难度，1-2 轮）:
  → 自测向量能快速判断正确性，反馈明确
  → 不需要独立迭代 Agent

logic_composer（🔴🔴🔴🔴 高难度，3-5 轮）:
  → 为什么难：lint→综合→仿真三道关卡，几乎不可能一次过
  → 迭代机制：
      Round 1: LLM 生成 RTL → lint 报 warning → LLM 修 → 再 lint pass
      Round 2: 综合 → timing violation → LLM 加流水线 → 再综合 pass
      Round 3: 仿真 → 功能错 → LLM 修逻辑 → 再仿真 pass
  → ✅ 必须单开 Agent，必须有自动化反馈循环

scenario_designer（🟡🟡🟡 中等难度，3-4 轮）:
  → 为什么难：约束设计是数学问题，LLM 天然不擅长
  → 迭代机制：覆盖率反馈 → 调约束 → 补定向 test → 再覆盖
  → ✅ 建议单开 Agent
```

---

### 3.4 推理诊断类 —— "从现象反推原因，从数据识别模式"

| Agent | LLM 认知动作 | 输入 | 输出 |
|-------|-------------|------|------|
| **`property_inferrer`** | 设计意图 → 时序属性推理 | 设计描述 + 信号列表 | SVA property + assume/assert 分类 |
| **`failure_clusterer`** | 失败模式聚类 + 共同根因识别 | 回归结果（pass/fail + log） | 聚类后的失败组 + 共同根因假设 |
| **`root_cause_tracer`** | 故障现象 → 根因的多跳因果追踪 | 错误摘要 + 信号 dump | 根因定位 + 修复方向 + 责任路由 |

**共同的认知特征：**
- 核心能力是**因果推理和模式匹配**——从结果反推原因
- **反馈驱动**——每轮推理需要工具验证（形式验证 counterexample、仿真波形、失败 log）
- 这是 LLM 在验证流程中**最有壁垒**的认知工作——传统工具能做数据收集，但做不了因果推理

**共同的难度与迭代需求：**

```
property_inferrer（🟡🟡🟡 中等难度，3-4 轮）:
  → 为什么难：SVA 精确性要求极高（一个 cycle 偏差断言就废了）
  → 迭代机制：生成 SVA → 形式验证 → counterexample → 修断言 → 再验证
  → ✅ 建议单开 Agent

failure_clusterer（🟢🟢 低难度，1-2 轮）:
  → 为什么简单：dvsim API 已经做了大部分数据收集，LLM 只做语义聚类
  → 不需要独立迭代 Agent

root_cause_tracer（🔴🔴🔴🔴🔴 最高难度，4-5 轮）:
  → 为什么最难：因果链 5 跳以上，没有工具验证就是瞎猜
  → 迭代机制：假设生成→波形/仿真验证→排除/确认→下一轮假设→...→收敛
  → ✅✅ 必须单开 Agent，必须有多轮假设-验证循环
```

---

### 3.5 综合报告类 —— "数据聚合 + 自然语言翻译"

| Agent | LLM 认知动作 | 输入 | 输出 |
|-------|-------------|------|------|
| **`conclusion_synthesizer`** | 多源数据 → 签核决策叙述 | 覆盖率 + 回归结果 + bug 分析 + 风险因素 | 签核结论 + 风险评级 + 证据链 |

**认知特征：**
- 核心能力是**信息压缩 + 决策叙述**——从多维数据合成一个判断
- LLM 占比 60%，传统工具做数据聚合和格式化
- 全流水线**最容易**的 LLM 任务——单次调用即可，不需要迭代

---

## 四、全局热力图：按认知类型重新排列

```
                         认知类型      LLM难度   迭代轮数  需独立Agent?
                         ────────      ──────    ────────  ───────────
intent_extractor         语义理解      🔴🔴🔴🔴    3-4轮    ✅ 必须
gap_interpreter          语义理解      🟢🟢        1轮      ❌
semantic_reviewer        语义理解      🟢🟢        1轮      ❌
───────────────────────────────────────────────────────────────
module_decomposer        结构分解      🟢🟢        1-2轮    ❌
testbench_orchestrator   结构分解      🟡🟡🟡      2-3轮    ⚠️ 可选
───────────────────────────────────────────────────────────────
behavior_modeler         代码生成      🟢🟡        1-2轮    ❌
logic_composer           代码生成      🔴🔴🔴🔴     3-5轮    ✅ 必须
scenario_designer        代码生成      🟡🟡🟡      3-4轮    ✅ 建议
───────────────────────────────────────────────────────────────
property_inferrer        推理诊断      🟡🟡🟡      3-4轮    ✅ 建议
failure_clusterer        推理诊断      🟢🟢        1-2轮    ❌
root_cause_tracer        推理诊断      🔴🔴🔴🔴🔴   4-5轮    ✅✅ 必须
───────────────────────────────────────────────────────────────
conclusion_synthesizer   综合报告      🟢          1轮      ❌
```

---

## 五、6 个需要"迭代收敛 + 独立 Agent"的核心点

从认知难度分析中筛选出以下 6 个：

| 优先级 | Agent（新名） | LLM 在干什么活 | 为什么必须迭代 | 迭代机制 | 预估工作量 |
|:---:|------|---------------|--------------|---------|:---:|
| **P0** | `root_cause_tracer` | 多跳因果追踪 | 单次推理 ≈ 瞎猜，必须假设→验证→排除循环 | 波形 dump + 仿真复现 | 🔴 最高 |
| **P1** | `logic_composer` | 约束框架内填空 | lint/synth/sim 三关不可能一次过 | lint→fix→synth→fix→sim→fix | 🔴 高 |
| **P1** | `intent_extractor` | 意图提取 + 隐含约束 | 反馈极度稀疏，漏了要等 coverage 才发现 | 多阶段交叉验证 | 🟡 中高 |
| **P2** | `property_inferrer` | 时序属性推理 | SVA 一个 cycle 偏差就废 | 形式验证 counterexample | 🟡 中 |
| **P2** | `scenario_designer` | 测试场景 + 约束设计 | 约束是数学问题，LLM 天生不精确 | 覆盖率反馈 → 调约束 | 🟡 中 |
| **P3** | `testbench_orchestrator` | 验证拓扑编排 | 编译反馈循环（走 Jinja2 后减轻） | 编译→修参数→再编译 | 🟢 中低 |

---

## 六、6 个"不需要迭代、跟着主流水线走即可"的 Agent

这些 Agent 的 LLM 认知工作**单次调用就能产出可用的结果**，不需要独立的迭代循环：

| Agent（新名） | LLM 在干什么活 | 为什么不需要迭代 | 放在哪个阶段 |
|-------|---------------|----------------|------------|
| `module_decomposer` | 功能→模块分解 | 人工 review 替代迭代，1-2 轮调整收敛 | 跟在 `intent_extractor` 后面 |
| `behavior_modeler` | 功能→算法翻译 | 自测向量快速验证，反馈明确 | 跟在 `module_decomposer` 后面 |
| `semantic_reviewer` | 语义级代码审查 | lint 前置过滤后 LLM 只看语义，单次够用 | 各代码生成阶段之后 |
| `gap_interpreter` | 覆盖率缺口解释 | 输入已有明确数字，LLM 只做"翻译" | 覆盖率收集之后 |
| `failure_clusterer` | 失败模式聚类 | dvsim API 做了大部分工作，LLM 只做语义聚类 | 回归执行之后 |
| `conclusion_synthesizer` | 证据→签核结论 | 纯聚合+翻译，全流水线最简单的 LLM 活 | 流水线末端 |

---

## 七、迭代收敛 Agent 的通用架构

6 个需要迭代的 Agent 共享同一个设计模式——**"生成-验证-修复"循环**：

```
┌─────────────────────────────────────────────────────────────┐
│               迭代收敛 Agent 通用架构                          │
│                                                               │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│   │   LLM        │───▶│  传统工具     │───▶│  收敛判断     │   │
│   │   认知动作    │    │  验证反馈     │    │              │   │
│   │              │    │              │    │  ✅ 收敛 → 出口 │   │
│   │  提取/推理   │    │ lint/综合    │    │  ❌ 未收敛    │   │
│   │  分解/生成   │    │ 仿真/形式    │    │      ↓        │   │
│   │  设计/合成   │    │ 编译/覆盖率  │    │  反馈摘要     │   │
│   └──────────────┘    └──────────────┘    └──────┬───────┘   │
│         ▲                                        │           │
│         └────────────────────────────────────────┘           │
│                     反馈摘要（结构化）                         │
│                                                               │
│   关键设计原则：                                                │
│   1. LLM 只看"反馈摘要"（传统工具预处理后的结构化信息）          │
│   2. 每一轮迭代必须产生可验证的输出                              │
│   3. 收敛条件必须可量化（"0 error + 0 warning"）               │
│   4. 最大迭代次数硬限制（防止无限循环烧 token）                 │
│   5. 每轮迭代记录 artifact manifest（可追溯"为什么改了三轮"）   │
└─────────────────────────────────────────────────────────────┘
```

**不同 Agent 的反馈工具对应关系：**

| Agent | 反馈工具 | 反馈内容 | 收敛条件 |
|-------|---------|---------|---------|
| `logic_composer` | `tool_check_lint` + `tool_run_synthesis` + `tool_run_sim` | lint warning/error + timing report + sim mismatch | 0 error + 0 warning + sim pass |
| `root_cause_tracer` | `tool_sim_wave_dump` + `tool_diff_failures` | 关键信号波形 + 失败 diff 摘要 | 修复后仿真 pass + 无新回归失败 |
| `intent_extractor` | 交叉验证（与 design/assert/cover 的输出比对） | 遗漏的测试点 / 多余的功能点 | 覆盖率 100% 或 gap 可解释 |
| `property_inferrer` | `tool_formal_verify` | counterexample trace | 0 counterexample + 0 vacuous pass |
| `scenario_designer` | `tool_cov_merge` + `tool_cov_report` | 覆盖率缺口 vs 目标 | 覆盖率达到目标 或 剩余 gap 判定为 dead code |
| `testbench_orchestrator` | `tool_check_compile` + `tool_check_loopback` | 编译错误 + loopback mismatch | 0 compile error + loopback pass |

---

## 八、与原始 Agent 命名的对比总结

| 旧名 | 新名 | 旧名的问题 | 新名的改进 |
|------|------|-----------|-----------|
| `spec_planner` | `intent_extractor` | "planner" 太宽泛，像是项目经理 | "extractor" 精确描述 LLM 认知动作：从文本中提取 |
| `design_architect` | `module_decomposer` | "architect" 暗示全局设计，但 LLM 只做分解 | "decomposer" 标明 LLM 是把整体拆成部分 |
| `verify_architect` | `testbench_orchestrator` | 又是 "architect"，和 design_architect 没区分度 | "orchestrator" 强调编排连接的认知动作 |
| `model_agent` | `behavior_modeler` | "agent" 没有任何信息量 | "modeler" 标明建模算法行为的认知动作 |
| `write_rtl` | `logic_composer` | "write" 像秘书干活，没有认知含量 | "composer" 标明在约束框架内组合逻辑 |
| `test_engineer` | `scenario_designer` | "engineer" 又宽泛了 | "designer" 标明设计测试场景的创造性认知 |
| `assertion_engineer` | `property_inferrer` | 同上，"engineer" 没有区分度 | "inferrer" 标明从意图推理属性的认知动作 |
| `coverage_manager` | `gap_interpreter` | "manager" 暗示管理数据，但 LLM 做的是解释 | "interpreter" 标明解释缺口语义的认知动作 |
| `regression_manager` | `failure_clusterer` | "manager" 同上问题 | "clusterer" 标明聚类失败的认知动作 |
| `debug_engineer` | `root_cause_tracer` | "debug" 是结果不是认知过程 | "tracer" 标明从现象追踪到根因的认知链 |
| `quality_assurance` | `semantic_reviewer` | "assurance" 是目标不是动作 | "reviewer" 标明代码审查的认知动作，加 "semantic" 区分 lint |
| `report_generator` | `conclusion_synthesizer` | "generator" 像自动化的，没有认知含量 | "synthesizer" 标明从多源信息合成结论 |

---

## 九、行动路线图

| 阶段 | 做什么 | 预计工作量 |
|:---:|--------|:---------:|
| **Phase A** | 代码中重命名 12 个 Agent 目录/类名/配置（`src/agents/` 下所有引用） | 1 天 |
| **Phase B** | 先加固 6 个反馈工具（sim_log 预处理、lint 反馈、form 验证、约束检查器、编译反馈、覆盖率 merge）——没有好反馈 LLM 迭代就是瞎迭代 | 2-3 周 |
| **Phase C** | 实现"生成-验证-修复"循环框架 `src/core/iterative_loop.py`——6 个需要迭代的 Agent 都用同一个循环框架 | 1 周 |
| **Phase D** | 按 P0→P1→P2→P3 顺序，逐个 Agent 接入迭代循环 | 每个 2-5 天 |
| **Phase E** | 收敛条件可观测化——能看到每个 Agent 迭代了几轮、每轮 diff 是什么 | 1 周 |

---

## 十、核心设计原则（总结）

> 1. **Agent 名 = LLM 认知动作**。一看名字就知道 LLM 在干什么活，传统工具在干什么活。
>
> 2. **提取/推理/追踪 → 这些是 LLM 的活，传统工具替代不了。** 归入"必须迭代"的高优先级 Agent。
>
> 3. **聚类/解释/合成 → 这些也是 LLM 的活，但一次就够了。** 归入"跟主流水线"的 Agent，不需要独立迭代。
>
> 4. **分解/编排/建模/设计 → 这些 LLM 能做，但传统工具和人也可以做。** 根据反馈信号密度决定要不要迭代。
>
> 5. **不是"让 LLM 一次生成对的"，而是"让 LLM 快速失败、快速修复"。** 迭代收敛的本质是缩短反馈循环——从人工几小时缩短到自动化几秒。
