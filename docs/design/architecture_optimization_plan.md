# SignOffAI 架构优化方案

> **文档性质**：实施方案（不是评估报告）。每一项都给出问题、证据、改法、验证方式。
>
> **依据**：对当前分支 `refactor/langgraph-migration` 的静态通读 + 逐点核验。
> 所有结论均带 `file:line`。**文中标记 ⚠️ 的判断未经运行时验证**，动手前需按第 6 节做基线确认。
>
> **配套文档**：`docs/design/langgraph_multiagent_refactor_review.md`（对外部提案的评估）
>
> 日期：2026-10-08

---

## 0. 结论摘要

**一句话**：架构骨架是对的，**不需要换设计，需要补收尾**。

| | |
|---|---|
| ✅ 已经做对的 | L1 零 LLM 确定性层 / 决策边界（`HARD_ACTIONS` 不走 RL）/ LLM 围栏范例（`_is_valid_rtl`）/ Stage 与 Agent 的正交划分 / 证据链与治理设施 |
| 🔴 三个断链 | HITL（审批只有 GUI 能触发）/ 规则闭环（`mark_accepted` 只有 GUI）/ Token 预算（4 处裸调绕过 `query_engine`） |
| 🟠 四个静默 | `analyze_specification` 静默填 `"dut"` 等 —— 这才是"跑不通"的真因 |
| ⚪ 一批冗余 | 死代码 / `tool_system.py` 重复实现 / `langchain_classic` 隐性依赖 / 跨板块反向依赖 / 巨型文件 |

**主轴：三个断链。** 它们直接打击 CLAUDE.md 的四个支柱（可复现 / 可审计 / 可治理 / 可交付），
且**都是"能力建好了、代码写好了，只差接线"**。

---

## 1. 现状基线（已核验的事实）

### 1.1 分层骨架

```
src/
├── cli/          5.4k 行    交付面（commands.py 单文件 5061 行 / 49 命令）
├── layers/
│   ├── l1_infrastructure   2.9k  零 LLM 确定性层：EDA/编译/覆盖率/Git/文件
│   ├── l2_orchestration    8.9k  LangGraph 闭环图 + Agent + 工具总线 + 治理 + 证据链
│   ├── l3_decision         2.0k  规则引擎（硬编码优先级链）+ RL + 知识图谱
│   ├── l4_memory           4.6k  SQLAlchemy 持久化 + 各类 registry
│   └── l5_evolution        0.4k  经验蒸馏（debug→fix 模板 / gap→策略 / 效果→权重）
├── agents/       3.8k 行    8 个 Agent
├── tools/       37.9k 行    18 个工具域
└── workbench/   24.8k 行    PySide6 桌面 GUI（活代码，与 CLI 无业务逻辑重复）
```

**层间依赖不是严格单向**，有 3 处反向依赖（均靠函数内延迟 import 遮掩）：

| 违规 | 位置 |
|---|---|
| L1 → L2 | `l1_infrastructure/golden_baseline.py:149` |
| L1 → L4 | `l1_infrastructure/infrastructure.py:532` |
| L3 → L5 | `l3_decision/decision_engine.py:247` |

真实拓扑是：**L4 是被全员依赖的底座**，L5 被 L2/L3 反向依赖。

### 1.2 图与 Stage：24 节点 / 8 Agent / 14 框架节点

`stages.py` 是节点元数据的**唯一来源**，定义 `StageSpec`：

```python
@dataclass(frozen=True)
class StageSpec:
    id: str            # 与 graph.py 的节点名一一对应
    title: str         # 中文显示名
    group: str         # control/design/verify/exec/analysis/converge/signoff
    agent: str = ""    # 归属 agent role（""=框架节点）
    round_scoped: bool = False
    summary_key: str = ""
```

| 分组 | Stage |
|---|---|
| control | `init`, `round_bump` |
| design | **`front`**, **`design`**, **`model`** |
| verify | **`verify`**, **`env_arch_check`** |
| exec | **`ops`** |
| analysis | **`coverage`**, **`debug_functional`** |
| converge | **`decide`**, `governor`, `governor_retry`, `approval`, `record_decision`, `apply_converge`, `apply_compile_retry`, `refactor_rtl`, `apply_update_model`, `apply_directed_test`, `apply_relax`, `apply_expand_seeds` |
| signoff | **`audit`**, `finalize` |

**24 Stage = 10 有 agent 归属 + 14 框架节点；8 个不同 Agent。**

（`decide` 与 `coverage` 都归 `coverage` agent —— **一个 Agent 服务多个 Stage**，这是 Stage ≠ Agent 的铁证。）

> ⚠️ 小问题：`stages.py` docstring 说「闭环图 **23** 个节点」，实际 **24** 个。`tests/test_stages.py` 钉住了两表一一对应，所以只是注释漂移。

### 1.3 澄清：节点不是 Agent，这**不是**问题

LangGraph 的节点是普通 callable，官方明确支持三类：**纯函数 / LLM 调用 / 完整 agent**。

**你的 24 个节点实际的分布：**

| 类型 | 数量 | 节点 |
|---|---|---|
| **纯函数**（不碰 agent） | 12 | `init`, `env_arch_check`, `round_bump`, `decide`, `governor`, `governor_retry`, `approval`, `record_decision`, `apply_converge`, `apply_relax`, `apply_expand_seeds`, `finalize` |
| **调 agent**（经 `_run_agent`） | 12 | `front`, `design`, `model`, `verify`, `ops`, `coverage`, `debug_functional`, `audit`, `apply_compile_retry`, `refactor_rtl`, `apply_update_model`, `apply_directed_test` |

**而且 `_run_agent` 本身也是确定性的**（`graph.py:161`）：它调 `agent.execute_task()`，然后跑
`governor.after_action()`（熔断计数）、`_quality_check()`（质量门禁）、`_record_agent_files()`
（证据链）。**节点负责的是"调哪个执行器、怎么校验、怎么留证"——全是确定性逻辑。**

