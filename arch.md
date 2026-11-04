# SignOffAI 架构手册

> 基线：2026-11-04 · 分支 `refactor/langgraph-migration`
> 面向开发者：先读「主线」，再按需查「参考手册」。
> 相关文档：`data.md`（数据路径）、`docs/design/architecture_refactor_plan.md`（重构）、
> `docs/design/evidence_loop_alignment.md`（证据闭环）。

---

## 怎么读这份文档

这份手册分三层，**按顺序读不会迷路**：

1. **主线**（第 0–3 节）：它在解决什么问题、流水线怎么跑、三个关键机制。
2. **定位**（第 4 节）：分层怎么分、代码和产物放在哪。
3. **参考手册**（第 5–8 节）：契约/证据/门禁/3.0 的具体规则，查用为主。

---

## 0. 先看一句话：它在解决什么问题？

**芯片功能验证里，AI 生成的东西不可信，怎么办？**

SignOffAI 的答案是：**把“生成”和“信任”拆开。**

- AI / 规格 / Excel 只产生**候选意图**（猜的）；
- EDA 工具和确定性内核产生**证据**（实测的）；
- 门禁和工程师做**最终裁决**（拍板的）。

> 核心原则：**生成能力 ≠ 可信能力，证据才是事实源。**

---

## 1. 整条流水线长什么样？

```text
spec / RTL / casemodel / xlsx
        │
        ▼
[front]    → 解析规格，产出草稿
[verify]   → 生成 UVM 环境 + 契约（先冻结规则）
[ops]      → 跑真实仿真，落现场产物
[coverage] → 派生证据、聚合视图、门禁检查
[audit]    → 汇总、裁决、签核包
```

**五个阶段各管一段，不越界：**

| 阶段 | 只做 | 不做什么 |
|---|---|---|
| front | 解析 spec/RTL，产出草稿 | 不做最终裁决 |
| verify | 生成可执行环境与契约 | 不判签核 |
| ops | 真实仿真，落现场产物 | 不做覆盖率聚合 |
| coverage | 派生证据、聚合视图、门禁 | 不改写现场度量 |
| audit | 汇总、裁决、签核包 | 不改写 coverage 结论 |

---

## 2. 三个最关键的机制

### 2.1 契约先冻结，证据后采集

想象考试：**先交卷（冻结契约），再批改（采集证据）**。
批改只对那一版卷子有效，事后改答案没用。

- `contract_hash` 先写入账本（`contract_anchor`）；
- 之后所有证据只对**这一版契约**有效；
- 旧契约的证据 → 直接作废（`stale_contract`）。

构建物：`contract/contract.yaml` + `obligations.json` + `contract_manifest.json`。
契约哈希还覆盖**约束内容指纹**——id 没变、逻辑变了也能发现。

### 2.2 确定性裁决：`derive()` 是唯一法官

- 纯函数、可重放，**只读账本，不读模型/视图**；
- 结果取最严格：`MISSING > NOT_EXECUTED > PARTIAL > PROVEN`（`NA` 不参与）；
- 视图颜色和 `derive()` 判定不一致 → **硬失败**（`AUTHORITY_DIFF`）；
- TP 级还有影子对账：`tp_shadow` vs `tp_matrix`，差异非 0 进 caveat/硬失败；
- 证据包自带 `replay/replay.py`，离线与在线共用三态判定。

**deny-first 输入闸**：

- 旧契约证据 → `stale_contract`，日志/SCB/timing 一并作废；
- `judge_case()` 入口再查事实携带的 `contract_hash`，外来契约直接拒绝；
- `MODEL_UNAVAILABLE` 等结构性 caveat 由 `signoff_policy.yaml` 显式接受，不静默放过。

### 2.3 证据闭环：提议 → 验证 → 证据 → 解释 → 审查 → 下一轮

```text
Intent(候选) → EDA/人工确认 → Contract → Agent 提议
    → Control Plane(AUTO/APPROVAL/FORBIDDEN)
    → EDA 执行 → Evidence Store(事实类别)
    → Agent 解释 → 工程师审查 → derive → Gates → Signoff
```

