# 根本重构计划：从流程驱动到契约驱动（Verification OS v3）

> 状态：**M0（影子模式）已落地（2026-11-04）**，M1–M5 待推进。
> 落点：`src/layers/l3_decision/contract/`（契约 / 义务 / 账本 / 推导 / 影子）。
> 实测（npu_sched）：58 条义务 / 47 个事实包 / 212 条事实 / **对账 47 条、0 差异**，
> 哈希链完整。上一版 `architecture_transformation_plan.md`（Case View / 三集合）
> 已落地；本文回答它之后的那个问题：**这套东西离"本质跃迁"还差什么，怎么把差的部分
> 换掉，而不是继续往上叠。**
> 关联：`ARCHITECTURE.md` §9.11–§9.12（现有标准）、`docs/design/architecture_transformation_plan.md`
> （推导过程）、`docs/design/case_coverage_and_wave_traceability.md`。

---

## 0. 一句话

**把"流水线跑完 → 出报表"的架构，换成"契约 → 义务 → 事实 → 推导 → 裁决"的架构。**

现有的三集合、CELL、门禁都保留 —— 但它们的**控制方向要反过来**：
不再由阶段顺序决定产出什么，而由**契约产生的义务（Obligation）**驱动整条链；
不再由各处代码各自算状态，而由**一份只追加的事实账本 + 一套推导规则**算出唯一结论；
签核不再是"某一轮跑到了 audit"，而是**义务被清偿的比例**。

一句话概括这次重构：**换掉的是"谁说了算"——从流程节点，换成事实与规则。**

---

## 1. 现状审计（诚实版）

上一轮已经把 Case 契约、三集合、CELL、门禁、增量证据包做出来了。但按四个本质维度
对照，当前实现**仍然是一个"契约增强过的流程架构"**，不是契约架构：

| 本质维度 | 目标形态 | 现状 | 差距 |
|---|---|---|---|
| **数据主权** | 契约先于执行；没有契约不许跑 | `case_ir` 在 **verify 阶段生成**，是流程产物；ops 可以先跑再谈契约 | 契约不是构建物，是流水线中间件 |
| **验证粒度** | 三元组驱动的状态机 | 三集合已落地，但 **tp_matrix / case_tp / tp_cov_evidence / cell_matrix / case_view 五份投影各自算状态** | 状态有五份实现，天然会漂 |
| **拓扑** | 反向溯源：Cell → 义务 → 事实 → 执行 | 已有 `case_group_map`，但"为什么红"仍要人去读 4~5 个 JSON | 没有统一的 **义务—事实** 图 |
| **防伪** | 零信任：账本 + 规则推导 | `case_ir_sha` 已进 task_meta，gates 有 8 条，但结论是**各阶段各自 append 的 JSON** | 没有不可篡改的事实账本；`report.json` 是最后一步"写死"的 |

另外三处流程残留，是这次要动刀的地方：

1. **24 节点闭环**：verify/ops/coverage/audit 的先后由图的边决定；想"只补一条 SVA
   的证据"也得从头跑一轮。
2. **五份投影链**：`case_cov → case_tp → tp_matrix → tp_cov_evidence → cell_matrix
   → case_view`，每一步都重算一次状态（`SIGNED_OFF`、`PROVEN`、`green` 各有一套判据）。
3. **audit 是"阶段"不是"裁决器"**：caveat 从 5 个文件里拼，verdict 在最后一步合成；
   `gates.py` 只是被调用，不是规则引擎。

**结论**：上一轮换的是"心脏"（Case 的定义）和"神经末梢"（三集合证据）；
这一轮要换的是**中枢**——谁产生义务、谁记账、谁推导结论。

---

## 2. 目标架构：五层模型