**所以**：不需要为了"符合 LangGraph 用法"把节点改成 agent。反过来，若改成 LLM 驱动节点选择，
就是用 LangGraph 写出了 AgentExecutor 的效果，**白丢可复现性**。

### 1.4 LLM 的真实分布（9 处）

**唯一构造点**：`llm_factory.py:311 ChatOpenAI(**kwargs)`
（`llm_factory.py:323 ChatAnthropic` 是死分支 —— `langchain_anthropic` 未安装未声明）

**两条通道并存**：

```
通道 A（有治理）  LLMQueryEngine.query()          ← query_engine.py:104-106
                    └─ 唯一调用方 _call_llm_raw   ← llm_custom_logic.py:113
通道 B（无治理）  LLMFactory.create_for_task
                    └─ llm.invoke()               ← llm_refine.py:22-24
```

| # | 位置 | 通道 | 触发条件 | 干什么 |
|---|---|---|---|---|
| 1 | `design/main.py:283` | ✅ A | 每次生成 IP RTL | LLM 写 SystemVerilog 功能逻辑 |
| 2 | `design/main.py:395` | ✅ A | 每次生成 top | LLM 实例化 IP + 按端口名连线 |
| 3 | `coverage_tools/main.py:217` | ✅ A | 生成自定义覆盖逻辑 | LLM 写 drive/sample 逻辑 |
| 4 | `tool_find_spec_yaml/main.py:224` | ✅ A | 找 spec/yaml | LLM 解析定位 |
| 5 | `debug/main.py:635` | ❌ B | 模板无匹配 + 有错 | LLM 重写出错文件 |
| 6 | `execution.py:469` | ❌ B | 同上（执行层入口） | LLM 修复编译/仿真错误 |
| 7 | `llm_refine.py:339` | ❌ B | 仿真时序问题 | LLM 精修 timing |
| 8 | `debug/main.py:366` → `base.py:586` | ❌ C | `unique_errors > 0` | LangChain `AgentExecutor` 根因分析 |
| 9 | `llm_factory.py:424` | — | 探活 | 连接测试（非业务） |

**#7 的完整链路（三层）：**
```
tool_orchestrator.py:515  PipelineStep(tool="quality_report")
  → agent_tools.py:37     @tool("quality_report")
    → tool_quality_report/main.py:10  generate_quality_report
      → quality_report.py:100         llm_refine_sim_timing
        → llm_refine.py:339           call_llm   ← 真正的调用
```

**要点**：`design` 的两处（#1 #2）**每次跑都必调**，是 RTL 生成的主力路径。
LLM 决定你的 DUT 长什么样 —— 这不是"完形填空"，是核心生成。
（这也是为什么 `design` 的 prompt 写得最细、且有 `_is_valid_rtl()` 兜底。）

### 1.5 工具线现状

| | L1 | uvm_tools |
|---|---|---|
| 含 LLM | ❌ **确认零 LLM**（仅注释提及） | ⚠️ **仅 `tool_find_spec_yaml/main.py` 一个文件** |
| 对外能力 | `setup` / `compile` / `run_regression` / `simulate` / `collect_coverage` / `collect_waveform` / `archive_coverage` / `archive_rtl` / `git_tag` / `verify_reproducible` | `jinja_render` / `read_file` / `write_file` / `find_spec_yaml` / `check_static` / `check_compile` / `check_loopback` / `check_health` / `quality_report` / `testrun` / `uvmtestgen` / `sc_red` / `uvm` |

> ⚠️ **L1 没有 `lint` / `check_syntax`**（grep 为空）。
> ⚠️ **`file_audit` / `manifest` / `five_layer` 在 L2**（`l2_orchestration/evidence/`），**不在 L1**。

---

## 2. 核心诊断

### 2.1 主轴：三个断链

**三者的共同点：能力全部写好了，但 CLI 够不到 / 流量没走收口。**
而 CLI 是本项目的唯一交付面（CLAUDE.md：禁止 Web 前端）。

---

#### 断链 1：HITL —— 人工审批只有 GUI 能触发

**证据链**：

```
interrupt() 的触发条件  →  rt.interrupt_mode            graph.py:1086
interrupt_mode 的来源   →  saver is not None            execution.py:649
saver 的来源            →  只有 run_closed_loop_streaming 传了  execution.py:651
run_closed_loop_streaming 的调用者 → 只有 RunService（GUI）  run_service.py:467
```

**入口覆盖矩阵**：

| 入口函数 | 调用它的命令 | checkpointer | interrupt |
|---|---|---|---|
| `run_closed_loop`（`execution.py:488`） | `vagent run`(`commands.py:229`) / `ci verify`(`:2658`) / `multi`(`:421`) / REPL(`repl.py:196`) | ❌ | ❌ 阻塞式 gate |
| `run_closed_loop_streaming`（`execution.py:575`） | GUI / `RunService` | ✅ | ✅ |

**而且 `vagent approve/reject` 完全不驱动图**（`commands.py:4117-4150`）：

```python
approval = {"action": "approve", "reason": reason, "at": ..., "run": rid}
(run_dir / "approval.json").write_text(json.dumps(approval, ...))
```

**它只往 run 目录写一个文件——是审计记录，不是恢复机制。** 看起来像 HITL 闭环，实际是断的。

**打击支柱**：可治理（审批暂停/恢复）、可复现（从中间态重放）。
**后果**：CLAUDE.md 里「可治理」这张牌，在 CLI 上是**假**的。

---

#### 断链 2：规则闭环 —— 规则库"从失败里长"断在最后一步

`rule_draft.py` 自述：「**让规则库"从失败里长"，而不是只靠人手写**」