**事实类别**：

| fact_class | 来源 | derive 是否采信 |
|---|---|---|
| `OBSERVED` | 仿真/形式/编译/覆盖率引擎 | ✅ |
| `DERIVED` | 纯函数推导（带输入哈希） | ✅ |
| `HUMAN_DECISION` | 审批、豁免、裁决 | ✅ |
| `HYPOTHESIS` | LLM / Agent 生成 | ❌（需升级） |
| `TOOL_RECEIPT` | 工具调用回执 | 仅审计 |

**工程职责**（Govern / Guide / Judge）：

- Govern：定边界、批高风险动作 → `control_plane/`；
- Guide：定义意图、假设、优先级 → `intent/`；
- Judge：裁决证据、签核、豁免 → `gates` / `verdict`。

> **AI 说的不算数，EDA 跑出来的才算数。**

---

## 3. 一张图总结整个系统

```text
┌─────────────────────────────────────────────────────┐
│  候选层（不可信）                                      │
│  AI / xlsx / casemodel → Intent / Claims (HYPOTHESIS) │
└──────────────────────┬──────────────────────────────┘
                       │ 契约冻结（contract_anchor）
                       ▼
┌─────────────────────────────────────────────────────┐
│  证据层（可信）                                        │
│  EDA 仿真 / 回归 / 调试 → Evidence Store (OBSERVED)   │
└──────────────────────┬──────────────────────────────┘
                       │ derive() 确定性裁决
                       ▼
┌─────────────────────────────────────────────────────┐
│  裁决层（门禁 + 工程师）                                │
│  Gates → verdict (READY / PASS_WITH_CAVEAT / NEEDS_FIX)│
└─────────────────────────────────────────────────────┘
```

---

## 4. 分层、主题与目录

### 4.1 六个主题

| 主题 | 含义 | 落点 |
|---|---|---|
| **候选 vs 事实** | LLM/生成器的输出默认 `HYPOTHESIS`，不能参与判定 | `intent/`、`claims/`、`evidence_store/fact_class` |
| **契约先冻结** | 契约哈希锚定在账本里；证据只对那一版契约有效 | `contract/` + `contract_anchor` |
| **确定性裁决** | `derive()` 是唯一判定实现，纯函数、可重放 | `l3_decision/contract/derive.py` |
| **证据闭环** | 提议 → 工具验证 → 证据库 → 解释 → 工程师审查 → 下一轮 | `evidence_store/`、`control_plane/` |
| **硬失败优先** | 缺证据/缺绑定/缺 pred/回退 → 显式失败，不静默降级 | gates / caveats / verdict |
| **分层单向依赖** | `interfaces → executors → l2 → l3 → l1 → core` | `config/architecture_guard.py` |

桌面优先：GUI 是 **PySide6** 桌面窗口，不引入 Web 前端。

### 4.2 分层与依赖方向

```text
interfaces (cli/workbench/app) → executors → layers/l2 → layers/l3 → layers/l1 → core
```

| 层 / 目录 | 拥有 | 不拥有 |
|---|---|---|
| `src/core/` | 契约版本、ID、runtime（atomic/gc/errors）、provenance | 业务规则 |
| `src/layers/l1_infrastructure/` | EDA 后端、回归执行、证据源适配 | casemodel 语义 |
| `src/layers/l2_orchestration/` | 编排、DAG、run 仓库、证据包、regression_tools | 判定规则 |
| `src/layers/l3_decision/` | case_ir、TP IR、contract、derive、gates、case view | IO/模板 |
| `src/layers/l4_memory/` | ledger、persistence、evidence_store | 业务判定 |
| `src/layers/l5_evolution/` | metrics、closure、docs | 执行 |
| `src/executors/` | 薄编排 | 业务算法 |
| `src/tools/` | 适配器（UVM / EDA / IR 工具） | 跨阶段业务规则 |
| `src/cli/`、`src/workbench/`、`src/app/` | 接口层 | 算法 |

**当前门禁**：`config/architecture_guard.py` 的 `import_direction` 已并入 `check().ok`，
静态依赖违规 = 红。最近一次：`import_issues = 0`。