```text
┌──────────────────────────────────────────────────────────────────────┐
│  L5 裁决（Adjudication）                                              │
│    规则引擎：obligation + facts → status → verdict；Caveat/豁免/审批    │
├──────────────────────────────────────────────────────────────────────┤
│  L4 推导（Derivation）                                                │
│    纯函数：derive(obligations, facts) → statuses（无副作用、可重放）     │
├──────────────────────────────────────────────────────────────────────┤
│  L3 事实账本（Evidence Ledger）                                       │
│    append-only、按契约哈希绑定、每条事实带 producer + run/seed + sha     │
├──────────────────────────────────────────────────────────────────────┤
│  L2 义务（Obligations）                                               │
│    契约编译器产出：每个 group/sva/scb/tp 一条义务，带谓词与所需事实类型    │
├──────────────────────────────────────────────────────────────────────┤
│  L1 契约（Contract）                                                  │
│    casemodel / xlsx → Case IR（唯一可编辑源），带版本与哈希             │
└──────────────────────────────────────────────────────────────────────┘
        ▲ 生产端（LLM/工具）只做两件事：产出候选契约、产出事实
        ▼ 消费端（CLI/GUI/CI）只读 L3/L4：账本与推导结果
```

四条不变量（写进 CI，不靠自觉）：

1. **无契约不执行**：没有 `contract_id` 的回归任务一律拒绝生成。
2. **事实只追加**：账本一旦写入不可修改；更正靠"新事实 + 指向旧事实的 `supersedes`"。
3. **状态只推导**：任何 `SIGNED_OFF / green / VERIFIED` 都只能由 `derive()` 产生，
   不允许任何模块自己写死。
4. **视图只渲染**：GUI/HTML/CLI 不计算判据，只画 `derive()` 的结果。

---

## 3. 核心数据模型

### 3.1 Contract（L1）

现有 `case_ir_v1` 升级为 `contract_v2`：

```yaml
contract:
  id: CT-NPU_SCHED-20261104-3fa9
  module: npu_sched
  hash: sha256(canonical_yaml)
  cases:
    - id: CASE-D_DEP
      groups:
        - {group: CG-D_DEP, coverage_type: 观测覆盖, required_layers: [functional],
           scope: 指令队列管理, coverpoints: [cp_dep_type], requirements: [REQ-NPU-004]}
      sva:  [{id: SVA-RAW_NEVER_ISSUES, expr: "...", required: true}]
      scb:  [{id: SB-NPU-DUT, evidence: aggregate, required: true}]
```

**契约是构建物**：`vagent contract build` 由 casemodel/xlsx 生成，写入
`<run>/contract/contract.yaml`，并把 `contract.hash` 注入**每一条**下游事实。
没有 `vagent contract build`，`ops` 拒绝开跑。

### 3.2 Obligation（L2）

```json
{
  "obligation_id": "OBL-CASE-D_DEP-CG-D_DEP-P1-functional",
  "contract_id": "CT-NPU_SCHED-...",
  "kind": "group_layer",              // group_layer | sva | scb | tp_bin | timing | path
  "subject": {"case": "CASE-D_DEP", "group": "CG-D_DEP", "cell": "CELL-D_DEP-P1"},
  "predicate": {
    "fact_type": "bin_hit",
    "where": {"cp": "cp_dep_type", "bins": ["*"], "stage": "p1"},
    "op": "all_bins_hit"
  },
  "required": true,
  "depends_on": []
}
```

义务由**契约编译器**一次性展开（`contract → obligations`），数量可预测
（当前 npu_sched：13 组 × 层 + 4 SVA + 1 SCB + 70 TP ≈ 120 条）。
**义务是流水线的输入**，不是它的输出。

### 3.3 Fact（L3）

```json
{
  "fact_id": "F-000123",
  "type": "bin_hit",                  // bin_hit | sva_result | scb_result | timing | wave | log
  "contract_hash": "3fa9…",
  "run_id": "...", "tst_id": "TST-...@10001", "seed": 10001,
  "subject": {"cp": "cp_dep_type", "bin": "raw"},
  "value": {"hits": 12},
  "producer": "coverage.collector@v3",
  "evidence": {"ucdb": "cov/.../questa.db", "log": "sim_vsim.log"},
  "prev_hash": "…"                    // 哈希链
}
```

事实**只有生产者、没有编辑器**：`coverage` 写 `bin_hit/sva_result/scb_result/timing`；
`ops` 写 `wave/log`；`verify` 写 `generated`（证明某文件由哪个契约生成）。

### 3.4 Derivation（L4）与 Adjudication（L5）

```python
statuses = derive(contract, obligations, ledger)   # 纯函数，可重放
verdict  = adjudicate(contract, statuses, policy)  # 规则 + 豁免 + 审批
```

