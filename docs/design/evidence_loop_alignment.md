# 对齐“证据闭环”框架：架构改造方案

> 来源：芯华章 DVCon China 2026《从生成到信任：芯片验证智能体的证据闭环》
> 日期：2026-11-04
> 结论：**方向同源，但缺三块骨架** —— 意图模型、统一证据库、控制平面。

---

## 1. 芯华章框架 vs 当前架构

| 芯华章支柱 | 当前实现 | 差距 |
|---|---|---|
| **验证语义映射**（意图 → 结构化目标；映射是候选假设） | `case_ir` / TP IR / `verification_ir_v3` / contract | 没有 **Intent** 一等公民；没有 `CANDIDATE → CONFIRMED` 生命周期；来源文本与假设没有进契约 |
| **EDA 引擎证据驱动**（工具为结论背书；Evidence Store） | append-only `evidence/ledger.jsonl`、`derive()`、provenance、gates | 没有 **事实类别**（引擎观测 / 派生 / 假设 / 人工决定）；没有 **claim → evidence** 绑定；LLM 生成物和工具事实同库不同类 |
| **可治理控制平面**（策略 / 权限 / 风险 / 审批 / 审计） | approval gate、`signoff_policy.yaml`、waivers、`tool_receipts.jsonl`、`llm_audit.jsonl` | 审批是**阶段门**，不是**动作级策略引擎**；没有 AUTO / APPROVAL / FORBIDDEN 三态；没有统一 action audit |

一句话：**我们已经有“判定内核”，缺的是“判定之前”的意图与“判定之后”的治理。**

---

## 2. 目标主链

```text
自然语言 / 规格 / 验证计划
        │
        ▼
[Intent Model]  候选语义映射（CANDIDATE）
        │        · 信号 / 事务 / 场景 / 断言 / 覆盖率 / 证据需求
        │        · assumptions / source_span / confidence
        ▼
EDA 校验 或 人工确认  ──►  CONFIRMED / REJECTED（写入证据库）
        │
        ▼
[Unified IR v3]  attributes / behaviors / configurations / resources / verification
        │
        ▼
[Contract]  claims[] + obligations[]（每条义务绑定 claim_id）
        │
        ▼
Agent 提议动作 ──► [Control Plane] AUTO / APPROVAL / FORBIDDEN
        │                  │
        │                  └─ 决策写入 action audit（含审批 token）
        ▼
EDA 引擎执行 ──► [Evidence Store]  编译 / 仿真 / 形式 / 波形 / 覆盖率 / 证明 / 人工
        │                  │
        │                  └─ fact_class: OBSERVED | DERIVED | HYPOTHESIS |
        │                                  HUMAN_DECISION | TOOL_RECEIPT
        ▼
Agent 解释证据 ──► 工程师审查（Govern / Guide / Judge）
        │                  │
        │                  └─ 审查结论回写证据库 + 下一次迭代上下文
        ▼
derive()  ──►  Gates  ──►  Signoff（三态 + 人工裁决）
```

**硬规则：`derive()` 只吃 `OBSERVED` / `HUMAN_DECISION` / 受控 `DERIVED`；
`HYPOTHESIS` 永远不能单独把义务推成 PROVEN。**

---

## 2.1 未来验证工程师：Govern / Guide / Judge

| 职责 | 含义 | 落到哪里 |
|---|---|---|
| **Govern** | 定边界、批高风险动作、管智能体团队 | `control_plane/` 策略 + approvals + action audit |
| **Guide** | 定义意图、假设、优先级；拒绝错误语义映射 | `intent/`（CANDIDATE→CONFIRMED）+ worklist |
| **Judge** | 裁决证据是否充分、是否签核、是否豁免 | `gates` / `verdict` + `HUMAN_DECISION` 事实 |

**工程师不是“消息发送者”，而是闭环里的治理节点**：他可以批准/否决智能体动作，
但审批本身也要作为证据被记录、被审计、可复核。

---

## 2.2 Pillar 2：五步闭环与反馈

```text
① Agent proposes       ② Tools validate       ③ Evidence Store records
        │                       │                        │
        └──────────────► ④ Agent interprets ◄────────────┘
                                │
                                ▼
                        ⑤ Engineer reviews
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
        回写证据库（审批/裁决）          下一次迭代上下文（证据 + 计划）
```