### 4.3 仓库目录

```text
cdv_advanced/
├─ src/
│  ├─ core/                      契约版本 / ID / runtime（atomic、gc、errors）/ provenance
│  ├─ layers/
│  │  ├─ l1_infrastructure/      EDA 后端、回归执行、证据源适配（evidence_providers）
│  │  ├─ l2_orchestration/       图编排、runtime、证据包、regression_tools、governance
│  │  ├─ l3_decision/            语义与判定：
│  │  │   intent/ claims/ contract/ casemodel/ case_ir/ case_view/
│  │  │   verification_ir/ resource_model/ obligation/ attribution/
│  │  │   control_plane/ evidence/ spec_tools/
│  │  ├─ l4_memory/              ledger（哈希链）、persistence、evidence_store
│  │  └─ l5_evolution/           metrics、closure（缺口/动作规划）、docs
│  ├─ executors/                 front / design / model / verify / ops / coverage / debug / audit
│  ├─ tools/                     纯适配器：
│  │   generation/（uvm / casemodel / cmodel / isa）
│  │   checking/（verification_os / assertion）
│  │   humanview/（aivm / covg / scb / sva / verification_md）
│  │   common/lib、flow/trend、integration/ide
│  ├─ cli/                       Click 命令入口
│  ├─ workbench/                 PySide6 桌面窗口
│  └─ app/                       services（flow / run / coverage API）
├─ config/                       architecture_guard / budget / paths / control_plane / settings
├─ specs/<module>/               casemodel、case_bindings、util_comp、resources、signoff_policy
├─ docs/design/                  设计与方案（重构、契约、证据闭环）
├─ scripts/                      golden_diff、guard、e2e 检查
├─ tests/                        golden 基线与测试
├─ output*/                      每次运行的产物目录（见下）
├─ arch.md · data.md             架构 / 数据路径
```

**一次 run 的产物目录**：

```text
<run>/
├─ inputs/          spec.json / casemodel.yaml / resources.yaml / UVM YAML
├─ agents/ env/ bench/           生成的 UVM 源码（含 <env>_resource_checker.sv）
├─ regression_run/               逐 test：cov/ wave/ log/ task_meta.json
├─ sim/coverage/                 ucdb / coverage_result.json / per-test ucdb
├─ coverage/                     case_ir / testpoints / intents / claims /
│                                verification_ir / resource_* / attribution_v2 / gates
├─ contract/                     contract.yaml / obligations.json / manifest
├─ evidence/ledger.jsonl         只追加 + 哈希链（契约锚点在前）
├─ docs/                         evidence_index / evidence_sources /
│                                action_audit / obligations_v3 / ir_first_audit
├─ status/                       worklist / authority_diff / interpretations /
│                                next_iteration_context / closure_plan
└─ signoff_evidence/             verdict / caveats / 证据包 / replay
```

---

## 5. 参考手册

### 5.1 契约：Case 四集合

`coverage/case_ir.json` 是**身份来源**，每条 CASE 是显式容器：

```json
{
  "id": "CASE-...",
  "groups":   [{"group": "CG-...", "cell": "CELL-...", "required_layers": ["functional", "timing", "data"]}],
  "sva":      [{"id": "SVA-...", "cell": "CELL-..."}],
  "scb":      [{"id": "SB-...", "cell": "CELL-..."}],
  "constraints": ["p_..."],
  "not_applicable": {"sva": "原因", "scb": "原因"},
  "waivers":  [{"id": "...", "owner": "...", "approver": "...", "reason": "...", "expires": "..."}]
}
```

规则：

- `groups` 非空；`sva/scb` 可以为空，但字段必须存在且 `not_applicable` 写原因；
- 每项带 `cell`，证据落回 CELL 枢纽；
- `constraints` 是策略 id，不编造；
- `waivers` 缺 `owner/approver/reason/expires` → `waiver_incomplete` blocker；
- `source` 区分 `declared` / `synthesized` / `xlsx`。

**输入双轴**：