| 环节 | 状态 | 证据 |
|---|---|---|
| 失败 → 自动写草案 | ✅ 通 | `graph.py:730-734` `drafts_from_triage` + `write_drafts` |
| 按指纹去重 | ✅ 通 | `write_drafts` 内部 |
| 草案 → 可粘贴的 `@rule` 骨架 + 测试骨架 | ✅ 通 | `flow_tools/api.py:1586` `rule_skeleton(d)` |
| **人接受草案** | 🔴 **断** | `mark_accepted`（`rule_draft.py:189`）**唯一调用者是 `workbench/modules/flow/drafts/module.py:141`** |
| **CLI 入口** | 🔴 **不存在** | `grep draft src/cli/commands.py` → 空 |

**打击支柱**：可治理。
**注意**：这与断链 1 **是同一个病** —— 两个核心治理动作（审批、接受规则）都只有 GUI 能触发。

---

#### 断链 3：Token 预算 —— 4 处裸调绕过收口

`LLMQueryEngine` 是设计来管 token 预算的（`query_engine.py:67-72` 超限直接返回空串）。
但第 1.4 节的 #5 #6 #7 #8 **根本不经过它**。

| 通道 | 位置数 | 预算 | 缓存 | 审计 |
|---|---|---|---|---|
| A（query_engine） | 4 | ✅ | ✅ | ✅ |
| B（裸调 invoke） | 3 | ❌ | ❌ | ❌ |
| C（AgentExecutor） | 1 | ❌ | ❌ | ❌ |

**后果**：预算只管住一半流量。而 #5 #6 #7 恰好是**最容易失控的点**——
它们是"出错后的兜底重试"路径，本来就可能在循环里反复触发。

**打击支柱**：可治理（Token 预算）。

---

### 2.2 四个静默 —— 这才是"跑不通"的真因

**"跑不通"不是因为流程是确定性的，是因为系统在覆盖不到时静默给默认值。**

| # | 位置 | 现状 | 危险度 |
|---|---|---|---|
| 1 | `spec_tools/main.py:42` | 正则解不出 design_name → **静默填 `"dut"`** | 🔴 **入口，错误全链传播** |
| 2 | `design/main.py:56` | `analyze_specification` 抛异常 → 静默 `{"design_name": "dut"}` | 🔴 |
| 3 | `decision_engine.py:466` | 归因不出 bug 类别 → 静默 `FIX_FUNCTIONAL` | 🟡 |
| 4 | `decision_engine.py` `verification_plan` | 未知根因 → 静默用最保守计划 | 🟡 |

**第 1 条最要命**。`front/main.py:88` 的注释已经意识到了这件事：

> 「**没有输入就别往下走** —— 静默给一个 `design_name: dut` 会让后面整条链在一个不存在的设计上跑，
> 最后报一堆看不懂的错。」

但 `front` 只挡住了**空输入**。给一个非空、但格式没见过的 spec，`analyze_specification`
照样静默变 `dut`（`spec_tools/main.py:42` 的 `or "dut"`），然后全链在一个不存在的设计上跑。

**结论**：修法不是"提高灵活性"，是**让系统响亮地说"我覆盖不到"**，
然后把这个缺口变成可学习的对象（接回断链 2）。

---

### 2.3 冗余清单

| 类别 | 内容 | 证据 |
|---|---|---|
| **隐性依赖** | `langchain_classic`（`base.py:12` 顶层 import，**未在 requirements/pyproject 声明**） | 靠 langchain 1.x 传递依赖装入 |
| **死代码** | `src/core/`（`registry.py:5` import 不存在的 `src.core.base` → 一 import 就炸） | 全仓无引用 |
| | `src/tools/scmodel_tools/` | 空目录 |
| | `src/tools/uvm_tools/_tools_old.py` | 1753 行，是 `lib/llm_refine.py` 的旧副本；仅 `commands.py:3360` 引用其两个**非 LLM** 函数 |
| **重复实现** | `tool_system.py` vs `tool_hub.py` | 两套注册表 / 三处 schema 校验 / **两个同名 `wrap_agent_tools`**（`tool_hub.py:385` vs `tool_system.py:592`） |
| **跨板块反向依赖** | `cmodel_tools` → `uvm_tools.tool_uvm.gen_uvm.JinjaRenderer` | `gen_cmodel.py:62`、`dpi_compile.py:28` |
| **巨型文件** | `commands.py` 5061 / `gen_uvm.py` 3590 / `graph.py` 1741（**建图仅约 90 行**） | — |
| **失效抽象** | `base.py:252-273` 三岔路口：`_executor` 分支仅 debug 可达；`_direct_chain` 分支**彻底死**；`_offline_result` 两个调用点几乎不可达 | 7/8 agent 的 `_get_prompt_template()` 返回 `None` |
| **未挂载** | `state.py:39` `exclusive` reducer（定义了但无字段 `Annotated` 引用） | — |
| | `graph.py:1650` `store` 形参（有 API 但无调用者传值） | — |
| **风险分级虚设** | 46 处 `@tool` 仅 3 处标了 `ToolRisk.WRITE` | `regression_tool.py` |
| **无强制分层** | 所有 `__init__.py` 为空，无 re-export，无依赖方向测试 | — |

---

## 3. 目标架构

### 3.1 六条原则

| # | 原则 | 理由 |
|---|---|---|
| **P1** | **L1 永远零 LLM** | 它是"可复现"的锚。已成立，守住。 |
| **P2** | **流程控制必须确定性，LLM 只进具体节点内部** | 流程不确定 = 不可复现 + 不可审计。 |
| **P3** | **每个 LLM 调用点必须有契约校验围栏** | 范例：`design._is_valid_rtl()`。 |
| **P4** | **覆盖不到时响亮失败，不静默降级** | 静默降级是"跑不通"的真因。 |
| **P5** | **治理能力必须 CLI 自足** | CLI 是唯一交付面。GUI 只能是可选适配器。 |
| **P6** | **所有 LLM 流量走 `LLMQueryEngine`** | 否则 token 预算/审计有洞。 |