| 步骤 | 当前落点 | 缺什么 |
|---|---|---|
| ① 智能体提议 | P5 `ActionCandidate`、StimulusPlan、生成物 | 提议必须带 `claim` 与 `evidence_required`，且默认 `HYPOTHESIS` |
| ② 工具验证 | executors + EDA backends + `tool_receipts.jsonl` | 回执要带 `act_id` 与输入/输出哈希；工具缺失时显式 `unavailable` |
| ③ 证据库记录 | `evidence/ledger.jsonl` + provenance | 缺 `fact_class` / `producer_class` / `claim_ids` |
| ④ 智能体解释 | 目前没有独立产物 | 缺 **Interpretation**：`evidence_ids[] / insights[] / plan_updates[]`，默认 `HYPOTHESIS` |
| ⑤ 工程师审查 | approval gate / waivers / verdict | 审查结论要作为 `HUMAN_DECISION` 证据回写，并绑定被审对象哈希 |
| 反馈 | 覆盖率/缺口→动作 | 缺 **context retrieval**：按 claim/obligation 聚合证据与未决项，形成下一轮上下文 |

---

## 2.3 Governed Agent Team（受治理的智能体团队）

| 芯华章角色 | 本仓库对应 | 允许动作（示例） | 证据要求 |
|---|---|---|---|
| Requirement Agent | design / front | 读规格、产候选 Intent、提假设 | 意图必须有 `source_span`；不能直接改 contract |
| Assertion Agent | verify | 产候选断言/约束、编译校验 | 每条断言绑 `claim_id`，需编译/形式证据 |
| Emulation Agent | ops / execution | 跑仿真、回归、覆盖率采集 | 回执 + 波形/覆盖率证据 |
| Debug Agent | debug | 提调试假设、定位故障 | 假设默认 HYPOTHESIS，需仿真/波形复核 |
| （现有）Coverage / Audit | coverage / audit | 归因、门禁、签核证据包 | 只读派生；不能改账本 |

治理约束：

- 每个角色有**允许动作白名单**（`control_plane/roles.py`），未知动作默认 `FORBIDDEN`；
- **智能体不能审批自己的提议**（approver ≠ proposer）；
- 任何跨边界动作（改意图、改假设、豁免、影响签核）都必须走工程师审批。

---

## 2.4 EDA 证据来源

| 工具 | 证据种类 | 当前状态 |
|---|---|---|
| Simulation | `sim_result` / 波形 / 断言 | ✅ 已有仿真与日志 |
| Debug | 调试会话 / 波形定位 | ✅ 日志与 task_meta |
| Formal Verification | `formal_proof` / `proof_core_coverage` | ⚠️ 仅 path_result，未接证明器 |
| Lint / CDC / RDC | `lint_report` / `cdc_report` / `rdc_report` | ❌ 未实现，先加证据类型与适配器位 |
| Emulation | `emulation_run` | ❌ 未实现 |
| Regression Infrastructure | 轮次 / 种子 / 合并覆盖率 | ✅ round_manifest / seed_index |

原则：**工具不在就报 `unavailable`，不伪造证据**；证据种类先定，适配器后接。

---

## 3. 新增模块（按现有分层放）

### 3.1 L3 · `intent/` —— 验证意图模型

```text
src/layers/l3_decision/intent/
  schema.py      Intent, IntentGoal, Mapping, Assumption, IntentStatus
  compiler.py    spec / NL / xlsx → 候选 Intent（不写 case_ir）
  validator.py   引用闭合：信号/事务/场景是否存在于 IR
  promote.py     CANDIDATE → CONFIRMED / REJECTED（需证据或审批）
```

关键字段：

```text
intent_id, source (spec/xlsx/human/agent), source_span, statement
goals[]: {kind: signal|transaction|scenario|assertion|coverage|evidence, target, rationale}
assumptions[], confidence, status, confirmed_by, evidence_ids[]
```

- **生成即候选**：compiler 只能产 `CANDIDATE`；
- 进入 `case_ir` / contract 前必须 `CONFIRMED`（EDA 校验或人工审批）；
- `REJECTED` 的假设保留，作为“为什么没这么测”的证据（不删）。

### 3.2 L4 · `evidence_store/` —— 统一证据库

不新建平行事实系统：**是现有 ledger 之上的类型化视图 + 索引**。

```text
src/layers/l4_memory/evidence_store/
  kinds.py           EVIDENCE_KINDS / FACT_CLASSES / PRODUCER_CLASSES
  writer.py          append(evidence) —— 复用 hash chain + contract_anchor
  query.py           evidence_for(claim/obligation/tp/case)、claims_coverage()
  index.py           docs/evidence_index.json（可重建缓存）
  interpretation.py  证据解释记录（HYPOTHESIS，待工程师复核）
  context.py         下一次迭代上下文（证据 + 未决义务 + 已批决策）
```

事实类别：

