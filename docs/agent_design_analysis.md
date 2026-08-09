# SignOffAI Agent 设计规划合理性分析

> 日期：2026-08-09  
> 核心问题：当前 11 Agent + 17 阶段流水线是否匹配数字前端验证的真实业务流程？

---

## 1. 流水线全景图

```
17 个阶段，11 个 Agent，6 个纯文档阶段

 前端设计 de/                          功能验证 dv/
┌─────────────────────────┐    ┌──────────────────────────────────────────┐
│ spec  → design → model  │    │ vplan → tpoint → rtm → UVM → test       │
│  AGENT   AGENT   AGENT  │    │  DOC     DOC     DOC   AGENT  AGENT     │
│                         │    │                                          │
│ ifspec → rtlsign        │    │ assert → regress → cover → debug        │
│  DOC      DOC ← 问题！   │    │  AGENT    AGENT    AGENT   AGENT       │
└─────────────────────────┘    │                                          │
                               │ qa → report → vclose                    │
                               │ AGENT AGENT    DOC                      │
                               └──────────────────────────────────────────┘

AGENT = 由 LLM Agent 执行    DOC = 纯文档生成 (doc_only=True，无 Agent 参与)
```

---

## 2. Agent I/O 契约矩阵

| 顺序 | 阶段 | Agent | consumes | produces | 状态 |
|:---:|------|-------|----------|----------|:---:|
| 1 | spec | spec_and_test_planner | `[]` | `spec` | AGENT |
| 2 | design | design_architect | `{spec: [features, interfaces, registers]}` | `design_arch` | AGENT |
| 3 | model | model_agent | `[spec]` | `model` | AGENT |
| 4 | ifspec | — | — | — | ⚠️ DOC |
| 5 | rtlsign | — | — | — | ⚠️ DOC |
| 6 | vplan | — | — | — | ⚠️ DOC |
| 7 | tpoint | — | — | — | ⚠️ DOC |
| 8 | rtm | — | — | — | ⚠️ DOC |
| 9 | UVM | verification_architect | `[spec]` | `env` | AGENT |
| 10 | test | test_engineer | `[spec, env]` | `tests` | AGENT |
| 11 | assert | assertion_engineer | `[]` | — | AGENT |
| 12 | regress | regression_manager | `[env, tests]` | `regression` | AGENT |
| 13 | cover | coverage_manager | `[spec, regression]` | `coverage` | AGENT |
| 14 | debug | debug_engineer | `[]` | — | AGENT |
| 15 | qa | quality_assurance | `[regression, coverage]` | — | AGENT |
| 16 | report | report_generator | `[]` | — | AGENT |
| 17 | vclose | — | — | — | ⚠️ DOC |

---

## 3. 与真实数字前端业务流程的对比

### 3.1 标准 IC 验证流程（V-Model）

```
        需求规格                   签核交付
          ↓                         ↑
      架构设计                   验收测试
          ↓                         ↑
      模块设计      ──────→     系统测试
          ↓                         ↑
      RTL编码                  集成测试
          ↓                         ↑
      单元测试  ←──────       RTL验证
                    UVM环境 → 回归 → 覆盖率 → 签核

真实流程特征：
  1. 设计+验证是并行迭代的，不是串行瀑布
  2. 验证环境搭建和 RTL 开发几乎同时开始
  3. 回归是持续运行的（每次 RTL 变更都触发）
  4. Debug 贯穿全流程，不是单独一个阶段
  5. 签核是多维度的——不是最后一步，而是持续评估
```

### 3.2 SignOffAI 流水线 vs 真实流程映射

| 真实流程 | SignOffAI 阶段 | 是否匹配 | 问题 |
|----------|:---:|:---:|------|
| 需求分析 | spec | ✅ | 基本合理 |
| 架构设计 | design | ⚠️ | 只出 JSON hierarchy，不出 RTL |
| 参考模型 | model | ✅ | C++ 模型方向对，但位置偏早 |
| **接口文档** | ifspec (DOC) | ⚠️ | 不应是空模板，应基于 spec 生成 |
| **RTL签核** | rtlsign (DOC) | ❌ | **签核在验证之前？顺序错误** |
| 验证计划 | vplan (DOC) | ❌ | 核心交付物却用模板填充 |
| 测试点分解 | tpoint (DOC) | ❌ | 同上，应该由 LLM 分析生成 |
| 需求追踪 | rtm (DOC) | ❌ | 同上 |
| UVM环境搭建 | UVM | ✅ | 方向对，Jinja2 模板生成 SV 代码 |
| 测试开发 | test | ✅ | YAML→SV 模板生成 |
| 断言编写 | assert | ⚠️ | consumes=[] 不合理 |
| 回归执行 | regress | ✅ | 方向对 |
| 覆盖率分析 | cover | ⚠️ | 依赖回归结果，合理 |
| 问题定位 | debug | ⚠️ | consumes=[] 不合理 |
| 质量审查 | qa | ⚠️ | 方向对 |
| 报告生成 | report | ⚠️ | consumes=[] 不合理 |
| 验证收敛 | vclose (DOC) | ❌ | 核心签核物用模板填充 |