### 3.2 分层职责（维持现状，不重构）

```
┌─ CLI（唯一交付面，必须自足）──────────────────────────────┐
│  run / resume / approve / reject / draft / audit / dump  │
└───────────────────────┬──────────────────────────────────┘
                        │  ← 唯一入口函数（GUI 只是可选适配器）
┌───────────────────────▼──────────────────────────────────┐
│ L2：LangGraph 闭环图（24 Stage）                          │
│   · checkpointer 常开 → interrupt 可暂停/可恢复            │
│   · 节点 = 纯函数（12） or 调 agent（12）—— 均可            │
└───────────────────────┬──────────────────────────────────┘
                        │
    ┌───────────────────┼───────────────────┐
    ▼                   ▼                   ▼
┌─ Agent ────┐   ┌─ L3 决策 ──┐   ┌─ 证据链 ───────┐
│确定性管线   │   │ 规则 + RL  │   │横切：每 stage  │
│+ 点状 LLM  │   │           │   │自动出 manifest │
└─────┬──────┘   └───────────┘   └────────────────┘
      │
┌─────▼──────────────────────────────────────────────────────┐
│ L1：零 LLM 确定性层（EDA / 编译 / 覆盖率 / Git / 文件）      │
└─────┬──────────────────────────────────────────────────────┘
      │
┌─────▼──────────────────────────────────────────────────────┐
│ Tools：ToolHub 唯一收口（统一契约：in dict / out dict / риск）│
└────────────────────────────────────────────────────────────┘
```

### 3.3 Stage 声明式补强（小改动，高收益）

`StageSpec` 已有 `id` / `title` / `group` / `agent` / `round_scoped` / `summary_key`，
且 `outputs_of()` 已从 `PHASE_OWNERS` 反查出「产出哪些字段」。

**只差两个字段**：

```python
@dataclass(frozen=True)
class StageSpec:
    id: str
    title: str
    group: str
    agent: str = ""
    round_scoped: bool = False
    summary_key: str = ""
    requires_llm: bool = False      # ← 新增：这个 Stage 是否烧 token
    risk: str = "safe"              # ← 新增：safe / write / destructive
```

补上之后自动可用：

| 能力 | 实现 |
|---|---|
| `vagent stage list` 显示哪些 Stage 烧 token | 读 `requires_llm` |
| Token 预算按 Stage 扣减 | 读 `requires_llm` |
| 风险门控有输入源 | 读 `risk`（现在 46 个 `@tool` 只标了 3 个，因为没地方标） |

**注意**：有 `agent` 归属的 10 个 Stage 中，只有 `design` / `coverage` / `verify` / `debug` 涉及 LLM；
`front` / `model` / `ops` / `audit` / `env_arch_check` 不涉及。⚠️ 需运行时确认。

### 3.4 LLM 围栏原则（范例已在）

`design/main.py` 是全项目最认真对待 LLM 的地方，应作为模板复制：

```python
# 1. 精确 prompt 约束
prompt = """...
要求：
1. 生成完整的 module，端口 = 时钟/复位 + 接口信号
2. 用 always_ff 写真实的功能逻辑（状态机/寄存器/组合逻辑，不是占位）
3. 每个 reg 变量只能在一个 always_ff 块里赋值（禁止多驱动）
5. 只输出 SystemVerilog 代码，无 markdown 代码块、无解释
"""
# 2. 调用（失败返回空串，不假装成功）
try:
    return _call_llm_raw(prompt, "", "")
except Exception:
    return ""

# 3. 契约校验围住输出
@staticmethod
def _is_valid_rtl(rtl: str) -> bool:
    """RTL 完整性校验：module 声明 + 端口闭合 `);` + endmodule。
    LLM 生成的 RTL 可能截断，这种残缺 RTL 会导致 vlog 编译错误，必须丢弃。"""
```

**推广目标**：#1 #3 #5 #6 #7 这 5 个调用点，都应加上对应的输出校验。

---

## 4. 优化项

> 每项：**问题 / 证据 / 改法 / 改动点 / 验证 / 风险**

---

### P0-1 + P0-3：CLI 接入 checkpointer + 合并 A/B 入口

**问题**：`run_closed_loop` 无 checkpointer → `interrupt_mode=False` → CLI 上的审批永远是阻塞式。
且它与 `run_closed_loop_streaming` 是两份独立实现，各写了一遍输入装配，
`--rtl` 曾因只改一处而在 CLI 上被整个忽略。

**证据**：
- `execution.py:524` `graph = build_closed_loop_graph()` ← 无 saver
- `execution.py:526-545` vs `:670-704` ← 两份 `--rtl` 拷贝逻辑
- `execution.py:526` 注释自述：「第一版只补了 `_stream_run` —— 于是 CLI 上 `--rtl` 被整个忽略」

**改法**：把 `run_closed_loop` 改成 `run_closed_loop_streaming` 的**薄包装**。

**关键依据**：`run_closed_loop_streaming` 的 docstring 已明确承诺：
> 「**返回结构与 `run_closed_loop` 完全一致，所以调用方可以按需替换。**」