| 输入 | 回答 | 角色 |
|---|---|---|
| `*.testpoint.xlsx` | 该测什么（Feature → Sub_Feature → 用例意图） | CASE/CCAT 真源（`source=xlsx`） |
| `casemodel.yaml` | 怎么测/怎么量（维度/bin/cross/批次） | 覆盖/checker/批次实现模型 |
| `case_bindings.yaml` | CASE ↔ 维度/cells/tests | 唯一桥；留空 → `case_without_binding` blocker |

**TP IR 多对多**：一条 TP（维度 × 取值）可被多条 CASE 共享：

```yaml
tp_id: TP-...
case_id: CASE-A          # 主身份
case_ids: [CASE-A, CASE-B]  # 全量
groups: [CG-...]
sva: [SVA-...]
scb: [SB-...]
constraints: [p_...]
```

契约按**每个** `case_ids` 归并；只看主 `case_id` 会让后绑的 CASE 永远空。

### 5.2 证据链与确定性裁决

```text
contract → obligations → evidence/ledger.jsonl → derive() → status/*
```

- **账本**：只追加 + 哈希链（`prev_hash`），FactBundle 幂等写入，跨进程锁；
- **derive()**：唯一判定实现，纯函数；同上 `worst()` 取最严格；
- **状态权威对账**：`case_view` 展示色 vs derive 判定；差异非 0 → 硬失败；
- **TP 影子**：`tp_shadow` 与 `tp_matrix` 对账；
- **离线 replay**：证据包自带 `replay/replay.py`，与在线共用三态判定。

**事实类别与证据闭环**（详见 5.8）：

- `Fact` 带 `fact_class / producer_class / claim_ids / actor`；
- `derive()` 只采信 `OBSERVED / DERIVED / HUMAN_DECISION`；
- `HYPOTHESIS` 永远不会单独把义务推成 `PROVEN`。

### 5.3 覆盖语义与闭合

| 语义 | 落点 |
|---|---|
| `ignore_bins` | 不计入分母（工具级排除） |
| `illegal_bins` | 命中即错 |
| `transition bins` | `(a => b)` |
| `weight` / `at_least` | 覆盖点/组级 `option.*` |
| `per_instance` / `auto_bin_max` / `strobe` | covergroup 选项 |
| 维度 `goal` | 分层闭合目标 |

**闭合公式**：

```text
required = 仓数 − ignore
waived   = CASE waivers[].scope 命中的仓
denominator = required − waived
```

`waived` 与 `ignored` 分开审计；`NA` 不是 pass。

**缺口闭环**：

- `coverage/coverage_holes.json`：`stimulus_gap / model_drift / signoff_gap / backend_pending`；
- `status/worklist.json`：缺口建议合并进 `items` / `regex`；
- `incremental/plan.json`：非保守结论时给 `impact_suggested`，驱动最小重跑；
- 覆盖率 delta 门禁：`SIGNOFFAI_COVERAGE_BASELINE` 指定基线，回退 → 硬失败。

### 5.4 环境架构与 Pred/Scoreboard

```text
in agent monitor ──► pred.in_export
pred.out_port    ──► scb.expected_export
out agent monitor ─► scb.actual_export
```

- **Pred**：参考模型。可以是 SV（`common_pred.svh` / `util_comp.yaml` 的 `body`），
  也可以是 C/DPI（`cmodel_tools` 生成 wrapper + predictor，编译共享库 + `-sv_lib`）。
- **不生成假 pred**：双向 agent 没有真实模型 → 生成阶段硬失败，不写 env。
- **Scoreboard vs DUT Checker**：
  - Scoreboard = 事务级 expected vs actual；
  - `[SCB_DUT]` / `[SCB SB-*]` 若来自 `env_cov` 的逐拍规则检查，标
    `evidence_kind=dut_rule_checker`，视图列名 `Scoreboard/Checker`，不冒充事务 scoreboard。
- **SV pred 装配单**：`specs/<module>/util_comp.yaml` →
  `<run>/inputs/yaml/uvm/util_comp.yaml`；env 生成时校验端口类型与三条连接。
