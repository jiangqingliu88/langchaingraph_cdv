# 垂直验证智能体全面介入 GUI —— 业务架构模型重构

> 版本：v1.0 ｜ 日期：2026-10-03 ｜ 状态：方案评审
> 范围：`src/workbench/` ⟷ `src/agents/` + `src/layers/` 的业务架构关系
> 前置阅读：[`gui_pipeline_architecture.md`](gui_pipeline_architecture.md)、[`tool_layer_architecture.md`](tool_layer_architecture.md)、`PROJECT_STATUS.md`
> 本文回答一个问题：**这个垂直验证智能体，怎么才能"全面介入" GUI？**

---

## 0. 一句话结论

**现在的 GUI 只碰到了智能体的一个角。**

业务架构必须从「三条视图分组 + 九个模块」重构为 **「七条 agent 业务线 + 一条流程与证据线」**，并把「介入」拆成三层一起交付：**看得见（读）→ 点得动（驱动）→ 管得住（治理）**。

今天的 GUI 三层里只有"看得见"的一小半：能启停闭环、看阶段进度、浏览产物文件树、答审批。而 CLAUDE.md 定位的**第一差异化——签核证据链 + 治理——在界面上几乎完全不存在**：`evidence_chain.json`/`signoff_ready`、`vagent dump` 证据包、manifest 完整性校验、governor 的预算/熔断/干预、quality_guard、exclude 审批链、L5 蒸馏与回滚，**一条都没有绑定**。

> 这不是"再加几个页面"的问题，是**业务架构的分组维度错了**：现在的三条线是"视图分组"（调试/设计/验证），而智能体的能力是"角色分组"（design/model/verify/ops/coverage/debug/audit）。分组维度不齐，能力就永远只能零散地漏进来。

---

## 1. 现状审计（事实）

### 1.1 现在的业务架构

```
业务线（config/workbench.yaml:29-32）        模块（9 个）                      agent 能力
─────────────────────────────────────────────────────────────────────────────────────
调试技术    debug   order 10   ──▶  debug.sim_log / debug.fingerprint      ── debug（2/5 个面）
集成设计环境 ide     order 20   ──▶  ide.manual_nodes                      ── —（声明性 YAML）
验证管理系统 vms     order 30   ──▶  vms.casemodel / vms.tracking /        ── verify（仅 casemodel 面）
                                    vms.trend / vms.pipeline /                 （全 7 agent，但是不可见的黑盒）
                                    vms.runs / vms.evidence
```

GUI 到引擎的**唯一通道**是白名单绑定表 `src/workbench/bridge/catalog.py`（`BINDINGS`）。表里有什么，界面就够得到什么；表外的一切，无论代码写得多好，界面上都不存在。

### 1.2 能力 × 可达性矩阵

「看」= 只读绑定的视图；「驱动」= 从界面触发；「治理」= 有约束/审批/回滚语义的动作。

| agent | 看（现状） | 驱动（现状） | 治理（现状） | 该 agent 值得上界面的东西 |
|---|---|---|---|---|
| **design** | ❌ 只有 `vms.pipeline` 里一个阶段名 | ❌ | ❌ **（铁律一：vlog 门禁）** | IP 拆解 / `function_hier` / 寄存器 / 接口表 / `rtl_placeholder` / vlog 回执 |
| **model** | ❌ | ❌ | ❌（placeholder 应拒签核） | 版本列表 / `golden_ref` / `placeholder` 标记 / 回滚 |
| **verify** | ⚠️ 仅 casemodel 面 | ❌ | ❌ | UVM env / 用例清单 / 场景 / SVA 断言 / gap 定向序列 |
| **ops** | ⚠️ 仅在 runs/evidence 里间接可见 | ❌ | ⚠️ EDA 缺失→BLOCKED（藏在状态里） | 回归 pass/fail/total / EDA 缺失 / 失败用例 / 回归趋势 |
| **coverage** | ❌（`vms.coverage` 在清单里被注释掉） | ❌ | ❌ **（铁律二：ucdb SHA256 归档）** | gap 归因（unreachable/constraint/unstimulated）/ `coverage_map` / calibration |
| **debug** | ⚠️ 日志收集 + 指纹两个面 | ⚠️ 部分 | ❌ | 5 阶段根因 / 二分 / 信号诊断 / `llm_analysis` / 修复后的 EDA 重验 |
| **audit** | ❌（只能在证据文件树里瞄到 `report.json`） | ❌ | ❌ **（四道门禁）** | `verdict`（READY/NEEDS_FIX）/ 四道门禁逐条 / `pass_rate` / signoff 状态 |
| **流程与证据（横切）** | ⚠️ 只有原始文件树 + 覆盖率小表 | ❌ | ❌ | 五层证据链 / `signoff_ready` / manifest 完整性 / `dump` 导出 / 两次签核 diff |
| **治理（横切）** | ❌ | ❌ | ❌ | 预算（token/时间/EDA）/ 熔断器 / `.harness_cmd` 干预 / quality_guard 兜底 |
| **L3 决策（横切）** | ❌（只在"实时日志"文本里） | ❌ | ❌ | 每轮决策 + reason / gap→action 归因 / KG 追溯链 / RL 统计 |
| **L4 记忆（横切）** | ❌ | ❌ | ❌ | 用例库组合 / 有效性评分 / **exclude 审批链** |
| **L5 进化（横切）** | ❌ | ❌ | ❌ | 蒸馏提案 / live 清单 / **回滚** |