```python
async def run_closed_loop(self, spec_text: str, output_root: str = "output",
                          target: Optional[float] = None, max_rounds: int = 5,
                          design_style: str = "baseline",
                          bypass_design_model: bool = False,
                          sim_modes=None, manual_gate: bool = True, rtl_dir: str = "",
                          approval_gate=None, run_id: str = "",
                          resume: Optional[str] = None) -> dict:
    """CLI 主入口 —— `run_closed_loop_streaming` 的薄包装。

    合并理由：两者共享同一张图，却各写了一遍输入装配（`--rtl` 曾因只改一处
    而在 CLI 上失效，见 execution.py:526）。合并后只有一份装配逻辑，
    CLI 与 GUI 行为天然一致，且 CLI 也获得检查点能力。
    """
    return await self.run_closed_loop_streaming(
        spec_text, output_root=output_root, target=target, max_rounds=max_rounds,
        design_style=design_style, bypass_design_model=bypass_design_model,
        sim_modes=sim_modes, manual_gate=manual_gate, rtl_dir=rtl_dir,
        approval_gate=approval_gate,
        on_event=None,          # CLI 不需要进程内回调，只看落盘的 journal
        checkpointing=True,     # ← 关键：CLI 也落检查点
        run_id=run_id, resume=resume,
    )
```

**改动点**：
| 文件 | 改动 |
|---|---|
| `execution.py:488-573` | `run_closed_loop` 主体替换为上述包装；删除重复的 `--rtl` 装配块 |
| `execution.py:575` | `run_closed_loop_streaming` 增加 `run_id` / `resume` 透传（已有） |
| `commands.py:229` 等调用点 | 签名兼容，**无需改动** |

**验证**：
1. `vagent run --spec ... ` 跑通，行为与改前一致（除多落一个 `docs/checkpoints.sqlite`）
2. `vagent run --rtl <dir>` 确认外部 RTL 被纳入（改前 CLI 上失效）
3. `grep -c "rtl_dir" execution.py` 装配逻辑只应剩一份

**风险**：中。检查点是新增副作用（多一个 sqlite 文件）；`_safe_checkpointer` 已提供"缺依赖就降级"的兜底，不会阻断运行。

---

### P0-2：`approve` / `reject` 真正驱动图恢复

**问题**：`vagent approve/reject` 只写 `approval.json`，不驱动图恢复 —— **看起来像 HITL 闭环，实际是断的**。

**证据**：`commands.py:4117-4150`，函数体只做 `write_text(approval.json)`。

**改法**：改为调用 `run_closed_loop(..., run_id=rid, resume="approve"|"reject")`。

**resume 值的形制**（`graph.py:1010-1013`）：
```python
decision = ApprovalDecision(str(answer).strip().lower())
except (ValueError, TypeError): decision = ApprovalDecision.SKIP
```
→ 传**纯字符串** `"approve"` / `"reject"` / `"skip"`。
**认不出的答案一律按 SKIP**（「没人明确说"批"就不放行」）。

**改动点**：

```python
def _resume_run(run_id: str, answer: str, reason: str):
    """把一个挂起的运行从检查点接着跑。"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]"); return
    run = repo.get_run(rid)
    output_root, spec_text = run["output_root"], run.get("spec_text", "")
    # 审计记录照旧写（保留可追溯性）
    (Path(run["run_dir"]) / "approval.json").write_text(json.dumps(
        {"action": answer, "reason": reason, "at": datetime.now().isoformat(),
         "run": rid}, indent=2, ensure_ascii=False), encoding="utf-8")
    # ← 新增：真恢复
    asyncio.run(_run_loop(output_root, spec_text, rid, answer))

@cli.command("approve")
@click.option("--run", "run_id", default="")
@click.option("--reason", default="")
def approve(run_id, reason):
    """人工审批 —— 批准并**恢复**挂起的运行。"""
    _resume_run(run_id, "approve", reason)
```

⚠️ **需要先确认**：`spec_text` 是否持久化在 run 记录里（`run_repository.get_run` 的字段）。
若不持久化，改从 run 目录的输入副本读取。

**验证**：
1. 构造一个会触发审批的运行（`manual_gate=True` + 高风险动作）
2. 观察到 `docs/checkpoints.sqlite` 生成、运行停在 `approval` 节点
3. 另一个终端 `vagent approve --run <id>` → 确认运行**继续跑完**
4. `vagent reject` → 确认走 `audit` 分支

**风险**：中。恢复路径依赖检查点完整性；`hydrate_runtime`（`graph.py:324`）已处理"运行期对象重建"，
但需确认新进程里能重建全部对象（`engine` / `planner` / `infra` / 两个注册表 / 审计链）。

---

### P0-4：删 `langchain_classic` 隐性依赖

**问题**：`base.py:12` 顶层 `from langchain_classic.agents import AgentExecutor` ——
**未在 `requirements.txt` / `pyproject.toml` 声明**，靠 langchain 1.x 传递依赖装入。
上游一调依赖图，整个 `agents` 包 import 失败。

**证据**：
- `base.py:12`（顶层，必然执行）
- `base.py:256`（函数内，仅 `self.llm and prompt and tools` 时）
- `tool_system.py:610`（函数内，仅 `agent._executor` 存在时）
- grep `requirements.txt` / `pyproject.toml` → **NOT DECLARED**

**改法**：删掉整条 `AgentExecutor` 路径。

**依据**：`AgentExecutor` 的唯一可达用户是 `debug`（`debug/main.py:366` 调 `super().execute_task()`），
且 debug 自己的五阶段管线**已经直接调过那 7 个工具**（`call_tool("collect_sim_log", ...)`、
`fingerprint_error`、`bisect_failed_tests`），而它的 prompt 只要求 JSON 输出、**不要求调工具**。

**改动点**：

| 文件 | 改动 |
|---|---|
| `debug/main.py:366` | `super().execute_task(task)` → 直连 chain（约 10 行） |
| `base.py:12` | 删 `langchain_classic` import |
| `base.py:252-273` | 删 `_executor` / `_direct_chain` 构造 |
| `base.py:585-601` | 删三岔路口，保留 `_offline_result()` 作为唯一的确定性路径 |
| `base.py:13` | `from langchain.tools import BaseTool` → `from langchain_core.tools import BaseTool` |
| `tool_system.py:610` | 随 P2-2 一并删除 |

