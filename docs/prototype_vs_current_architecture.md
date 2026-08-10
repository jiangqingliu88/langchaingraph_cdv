# 原型架构 vs 当前 12-Agent 架构：9 个维度的差异分析

> **左侧**：你提供的 300 行原型（8 阶段 PlannerAgent + 占位工具 + argparse + 人工审批）
>
> **右侧**：当前 SignOffAI 工程（12 Agent + ToolHub + Click CLI + LLM + 证据链）
>
> **核心问题**：原型"小而美"，当前"大而全"——谁对谁错？或者说，各有什么对方该学的东西？
>
> 日期：2026-08-10

---

## 零、先看一眼两个架构长什么样

### 原型架构（~300 行）

```
main()
  └── cmd_plan()
        └── PlannerAgent.plan(spec)
              └── for stage in stages:
                    ├── tool_func = registry.get(stage.tool)
                    ├── result = tool_func(ctx)
                    ├── if stage.requires_approval:
                    │     └── input("y/n/q?")
                    └── ctx["_history"].append(result)
              
              └── return SPA JSON
```

**核心理念：** 一个 Agent 拿着注册表里的工具，按固定阶段列表顺序调用，4 个审批点人工确认，最后输出一份 JSON。

### 当前架构（~30,000+ 行）

```
vagent verify
  └── Click CLI (commands.py:2024 L)
        └── PipelineExecutionService (execution.py)
              └── StepExecutor (step_executor.py)
                    └── for agent in workflow:
                          ├── Agent.run() (12 个独立 main.py)
                          │     ├── LLM 决策
                          │     └── ToolHub.call(tool)
                          │           └── 真实 EDA 工具 (dvsim/VCS/Jinja2/...)
                          ├── Manifest.record()
                          ├── EvidenceChain.append()
                          └── Checkpoint.save()
                    
                    └── return EvidencePackage
```

**核心理念：** 12 个专职 LLM Agent + 真实 EDA 工具 + 证据链 + 断点续跑 + 23 个命令组。

---

## 一、架构哲学：两种世界观

| 维度 | 原型 | 当前 SignOffAI | 分析 |
|------|------|---------------|------|
| **世界观** | "流程是一组有序的工具调用" | "流程是一群专业 Agent 的协作" | 原型把问题看成**过程编排**；当前把问题看成**智能体协作**。这两种世界观不是对立的，但决定了后续所有设计选择 |
| **复杂度来源** | 工具的数量和审批规则 | Agent 的数量、LLM prompt、工具链深度 | 原型的复杂度是 O(n_tools)；当前的复杂度是 O(n_agents × n_tools × n_llm_calls) |
| **设计目标** | "让一个工程师能跑通一条验证流程" | "让验证变成可复现、可审计、可治理的工程平台" | 原型是**工具**；当前是**平台**。这两种目标对应的代码量级差 100 倍是合理的 |
| **核心约束** | 每个阶段必须人工确认 | LLM 自动决策 + 事后审计 | 原型**不信任自动化**（4/8 阶段需审批）；当前**信任 AI 但保留证据** |

### 一句话总结

> **原型是 "流水线 + 审批" 模式——面向项目经理。**
>
> **当前是 "多 Agent + 证据链" 模式——面向验证工程师。**

---

## 二、流程粒度：8 阶段 vs 12 Agent

### 2.1 一一对照映射表

| 原型阶段 | 对应当前 Agent | 粒度差异 |
|---------|---------------|---------|
| RTL 编译 | `write_rtl` 的一个子步骤 | 原型：1 阶段 → 当前：1 Agent 包含编译检查 |
| UVM 环境编译 | `verify_architect` 的一个子步骤 | 同上 |
| 时序约束检查 | **无对应**（当前在 assertion_engineer 里隐式处理） | 原型有，当前缺失！ |
| Smoke 测试 | `regression_manager` 的子集 | 当前把 smoke 和全量回归混在一起 |
| 测试用例生成 | `test_engineer` | ✅ 粒度匹配 |
| 全面回归执行 | `regression_manager` | ✅ 粒度匹配 |
| 覆盖率分析 | `coverage_manager` | ✅ 粒度匹配 |
| 签核证据包生成 | `report_generator` | ✅ 粒度匹配 |