**读法**：❌ 占绝大多数。能过界的只有 `pipeline.*` 那 10 个绑定（启停/观测/审批）+ casemodel + 两个 debug 只读面。

### 1.3 四处结构性缺口

1. **证据链缺口（最要命）**——`vms.evidence` 只递归铺 `output/{run}/` 的**原始文件树**（`evidence/module.py:142`），既不读 `docs/evidence_chain.json`（`FiveLayerEvidence.build`，`five_layer.py:212`），也不读 `signoff_ready`（`five_layer.py:243`）、`manifest_hash`/`evidence_hash`、`file_change_chain.json`（`FileAuditTrail.verify_persisted`，`file_audit.py:122`）。**"可审计"这条承诺在界面上是空的。**
2. **治理缺口**——`governor.status()`（预算/熔断，`governor.py:183`）、`Intervention`（`.harness_cmd`，`governor.py:108`）、`QualityGuard` 全都无绑定。更危险的是：GUI 驱动的 run 一旦触发 governor 的 `_escalate_to_human`，会去**读 stdin**（`execution.py:353`）——界面驱动的运行会卡在一个看不见的终端提示上。
3. **进化/记忆缺口**——`ExcludeRegistry.approve_exclude`（`exclude_registry.py:125`）、`DistillationOrchestrator.rollback`（`distillation.py:203`）这类**带审批/回滚语义的高价值动作**，恰恰是最该有界面和确认框的，却一个都没接。
4. **触发面缺口**——CLI 有 `vagent agent run <role>`（走 `PipelineExecutionService.run_single_agent`，`execution.py:854`），GUI **没有**对应入口。用户想"只重跑 verify"只能回终端。

### 1.4 为什么只能碰到这么点（三道门）

| 门 | 位置 | 后果 |
|---|---|---|
| **白名单门** | `bridge/catalog.py` 的 `BINDINGS` | 表外能力界面上不存在。设计意图是好的（防"切个标签页就跑起来"），但**只登记了 pure 绑定**，于是驱动/治理类能力被一并挡在门外 |
| **单一入口门** | `run_service.py` 是 GUI 触达 L2 的**唯一**文件 | 除了 `pipeline.*` 那组，GUI 没有别的 L2 入口；per-agent 能力没有门可进 |
| **没有"面"门** | `src/tools/` 里有纯工具，但 agent 侧没有 per-agent facade | 工具层架构（`tool_layer_architecture.md` §4.1）规定了"工具/面/编排"三层，**agent 这一层的"面"从没为 GUI 造过** |

---

## 2. 判定：业务架构的错位在哪

### 2.1 三条业务线是"视图分组"，不是"能力分组"

`调试技术 / 集成设计环境 / 验证管理系统` 是**按"看什么"分的**（日志 / 源码 / 验证数据）。而智能体的能力是**按"谁干的"分的**（7 个 agent）。

两者不齐，就出现三个症状：
- 一个 agent 的能力被劈到多条线（`verify` 的 casemodel 在 vms，UVIC 环境却哪条线都没有）；
- 一条线里混着多个 agent（vms 里既有 verify 的 casemodel，又有全 7 agent 的 pipeline）；
- **横切能力（证据/治理/记忆/进化）无处安放**——它不属于任何单个 agent，三条线里也就都没有。

### 2.2 七 agent 是纵向能力，缺一条横向的"流程与证据"线

7 个 agent 是**纵向**的领域角色（`PROJECT_STATUS.md` §2 的"驾驶员"）。但有一大批能力是**横向**的：闭环编排、证据链、治理、决策、记忆、进化。它们不归任何单个 agent，却贯穿全部。

按"纯七条 agent 线"重构会**再次把横切能力弄丢**。所以目标模型是 **7 + 1**：七条 agent 线 + 一条 `flow`（流程与证据）线。