**验证**：
1. `python -c "import langchain_classic"` 应在卸载后失败，而 `import src.agents.debug.main` 成功
2. `vagent run` 跑到 debug 阶段，确认 LLM 根因分析照常产出（`llm_analysis` 非空）
3. 从 requirements 移除 `langchain` / `langchain-community`

**风险**：低。被删路径仅 debug 一个调用点，且改为等价直连。

---

### P1-1：消除 `analyze_specification` 静默降级（"跑不通"的头号来源）

**问题**：正则解不出 `design_name` 时静默填 `"dut"`，导致全链在不存在的设计上跑。

**证据**：`spec_tools/main.py:41-42`
```python
result["design_name"] = re.sub(r'[^0-9A-Za-z_]+', '_',
                               result["design_name"] or "dut").strip('_') or "dut"
```

**改法**（三步）：

```
正则提取 design_name
  ├─ 成功 → 照常
  └─ 失败
      ├─ 1. LLM 语义解析（带 schema 校验）
      │      prompt: 从 spec 文本提取模块名/接口/寄存器，输出 JSON
      │      校验: 输出必须是合法 JSON 且含非空 design_name
      │      失败 → 下一步
      └─ 2. 显式失败：返回 {"error": "无法从 spec 提取 design_name", "need_input": True}
             由 front 节点像对待"空输入"一样终止（front/main.py:88 已有先例）
```

**改动点**：
| 文件 | 改动 |
|---|---|
| `spec_tools/main.py` | `analyze_specification` 增加 LLM 兜底 + 失败时返回 error 而非 `"dut"` |
| `front/main.py:78-95` | 识别 `need_input` → 走既有的"没有输入"分支 |
| `design/main.py:53-57` | 识别 `need_input` → 不再静默 `{"design_name": "dut"}` |
| `graph.py:483` | 同上 |

**顺带**：此处是 P6（LLM 走 `query_engine`）的自然落点 —— 新增的 LLM 兜底直接用 `_call_llm_raw`。

**验证**：
1. 用一份**格式非标准**的 spec（无 `<!-- module: -->`、无 `#` 一级标题）跑 `vagent run`
2. 改前：静默变 `dut`，全链跑歪
3. 改后：要么 LLM 正确提取，要么响亮失败并提示

**风险**：中。新增 LLM 调用点会改变行为（原先"总是能跑"变成"可能拒绝跑"）——
但这正是本项的目的。**建议先用现有 spec 回归确认常规路径不受影响。**

---

### P1-2：CLI 接上规则草案闭环

**问题**：`rule_draft` 自动写草案，但接受动作只有 GUI（`workbench/modules/flow/drafts/module.py:141`）。

**改法**：加两个子命令。

```python
@cli.group("draft")
def draft_group():
    """规则草案 —— 让规则库从失败里长。"""

@draft_group.command("list")
@click.option("--run", "run_id", default="")
def draft_list(run_id):
    """列出本次运行产生的规则草案（含可直接粘贴的 @rule 骨架）。"""
    # 复用 flow_tools/api.py:1574-1586 的 collect_drafts + rule_skeleton

@draft_group.command("accept")
@click.option("--run", "run_id", default="")
@click.argument("rule_id")
@click.option("--by", default="", help="接受人（审计用）")
def draft_accept(run_id, rule_id, by):
    """接受一条草案 —— 记入 accepted，下次运行即生效。"""
    from src.layers.l4_memory.rule_draft import mark_accepted
    ok = mark_accepted(run_dir, rule_id, by=by)
```

**改动点**：仅 `commands.py` 新增（复用已有函数，无新逻辑）。

**验证**：构造一次失败 → `vagent draft list` 看到草案 → `vagent draft accept <id>` → 确认 `accepted_ids` 包含它。

**风险**：低。纯新增，复用已跑通的函数。

---

### P1-3：给静默默认值加 `uncovered` 标记

**问题**：`classify_fix_bug` 的 `FIX_FUNCTIONAL` 默认、`verification_plan` 的未知根因默认，
下游看不出这是"判出来了"还是"没判出来"。

**证据**：`decision_engine.py:466` 的注释其实已有正确意识：
> 「**判不出来的不硬塞**：功能类是诚实的默认值，不是垃圾桶」

但这份"诚实"**没有传到下游**。

**改法**：默认分支附加标记。

```python
# classify_fix_bug
if not evidence_matched:
    return FIX_FUNCTIONAL          # 保持返回值不变（兼容 RL 记账）
    # 同时在 Observation 上置 uncovered=True

# verification_plan
plan = VERIFICATION_PLANS.get(canonical_action(action_type))
if plan is None:
    plan = dict(VERIFICATION_PLANS[FIX_FUNCTIONAL])
    plan["uncovered"] = True       # ← 新增
```

**验证**：构造一个无证据的失败，确认 `verification_plan` 返回含 `uncovered: True`。

**风险**：低。加字段，不改既有分支行为。

---

### P1-4：4 处裸调接入 `LLMQueryEngine`

**问题**：第 1.4 节 #5 #6 #7 #8 绕过 `query_engine`，token 不计预算、不进审计。

**改法**：把 `llm_refine.call_llm` 从「`LLMFactory.create_for_task` + `llm.invoke()`」
改为「`LLMQueryEngine.get_instance().query(...)`」——即照 `_call_llm_raw`（`llm_custom_logic.py:104-125`）的样子。

```python
# llm_refine.py:18-40 现状
def call_llm(prompt: str, code: str, errors: str) -> str:
    llm = LLMFactory.create_for_task("code_generation")
    resp = llm.invoke([...])          # ← 绕过预算/审计

# 改为
def call_llm(prompt: str, code: str, errors: str) -> str:
    from src.layers.l2_orchestration.context.query_engine import LLMQueryEngine
    return LLMQueryEngine.get_instance().query(
        "code_generation", messages, cache_key=prompt) or ""
```