| fact_class | 来源 | derive 是否采信 |
|---|---|---|
| `OBSERVED` | 仿真 / 形式 / 编译 / 覆盖率引擎 | ✅ |
| `HUMAN_DECISION` | 审批、豁免、裁决 | ✅ |
| `DERIVED` | 纯函数推导（带输入哈希） | ✅（可重放） |
| `HYPOTHESIS` | LLM / Agent 生成 | ❌（需升级） |
| `TOOL_RECEIPT` | 工具调用回执 | 仅审计 |

证据种类对齐芯华章：`compile_result`、`sim_result`、`formal_proof`、
`waveform`、`coverage_report`、`proof_core_coverage`、`human_approval`、
`action_decision`。

### 3.3 L3 · `control_plane/` —— 动作级治理

```text
src/layers/l3_decision/control_plane/
  actions.py     Action 词表 + 风险分类
  roles.py       智能体角色白名单（Requirement/Assertion/Emulation/Debug）
  policy.py      读 config/control_plane.yaml（模块可覆盖）
  decide.py      decide(action, context) → AUTO | APPROVAL | FORBIDDEN
  approvals.py   审批请求 / token / 过期 / 绑定 action hash
```

策略样例：

```yaml
defaults:
  unknown_action: FORBIDDEN        # 默认拒绝，白名单放行
rules:
  - action: run_simulation        -> AUTO
  - action: generate_assertion    -> AUTO      # 只产 candidate
  - action: read_coverage         -> AUTO
  - action: modify_intent         -> APPROVAL
  - action: change_assumption     -> APPROVAL
  - action: waive_failing_proof   -> APPROVAL  # 需 owner + approver
  - action: affect_signoff_state  -> APPROVAL
  - action: accept_caveat         -> APPROVAL
  - action: edit_ledger           -> FORBIDDEN
  - action: fabricate_evidence    -> FORBIDDEN
  - action: bypass_gate           -> FORBIDDEN
```

每次决策写 `docs/action_audit.jsonl`：

```json
{"act_id":"ACT-...","action":"modify_intent","risk":"HIGH",
 "decision":"APPROVAL","policy_id":"CP-007","appr_id":"APR-...",
 "input_sha256":"...","output_sha256":"...","actor":"agent:design"}
```

### 3.4 Contract / Gates 的增量

- `contract` 增加 `claims[]`：`claim_id / statement / subject / evidence_required[] / status`；
- 每条 `obligation` 增加 `claim_ids[]`；**没有 claim 的义务只能是 `PARTIAL`**；
- `verdict` 增加三个硬失败来源：
  1. `claims_without_evidence`（claim 没有引擎/人工证据）
  2. `hypotheses_in_contract`（HYPOTHESIS 混进契约）
  3. `unapproved_high_risk_actions`（高风险动作无审批 token）
- 形式验证证据补 `proof_core_coverage`，进入 gates 的覆盖分母（对齐芯华章指标）。

### 3.5 解释与上下文（闭环的 ④ 和反馈）

```text
Interpretation
  interp_id, actor (agent:design|verify|debug), evidence_ids[],
  insights[] (每条带 claim_id / confidence),
  plan_updates[] (动作候选 / 新义务 / 需人工确认项),
  status: DRAFT | REVIEWED | REJECTED, reviewed_by, reviewed_at
```

- 解释**不是事实**：默认 `HYPOTHESIS`，只有工程师复核后其结论才可晋升；
- `context.py` 聚合：命中证据 + 未决义务 + 被拒解释 + 已批动作 →
  `status/next_iteration_context.json`，作为下一轮 Agent 的**唯一上下文入口**；
- 这样“为下一次迭代检索上下文”是确定性查询，而不是把历史全塞回 prompt。

---

## 4. 现有代码的改造点

| 位置 | 改什么 |
|---|---|
| `verification_os/contract_model.py` | `Fact` 增加 `fact_class` / `producer_class` / `claim_ids`；`FactBundle` 带 `actor` |
| `l3_decision/contract/derive.py` | 只采信 `OBSERVED` / `HUMAN_DECISION` / 合法 `DERIVED`；`HYPOTHESIS` 记 `UNKNOWN` |
| `l3_decision/obligation/derive.py` | 义务状态受 claim 证据约束；`FAILED` 与 `UNKNOWN` 已分开，继续保留 |
| `evidence/evidence_pipeline.py` | 增加 `evidence_index` 步（重建索引，不改变判定） |
| `l2_orchestration/runtime.py` | 工具调用前 `control_plane.decide()`；回执带 `act_id` / `appr_id` |
| `l2_orchestration/evidence/verdict.py` | 并入 claim/evidence/审批三类硬失败 |
| `l3_decision/evidence/evidence_pipeline` | 增加 `interpretation` / `context` 两步（只产候选，不改判定） |
| `executors/audit` | 收走 `interpretations.json` / `next_iteration_context.json` |
| `l3_decision/case_ir` / TP | 增加 `intent_id`；生成前校验 Intent 已 `CONFIRMED` |
| `tools/.../casemodel_tools` | 从 Intent/IR 读语义，不自行解释规格 |
| `executors/*/audit` | 证据包收录 `intent` / `claims` / `action_audit` / `evidence_index` |
| `workbench`（PySide6） | 增加“意图状态 / claim 证据链 / 高风险动作审批”视图（只读优先） |