### 2.2 关键差异

| 原型有、当前缺失的 | 当前有、原型缺失的 |
|-------------------|-------------------|
| **时序约束检查**（独立阶段） | **spec_planner**（规格分析→测试计划） |
| **人工审批门控**（4 个 gate） | **design_architect**（模块层次+寄存器） |
| | **model_agent**（C++ 参考模型） |
| | **assertion_engineer**（SVA 断言） |
| | **debug_engineer**（失败分析） |
| | **quality_assurance**（代码审查） |

### 2.3 粒度判断

**原型的问题：太粗。** "RTL 编译"和"UVM 环境编译"只是编译——在那之前，RTL 和 UVM 环境是哪来的？原型假设 **RTL 已经存在**，所以只需要编译检查。这是一个"验证执行框架"，不是"验证生成框架"。

**当前的问题：太细。** 12 个 Agent 对简单模块（比如一个只读寄存器）是过度设计。一个 50 行的寄存器模块跑 12 个 Agent 就像用猎枪打蚊子。

**正确的粒度应该是可变的——原型用 `task_type` 参数（fast_qa=4 阶段，final_signoff=8 阶段）实现了这一点。** 当前架构的 `_WORKFLOW_PHASE_MAP` 在设计上支持工作流裁剪，但还没暴露给用户。

---

## 三、编排模式：单 Planner vs 多 Agent 流水线

这是两个架构最本质的差异。

### 3.1 原型的 PlannerAgent

```python
class PlannerAgent:
    def plan(self, spec) -> Dict:
        for stage in stages:
            result = tool(ctx)       # 调工具，收集结果
            if stage.approval:       # 问人
                input()
        return spa                   # 输出一份 JSON
```

**特征：**
- **单 Agent 负责全部决策**：选哪个工具、按什么顺序、结果怎么解读
- **Agent 不做推理**：它只是一个循环控制器，不调用 LLM
- **智能在哪里？** 在 `build_stages()` 函数里——"fast_qa 跑 4 个阶段，final_signoff 跑 8 个"——这是**规则驱动的智能，不是 LLM 驱动的智能**

### 3.2 当前的 12-Agent 流水线

```python
class PipelineExecutionService:
    def execute(self, workflow) -> EvidencePackage:
        for agent in workflow:
            agent_output = agent.run(ctx)   # Agent 内部调用 LLM + 工具
            manifest.record(agent_output)
            evidence.append(agent_output)
            checkpoint.save()
        return evidence_package
```

**特征：**
- **多 Agent 分步决策**：每个 Agent 有自己的 prompt、工具集、输出契约
- **Agent 调用 LLM 做推理**：每个 Agent 内部是 LLM + Tool 的循环
- **智能分布在各 Agent 的 prompt 里**：spec_planner 有"如何分析 Spec"的知识，debug_engineer 有"如何定位根因"的知识

### 3.3 对比表

| 维度 | 原型（单 Planner） | 当前（多 Agent） |
|------|-------------------|-----------------|
| **决策者** | 1 个 Planner | 12 个 Agent (每个有独立 LLM) |
| **决策方式** | 规则 `build_stages()` | LLM prompt + Tool calling |
| **智能水平** | 低（只有路由逻辑） | 高（每步有领域推理） |
| **可解释性** | 极高（调度逻辑就是代码） | 中（prompt 可读，但 LLM 推理过程不透明） |
| **可维护性** | 极高（改 `build_stages()` 就改全流程） | 中（改流程要动多个 Agent + execution.py） |
| **失败处理** | 人工审批时拒绝 = 终止 | checkpoint 断点续跑 + retry-failed |
| **并行能力** | 0（单线程 for 循环） | 0（当前也是串行，但架构允许并行） |

### 3.4 原型在这里赢了什么

原型把一个关键概念表达得非常干净：

```python
ctx = {"spec": spec_content, "_history": [], "_approvals": []}
```

**`ctx` 是贯穿全流程的共享状态字典。** 每个阶段读写同一个 `ctx`，`_history` 记录每一步做了什么，`_approvals` 记录每一步人工决策。这个概念在当前架构里被拆成了 4 个模块（`context.py` + `manifest.py` + `evidence.py` + `checkpoint.py`），数据流变得复杂得多。