**收益**：#5 #6 #7 三处（debug / execution / quality_report）一次接上。
#8（debug 的 AgentExecutor）随 P0-4 删除后自然消失。

**验证**：
1. `LLMQueryEngine.get_budget_status()`（`query_engine.py:153`）的计数应包含原先裸调的流量
2. 触发一次编译失败 → LLM 修复 → 确认预算计数增长

**风险**：低。`query_engine` 已跑通，只是调用点没接。

---

### P1-5：抽 `JinjaRenderer` 到公共位置

**问题**：`cmodel_tools`（设计板块）反向依赖 `uvm_tools.tool_uvm.gen_uvm` 的 `JinjaRenderer`。
它本是通用模板渲染能力，却藏在 UVM 专属包里。

**证据**：
- `cmodel_tools/gen_cmodel.py:62` `from src.tools.uvm_tools.tool_uvm.gen_uvm import JinjaRenderer, TEMPLATES_DIR`
- `cmodel_tools/dpi_compile.py:28` 同上
- `gen_uvm.py` 本身 3590 行，`JinjaRenderer` 只是其中一小块

**改法**：把 `JinjaRenderer` + `TEMPLATES_DIR` 抽到 `src/tools/lib/template_renderer.py`，
`gen_uvm.py` 与 `cmodel_tools` 都改为 import 它。

**验证**：
1. `grep -rn "from src.tools.uvm_tools.tool_uvm.gen_uvm import JinjaRenderer" src/` → 应为空
2. `vagent run --rtl <含 cmodel 的目录>` 跑通

**风险**：低。纯搬迁 + 改 import；`gen_uvm.py` 的模板一致性由既有契约测试钉住。

---

### P2：清理

| # | 动作 | 说明 | 风险 |
|---|---|---|---|
| P2-1 | 删 `src/core/` | `registry.py:5` import 不存在的 `src.core.base`，一 import 就炸；全仓无引用 | 极低 |
| P2-2 | 删 `src/tools/scmodel_tools/` | 空目录 | 极低 |
| P2-3 | 删 `uvm_tools/_tools_old.py` | 1753 行旧副本；先把 `commands.py:3360` 引用的两个非 LLM 函数迁走 | 低 |
| P2-4 | 删 `tool_system.py` | 与 `tool_hub.py` 重复。**注意**：`ToolRegistry` / `Tool` 类型被多处引用，需先确认替换路径 | 中 |
| P2-5 | `StageSpec` 加 `requires_llm` / `risk` | 见 3.3 | 低 |
| P2-6 | 拆 `graph.py` | 建图仅约 90 行，其余 1600+ 行是节点/路由/业务辅助。**注意**：与 `Runtime` 强耦合，拆分需一并提出 `Runtime` | 中 |
| P2-7 | 拆 `commands.py`（5061 行 / 49 命令） | 按域分模块 | 中 |
| P2-8 | 加依赖方向测试 | 把 3 处反向依赖从"靠延迟 import 遮掩"变成 CI 拦截 | 低 |
| P2-9 | 补全 `ToolRisk` 标注 | 46 处 `@tool` 仅 3 处标注 | 低 |
| P2-10 | 统一工具返回值为 dict | 现 dict / JSON 字符串混用，靠 `workbench/bridge/binding.py:1-15` 兜底 | 中 |

---

### P3：用足已装能力

| # | 动作 | 替代对象 / 收益 |
|---|---|---|
| P3-1 | `RetryPolicy` | 替代手写的 `compile_retries` / `governor_retry` 节点 |
| P3-2 | **`get_state_history`（time travel）** | **直接支撑 `vagent dump` 的"任意一步可复现"** |
| P3-3 | `Send` API | 替代外挂的 `pipeline_scheduler`，多模块并发进图 |
| P3-4 | `store` | 接 L4，实现跨 run 长记忆（现为空挂形参） |
| P3-5 | 挂载 `exclusive` reducer | 让"单写者纪律"从静态表（`PHASE_OWNERS`）变成运行时保障 |
| P3-6 | Stage 概念收尾 | 见 3.3 —— 实为 P2-5 的延续 |

---

## 5. 路线图

### 顺序与依赖

```
P0-4 删 langchain_classic ────┐
   （最低风险，先拆炸弹）      │
                              ▼
P0-1+P0-3 接 checkpointer + 合并 A/B ──→ P0-2 approve/reject 真恢复
   （CLI 获得检查点）                    （依赖检查点存在）
                              │
                              ▼
                    端到端验收：CLI 上可暂停/可恢复
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   P1-1 去静默          P1-2 草案 CLI        P1-4 LLM 收口
   P1-3 uncovered 标记   （独立）            P1-5 抽 JinjaRenderer
        │
        ▼
   P2 清理（P2-5 StageSpec 加字段优先）
        │
        ▼
   P3 用足 LangGraph
```

### 建议的先后顺序与理由

| 顺序 | 项 | 理由 |
|---|---|---|
| 1 | **P0-4** | 工作量最小、零行为变化、拆掉最高危隐性依赖 |
| 2 | **P0-1 + P0-3** | 兑现"可复现"，且是 P0-2 的前置 |
| 3 | **P0-2** | 兑现"可治理"，CLI 首次具备真 HITL |
| 4 | **P1-1** | "跑不通"的头号来源 |
| 5 | **P1-2 / P1-4 / P1-5** | 相互独立，可并行 |
| 6 | **P2-5 → P2 其余** | StageSpec 加字段能让风险标注有处可写 |
| 7 | **P3** | 架构稳定后再拓展 |

---

## 6. 验证方案

### 6.1 动手前的基线（**必做**）

本文档所有结论来自**静态阅读**。以下判断需运行时确认：