`derive` 的输出是一张表：`obligation_id → {status, discharged_by, reasons}`。
状态词汇与今天一致（PROVEN / PARTIAL / MISSING / PENDING_BACKEND / NOT_APPLICABLE），
但**只有一处实现**。

---

## 4. 模块重构（改什么、删什么）

### 4.1 保留并升格

| 现有 | 新角色 | 变化 |
|---|---|---|
| `humanview/case_ir` | **契约编译器**（L1→L2） | 新增 `compile_obligations()`；`case_ir.json` 改名 `contract/contract.yaml` |
| `coverage_tools/evidence_pipeline` | **事实采集器**（L3 写入端） | 只写事实，不再算 `PROVEN/green` |
| `humanview/case_associate_view/gates` | **规则引擎**（L4/L5） | `gates.yaml` 升级为推导规则表（可组合、可版本化） |
| `case_associate_view`（视图） | **渲染器** | 只读 `derive()` 结果 |
| `signoff_package` | **账本导出器** | 导出 ledger + 推导结果 + 回放配方 |

### 4.2 合并/删除（这是"根本"的部分）

| 现有 | 处置 | 理由 |
|---|---|---|
| `case_cov` 里的 `signed_off/case_status` | **删除判定字段**，只留原始命中 | 判定归 L4 |
| `case_tp.json` | **合并进 ledger**（`tp_bin` 事实 + 视图） | 与 `tp_matrix` 重复 |
| `tp_matrix.json` | 降级为**导出视图**（从 ledger 推导后渲染） | 五份投影之一 |
| `tp_cov_evidence.json` | 降级为**导出视图** | 同上 |
| `cell_matrix.json` | 降级为**导出视图** | 同上 |
| `report.json` 的 verdict | 改为**导出视图**（adjudicate 的结果快照） | 不再由 audit 阶段"写死" |
| audit 的 `_caveat` 拼接 | 改为**规则输出**（每条 caveat 由一条规则产生，带 `rule_id`） | 现在 caveat 与 gate 是两套 |

> 保留的**实体**只有三样：**契约**、**事实账本**、**推导结果**。
> 其余全部是这三样的派生视图（可随时删掉重建）。

### 4.3 主链的去流程化

`front → verify → ops → coverage → audit` 五个节点仍在，但职责变成：

| 节点 | v3 角色 | 不再做的事 |
|---|---|---|
| front | 产 spec/输入 | — |
| verify | **编译契约** + 生成实现 | 不再"顺带"算签核状态 |
| ops | 按义务清单**规划执行**（worklist） | 不再固定 loopback→p0→p3 的死顺序，而是"清偿义务需要哪些 test/seed" |
| coverage | **采集事实**（追加进账本） | 不再算矩阵/CELL |
| audit | **裁决**（derive + adjudicate + 导出） | 不再从 5 个文件拼 caveat |

**闭环保留，但驱动方式变了**：从"跑到收敛"改为"义务清偿率到阈值"；
未清偿的义务自动变成下一轮 worklist（`OBL-... → need test=tp_npusch_d_dep_raw seed=4001`）。

---

## 5. 目录与产物（v3）

```text
<run>/
├── contract/
│   ├── contract.yaml            # L1 唯一可编辑源（生成物，带 hash）
│   ├── obligations.json         # L2 展开结果（带 hash，供 ops 规划）
│   └── contract_manifest.json   # hash + 生成器版本 + 输入 sha
├── evidence/
│   ├── ledger.jsonl             # L3 只追加事实（每行带 prev_hash）
│   └── ledger.lock              # 写入锁 + 最后一条 hash
├── status/
│   ├── obligations.json         # L4 derive 结果（每条义务一条）
│   └── verdict.json             # L5 adjudicate 结果（含规则 id / 豁免）
├── coverage/                    # 只保留原始产物（case_cov 原始命中 / ucdb）
├── regression_run/              # 度量原件（不变）
└── signoff_evidence/            # 导出：contract + ledger + status + 视图
```

`case_view.{json,md,html}` 仍然在 `coverage/`（兼容），但它现在只是
`status/` 的**渲染**；GUI 读 `status/`，不读中间 JSON。

---

## 6. 分阶段落地（每阶段都可停、可回滚）