- **资源 checker**：`resources.yaml` 的 `agent + watch` → `<env>_resource_checker.sv`，
  由 env 的 analysis port 驱动；没有 `agent/watch` 的操作不生成观测点（见 5.7）。

### 5.5 门禁与签核

`gates.json` 分 blocker / warning / info；关键 blocker：

| 规则 | 含义 |
|---|---|
| `case_without_binding` | 业务 CASE 没有 dimensions/tests |
| `unknown_dimension` | CASE 绑定的维度不在 casemodel |
| `checker_without_tp` | checker 没绑到任何 TP |
| `CASE_GROUPS_EMPTY` | 用例没有功能组 |
| `CASE_SVA/SCB_UNDECLARED` | 四集合字段缺失 |
| `CASE_ITEM_NO_CELL` | 集合项缺 cell |
| `CASE_STATUS_OVERCLAIM` | 状态越报 |
| `CASE_IR_EVIDENCE_MISMATCH` | 契约与证据不一致 |
| `waiver_incomplete` | 豁免缺审批字段 |
| `AUTHORITY_DIFF` | 视图与 derive 分叉 |
| `COVERAGE_REGRESSION` | 覆盖率回退 |

**签核三态**（`evidence/verdict.py`，唯一实现）：

```text
hard_ok=False            → NEEDS_FIX
hard_ok=True + caveat    → PASS_WITH_CAVEAT
hard_ok=True + 无 caveat → READY
```

`score` 不能覆盖 `verdict`；`MODEL_UNAVAILABLE` 是否接受由 `signoff_policy.yaml` 决定。

**人工签核与 TB/RTL 封存**（Workbench「签核判定 → 人工签核」）：

- 表格逐 CASE 显示证据状态、人工结论、签核人、时间、备注；
- 结论写 `status/manual_signoff.json`，动作进 `docs/action_audit.jsonl`（带 `appr_id`）；
- **全部用例有结论**后才能「封存 TB/RTL」：逐文件哈希 + 聚合哈希写入
  `status/seal_manifest.json`，并复制到 `signoff_evidence/seal_manifest.json`；
- 封存后签核表锁定；解封必须填写签核人 + 原因，动作同样留审计。

**人机审阅**（同一页的「人机审阅」标签）：

- **意图 / 结论 / 解释** 三合一表：Intent `CANDIDATE→CONFIRMED/REJECTED`、
  Claim 人工确认（记 `confirmed_by`）、Interpretation `DRAFT→REVIEWED/REJECTED`；
- **下一轮上下文**：未决义务 / 覆盖缺口 / 无证据 Claim，只读；
- **证据门禁**：Claim 证据覆盖、失败义务、闭环状态、可用/占位证据源、
  高风险未审批动作；`SIGNOFFAI_EVIDENCE_GATE` 当前模式只读展示。
- 所有审阅动作写 `docs/action_audit.jsonl`（`review_intent / review_claim /
  review_interpretation`，带 `appr_id`）。

**证据闭环相关读数**（默认 `warning`，`SIGNOFFAI_EVIDENCE_GATE=block` 才硬失败）：

- `claim_confirmed_without_evidence`
- `claim_from_agent_confirmed`
- `unapproved_high_risk_action`
- `failed_obligations` / `closure_continue`

### 5.6 Architecture 3.0（已接主链）

| 能力 | 模块 | 主链产物 |
|---|---|---|
| Unified Verification IR v3 | `l3_decision/verification_ir/` | `coverage/verification_ir.json` |
| Resource / Interaction Model | `l3_decision/resource_model/` + `tools/.../resource_checker.py` | `coverage/resource_model.json`、`resource_scenarios.json`、`env/<env>_resource_checker.sv`、`docs/resource_checker.json` |
| Exact Attribution v2 | `l3_decision/attribution/` + `evidence/per_test_bins.py` | `coverage/per_test_bins.json`、`attribution_v2.json`、`per_test_v2/*.json` |
| Unified Obligation | `l3_decision/obligation/` | `docs/obligations_v3.json` |
| Autonomous Closure | `l5_evolution/closure/` | `status/closure_plan.json` |
| UVM IR-first | `tools/generation/uvm_tools/generation/ir/` | `docs/ir_shadow_diff.json`、`docs/ir_first_audit.json`（就绪读数，默认不切换） |