| 待确认 | 方法 |
|---|---|
| ⚠️ 7/8 agent 的 `_get_prompt_template()` 返回 `None` → `_executor` 不构造 | 在 `base.py:252` 加临时日志，跑一次 `vagent run`，看 `prompt` 是否为 `None` |
| ⚠️ `_offline_result` 实际不触发 | 同上，在 `base.py:601` 加临时日志 |
| ⚠️ `AgentExecutor` 仅 debug 可达 | 在 `base.py:586` 加临时日志 |
| ⚠️ `analyze_specification` 真的静默降级 | 用一份非标准格式的 spec 跑 `vagent run`，看 `design_name` 是否变 `dut` |
| ⚠️ 各处 `requires_llm` 归类 | 跑一次完整 run，统计 `LLMQueryEngine` 的 audit_log 落在哪些阶段 |

### 6.2 回归基线

```bash
# 当前测试规模：tests/ 75 个文件 8.2k 行；workbench/tests/ 30 个文件 8.3k 行
pytest tests/ -x -q
pytest src/workbench/tests/ -x -q
```

**记录基线通过率**，作为后续每项改动的对照。

### 6.3 每项的验收（见第 4 节各条"验证"）

### 6.4 端到端验收（P0 完成后）

```bash
# 1. 跑一次会触发审批的运行
vagent run --spec specs/xxx.md --manual-gate

# 2. 确认停在审批点
ls output/*/docs/checkpoints.sqlite        # 应存在
vagent runs                                 # 应显示 WAITING_APPROVAL

# 3. 另一个终端放行
vagent approve --run <id> --reason "RTL 已复核"

# 4. 确认运行继续跑完
vagent show --run <id>                      # 应显示完成

# 5. 确认可复现
vagent dump --run <id>                      # 导出的证据包含完整决策链
```

---

## 7. 附录 A：LLM 调用点全清单（改造前后对照）

| # | 位置 | 改造前 | 改造后 |
|---|---|---|---|
| 1 | `design/main.py:283` | ✅ query_engine | 不变（补输出校验） |
| 2 | `design/main.py:395` | ✅ query_engine | 不变（有 `_is_valid_rtl`） |
| 3 | `coverage_tools/main.py:217` | ✅ query_engine | 不变（补输出校验） |
| 4 | `tool_find_spec_yaml/main.py:224` | ✅ query_engine | 不变（补输出校验） |
| 5 | `debug/main.py:635` | ❌ 裸调 | **→ query_engine** |
| 6 | `execution.py:469` | ❌ 裸调 | **→ query_engine** |
| 7 | `llm_refine.py:339` | ❌ 裸调 | **→ query_engine** |
| 8 | `debug/main.py:366` | ❌ AgentExecutor | **删除**（改直连 chain） |
| 9 | `llm_factory.py:424` | 探活 | 不变 |
| — | `_tools_old.py:435/441` | 死代码 | **删除** |

**目标**：所有业务 LLM 调用 100% 走 `LLMQueryEngine`（P6）。

---

## 8. 附录 B：与外部提案的差异

本方案在形成过程中评估过两份外部提案，差异如下：

### B.1 「LangGraph 多 Agent 重构」（Supervisor / Handoff / Subagents）

| 提案主张 | 本方案 | 理由 |
|---|---|---|
| Custom Workflow 为主骨架 | ✅ 采纳 | 已有 |
| 确定性节点嵌入 | ✅ 采纳并加强 | 已有，是壁垒 |
| 覆盖率反馈循环 | ✅ 采纳（修数据 bug） | 已有：`decide → apply_* → round_bump → ops → coverage` |
| HITL `interrupt()` 审批点 | ✅ **采纳，列为 P0** | 设施已有，CLI 断链 |
| Handoff 用 `Command(goto=)` | ❌ 不改 | 条件边功能等价；改写会复杂化 checkpoint 语义 |
| Supervisor 模式 | ❌ 不改 | 中央 `decide` + `governor` 已承担 |
| Async Subagents | ⏸️ 押后 | 有 `pipeline_scheduler`，收益需评估 |
| **Agent 由 LLM 驱动决策** | ❌ **拒绝** | 与 CLAUDE.md 正面对立，摧毁可复现/可审计/可治理 |

**事实纠正**：提案称「Agent 之间没有真正的通信和协作」—— 已核验为**错误**。
上下文传递有 `_read_ctx`/`_write_ctx`（`base.py:295/338`）+ Context 黑板（`context.py:142/215`）
+ `PipelineState` 承载全部阶段产物（`state.py:118-141`）。

### B.2 「两条工具线」（L1 vs tool_uvm）

| 提案主张 | 核验结果 |
|---|---|
| L1 零 LLM | ✅ **对** |
| L1 提供 `lint` / `check_syntax` | ❌ 不存在 |
| L1 提供 `file_audit` / `evidence` / `manifest` | ❌ **在 L2**（`l2_orchestration/evidence/`） |
| uvm_tools 有 `render_uvm_template` / `read_yaml` / `run_simulation` / `check_coverage` / `analyze_failure` / `generate_testcase` | ❌ **6 个名字 5 个不存在** |
| uvm_tools 里 `generate_testcase` / `analyze_failure` 含 LLM | ❌ 仅 `tool_find_spec_yaml` 一个文件含 LLM |
| 设计板块不碰 uvm_tools | ❌ **`cmodel_tools` 在 `gen_cmodel.py:62` / `dpi_compile.py:28` 反向依赖 `uvm_tools`** |

**采纳的部分**：`cmodel_tools → uvm_tools` 这个跨板块耦合是真问题 → 本方案 P1-5。

---

## 9. 附录 C：本文档与 `langgraph_multiagent_refactor_review.md` 的关系

| 文档 | 性质 |
|---|---|
| `langgraph_multiagent_refactor_review.md` | **评估**——对外部提案的逐条核验与差异说明 |
| **本文档** | **方案**——可直接实施的四阶段优化路线 |

两份结论一致：**骨架不动，补收尾**。