**原型的 `ctx` 字典 + `_history` 列表 = 当前架构 500+ 行 context/manifest/evidence 代码的核心思想。** 复杂性的增加是因为要处理 LLM 的不确定性、断点续跑、增量更新的场景——但思想是一样的。

---

## 四、工具模型：占位符 vs 真实 EDA 集成

### 4.1 原型的工具层（50 行）

```python
class ToolRegistry:
    def register(self, name, func): ...
    def get(self, name) -> Callable: ...

def compile_rtl(ctx) -> Dict:
    return {"status": "PASS", "log": "Mock: RTL compile passed"}  # 占位！
```

- 8 个工具，全部返回 `{"status": "PASS", ...}`
- 注册表是 Python dict
- 无 schema 校验、无超时、无沙箱、无版本管理

### 4.2 当前的工具层（~3,000 行）

```
src/core/tool_protocol.py   → ITool 协议定义
src/core/tool_system.py     → ToolSchema + Permission + ProjectMemory
src/core/tool_hub.py        → 统一注册中心
src/core/tool_sandbox.py    → 隔离执行（超时/资源/子进程）
src/core/tool_orchestrator.py → 声明式编排 DSL
src/tools/                  → 30+ 个真实工具实现
```

- 30+ 个真实工具（VCS 编译、dvsim 回归、Jinja2 渲染、DPI-C 编译...）
- Schema 契约 + 输入输出验证 + 风险分级
- 隔离执行（超时 kill、资源限制）
- 工具发现 + 直接调用（`vagent tool call`）

### 4.3 对比

| 维度 | 原型 | 当前 |
|------|------|------|
| **真实性** | Mock（全返回 PASS） | 真实 EDA 工具集成 |
| **可靠性** | N/A（mock 没有失败场景） | 有超时/重试/沙箱隔离 |
| **安全性** | 无（直接 exec） | 风险分级 + 沙箱 |
| **可发现性** | `registry.list_tools()` | `tool_hub.list()` + `vagent tool list` |
| **版本管理** | 无 | ToolManifest 含版本号 |

### 4.4 判断

**这不是优劣对比，是开发阶段不同。** 原型处于 Phase 0（概念验证），所有工具都是占位符是正确的做法——先验证流程跑得通，再替换真实工具。当前架构处于 Phase 1-2（工程落地），占位符已经替换为真实 EDA 集成。

**但原型有一个优点：** 工具函数签名极其简单——`def compile_rtl(ctx: Dict) -> Dict`。统一输入是 `ctx` 字典，统一输出是 `{"status": "PASS/FAIL", ...}` 字典。当前架构的 `ITool` 协议要定义 schema、manifest、权限——更强大也更重。**对于简单工具，原型的"ctx 进，dict 出"可能是更好的接口设计。**

---

## 五、人工审批：最关键的差异

### 5.1 原型的人工审批

```python
if stage.get("requires_approval", False):
    user_input = input(f"确认 {stage['name']} 通过并继续？ (y/n/q): ")
    if user_input == 'n':
        return ctx   # 终止流程
```

**4 个审批点：** RTL 编译、UVM 环境编译、时序检查、Smoke 测试——全部在前半段。后半段（测试生成→回归→覆盖率→签核）全自动。

**设计逻辑：** "前半段是环境搭建，错不起，需要人看一眼。后半段是执行层，可以自动化。"

### 5.2 当前的人工审批

**当前架构没有内建的人工审批机制。** CLI 里有 `vagent verify` 全部自动化跑完，没有中间停下来让人确认的步骤。治理能力体现在事后审计（`vagent dump` + `vagent signoff --verify`）而不是事中审批。

### 5.3 对比

| 维度 | 原型 | 当前 |
|------|------|------|
| **审批模式** | 同步阻塞（`input()`） | 无（事后审计） |
| **审批粒度** | 阶段级（4 个 gate） | N/A |
| **审批决策** | 人直接 y/n/q | 人读 signoff 报告后判断 |
| **适用场景** | 单人工位，人在终端前 | 无人值守 + 事后审查 |
| **CI 兼容性** | ❌ `input()` 会卡住 CI | ✅ 完全可自动化 |