### 2.3 「介入」= 看 + 驱动 + 治理，现在只做了半层

| 层 | 含义 | 如今的覆盖 | 门槛 |
|---|---|---|---|
| **看**（read） | 只读视图，pure 绑定 | ~15% | 低——加 pure 绑定 + 模块 |
| **驱动**（drive） | 从界面触发/重跑 | 0%（只有整体闭环启停） | 中——需要 per-agent facade + `pure=False` 绑定 |
| **治理**（govern） | 审批/回滚/干预/完整性校验 | 0% | 高——需要审计记录 + 确认对话框 |

---

## 3. 目标业务架构模型

### 3.1 总览

> **落地补充（2026-10-04）**：上面的"7 + 1"在导航树上又收了一层 —— 见 §3.4「业务域」。
> 域不是新概念，是把 §3.2/§3.3 那三类（agent 线 / 横切线 / 设计时线）**显式化成树的一层**，
> 这样切换才有"进到某一段"的层次感，而不是在一列 9 条线里点。

```
                    ┌──────────────────────────────────────────────────┐
                    │  界面层  src/workbench/  （清单驱动 · 只做渲染）  │
                    │  8 条业务线 = 7 条 agent 线 + 1 条流程与证据线    │
                    └───────────────────────┬──────────────────────────┘
                                            │  只经白名单绑定（可审计）
                    ┌───────────────────────▼──────────────────────────┐
                    │  面层  src/layers/l2_orchestration/agent_service │  ← 新增
                    │  run_service（已有）｜ agent_service（新）｜ flow_*│
                    └───────────────────────┬──────────────────────────┘
                                            │
   纵向：7 个 agent（驾驶员）              横向：流程与证据（仪表盘与记录）
   ┌───────┬───────┬───────┬───────┬───────┬───────┬───────┐   ┌──────────────┐
   │design │ model │verify │  ops  │cover- │ debug │ audit │   │ 闭环编排      │
   │       │       │       │       │ rage  │       │       │   │ 证据链·治理   │
   └───┬───┴───┬───┴───┬───┴───┬───┴───┬───┴───┬───┴───┬───┘   │ 决策·记忆     │
       │       │       │       │       │       │       │       │ 进化·追溯     │
   ┌───▼───────▼───────▼───────▼───────▼───────▼───────▼───┐   └──────┬───────┘
   │  五层引擎  L1 基础设施 │ L2 编排 │ L3 决策 │ L4 记忆 │ L5 进化 │◀────────┘
   └────────────────────────────────────────────────────────┘
```

### 3.2 纵向：七条 agent 业务线

每条线 = **一个 agent 的能力** 在界面上的完整表达：它的产出（看）、它能被单独触发（驱动）、它的硬门禁（治理）。

| 业务线 | `group` | 名称 | 已见模块 | 本 model 新增（读） | 新增（驱动） | 治理 |
|---|---|---|---|---|---|---|
| design | `design` | 设计构建 | — | `design.arch`（IP/层次/寄存器/接口）、`design.rtl`（RTL 文件 + vlog 回执） | `design.run`（重生成某 IP） | vlog 门禁不过即拒收 |
| model | `model` | 参考模型 | — | `model.versions`（版本 + golden_ref + placeholder） | `model.run` / `model.rollback` | placeholder 拒签核 |
| verify | `verify` | 验证构建 | `vms.casemodel`→迁入 | `verify.env`、`verify.tests`、`verify.assertions` | `verify.run`（supplement / gap 定向） | 编译门禁 |
| ops | `ops` | 编译与回归 | — | `ops.regression`（pass/fail + 趋势）、`ops.failures` | `ops.rerun`（重跑失败用例） | EDA 缺失→BLOCKED |
| coverage | `coverage` | 覆盖率 | — | `coverage.gaps`（归因）、`coverage.map` | `coverage.collect` | ucdb SHA256 归档 |
| debug | `debug` | 调试技术 | `debug.sim_log`、`debug.fingerprint`（保留） | `debug.roots`（5 阶段根因） | `debug.run`、`debug.bisect` | 修复后 EDA 重验 |
| audit | `audit` | 签核审查 | — | `audit.verdict`（四道门禁 + verdict）、`audit.signoff` | `audit.generate` | 门禁不过→NEEDS_FIX |

> **`debug` 名字不变**：它现在就是业务线名，又是 agent 名，天然对齐，迁移零成本。

### 3.3 横向：一条「流程与证据」业务线

承载不属于任何单个 agent、但贯穿全部的横切能力。这也是**第一差异化的落点**。