### M0 —— 账本与义务的"影子模式"（1 周）✅ 已落地

- 新增 `contract/obligations.json`、`evidence/ledger.jsonl`；**不改变现有判定**。
- 现有流水线照跑，结束时把同样的事实**双写**进账本。
- 验收：`derive()` 的结果与现有 `cell_matrix` **逐条一致**（影子比对，差异进日志）。

**落地情况**（`src/layers/l3_decision/contract/`）：

| 模块 | 内容 |
|---|---|
| `contract_model.py` | Pydantic 强类型：`Contract / CaseSpec / GroupSpec / SvaSpec / ScbSpec / Obligation / Predicate / Fact / FactBundle`；`FACT_TYPES` 是唯一事实清单，未知类型/证据层在类型层就拒 |
| `compiler.py` | `compile_obligations()`：每层一条 group 义务 + 每 SVA/SB 一条；id 确定性生成 |
| `ledger.py` | append-only JSONL + `prev_hash` 哈希链；按 **FactBundle 批次**写、每包一次锁；重复包幂等；`verify_chain` 能抓篡改 |
| `derive.py` | 唯一判定实现（纯函数）：`all_bins_hit / ok / matched / proven / no_fail / executed` |
| `shadow.py` | `run_shadow()`：case_ir → Contract → 义务 → 事实包 → 账本 → 推导 → 与 case_cov 逐条对账，写 `status/shadow_report.json` |

影子对账口径：**case 级**（组结果 / SVA / SCB / case_status）。
实测 npu_sched：**58 义务 / 47 包 / 212 事实 / 47 条对账 0 差异**；批次测试
（220 条无 case 身份）如实计入 `bundles_skipped_no_case`，不混进对账。
CELL 主色仍由 `tp_cov_evidence` 提供，M2 接管。

### M1 —— 契约成为构建物（1 周）✅ 已落地

- `vagent contract build`（新增），ops 前置校验 `contract.hash`。
- `task_meta` 记 `contract_hash`（替换 `case_ir_sha`，语义更准）。
- 验收：没有契约时 ops **拒绝开跑**；换了契约，旧账本事实自动标 `stale`。

**落地情况**：

| 落点 | 内容 |
|---|---|
| `verification_os/build.py` | `write_contract()` 产出 `contract/{contract.yaml, obligations.json, contract_manifest.json}`；`check_contract()` 校验哈希自洽；`load_contract()` 读回 |
| verify | Case IR 落盘后立刻编译契约（`executors/verify/ir_artifacts.py`），契约文件进本轮产物清单 |
| ops | `_contract_gate()`：**有 TP IR 却没有（或损坏的）契约 → 拒绝开跑**；历史/手工 run（无 TP IR）不误伤；`SIGNOFFAI_CONTRACT_GATE=off` / `params.contract_gate=False` 可显式旁路 |
| `task_meta` | 新增 `contract_hash`（读 `contract/contract_manifest.json`），`case_ir_sha` 保留为兼容键 |
| 账本 | 事实的 `contract_hash` 来自**构建物**；契约换版后旧事实计入 `stale_facts`，不参与新契约推导（只追加、不删除） |
| CLI | `vagent contract build / check / show` |

**修掉的一个真 bug**：契约哈希原先包含 `id`，而 `id` 又由哈希派生 —— 读回来永远
对不上清单。现在 `compute_hash` 排除 `hash` 与 `id`（内容哈希），往返一致。

### M2 —— 事实采集统一（1–2 周）✅ 已落地

- `coverage` 只写事实；`case_cov` 去掉 `signed_off / case_status`。
- `derive()` 接管 `case_tp / tp_matrix / tp_cov_evidence / cell_matrix` 的判定，
  这些文件改为导出。
- 验收：五个文件的判定字段**全部由 derive 生成**（旧实现删除）。

**已落地（M2a）**：

| 落点 | 内容 |
|---|---|
| `verification_os/tp_shadow.py` | run 级 `bin_hit`（**与 `_tp_matrix` 同源**：优先计划合并报告 `tp_report`，不是单测报告）+ `tp_attr` 事实；`derive_tp_status()` 复现 HIT/MISS/OBSERVED/BACKDOOR/UNMAPPED/PENDING_BACKEND |
| `collect_real_coverage._status_for` | **改为委托** `verification_os.tp_shadow.status_for_hits` —— TP 状态判据只剩一份实现（"状态只推导"从 TP 级开始成立），产物形状不变 |
| evidence_pipeline | 新增 `os_tp_shadow` 步：run 级事实与 TP 属性入账本，写 `status/tp_shadow.json` |
| 实测 | npu_sched：**70 条 TP、106 条 run 事实、0 差异** |