**匹配度：仅 4/17 阶段合理（24%），6/17 是空模板（35%），7/17 存在设计问题（41%）。**

---

## 4. 核心设计问题

### 4.1 🔴 致命问题：RTL Signoff 放在验证之前

```
流水线顺序：
  spec → design → model → ifspec → rtlsign → vplan → tpoint → ... → UVM → test → regress

真实顺序应该是：
  spec → design(RTL) → vplan → UVM → test → regress → cover → debug → signoff
                                                              ↑
                                                    签核在所有验证之后
```

当前流水线在阶段 5 就做了 `rtlsign`（RTL 签核报告），而验证工作（UVM/test/regress/cover/debug）在阶段 9-14 才开始。**这是流程的根本性错误**——还没有验证就签核 RTL，等于没体检就发健康证。

### 4.2 🔴 致命问题：6 个核心交付物是空模板

```
vplan   — 验证计划     → doc_only=True，生成空模板
tpoint  — 测试点分解   → doc_only=True，生成空模板
rtm     — 需求追踪矩阵 → doc_only=True，生成空模板
ifspec  — 接口规范     → doc_only=True，生成空模板
rtlsign — RTL签核      → doc_only=True，生成空模板
vclose  — 验证收敛     → doc_only=True，生成空模板
```

这 6 个交付物恰恰是验证流程中**最有价值的文档**——验证计划定义了测什么、怎么测；测试点分解是测试用例的来源；需求追踪矩阵是签核的证据链。把它们做成空模板等于放弃了 AI 最大的价值——**智能分析生成**。

对比项目的六大引擎（`src/core/engines.py`）：
- `VPlanGenerator` — 正是用来**智能生成验证计划**的引擎
- `PPAAnalyzer` — 正是用来**智能分析签核数据**的引擎

引擎能力存在，却没有接入流水线。doc_only 的阶段应该由这些引擎驱动，而不是空模板。

### 4.3 🟡 数据流断裂

多个 Agent 的 `consumes` 为空或不完整：

```
assertion_engineer:  consumes = []        ← 不知道 spec 和接口信息，如何写断言？
debug_engineer:      consumes = []        ← 没有回归日志和仿真结果，如何定位？
report_generator:    consumes = []        ← 没有 coverage/regression/qa 数据，如何出报告？
```

虽然 `ctx` 共享上下文中有数据，但 Agent prompt 中声明 `consumes` 是为了让框架做依赖检查和字段级输入过滤。声明为空意味着：
1. 依赖检查被跳过——前面阶段失败，这个阶段照样跑
2. prompt 中收到的 input 可能是空 JSON，全凭 LLM "猜测"

### 4.4 🟡 反馈闭环过于简陋

```python
# execution.py
MAX_FEEDBACK_LOOPS = 2
# debug → fix_agent → re-run，但只在 debug_engineer 有输出时触发
# fix_agent 只映射了 4 个角色：design/verification/model/spec
# coverage_manager、test_engineer 等无法被修复
```

真实验证中，回归失败 → 定位 → 修复 → 重新回归 是频繁发生的循环。当前设计只有一个粗糙的 2 轮反馈，且只覆盖了 4 种错误类型。

### 4.5 🟡 流水线是单向瀑布，不是迭代协作

真实验证流程的特征：
- **设计+验证并行**：RTL 开发的同时搭建 UVM 环境
- **持续回归**：每次 commit 都触发回归，不是"一个阶段"
- **增量式**：先跑冒烟测试，再跑完整回归
- **多人协作**：设计工程师、验证工程师、签核经理并发工作

当前流水线：
- 严格串行：spec → design → model → ... → report
- 一次性：一次跑完所有阶段，没有增量概念
- 单线程：所有 Agent 顺序执行，没有并行

---

## 5. 设计亮点

尽管有上述问题，有几个设计是合理的：