| `group` | 模块 | 看什么 | 驱动/治理 |
|---|---|---|---|
| `flow` | `flow.pipeline`（由 `vms.pipeline` 迁入） | 阶段时间线 / 实时日志 / 审批条 | 启停 / 取消 / 审批（已有） |
| `flow` | `flow.runs`（由 `vms.runs` 迁入） | 运行历史（含在跑的） | 选中广播 |
| `flow` | `flow.evidence`（由 `vms.evidence` 升级） | 产物树 | — |
| `flow` | **`flow.chain`（新）** | **五层证据链逐层通过情况 + `signoff_ready` + 门限矩阵** | — |
| `flow` | **`flow.manifest`（新）** | manifest / `manifest_hash` / `evidence_hash` / 文件变更哈希链 | **导出证据包 + 完整性校验 + 两次签核 diff** |
| `flow` | **`flow.govern`（新）** | 预算用度 / 熔断器状态 / quality_guard 兜底统计 | **`.harness_cmd` 干预（pause/skip/step/override）** |
| `flow` | **`flow.decision`（新）** | 每轮决策 + reason / gap→action 归因 / KG 追溯链 | — |
| `flow` | **`flow.memory`（新）** | 用例库组合 / 有效性评分 / 待审 exclude | **exclude 审批（通过/驳回，签名进链）** |
| `flow` | **`flow.evolution`（新）** | 蒸馏提案 / live 清单 / 学习曲线 | **回滚某个蒸馏提案** |

### 3.4 业务域 —— 导航树上的那一层

上面的三类（agent 线 / 横切线 / 设计时线）在**导航树上是显式的三级**：

```
业务域（GroupSpec.section）   业务线（group）              这一段是什么
──────────────────────────────────────────────────────────────────────────────
设计时                        ide                          跑之前把输入写对
运行时                        design model verify ops      七个领域 agent，
                              coverage debug audit         按流水线顺序
贯穿层                        flow                         横切：编排 / 运行 /
                                                         证据 / 签核 / 跟踪 / 趋势
```

**实现**：`spec.py` 给 `GroupSpec` 加一个 `section` 字段 + `WorkbenchManifest.sections()`；
`nav_pane.py::populate()` 据此建三级树。**不写 `section` 的清单退化成两级**（`sections()`
只返回一个空域），老清单与测试夹具完全不受影响。

两条规则：
- **域的顺序由「域内最小 order」决定** —— 业务线本来就有先后，域跟着走就好；
  所以 `ide` 的 `order` 被调到 5（比 `design` 的 10 小），三段自然排成
  "设计时 → 运行时 → 贯穿层"。
- **没写 section 的业务线压到最后** —— 它是"还没归类"，不该插在真域前面。

**命名上的一个坑**：第三段**刻意不叫"流程与证据"** —— 那会和 `flow` 那条业务线
同名套同名（`- 流程与证据 / - 流程与证据`），树上看着像坏了。用"贯穿层"。

### 3.5 三层职责：绑定 → 面 → 能力

沿用 `tool_layer_architecture.md` §4.1 的三层纪律，**为 agent 补齐缺失的那一层**：

```
  界面模块（workbench/modules/<line>/<mod>/module.py）
      │  只做 build_content + refresh；不 import 引擎
      ▼
  绑定表 src/workbench/bridge/catalog.py  ← 唯一门禁，可审计
      │  名字用「域.动作」：design.arch / agent.verify.run / govern.status
      ▼
  面层 src/layers/l2_orchestration/
      ├── run_service.py      （已有，闭环）
      ├── agent_service.py    （新增：per-agent 读 + 驱动，镜像 run_service）
      └── flow_service.py     （新增：证据/治理/记忆/进化的读 + 动作，包一层纯函数）
      │
      ▼
  能力：src/agents/<role>/  ·  src/layers/l3..l5/  ·  src/tools/
```

**关键纪律（一条都不能破）**：
- 工具层不 import PySide6（`tool_layer_architecture.md` §4.1）——唯一例外是 `src/workbench/`。
- GUI 不直接 `import graph.py` / `execution.py`（`gui_pipeline_architecture.md` §8）——一律经绑定表。
- **不改流程拓扑**：七条 agent 线只做"触发与观测"，`graph.py` 的 23 个节点仍是产品资产。GUI 可以编辑**声明**（如 `ide.manual_nodes` 的人工节点 YAML），但不能编辑**拓扑**——声明是输入，拓扑是资产，两者不是一回事。

### 3.6 绑定分级（把门禁做细，而不是拆掉）

白名单要扩，但不能把"防误触"一起丢掉。**按介入层次给绑定分级**：