### 5.4 判断

**原型的人工审批是它最有价值的贡献。** 当前架构完全没有这个机制，这是一个功能缺口。

但 **`input()` 阻塞式审批太粗糙了**。更好的设计（原型值得学习 + 当前应该加上的）：

```python
# 介于两者之间的设计 —— 当前架构应该实现的
class ApprovalGate:
    """支持三种模式的审批门控"""
    MODE_INTERACTIVE = "interactive"   # 终端 input()
    MODE_AUTO = "auto"                 # CI 模式，全自动
    MODE_THRESHOLD = "threshold"       # 只有风险 > 阈值才审批

# CLI 使用
vagent verify --approval-mode interactive   # 原型的方式
vagent verify --approval-mode auto          # 当前的方式（默认）
vagent verify --approval-mode threshold --risk-threshold high  # 折中
```

**这正是你的 CLAUDE.md 路线图 Phase 3（个人级治理）该包含的功能。**

---

## 六、输出物：SPA JSON vs 证据链 Manifest

### 6.1 原型的输出：一份 JSON

```json
{
  "spa_id": "spa_abc123",
  "task_type": "fast_qa",
  "stages_executed": ["RTL 编译", "UVM 环境编译", ...],
  "history": [
    {
      "stage": "RTL 编译",
      "tool": "compile_rtl",
      "timestamp": "2026-08-09T...",
      "result": {"status": "PASS", "log": "..."}
    }
  ],
  "approvals": [
    {"stage": "RTL 编译", "decision": "approve", "timestamp": "..."}
  ]
}
```

**SPA (Signoff Package Artifact)** 是一个扁平 JSON——把所有历史、审批、覆盖率、回归结果平铺在里面。

### 6.2 当前的输出：证据链 + Manifest + 签核报告

```
output_jiang_20260809_143022/
├── manifest.json          ← 每个阶段的输入输出 hash + 工具版本
├── evidence_chain/
│   ├── L1_spec_planner/   ← 5 层证据链
│   ├── L2_design_architect/
│   └── ...
├── artifacts/
│   ├── rtl/*.sv
│   ├── uvm/*.sv
│   └── tests/*.sv
├── coverage/
├── regression/
├── debug/
└── signoff_report.html     ← 最终签核报告
```

### 6.3 对比

| 维度 | 原型 SPA JSON | 当前 EvidenceChain |
|------|-------------|-------------------|
| **完整性** | 一份 JSON 包含全部 | 目录树 + 多份文件 |
| **可追溯性** | 有时间戳、有审批记录 | 有 hash、有输入输出 manifest |
| **可复现性** | ❌ 没有记录工具的版本和输入 hash | ✅ `vagent dump` 可复现 |
| **可审计性** | ⚠️ 审计员能看懂 JSON，但无法验证真伪 | ✅ hash 链可验证 |
| **可移植性** | ✅ 一份 JSON，随便拷 | ⚠️ 目录树 + DB 记录 |
| **人类可读性** | ✅ `vagent show spa.json` 几行搞定 | ⚠️ 需要多个命令才能看清 |

### 6.4 原型在这里赢了什么

**原型的 SPA JSON 是一个"扁平快照"——所有信息在一份文件里。** 这对快速分享和审查非常友好。当前架构的证据链更完整更可信，但"看一眼就明白"的能力不如原型。

**借鉴点：** 当前的 `report_generator` 应该能输出一份类似原型 SPA 格式的"摘要 JSON"——不替代完整证据链，但给人一个快速概览。

---

## 七、CLI 设计：argparse 30 行 vs Click 2000 行

### 7.1 原型

```python
# 两个子命令，30 行
parser_plan = subparsers.add_parser("plan", ...)
parser_plan.add_argument("--task-type", choices=["fast_qa", "final_signoff"], ...)
parser_plan.add_argument("--spec", required=True, ...)
parser_plan.add_argument("--output", default="spa.json", ...)

parser_show = subparsers.add_parser("show", ...)
```