**M2b（判定切换，已完成）**：

| 落点 | 内容 |
|---|---|
| `verification_os/case_judge.py` | `build_raw_facts()`（bins / sva present+fail / scb aggregate+逐条 / timing）+ `judge_case()`（编译该 case 的义务 → derive → 组层状态 / SVA / SCB / case_status） |
| `case_cov._evaluate_case` | 采集端只给**原始事实**，判定改由 `judge_case()` 给出（无契约时保留旧判定作兼容）；字段形状不变，`sva[]` 新增 `present`（断言有没有被求值过） |
| `tp_evidence._contract_status` | 委托 `derive.tp_contract_status`（四层证据 → VERIFIED/PARTIAL/NOT_VERIFIED 只剩一份实现） |
| 实测 | **267 份 case_cov 的判定字段与改造前逐条一致；case shadow 0、TP shadow 0** |

顺带修掉一个**流水线顺序 bug**：`evd` 原先排在 `cell_matrix` 之前，导致新 run 的
EVD 行 `cells` 全空（47 行），只有重跑时拿到上一轮 cell_matrix 才对。现在
`cell_matrix → evd`，`with_cells` 118 → 165 且两次重跑逐字节一致。

> 说明：`case_cov / case_tp / tp_matrix / tp_cov_evidence / cell_matrix` 的
> **字段仍然保留**（下游读者不变），但它们的判定已全部由 derive 产出 ——
> 保留的是"导出的缓存"，不是第二套判据。

### M3 —— 规则引擎（1 周）✅ 已落地

- `gates.yaml` 升级为**推导规则**（条件 + 证据类型 + 级别 + 规则 id）。
- 每条 caveat 带 `rule_id`；`EXPECTED_CAVEATS` 改为从规则表生成。
- 验收：新增一条规则 = 改一处 YAML；CI 能列出"每条 blocker 的证据链"。

**落地情况**：

| 落点 | 内容 |
|---|---|
| `gates.yaml#declarative` | **纯 YAML 规则**：`source`（case_cases / case_groups / case_cov / cells / evd / view_cases）+ `where`（eq/ne/empty/nonempty/missing/present/in）+ `target`/`message` 模板 + `evidence` 字段 + `enabled` |
| `gates.py` | 声明式规则求值器 + 规则表导出（`rules_table`）+ finding 统一带 `rule_id` 与 `evidence`；`enabled: false` 直接关掉一条规则 |
| CLI | `vagent coverage case-gate --rules` 列出规则表（id / 级别 / 阶段 / 开关） |
| 实测 | npu_sched：规则表 19 条；新增的 `CASE_GROUP_NO_REQUIREMENT` 在真实 run 上命中了 1 条（行为域组没有需求编号）—— 新规则不写代码就生效 |

`EXPECTED_CAVEATS` 仍按 audit 的 caveat 白名单维护（caveat 是审计口径，规则是门禁
口径，两者刻意不合并）；但每条 caveat 的 message 已带 `rule@target`。

### M4 —— 义务驱动的执行规划（2 周）🟡 已落地（opt-in）

- ops 从"跑全量"改为"按未清偿义务生成 worklist"；种子/分级由义务属性决定。
- 保留"全量回归"开关（CI nightly），但默认是义务驱动。
- 验收：补一条 SVA 证据 < 3 分钟（不重跑全量）；每轮耗时下降可量化。

**落地情况**：