| 级别 | 语义 | 寄存器字段 | 界面表现 |
|---|---|---|---|
| `read` | 纯读，反复调无害 | `pure=True` | 切标签页即刷新 |
| `drive` | 触发 agent/回归，烧 LLM 或 EDA | `pure=False` | 必须**显式按钮** `force=True`；按钮需二次确认 |
| `govern` | 审批/回滚/干预/导出，有审计语义 | `pure=False` + 审计 | 弹确认对话框；动作写审计记录 |

对应到 `ToolBinding`（`bridge/binding.py`）：`read` 就是现在的默认；`drive`/`govern` 用现成的 `pure=False` 机制（`ToolRegistry.call` 已经会在 `pure=False` 且未给 `force` 时拒调，见 `binding.py:105`）。

---

## 4. 关键设计决策

**AADR-1｜业务架构按 agent 角色重构，7 + 2 而不是纯 7**
理由：7 个 agent 是纵向能力，横切能力（证据/治理/记忆/进化）无边可挂。纯 7 会重演今天"横切无处安放"的病。**结论：7 条 agent 线 + 1 条 `flow` 线 + 1 条 `ide` 线。**
`ide`（集成设计环境）**不在本方案的 7+1 里**，是落地时按用户的产品定义加回的：它是**设计时的声明式编辑**（编辑喂给流程的中间 YAML，如流程人工节点），与运行时的 agent/flow 两类并列 —— 硬塞进任何一条 agent 线都是错位。取舍见 §6 P1 的说明。

**AADR-2｜为 agent 新增 `agent_service` 面，镜像 `run_service`**
理由：GUI 触达 L2 只能经白名单 + 面层。已有 `run_service` 只覆盖闭环；per-agent 能力缺门。新增 `src/layers/l2_orchestration/agent_service.py`，提供 per-agent 的**读**（从最近一次 run 的 `PipelineState`/产物里取该 agent 的字段）与**驱动**（薄包 `run_single_agent`，`execution.py:854`）。
⚠️ 诚实标注：现有 `run_single_agent` 传的是**空的 `ctx: {}`**（`execution.py:865`），不具备共享状态——"只重跑 verify 且复用已有 design_arch"需要给 facade 补上下文注入，这是 P2 的真实工作量。

**AADR-3｜绑定分级 read / drive / govern**
理由：扩展白名单的同时保留"防误触"。见 §3.5。`drive`/`govern` 一律走 `pure=False` + 显式 `force` + 确认框。

**AADR-4｜不破"GUI 只是渲染器"**
理由：`gui_pipeline_architecture.md` §2 的立场不变——流程权威定义仍在 `graph.py`。本 model 只增加**触发与观测**，**不增加拓扑编辑**。人工节点 YAML（`ide.manual_nodes`）是唯一灰区：它是**声明**不是**拓扑**，本 model 明确其边界并在 §7"不做"里钉死。

**AADR-5｜现有三条线的迁移 = 重挂 `group`，不重写模块**
理由：`vms.casemodel`→`verify` 线、`vms.pipeline/runs/evidence`→`flow` 线、`debug.*` 原地不动、`ide.manual_nodes`→`design` 线（或留 `ide`）。改的是 `config/workbench.yaml` 的 `groups` + 各模块的 `group:` 字段 + readme + 清单断言，**模块代码基本不变**。
⚠️ 已知连带：业务线不占顶层菜单，但**只有 `debug` 线**的动作进「调试」菜单、其余进「工具」（`test_menu_structure.py:92`）。新增 7 条线后要重新决定菜单路由，否则 7 条线的动作全挤在「工具」下。

**AADR-6｜以现有 `graph.py` + 7 agent + 五层为准，DSH 重构提案暂缓**
理由：`refactor_to_deepseek_harness.md` 提议**删除** `src/agents/*` 与 `l2/execution.py`，与本 model（以及 `gui_pipeline_architecture.md`）直接冲突。若采纳 DSH，本文档整篇作废。**结论：本文档以现状代码为权威；DSH 提案单列，不在本 model 范围内裁决。**

---

## 5. 界面怎么摆（映射到四窗格）