语义约定：`FAILED`（显式违规）≠ `UNKNOWN`（无可信判据）≠ `OPEN`（没执行）；
归因分 **EXACT / WEAK / UNKNOWN**，分母固定、UNKNOWN 不参与美化；
closure 只做确定性排序，**硬失败优先，AI 建议不能覆盖门禁**。
P2 场景已并入 `StimulusPlan`；P0 的 IR→render-context 覆盖已接到渲染入口，
由 `SIGNOFFAI_UVM_IR_FIRST=on` 开启（默认关闭，切换前要求 `ir_shadow_diff=0`）。

### 5.7 资源 checker 的协议级生成规则

`resources.yaml` 里每个 operation 可以声明**怎么观测它**：

```yaml
check_window: 10            # 与 $time 同单位；0 = 只比较同一时刻
operations:
  - id: dma_wr
    owner: dma
    resource: sram0
    agent: npu_sched_in     # 用哪个 agent 的 monitor
    watch:                  # 事务字段表达式（SV，tr 是 seq_item 句柄）
      address: tr.src_addr
      length:  tr.len
      write:   1'b1
interactions:
  - {id: IX1, operation_a: dma_wr, operation_b: cpu_rd, relation: EXCLUSIVE}
```

生成链路：

```text
resources.yaml → ResourceModel → resource_scenarios.json
                                      │
environment.agents ───────────────────┤
                                      ▼
                    resource_checker plan（agent / watch 校验）
                                      │
                                      ▼
             env/<env>_resource_checker.sv（uvm_scoreboard）
                                      │
             env.sv：成员 + create + analysis port 连接
             env_pkg.sv：include（必须在 env.sv 之前）
```

判定语义：

- 只有 `EXCLUSIVE` / `FORBIDDEN_OVERLAP` 编译出的 `conflict=True` 场景会
  `uvm_error("RES_CONFLICT", …)`；`ARBITRATED_OVERLAP` / `SERIALIZED` 只计数并
  `uvm_info("RES_POLICY", …)`。
- `overlap` 用闭区间 `[address, address+length-1]` 计算，长度 ≤ 0 视为不重叠。
- **没有 `agent` / `watch.address` / `watch.length` 的操作不生成观测点**，
  以 `unsupported` 告警返回；不猜事务字段名（猜错会安静地检查一个永远为 0 的地址）。
- 多 agent 用 `uvm_analysis_imp_decl(_<agent>)` 展开独立 `write_<agent>`，避免
  单 imp 只能接一个事务类型。

### 5.8 证据闭环：Intent / Claim / Evidence Store / Control Plane

> 完整方案：`docs/design/evidence_loop_alignment.md`

目标链：

```text
Intent（CANDIDATE）→ EDA/人工确认 → Unified IR → Contract(claims+obligations)
   → Agent 提议 → Control Plane(AUTO/APPROVAL/FORBIDDEN)
   → EDA 引擎执行 → Evidence Store(fact_class)
   → Agent 解释 → 工程师审查 → 下一轮上下文 → derive → Gates → Signoff
```

| 新增层 | 落点 | 产物 | 状态 |
|---|---|---|---|
| 验证意图 | `l3_decision/intent/` | `coverage/intents.json` | ✅ 候选/确认生命周期 |
| 待证明结论 | `l3_decision/claims/` | `coverage/claims.json` | ✅ 默认 CANDIDATE |
| 证据库 | `l4_memory/evidence_store/` | `docs/evidence_index.json` | ✅ 事实类别 + claim 证据覆盖 |
| 证据源 | `l1_infrastructure/evidence_providers.py` | `docs/evidence_sources.json` | ✅ sim/regression/debug 真实；formal/lint/cdc/rdc/emulation 显式占位 |
| 控制平面 | `l3_decision/control_plane/` | `config/control_plane.yaml`、`docs/action_audit.jsonl` | ✅ 动作级三态 + 角色白名单 |
| 解释与上下文 | `evidence_store/interpretation.py`、`context.py` | `status/interpretations.json`、`status/next_iteration_context.json` | ✅ 默认 HYPOTHESIS |