| 落点 | 内容 |
|---|---|
| `verification_os/worklist.py` | `build_worklist()`：契约义务 −（当前契约事实推导出的）已清偿 = 未清偿；按 `tp_ids`/`case_id` 映射到 TP，再按 `regression_gen` 同一口径（`tp_<slug>`）映射到**真实存在**的回归 test；产出 `status/worklist.json` + 正则 |
| ops | `_regression_filter()`：**默认**在账本已有历史证据时用 worklist 正则；`params.worklist=False` 或 `SIGNOFFAI_WORKLIST=0/off/false` 显式关掉，否则回落增量基线/全量；算不出来（无契约/无回归清单/全新 run）**回落全量**，不静默缩小 |
| CLI | `vagent contract worklist --run …` |
| 实测 | npu_sched：58 条义务中 **25 条未清偿 → 47 条 test**（本轮 55 个任务 = 47 test + 8 build）；**163 s vs 全量 847 s（约 5×）**，273 → 55 条用例；另有 15 条映射不到回归 test（观测型/行为域组没有独立用例）进 `skipped_no_test` |

> 实测时踩到一个与产品无关的坑：把 run 复制到**更长**的目录名下跑，coverstore
> 路径超过 Windows MAX_PATH，`vsim-7` 打不开覆盖率库 → 该用例判 fail；换回短
> 目录名后 55/55 全过。worklist 本身没问题，但"输出目录别太长"值得进 `known_limitations`。

**默认开关（已翻）**：worklist **默认开**，但只在**账本里已有历史证据**时生效
（`prior_evidence`）。全新 run 的账本是空的，"全部未清偿"只是因为还没跑过 ——
此时 worklist 只含 TP test、漏掉批次用例，必须回落全量。显式关闭：
`params.worklist is False` 或 `SIGNOFFAI_WORKLIST=off`。

**仍保留的一处偏差**：没有加 `--worklist` CLI 开关 —— 要穿越
`PipelineState(extra="forbid")` 的 schema 与三处 façade（execution / run_service /
cmd_verify），代价与收益不成比例；环境变量覆盖同一场景。

### M5 —— 消费端切换（1 周）🟡 核心已落地

- GUI/CLI 读 `status/`；`case_view` 只渲染。
- 新增 `vagent why <obligation_id>`：一条命令回答"它为什么红"（缺哪条事实、由
  哪个 run/seed 提供、对应哪条规则）。
- 验收：任意红灯，从 GUI 三次点击内定位到具体事实与 test/seed。

**已落地**：

| 落点 | 内容 |
|---|---|
| `verification_os/explain.py` | `explain()`：契约 → 义务 → 谓词 → 相关事实（**旧契约事实被 stale 过滤**）→ 状态（同一份 `derive`）→ 缺什么 / 该跑哪条 test×seed（从 TP IR 反查）；`status_summary()`：契约 / 账本 / 两级对账 |
| CLI | `vagent contract why <obligation_id> --run …`（非 PROVEN 退出码 1）、`vagent contract status --run …` |
| GUI | 签核页「Case 证据」摘要行追加 **OS** 段（义务数 / 账本事实数 / 两级对账是否一致）；没有契约时如实不显示 |
| 实测 | npu_sched：契约 ok · 账本 468 条 · case/TP 对账一致；`why` 对 `OBL-GROUP-CASE-D_DEP-…` 给出 2651 次 run 级命中 + "该跑 d_dep 四条 test×seed" |

**已补完**：

- 签核页新增第 5 个标签页「**OS 账本**」：义务表（id / 类型 / 用例 / 状态）+
  未清偿计数 + "建议重跑 N 条 test"；数据来自 `flow.signoff.os`（`status_summary()`
  现算义务状态，读的是 `status/` 与账本，不是 `case_view`）。
- **逐条 SB 证据（生成侧已接完）**：case 模型的 `scoreboards[].rules` 声明这条
  SB 负责哪几条检查规则（= `assertions[].name`），verify 生成
  `env_cov_bins.yaml#dut_checker.scoreboards`；env 模板按规则计数归并，打
  `[SCB <id>] total=… matched=… mismatched=…`（有 X 时改打 `unverified=…`，
  不写 `mismatched=0`）。采集侧照旧：有逐条行 `evidence_level=per_scb`，
  没有退回聚合；`evidence: log` 没有自己那行 → `NOT_EXECUTED`。
  采集事实也按同一条行发（不再拿聚合数字冒充逐条）。
- **判据锚点收紧**：回归的 `grep` 从子串 `mismatched=0` 改为
  `(\[SCB_DUT\]|Scoreboard:).*mismatched=0` —— 否则"某条 SB 干净、聚合脏"
  会被逐条行骗过。逐条行与聚合行同一口径：有 X 不写 0。