```
┌─ 导航树（左）──────────┐┌─ 中央工作区（页签）─────────────────────────────┐
│ ▸ 设计构建             ││ [设计·架构] [验证·用例] [覆盖率·缺口] [签核·门禁] │
│    · 架构总览          ││                                                   │
│    · RTL 与门禁        ││   五层证据链：需求→设计→验证→执行→覆盖→签核       │
│ ▸ 参考模型             ││   ┌───────────────────────────────────────────┐   │
│ ▸ 验证构建             ││   │ 需求层 ✅  设计层 ✅  验证层 ⚠️ P2 缺 3     │   │
│    · UVM 环境          ││   │ 执行层 ✅  覆盖层 ❌ 功能覆盖 82%           │   │
│    · 用例 · 断言       ││   │ 签核层 ❌ signoff_ready = false            │   │
│ ▸ 编译与回归           ││   └───────────────────────────────────────────┘   │
│ ▸ 覆盖率               ││                                                   │
│ ▸ 调试技术 ◀────────── │└───────────────────────────────────────────────────┘
│    · 仿真日志          │┌─ 右窗格 ────────────┐┌─ 底部（调试线）──────────┐
│    · 错误指纹          ││ 证据 / 产物          ││ 仿真日志（Dock）         │
│ ▸ 签核审查             ││ 治理状态（新）       ││ 错误指纹（Dock）         │
│ ▸ 流程与证据 ◀──────── ││ 决策轨迹（新）       ││                          │
│    · 验证流程          │└─────────────────────┘└──────────────────────────┘
│    · 运行历史          │┌─ 状态栏 ─────────────────────────────────────────┐
│    · 证据链（新）      ││ apb_uart · 第 3 轮 · 覆盖率 85.5% · 预算 42% · 熔断:关 │
│    · 治理（新）        │└──────────────────────────────────────────────────┘
│    · 决策轨迹（新）    │
└───────────────────────┘
```

- 导航树 = 8 条业务线（`test_nav_pane.py:30` 已按 `sorted_groups()` 渲染，天然支持）。
- 中央 = 当前线的工作区页签；右窗格 = 跨线联合视图（证据/治理/决策）。
- 状态栏常驻治理摘要（预算/熔断）——**这是今天最危险的那个洞**（§1.3 第 2 条）的最小修法。

---

## 6. 路线图

### P0 · 止血 + 定位落点（只读，3–5 天）　【部分已实现】
> 目标：把"可审计"这条承诺变成界面上看得见的东西。
- ✅ **已实现** `vms.signoff`（签核判定）：一份视图同时给 **audit 的四道门禁 + 六层领域证据链 + 总判定**。
  - 工具 `src/tools/flow_tools/api.py::run_signoff(run_dir)`（纯读 `report.json` + `docs/evidence_chain.json`）
  - 模块 `src/workbench/modules/vms/signoff/module.py`（订阅 `run.selected`）
  - 绑定 `vms.signoff`（`read`）
  - 落地理由：**合并成一个视图**——"门禁"回答"该跑的都跑了吗"、"证据链"回答"每一层都闭合了吗"，合成一个问题"能不能签核"更好用，也省掉一条只有一个模块的业务线。
- ⬜ **未实现** `flow.govern`（治理只读）——**原因：拿不到真数据**。
  `Governor` 是运行线程里 `Runtime` 的一个字段（`execution.py:606`），**不落盘、也没有对外访问口**；
  预算（token/时间/EDA）与熔断器状态只在内存里。按"不拿假数据糊界面"的纪律**不做**。
  **补法**（很小的改动，留给 P2/P3）：`run_closed_loop_streaming` 里把 `rt` 存到服务上
  （`self._runtimes[run_id] = rt`），加一个 `run_service.governor_status(run_id)` 门面 + `govern.status` 绑定。
  届时它才有意义——**预算/熔断本来就是"正在跑的那次"才有的东西**。
  ⚠️ 顺带记一笔：GUI 驱动的 run 一旦触发 `_escalate_to_human` 会去读 stdin（`execution.py:353`），
  界面上会表现为"卡住"。这个洞在补上 governor 可视之前一直存在。
- **验收**：打开任一 run，能看到四道门禁逐条 + 六层证据链的逐层通过与 `signoff_ready`。✅

### P1 · 七条 agent 线落地（只读，5–8 天）　【基本已实现】
- ✅ **业务线重构**：`groups` 改 9 条（7 agent + `ide` + `flow`）；`modules/` 目录随之重建
  （`vms.{pipeline,runs,evidence,tracking,trend,signoff}` → `flow.*`，`vms.casemodel` → `verify.casemodel`）。
- ✅ **每条 agent 线一个"产出总览"**：`<line>.output` × 7，共用跨线视图
  `modules/agent_output.py` + 一个绑定 `agent.outputs`（role 作参数）。
  它给的是**这次运行里该 agent 跑了哪些阶段、产出了哪些文件** —— 数据来自运行日志
  （事件自带 `agent` 字段）与产物目录，全部是盘上已有的真东西。
  ⚠️ 与原计划的差异：原写的是 `design.arch` / `ops.regression` 这类**领域专用**视图，
  落地时先统一成「产出总览」。**领域专用视图（接口表、回归趋势、gap 归因图表）
  仍待补** —— 它们需要各自的数据契约，见下。