---

## 5. 分阶段实施（增量、golden 安全）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **A. 意图与 Claim** | `intent/` + `claims` 字段（additive）；生成期只产 CANDIDATE | `intents.json` 可编译；未确认意图进不了 contract |
| **B. 证据类别与解释** | ledger 事实加 `fact_class` / `producer_class`；`interpretation.py` + `context.py`；derive 过滤 HYPOTHESIS | 旧 run 缺字段按 `OBSERVED` 兼容；golden 0 差异 |
| **C. 控制平面与角色** | 策略引擎 + 角色白名单 + 动作审计；runtime 工具调用接入；审批 token 绑定 action | 每个高风险动作都有 `act_id + appr_id`；默认拒绝未知动作 |
| **D. 门禁收紧** | verdict 加 claim/审批三类硬失败；形式 proof core coverage | 现有 run 在 stage=report 下先只报告 |
| **E. 智能体改造** | Agent 输出统一写 HYPOTHESIS + claim_id；禁止直接写事实；解释与提议分离 | `grep` 不到 agent → ledger OBSERVED 的写路径 |
| **F. 闭环反馈** | `next_iteration_context.json` 成为下一轮唯一上下文入口 | 下一轮 plan 能追溯到证据/义务/审批 |

**顺序不能反**：先有事实类别，才能收紧 derive；先有控制平面，才允许 Agent 自动动作。

---

## 6. 不变量（改造期间必须保持）

1. **模型不是事实源**：LLM/Agent 输出只能进 `HYPOTHESIS`，升级需引擎证据或人工决定。
2. **不建平行账本**：Evidence Store 是 ledger 的索引视图，不是第二份事实。
3. **确定性裁决**：`derive()` 仍是唯一判定；控制平面只决定“能不能做”，不决定“对不对”。
4. **身份不另起**：`tp_id/case_id/tst_id/evd_id/cell_id` 不变；新增 `intent_id/claim_id/act_id/appr_id`。
5. **默认拒绝**：未知动作 / 无证据 claim / 未审批高风险动作 → 不能签核。
6. **人工是治理节点**：改需求、改假设、豁免、影响签核的动作必须留审批记录。
7. **依赖方向**：策略判定在 L3，审计存储与索引在 L4，执行器只调用。

---

## 7. 一句话

**把“生成 → 证据 → 治理”补成一条链：Intent 决定测什么（候选假设），
Evidence Store 证明凭什么信（引擎事实），Control Plane 规定谁能做（动作边界）；
现有 contract / derive / ledger / gates 不重写，只加类型与约束。**

---

## 8. 执行状态（2026-11-04）

| 阶段 | 状态 | 落点 |
|---|---|---|
| A Intent + Claim | ✅ | `l3_decision/intent/`、`l3_decision/claims/` |
| B 事实类别 + 解释/上下文 | ✅ | `contract_model.Fact`、`derive._by_type`、`l4_memory/evidence_store/` |
| C 控制平面 + 角色 + 审计 | ✅ | `l3_decision/control_plane/`、`config/control_plane.yaml` |
| D 门禁读数 | ✅（默认 report） | `case_view/gates.py`、`audit._apply_evidence_gate` |
| E Agent 输出假设化 | ✅（解释层 + LLM 审计） | Interpretation 默认 HYPOTHESIS；LLM 审计行带 `fact_class/producer_class/claim_id`；ledger 过滤 HYPOTHESIS |
| EDA 证据源 | ✅（真实 + 占位） | `docs/evidence_sources.json`：sim/regression/debug 真实；formal/lint/cdc/rdc/emulation 显式 unavailable |
| F 闭环反馈 | ✅ | `status/next_iteration_context.json` |

验证：`compileall` ok；新包 import ok；guard `ok`（import 0 / line 0 / complexity 0）；
基线 run 拷贝上 Intent 13 / Claim 74 / evidence_index 388 OBSERVED /
interpretations 1 项 / next_context 正常生成。