### 里程碑与停点

| 阶段 | 停点条件（不过就不进下一阶段） |
|---|---|
| M0 | 影子比对 100% 一致（差异必须解释，不允许"差不多"） |
| M1 | 无契约 run 被拒；契约变更后旧事实正确标 stale |
| M2 | 五份导出与 derive 结果逐字节一致（去掉时间戳） |
| M3 | caveat 全带 rule_id；规则表能回放出当前 report |
| M4 | 义务驱动与全量回归的结论一致；耗时有实测下降 |
| M5 | `vagent why` 对 20 个红灯人工抽查全对 |

---

### P6 —— 种子索引（收尾，已落地）

`vagent why` 回答"这条义务为什么红"；种子索引回答它的反面：**这颗 seed
清偿了哪些义务**（可复现证据的索引）。

| 落点 | 内容 |
|---|---|
| `verification_os/seeds.py` | 取当前契约的事实，按 `(tst, seed)` 分组重新 `derive` → 每组的 `discharged / remaining`；`by_seed` 汇总每颗 seed 的清偿数 |
| evidence_pipeline | 新增 `os_seeds` 步 → `status/seed_index.json` |
| CLI | `vagent contract seeds --run …` |
| 实测 | npu_sched：**6 颗 seed / 47 次执行 / 清偿 157 条义务**（seed 10001 清偿 10 条） |

边界：只有带 CASE 身份的执行才有义务（批次级 test 没有 case），所以索引覆盖
**用例证据**；批次用例的合并覆盖率仍由 `tp_shadow` 对账。

---

## 7. 验收指标（可度量，不靠感觉）

1. **宣称可证明率**：任何 `VERIFIED/green` 都能在 3 步内追溯到事实与执行实例。
2. **防伪**：注入一条"伪造 PASS"事实（手工改 JSON）→ 哈希链断裂 + gate 拦截。
3. **可重放**：同一 run 的 `derive()` 重跑逐字节一致；换机器一致。
4. **契约漂移**：改契约后，旧事实标 `stale` 的比例与预期一致（不静默复用）。
5. **补证据成本**：单条义务补齐 ≤ 3 分钟（含仿真），不触发全量回归。
6. **红灯定位**：`vagent why` 输出必须包含 `obligation → 缺的事实类型 → 需要的 test/seed`。

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 账本膨胀（70 TP × 多 seed × 多事实） | 事实按 `(contract_hash, tst, seed, type, subject)` 去重；账本按月分片 |
| 双写期结论不一致 | M0 只做影子，不一致**阻断合并**；M2 一次性切换判定 |
| LLM 生成层的不确定性 | 契约与事实都不由 LLM 直接写；LLM 只产"候选契约"（过 schema + 推导） |
| 规则引擎变成新的"万能配置" | 规则只允许引用**已声明**的事实类型；未知事实类型 → 阻断 |
| 旧视图/测试大面积失败 | 每一阶段保留导出视图的兼容字段；`tests/` 按阶段加"派生一致性"测试 |
| 过度设计（为一个 DUT 造 OS） | 每个阶段的停点都可回退；M4（义务驱动）是可选深化，M0–M3 已是完整收益 |

---

## 9. 明确不做

- 不做跨项目的中央证据服务（本方案是 run-local 账本 + 项目级归档）；
- 不引入数据库作为事实源（JSONL 足够；SQL 只在**查询**侧，且是派生）；
- 不要求所有真相都由 LLM 产出：LLM 只做"候选契约 / 修复建议"，判定永远确定性；
- 不推翻现有 UVM/回归/EDA 链路 —— 那是原材料，不是本次重构对象；
- 不把 `case_view` 变成签核入口（这条上一版就定了，v3 继续守）。

---

## 10. 与上一版（Case View）的关系

- **保留**：三集合、四层证据、四色 CELL、分级门禁、增量证据包、`case_view` 只读。
- **换掉**：判定权（从各模块 → 推导引擎）、契约位置（从 verify 中间件 → 构建物）、
  事实形态（从各阶段 JSON → 只追加账本）、执行规划（从固定分级 → 义务 worklist）。
- **一句话**：上一版让"用例有了契约"，这一版让**契约有了主权**。