**两个命令：** `plan`（跑流程）和 `show`（看结果）。

### 7.2 当前

```python
# 23 个命令组，50+ 子命令，2024 行
vagent verify --workflow/--step/--json/--resume/...
vagent signoff generate/export/verify/checklist/diff
vagent diff coverage/spec/regression
vagent tool list/show/call/history
vagent debug log/analyze/repl
# ... 等等
```

### 7.3 对比

| 维度 | 原型 | 当前 |
|------|------|------|
| **学习成本** | 2 个命令，5 分钟上手 | 50+ 命令，需要文档 |
| **功能密度** | 低（只做两件事） | 高（可以做 50+ 件事） |
| **错误提示** | argparse 默认 | Click + Rich 美化 |
| **CI 友好性** | ⚠️ 无 JSON 输出模式 | ✅ `--json` + 标准退出码 |
| **可扩展性** | 加命令 = 加一个 `subparser` | 加命令 = 加一个 `@cli.group()` |

### 7.4 判断

**原型的 CLI 在它的 scope 里完全够用。** 2 个命令 + 3 个参数 = 完美的 CLI。当前 CLI 的复杂性是因为功能域扩大了 25 倍。

**但原型给了当前架构一个警示：** `vagent plan` 这个命令当前不存在！原型只需要 `plan --spec xxx.md --task-type fast_qa` 就能跑起来——这种"一条命令出结果"的体验，当前架构反而丢了。

---

## 八、LLM 集成：无 vs 深度嵌入

### 8.1 原型的"智能"

```python
def build_stages(task_type: str) -> List[Dict]:
    if task_type == "fast_qa":
        return base        # 4 阶段
    if task_type == "final_signoff":
        return base + full # 8 阶段
```

**智能是硬编码的规则。** PlannerAgent 不做推理，只做路由。这注定了它处理不了以下场景：
- "这个 Spec 描述的是一个 UART，不是 APB bridge，我应该用不同的阶段吗？" → 规则无法判断
- "覆盖率 85%，但不达标的部分都是 corner case，能不能签？" → 规则无法判断
- "RTL 编译报了一个 warning，严重不严重？" → 规则无法判断

### 8.2 当前的 LLM 智能

每个 Agent 有独立的 system prompt + 工具集。比如 `debug_engineer`：

```
SYSTEM: 你是一个 IC 验证调试专家。给定仿真日志和覆盖率报告，
        定位失败根因并判断是 RTL bug 还是环境 bug。
        可用工具：read_log, parse_waveform, compare_expected...
```

**LLM 能处理原型处理不了的场景**——但代价是延迟、Token 消耗和不确定性。

### 8.3 对比

| 维度 | 原型（零 LLM） | 当前（深度 LLM） |
|------|-------------|----------------|
| **启动成本** | 0 | 每个 Agent 1-3s 的 LLM 调用 |
| **上限能力** | 低（只能做预定义的事） | 高（可处理未建模场景） |
| **可靠性** | 100% 确定性 | ~90%（LLM 可能幻觉） |
| **处理歧义** | ❌ 做不到 | ✅ 天然擅长 |
| **Token 成本** | 0 | 每次流水线 ~30K-65K tokens |

---

## 九、全局对照表

| 维度 | 原型 | 当前 SignOffAI | 谁更好 | 为什么 |
|------|------|---------------|--------|--------|
| **流程编排** | 单 Planner 硬编码 | 多 Agent LLM 驱动 | ↑ 当前 | LLM 能处理原型处理不了的场景 |
| **人工审批** | 4 个 `input()` gate | 无 | ↑ 原型 | 原型有审批，当前没有——这是功能缺口 |
| **工具真实性** | 8 个 Mock 占位符 | 30+ 真实 EDA 工具 | ↑ 当前 | 不在一个开发阶段 |
| **输出可复现性** | ❌ | ✅ hash + manifest | ↑ 当前 | 这是项目的核心差异化 |
| **输出可读性** | ✅ 一份 JSON | ⚠️ 目录树 + DB | ↑ 原型 | 原型更直观，当前应补充摘要 JSON |
| **简单性** | 300 行，全在单文件 | 30000+ 行，150+ 文件 | ↑ 原型 | 对于简单模块，当前是过度设计 |
| **功能深度** | 只能跑预定义流程 | 能生成 RTL/UVM/Test/Assertion | ↑ 当前 | 不在一个量级 |
| **CLI 上手难度** | 2 个命令 | 50+ 命令 | ↑ 原型 | 当前缺 `vagent plan` 这种一行命令 |
| **CI 兼容性** | ❌ `input()` 卡住 | ✅ `--json` + 退出码 | ↑ 当前 | 原型需要加 `--non-interactive` |
| **任务类型切换** | ✅ `--task-type fast_qa/final_signoff` | ⚠️ workflow 切换不直观 | ↑ 原型 | 当前应加 `--profile` 参数 |
| **失败恢复** | ❌ 失败 = 重头来 | ✅ checkpoint 断点续跑 | ↑ 当前 | 长流程必备 |