工程师职责固定为 **Govern / Guide / Judge**：
管边界（控制平面）、定意图（Intent）、裁决证据（gates/verdict）。
**模型不是事实源；没有引擎证据不签核；未知动作默认拒绝。**

### 5.9 重构现状（已完成）

| 项 | 结果 |
|---|---|
| 产物 golden 基线 | `tests/golden/architecture_baseline/`，`golden_diff` 0 差异 |
| 静态依赖方向 | `import_issues = 0`，已作为阻断门禁 |
| 巨型文件 | verify 1500→590、audit 1449→545、find_spec_yaml 1494→429、cli/commands 1353→746、execution 1000→42、infrastructure 1110→268、repository 1374→167、case_cov 1019→116、collect_real_coverage 1118→60、main_window 1008→47 |
| 目标门面 | `l3_decision/{contract,casemodel,evidence,spec_tools,case_ir,case_view}`、`l4_memory/ledger`、`l5_evolution/closure` |
| 旧 shim | 外层 shim 已删除；仅保留方向必要的边界隔离 |
| 原子写 | `core/runtime/atomic.py` 覆盖关键产物 |
| 存储回收 | `core/runtime/gc.py` + `vagent gc`（默认 dry-run） |

**仍待完成**：

- `tools/checking/verification_os` / `tools/generation/casemodel_tools` 的实现
  仍通过门面被引用；下一步迁进 `l3_decision` / `l4_memory`，再删旧路径。
- 形式 / Lint / CDC / RDC / Emulation 仍是显式占位适配器，工具接入后替换 provider。
- 资源 checker 的 SV 编译、P3 vcover 真机验证需要 EDA 环境。

---

## 6. 阅读导航

| 你想知道的 | 看哪节 |
|---|---|
| 这系统信什么、不信什么 | 第 0 节 + 第 7 节（关键不变量） |
| 流水线怎么跑 | 第 1 节 |
| 三个核心机制 | 第 2 节 |
| 代码/产物放哪 | 第 4 节 |
| 契约长什么样 | 5.1 |
| 证据怎么变成裁决 | 5.2 |
| 覆盖怎么闭合 | 5.3 |
| Pred / Scoreboard 怎么分 | 5.4 |
| 门禁有哪些硬规则 | 5.5 |
| 新加的 Intent / Evidence Store 干嘛的 | 5.8 |

---

## 7. 关键不变量

1. **产物 schema 是 API**：`case_ir_v1` / `testpoints` / `contract_v2` / `case_cov_v1`
   字段不改名、不换语义。
2. **契约先冻结，证据后采集**：`contract_anchor` 在证据之前写入账本。
3. **没有证据不下绿**：`NA ≠ pass`；聚合证据不能冒充逐条证据。
4. **确定性裁决不接受生成器自证**：`derive()` 只读账本，不读模型/视图。
5. **不自动猜**：绑定、维度、pred、waiver 缺失都显式报错/门禁，不编默认值。
6. **依赖只能向下**：`interfaces → executors → l2 → l3 → l1 → core`。
7. **模型不是事实源**：LLM/Agent 输出是 `HYPOTHESIS`，升级需引擎证据或人工审批。
8. **未知动作默认拒绝**：控制平面对未登记动作返回 `FORBIDDEN`；高风险动作必须留审批记录。
9. **工程师是治理节点**：Govern / Guide / Judge；审批本身也是可审计的证据。

---

## 8. 最后记住 3 句话

1. **AI 说的不算数，EDA 跑出来的才算数。**
2. **规则先冻结，证据只对冻结的那版规则有效。**
3. **缺证据、缺绑定、越权动作 → 直接报错，不静默放过。**

> 主链不变：`front → verify → ops → coverage → audit`。
> Case 四集合 + 契约锚点 + 只追加账本 + `derive()` 构成确定性主干；
> Intent / Claim / Evidence Store / Control Plane 把“生成”接到“信任”。