| 亮点 | 说明 |
|------|------|
| **Agent 契约模式** | `consumes/ produces/ min_score/ validate()` — 借鉴了微服务的 I/O 契约思想，Agent 间通过 `ctx` 共享上下文，松耦合 |
| **模型 Agent 选择纯 C++** | 设计文档解释了为何不用 SystemC：`g++` 直接编译、CI 友好、无库依赖——这是务实的工程决策 |
| **StepExecutor 重试** | 每个阶段有独立的 `StepExecutor`，支持重试、快照、回滚、diff——适合 LLM 输出的不确定性 |
| **backfill 机制** | `_backfill_ctx_deps` 在数据缺失时合成最小可用数据保证管道不中断——虽然目前是 Demo 模式，但方向对 |
| **UVM 环境的三阶段检查** | `static → compile → loopback` 三关质量门，符合"生成代码必须能编译跑通"的工程标准 |

---

## 6. 建议的重构方案

### 6.1 修正流水线顺序

```
修正后的流水线（对应真实 V-Model）：

阶段1:  spec      AGENT   规格分析 → spec JSON
阶段2:  design    AGENT   架构设计 → function hierarchy + register map
阶段3:  vplan     ENGINE  验证计划（VPlanGenerator 引擎驱动，非空模板）
阶段4:  tpoint    ENGINE  测试点分解（VPlanGenerator 引擎驱动）
阶段5:  rtm       ENGINE  需求追踪矩阵（从 spec+design+vplan 自动生成）
阶段6:  model     AGENT   参考模型（C++ reference model）
阶段7:  UVM       AGENT   UVM 环境生成（时机：spec+design 就绪后）
阶段8:  assert    AGENT   SVA 断言生成（时机：UVM env 的 interface 就绪后）
阶段9:  test      AGENT   测试用例生成（时机：vplan+tpoint 就绪后）
阶段10: regress   AGENT   回归执行
阶段11: cover     AGENT   覆盖率分析
阶段12: debug     AGENT   失败分析 + 路由修复建议
       ↓ (反馈回到 design/UVM/test 重新执行)
阶段13: qa        AGENT   质量审查
阶段14: signoff   ENGINE  签核报告（PPAAnalyzer + 证据链打包）
```

### 6.2 将 doc_only 阶段升级为引擎驱动

```
当前:
  vplan  → doc_only (空模板)
  tpoint → doc_only (空模板)
  rtm    → doc_only (空模板)
  vclose → doc_only (空模板)

改为:
  vplan  → VPlanGenerator.generate(spec)      ← 引擎已存在！
  tpoint → VPlanGenerator.decompose(vplan)    ← 引擎已存在！
  rtm    → VPlanGenerator.traceability(spec, vplan, tests)
  vclose → PPAAnalyzer.closure_report(all_data)
```

### 6.3 修复数据流

```
assertion_engineer.consumes  = ["spec", "env"]      # 需要 spec 的接口定义 + env 的 signal list
debug_engineer.consumes      = ["regression", "env"] # 需要仿真日志 + 环境文件路径
report_generator.consumes    = ["regression", "coverage", "qa"]  # 需要所有分析结果
```

### 6.4 支持增量工作流

```bash
# 全量流水线
vagent verify --workflow full

# 增量：只重新跑失败的阶段
vagent verify --workflow full --retry-failed

# 子集：只跑 coverage → debug → qa
vagent verify --workflow analysis

# 循环：regress → debug → fix → regress（直到收敛）
vagent verify --workflow converge --max-loops 5
```

---

## 7. 总体评估

| 维度 | 评分 | 说明 |
|------|:---:|------|
| 阶段覆盖度 | ⭐⭐⭐⭐ | 17 个阶段覆盖了从 spec 到 signoff 的完整链路 |
| 阶段正确性 | ⭐⭐ | **RTL signoff 在验证之前——流程顺序错误** |
| Agent 设计 | ⭐⭐⭐ | 契约模式、consumes/produces、validate 是亮点 |
| 数据流完整性 | ⭐⭐ | 多个 Agent consumes=[] 导致依赖断裂 |
| 引擎利用率 | ⭐ | 六大引擎闲置，核心阶段用空模板填充 |
| 迭代/反馈 | ⭐⭐ | 单向瀑布无迭代，反馈闭环仅 2 轮且覆盖不全 |
| 真实流程匹配 | ⭐⭐ | 24% 阶段匹配，65% 有问题或缺失 |
| **总体** | **⭐⭐** | **骨架正确，但血肉错位** |

---

## 8. 一句话总结

> **Agent 流水线的骨架（spec→design→UVM→test→regress→cover→signoff）方向是对的，但存在三个致命问题：① RTL signoff 跑到了验证前面（顺序错误）、② 6 个核心交付物被退化为空模板而闲置了已有的 VPlanGenerator/PPAAnalyzer 引擎、③ 数据流多处断裂（consumes 声明不完整）。修好这三件事，这套 Agent 设计才能匹配真实的数字前端验证业务流程。**