---

## 十、互相可以学什么

### 10.1 原型 → 当前架构（5 个应该借鉴的设计）

| 原型的做法 | 当前应该怎么做 |
|-----------|-------------|
| **`--task-type fast_qa/final_signoff`** — 一条命令切流程 | 加 `vagent verify --profile simple/full/deep` 参数，对标 `_WORKFLOW_PHASE_MAP` |
| **`input("y/n/q?")` 人工审批** — 4 个审批门控 | 加 `vagent verify --approval interactive/auto/threshold`，填补治理功能缺口 |
| **SPA JSON 单文件输出** — 一份 JSON 看清全貌 | `report_generator` 加一个 `--format summary-json` 输出模式 |
| **`cmd_show(spa.json)` 快速查看** — 2 秒看清结果 | 当前 `vagent status` 太弱，应增强为 `vagent show <run_id>` |
| **300 行单文件，零外部依赖** — 极致简单 | 发布一个 `signoffai-lite` 精简版，只含核心流程（不依赖 langchain） |

### 10.2 当前架构 → 原型（5 个原型缺失的能力）

| 当前的做法 | 原型为什么需要 |
|-----------|-------------|
| **LLM 驱动的 spec_planner** — 从自然语言 Spec 提取测试点 | 原型假设测试点已经存在，但实际 Spec 是自然语言 |
| **checkpoint 断点续跑** — 失败不重来 | 原型一停全停，8 阶段跑一半失败 = 从头开始 |
| **证据链 hash 验证** — 保证不可篡改 | 原型 SPA JSON 可以手动修改，没有防篡改机制 |
| **真实 EDA 工具集成** — VCS/dvsim/Jinja2 | 原型 Mock 工具跑得通流程但教不了你真东西 |
| **`tool_protocol.py` 工具契约** — schema 校验 + 风险分级 | 原型 `ctx in, dict out` 没有契约，工具坏了也不知道 |

---

## 十一、核心结论

### 这两个架构不是"谁取代谁"的关系

它们处于**不同的开发阶段**、**面向不同的使用场景**、解决**不同层次的问题**：

```
原型 ──────────────────────────→ 当前架构
 │                                │
 │  概念验证（Phase 0）             │  工程落地（Phase 1-2）
 │  占位工具                        │  真实 EDA 集成
 │  单 Agent 规则调度               │  多 Agent LLM 推理
 │  人工审批主导                    │  事后审计主导
 │  2 个 CLI 命令                   │  50+ CLI 命令
 │                                  │
 └── 共同的内核 ────────────────────┘
     • 分阶段执行
     • ctx 共享状态
     • _history 记录每一步
     • 工具注册表 + 按需调用
     • 最终输出签核包
```

### 原型定义了"签核流水线的骨架"——当前架构在这个骨架上加了肉（LLM）、加了血管（证据链）、加了神经（50+ CLI）。

### 但原型有 3 样东西是当前架构丢了的：

1. **人工审批门控** — 当前完全没有，应该补上
2. **`--task-type` 快速切换** — 当前有 `_WORKFLOW_PHASE_MAP` 但没暴露给用户
3. **单文件 JSON 输出** — 当前目录树 + DB 太重，应补充摘要 JSON 格式

### 补上这 3 样东西，就是原型和当前架构的最佳融合。