- ✅ **`flow.decision`（决策轨迹）**：按轮次列出决策动作 + 驾驭裁决。
  数据从 `decide` / `governor` 阶段事件的 `payload.delta` 里挖
  （`RunJournal.decision()` **定义了但没人调用**，日志里没有 `decision` 事件 —— 不能拿它当源）。
- ✅ **`flow.manifest`（运行清单）**：`manifest.json` 摘要 + `manifest_hash` /
  `evidence_hash` + 文件变更链。**只展示不校验**（校验要调 L2，属治理动作 → P3）。
- ⬜ **`flow.memory` / `flow.evolution`**：未做（用例库、蒸馏提案与回滚）。
- **验收**：任一 run 的 7 个 agent 产出都能在各自线里看到；决策轨迹可见。✅

### P2 · 驱动面（5–8 天）
- 新增 `agent_service.py`：per-agent 读 + 驱动（含上下文注入，见 AADR-2 警告）
- 新绑定（`drive`）：`agent.<role>.run`、`ops.rerun`、`coverage.collect`
- 界面：按钮 + 二次确认 + 明确显示"这次会烧 LLM/EDA"
- **验收**：能"只重跑 verify"；能重跑失败用例；失败/EDA 缺失照旧**响亮**。

### P3 · 治理面（5–8 天）
- 新绑定（`govern`）：`memory.exclude.approve/reject`、`evolution.rollback`、`govern.intervene`、`evidence.dump`、`evidence.verify`
- 界面：确认对话框 + 审计记录（写 `AuditLog` 链）
- **验收**：能审批 exclude（签名进链）、能回滚一个蒸馏提案、能写 `.harness_cmd` 干预、能导出并校验证据包。

---

## 7. 不做

- **不做 Web 前端 / SSE / 浏览器**（CLAUDE.md 铁律；`gui_pipeline_architecture.md` §8）。
- **不在 GUI 编辑流程拓扑**：23 个节点是产品资产。可编辑的只有**声明**（人工节点 YAML 等）。
- **不新增 AI 编排层**：本 model 只把已有能力接出来，不引入新的 agent 框架。
- **不裁决 DSH 重构**（AADR-6）：两套方案不混用。
- **不做 MCP server / 工具自动发现**：显式清单才是可审计的（`tool_layer_architecture.md` §8）。
- **不给 harness 做 GUI 配置**：`harness_feature_design.md` §3.2 已定其 CLI-only。
- **不做 run 进度百分比**：闭环没有可靠的百分比语义（`gui_pipeline_architecture.md` §8）。

---

## 附录 A · 新增绑定清单

| 名字 | 级别 | 目标（面） | 说明 |
|---|---|---|---|
| `evidence.chain` | read | `flow_service:evidence_chain` | 五层证据链 + `signoff_ready` |
| `audit.verdict` | read | `flow_service:audit_verdict` | 四道门禁 + verdict |
| `govern.status` | read | `flow_service:governor_status` | 预算 / 熔断 / 预算上限 |
| `manifest.info` | read | `flow_service:manifest_info` | manifest/file audit 哈希链 |
| `decision.trace` | read | `flow_service:decision_trace` | 每轮决策 + reason + gap 归因 |
| `memory.testcases` | read | `flow_service:testcases` | 用例库 + 有效性 |
| `evolution.proposals` | read | `flow_service:distillations` | 蒸馏提案 + live |
| `design.arch` / `model.versions` / `verify.tests` / `ops.regression` / `coverage.gaps` / `debug.roots` | read | `agent_service:<role>_read` | 各 agent 产出总览 |
| `agent.<role>.run` | drive | `agent_service:run_agent` | 单 agent 触发（`pure=False`） |
| `ops.rerun` | drive | `agent_service:rerun_failures` | 重跑失败用例（`pure=False`） |
| `coverage.collect` | drive | `agent_service:collect_coverage` | 触发覆盖率收集（`pure=False`） |
| `memory.exclude.approve` / `.reject` | govern | `flow_service:exclude_decide` | 审批 exclude（`pure=False`） |
| `evolution.rollback` | govern | `flow_service:rollback_distillation` | 回滚蒸馏（`pure=False`） |
| `govern.intervene` | govern | `flow_service:intervene` | 写 `.harness_cmd`（`pure=False`） |
| `evidence.dump` / `evidence.verify` | govern | `flow_service:dump_evidence` | 导出 + 校验证据包（`pure=False`） |

## 附录 B · 迁移对照（旧三线 → 新八线）

| 现有模块 | 现在 | 迁到 | 说明 |
|---|---|---|---|
| `debug.sim_log` | debug | `debug` | 不动 |
| `debug.fingerprint` | debug | `debug` | 不动 |
| `ide.manual_nodes` | ide | `design`（或保留 `ide`） | 见 AADR-4 灰区 |
| `vms.casemodel` | vms | `verify` | 它就是 verify 的 casemodel 面 |
| `vms.tracking` | vms | `flow`（或 `audit`） | 测试点/资产跟踪，偏签核 |
| `vms.trend` | vms | `flow` | 进度趋势属横切 |
| `vms.pipeline` | vms | `flow` | 闭环编排 |
| `vms.runs` | vms | `flow` | 运行历史 |
| `vms.evidence` | vms | `flow` | 升级为证据链视图 |

> `ide` 与 `vms` 两个 `group` id 是否保留，取决于是否要兼容既有书签/布局存储（`settings_store`）；建议一次性改到位，避免"新老两套分组"长期并存。

## 附录 C · 颗粒度审计：每一步单独看，闭环了吗？

> 问题：验证任务划到现在的颗粒度，**每一步是否都能自己闭环、AI 能执行、最终能收敛？**

### C.1 现在的颗粒度是三层，但只有两层真在用

```
项目 Project
 └─ PipelineRun        ← 一次闭环运行 = 现在的「一个验证任务」★ 最粗的那一层
     └─ phases          ← 7 个执行 agent 各一步（状态 / 耗时 / 评分）
         └─ TaskRecord  ← 每个 agent 的一次调用日志（DB 里有表，闭环里没人写）
```

外加一个**没接进来**的：**测试点**。`config/tracking/tracking.yaml` 是手工维护的声明，
闭环不读它；闭环跑出来的覆盖率也不回填。DB 里的 `feature_testpoint_map` 又从知识图谱
另写一份 —— 三处互不认识。

### C.2 逐步核：6/7 真闭环，`model` 是缺口

| agent | 本地门禁 | 判定 |
|---|---|---|
| design | `vlog` 编译 0/1，不过即丢弃/回退 | ✅ 真闭环 |
| **model** | **原本没有** —— 只打 `placeholder` 标记，判定**推迟到 audit** | ❌ → ✅ 已补（见 C.3） |
| verify | `_verify_compilation`，失败即回退空实现 | ✅ 真闭环 |
| ops | EDA 缺失→BLOCKED（不假通过）；回归 pass/fail | ✅ 真闭环 |
| coverage | ucdb SHA256 归档 + gap 归因 | 🟡 半闭环（收敛是外层的事） |
| debug | 修复后 EDA 重验 | ✅ 真闭环 |
| audit | 四道门禁 | ✅ 真闭环 |

### C.3 已补的两处

**① `model` 的编译门禁**（`src/agents/model/main.py::_verify_model`）
与 design 的 vlog 门禁对称：**过了才写稳定指针**（`{module}_stable.txt`），
编不过就不进 —— scoreboard 不会拿一份编不过的模型去比。**EDA 不在 ≠ 编译不过**：
前者标 `BLOCKED_EDA_MISSING` 照常推进（判不了就不冒充通过，也不冤枉一份可能没问题的
模型），后者才是 `FAIL`（这一步就是失败的）。

**② `flow.task` 任务总览** —— 界面上**缺的那条纵向流**。
其余视图都是"某个侧面"（阶段 / 门禁 / 曲线 / 决策），没有一处在回答最早那个问题：
**这个任务跑到哪了、还差多少、卡住了没有。** 它把一次运行当成一个任务看：
目标 / 当前覆盖率 / 差距 / 收敛预测（规划器的 `convergence_forecast`）/ 阶段通过数 / 卡点。
「跑完了」与「跑成功了」分开（`completed` vs `completed_with_errors`，沿用 DB 里
`PipelineRun.state` 的既有取值）。

### C.4 关于「收敛」

判据是 `coverage ≥ target` → `CONVERGE`（`TERMINAL_ACTIONS`，确定性终态）；
兜底是 `max_rounds`（默认 5）+ 熔断器（同一动作失败 3 次开路）。
但 **CLAUDE.md 自己引的学术结论说覆盖率收敛天花板低（10–20%）** ——
所以现在的「收敛」实质是 **"达标或跑满轮数就停"**，不是收敛性证明。
这件事界面上不该含糊：`flow.task` 把「收敛预测」与「覆盖率停滞」如实摆出来。

### C.5 界面要不要重构

- **业务线结构（9 条）✅ 不动** —— 它是能力维度，与颗粒度无关
- **业务流 ✅ 已补一条** —— `flow.task` 就是缺的那条纵向流
- **仍缺**：测点与闭环尚未接起来（`config/tracking/tracking.yaml` 还是死表）；
  步骤级驱动（只重跑某一步）仍是 P2
