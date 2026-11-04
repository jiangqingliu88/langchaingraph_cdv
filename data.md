# spec/RTL → 产物：一条数据路径

> 基线：2026-11-04 · 对应实现 `refactor/langgraph-migration`
> 实测 run：`output_e2e_final4_jiang_20261104_044624`（npu_sched，273/273 PASS，功能计划覆盖率 95.23%，签核 PASS_WITH_CAVEAT / CONDITIONAL；状态权威对账 0 差异、TP 影子 0 差异）

---

## 0. 输入（人给的东西）

| 输入 | 位置 | 说明 |
|---|---|---|
| **spec** | `specs/<模块>/<模块>_spec.md` | 人写。`---` 头里有 module / level / requirements，正文是功能描述 |
| **RTL** | `--rtl specs/<模块>` | 给了就跳过 design，原样拷进 `<run>/rtl/`；不给则由 design agent 生成 |
| **casemodel** | `specs/<模块>/casemodel.yaml`（人写，优先）<br>`config/casemodel/<m>.yaml` → `<run>/inputs/casemodel.yaml`（front 草稿） | 决定"每个维度有哪些取值、覆盖仓、交叉、断言、scoreboard、批次"。支持 **v1 扁平** 与 **v2 分节** 两种写法（见下），loader 等价展开 |
| **业务测试点表** | `*.testpoint.xlsx` | 人写的"**该测什么**"（Feature → Sub_Feature → 用例意图 / TestName / TestNum / Doc Section）。在 casemodel 里用 `case_source.xlsx` 声明后生效 |
| **case 绑定表** | `specs/<模块>/case_bindings.yaml` | 业务 CASE ↔ 覆盖模型的**唯一桥**：每条 CASE 只填 `dimensions / cells / tests`；留空由门禁报 `case_without_binding`（**blocker / block**，业务意图与证据脱节不允许签核），**不自动猜** |
| **可选** | `signoff_policy.yaml` / `axes.yaml` | 签核策略 / 轴声明 |

**契约不是输入，是构建物**：`contract/` 由 casemodel + TP IR 编译得到（见 ④）。

### casemodel_v2：分节写法（P0 兼容层）

casemodel 过去是一个 25 个顶层 key 的扁平文件，把「意图 / 覆盖 / 断言 / 激励 / 环境」挤在一起。v2 不拆文件，只把**边界显式写出来**：

```yaml
schema: casemodel_v2
identity: {object, object_code, object_cn, version, requirements}
plan:                       # vPlan 同源：意图与追踪
  source: {xlsx: ..., bindings: ..., module: ...}
  items: [{id, parent, maps_to, ...}]
coverage:                   # CGF 同源：只放覆盖模型
  sub_objects / dimensions / cross_matrix / cross_groups / sampling
checkers: {assertions, scoreboards}
stimuli: {themes, methods, checks, config_space, generation, case_defaults,
          behavior, path_groups}
bindings: {CASE-...: {dimensions, cells, tests}}
```

- loader（`repository/loader.py::normalize_sections`）把分节**等价展开**成现有扁平字段，行为不变；
- `plan.source` → `case_source`，`bindings` → 绑定表，`plan.items[].maps_to` 只在 `DIM-*` 时进 `dimensions`（覆盖组/证据引用不猜成维度）；
- 旧扁平写法继续可读，并给一条 `DeprecationWarning`；
- JSON Schema 用 `if coverage / else dimensions` 同时接受两种写法。

**可选拆文件（P2）**：`casemodel.yaml` 只做 manifest，loader 负责合并：

```yaml
schema: casemodel_v2
manifest:
  identity: identity.yaml
  coverage: coverage.yaml
  checkers: checkers.yaml
  stimuli: stimuli.yaml
  plan: plan.yaml
  bindings: bindings.yaml
```

**豁免（P1）**：`waivers[]` 每项必须有 `id / owner / approver / reason / expires`；
缺字段 → `waiver_incomplete` blocker，过期 → `waiver_expired` warning。
没有审批人的“不适用”不成立。

### 覆盖语义（对齐 UVM / CGF）

覆盖仓现在支持 **ignore_bins / illegal_bins / transition bins / weight / at_least**：

```yaml
sampling: {dut_module: dut, per_instance: true, at_least: 2, auto_bin_max: 16}
dimensions:
  - id: D_mode
    goal: 90                    # 该维度的闭合目标（0 = 用全局目标）
    fields:
      - name: mode
        cover_bins:
          - {name: b_tr, transitions: [[0, 1], [1, 2]], at_least: 3}
          - {name: b_ig, at: 9, ignore: true}       # 不计入分母
          - {name: b_hi, range: [6, 9], weight: 2}
```

- `ignore` → `ignore_bins`（工具级排除）；`illegal` → `illegal_bins`（命中即错）。
- 转移仓渲染为 `bins b = (0 => 1), (1 => 2);`。
- `weight` / `at_least` 是**覆盖点/组级** UVM 选项：所有仓一致时提升为
  `option.weight/at_least`，不一致则记账并用默认（SV 的 bins 没有逐仓语法）。
- **闭合分母显式化**：`required_bin_count = 仓数 − ignore`；
  `waived_bin_count` 来自 CASE 的 `waivers[].scope`（`D_x` / `DIM-D_x` / `CELL-D_x-*`）；
  `coverage_denominator = required − waived`。不做加权求和。

### 业务表 vs 覆盖模型（两条轴，不能互相替代）

| 维度 | `*.testpoint.xlsx` | `casemodel.yaml` |
|---|---|---|
| 回答 | **该测什么**（Feature → Sub_Feature → 用例意图） | **怎么测/怎么量**（维度 / bin / cross / 批次） |
| 角色 | **CASE / CCAT 的真源**（`source=xlsx`） | **覆盖仓 / checker / 批次的实现模型** |
| 接法 | `case_source.xlsx` 声明后投影成 Case IR | 维度经 `case_bindings.yaml` 接上业务 CASE |

把人写的 feature 层级硬塞进 dimensions，会把"场景"误当"属性取值"；只用维度
合成 CASE，则会丢掉业务表里的用例身份。两者通过绑定表接到一起，**不互相覆盖**。

**一条 TP 可被多条 CASE 共享**：CASE A 只绑 `D_type`、CASE B 绑
`D_type + D_dep` 时，`D_type` 下的 TP 同时归 A/B —— TP IR 写
`case_id`（主身份）+ `case_ids[]`（全量），契约按每个身份各聚合一份。
没有绑定就保留空身份，由门禁报，不编一个看起来对的。

### 入口预检（CLI / GUI / 服务共用一处）

运行开始前，`VerifyRequest.prepare()`（`src/layers/l2_orchestration/verify_request.py`）
统一做三件事：定输出目录（时间戳撞车加后缀）、把 casemodel 拷到
`inputs/casemodel.yaml`、套用全量回归 / 增量基线开关；并落
**`docs/run_config.json`**（`run_config_v1`）—— 记录生效值与来源
（`origin=cli|gui|service`）以及当前 `SIGNOFFAI_*` 环境变量。

CLI 与 GUI 都只构造这一份请求，**不各自推断路径/默认值**；CLI 不直连
`PipelineExecutionService`（`tests/test_service_boundary.py` 钉住）。

---

## 1. 主链（24 个节点里真正干活的 8 个）

```text
spec.md ─┐
         ├─[front]──► spec.json + inputs/ + 环境 YAML
RTL/ ────┘                  │
                            ▼
                    [verify] ──► agents/ env/ bench/
                            │    + TP IR + Case IR + 契约 + 覆盖率接口
                            ▼
                     [ops]  ──► regression_run/（逐级逐用例：覆盖库+波形+日志）
                            │    + waves/manifest + status/worklist
                            ▼
                  [coverage] ──► 合并 ucdb + 逐用例证据 + 矩阵 + 视图 + 门禁
                            │    + 事实账本 / 影子对账 / 种子索引
                            ▼
                   [audit]  ──► report.json / caveats / 五维质量门 /
                                证据包 v2（signoff_evidence/）
```

`init` / `finalize` / 路由 / 审批等不产业务数据，不在上图标出。

---

## 2. 逐阶段：读什么 → 写什么

### ① init（纯函数）

写 `phases.planning`（目标 + 里程碑），不落盘；日志里 `planning | PLAN` 来自这里。

### ② front（前置分析）

- **读**：`<run>/rtl/*.sv`、spec 正文
- **写**：
  - `<run>/spec.json` —— design_name / version / overview / interfaces
  - `<run>/inputs/casemodel.yaml` —— 草稿（有手写模型时不覆盖，只记 `casemodel_path`）
  - `inputs/yaml/uvm/{bench,env,<iface>}.yaml` 初版
- **日志**：`front：casemodel 已写出 …` / `case 模型：specs/npu_sched/casemodel.yaml（人写的优先于草稿）`

### ③ design / model

- `--rtl` 时 design **SKIP**（不生成 RTL）；model 产参考模型到 `<run>/model/<module>_v1/`（本项目占位模型 → 签核挂 `MODEL_UNAVAILABLE`）

### ④ verify（验证开发）—— 产物最多的一步

内部是 **8 步 DAG**（`src/executors/verify/steps_dag.py`，顺序即拓扑）：

```text
coverage_plan → find_spec_yaml → testpoints_prebuild → dut_channel
→ env_cov_bins → constraint_yaml → association_report → jinja_render
```

关键约束：`find_spec_yaml` **不再清空共享目录**——它只删自己上一轮 manifest
（`.find_spec_manifest.json`）登记的产物；拿不到 manifest 就一个都不删。
要进渲染的其它文件仍需晚于它，但"晚于"由 DAG 的 `deps` 声明 + 执行期
`StepRecorder` 强制，不再靠注释。`env_cov_bins` 必须在渲染前落盘，**落盘失败
直接让 verify 失败**（不再静默退回自动分箱）。

**原子落盘**：`testpoints.yaml/json`、`case_ir.json`、`case_closure.json`、
`contract/*`、`env_cov_bins.yaml`、`gates.json`、`worklist.json`、
`coverage_holes.json`、`authority_diff.json`、`incremental/plan.json` 都走
`src/core/runtime/atomic.py`（同目录临时文件 + `os.replace`）。读者永远看不到
半截 JSON/YAML。

| 路径 | 内容 |
|---|---|
| `agents/<iface>_agent/*` | 生成的 UVM 类 + `filelist.f` |
| `env/<m>_env*.sv`、`env/tests/`、`env/cons/` | 环境、测试类、约束 |
| `bench/<m>_bench_tb_top.sv` | tb_top（挂覆盖率接口） |
| `inputs/yaml/uvm/*.yaml` | 生成器契约（含 `dut_if` 身份、`dut_checker` 规则与逐条 SB 归属） |
| `coverage/testpoints.yaml` + `.json` | 测试点 IR（tp_id / 覆盖仓 / test / 种子 / 判据 / **case_id 主身份 + `case_ids[]` 全量**） |
| `coverage/case_ir.json` + `case_group_map.json` + `case_checker_map.json` | CCAT 分类树 + CASE 逻辑用例 + **四集合（groups / sva / scb / constraints）**；`source` 区分 `declared` / `synthesized` / **`xlsx`**（业务表投影）。`constraints` 是约束 id（`p_*` 策略名），按 coverage plan 的维度交集归属，附 `constraint_backing`（backed / dimensions / reason）。**多对多**：按 TP 的每个 `case_id` 归并，共享 TP 同时进多条 CASE 的契约。`waivers[]` 是人工豁免（必须有 owner/approver/reason/expires） |
| `coverage/case_closure.json` | **引用闭合**：CASE 绑定的维度是否在 casemodel 里、checker 是否绑到 TP、测试类是否存在。生成期只落读数，Case Gate 据此发 `unknown_dimension` / `checker_without_tp` blocker |
| `contract/contract.yaml` + `obligations.json` + `contract_manifest.json` | **契约构建物**：义务与规范哈希（M1）。构建时同步把 `contract_hash` 作为 **`contract_anchor`** 追加进 `evidence/ledger.jsonl` —— **证据产生前冻结契约版本**，之后改契约不会让旧事实自动对上新版 |
| `coverage/methodology.json` | 阶段记录 + TP IR 的 sha256 |
| `coverage/coverage_plan.yaml` / `coverage_points.json` | 覆盖点 + 批次 + 种子管理 |
| `coverage/stimulus_plan.json` | 可激励 / 不适用 的分配 |
| `coverage/<dut>_cov_if.sv` | bind 进 DUT 的覆盖率接口（含断言额外引的信号） |
| `coverage/tp_bitmap.json` | TP ↔ 接口位序（波形里看 `tp_seen`） |
| `docs/ir_shadow_diff.json` | **UVM IR 双写比对**：IR 派生视图 vs 渲染 ctx（`schema=uvm_ir_shadow_v1`，`counts.inconsistent` 是切 IR-first 的前置读数） |

**DUT 检查（真 pass 的"比对"半边）**：casemodel 的 `assertions` 既渲染成 SVA，也翻译成 env 逐拍规则；模型 `scoreboards[].rules` 声明归属后，env 额外打 `[SCB <id>] total/matched/mismatched`。有 X 时改打 `unverified=`，**不写 `mismatched=0`**。

### ⑤ ops（回归）

- **读**：Makefile/Sourceenv、`coverage/testpoints.yaml`（反查 TP 归属）、`contract/` + 账本（有历史证据时生成 worklist，只跑未清偿义务对应的 test；全新 run 回落全量）
- **写**（分级 loopback → p0 → p1 → p2 → p3）：

```text
regression_run/<stage>/build_<build>/test_<task>/
    sim.sh / status.env / sim_vsim.log   ← 命令、结论、UVM 日志
                                           （[DRV] 发送 / [MON] 采样 /
                                            [SCB] MATCH·MISMATCH·SUMMARY /
                                            [SCB_DUT] 聚合 / [SCB <id>] 逐条 /
                                            [TP_HIT]）
    task_meta.json                       ← 用例身份 v2（task/test/seed/stage/tp_ids/case_id 主身份/case_ids 全量/case_ir_sha/contract_hash/constraint_ids）
    cov/<test>/questa.db                 ← 这一条用例自己的覆盖库（267 份）
    waves/<test>.db                      ← 这一条用例自己的波形（qwave.db）
regression_stages.json                   ← 每级 passed/failed/total + blocked_at
waves/manifest.json                      ← 用例 ↔ 波形 ↔ TP（唯一反查表）
status/worklist.json                     ← 未清偿义务 + **覆盖缺口建议** → 该重跑哪些 test（M4）
```

### ⑥ coverage（度量 + 派生证据）

- **读**：全部 `regression_run/**/cov/*`、`case_cov` 所需的日志与 task_meta
- **度量（必须重跑仿真才能重建）**：
  - `sim/coverage/merged.ucdb`、`plan_merged.ucdb`、`reports/coverage_cvg.txt`
  - `sim/coverage/coverage_result.json`（functional_pct / overall_pct / 每 metric bins）
- **派生（可由度量 + 模型重建）**——证据流水线 **11 步**（`evidence_pipeline.py`）：

```text
case_cov → tp_matrix → tp_evidence → cell_matrix → evd
→ case_view → gates
→ os_shadow → os_tp_shadow → os_authority → os_seeds
```

顺序有约束：`cell_matrix` 必须在 `evd` 之前（EVD 要按 CELL 反查）；
`os_tp_shadow` 必须在 `os_authority` 之前（权威报告要带当轮 TP 阴影读数）；
`os_tp_shadow` 读**当场传入**的 coverage payload，不读尚未落盘的
`coverage_result.json`（否则会拿上一轮的 `tp_report`，实测 20 条假差异）。

| 文件 | 内容 |
|---|---|
| `coverage/case_cov/<stage>/<task>.json` | 单用例证据：仓命中 / illegal / SCB（`evidence_level`）/ 断言 / timing / 波形；身份写 `case_id`（主）+ `case_ids[]`（全量）。**契约版本不一致的证据直接作废**（`error=stale_contract`，日志/SCB/时序一并清空），不会拿去清偿新契约 |
| `coverage/case_tp.json` | 用例 ↔ TP 证据表（`signed_off_by = task@seed`） |
| `coverage/tp_matrix.json` | TP × 覆盖仓矩阵（HIT / BACKDOOR_HIT / OBSERVED / UNSIGNED …） |
| `coverage/tp_cov_evidence.json` | 四层证据（functional / timing / data / path） |
| `coverage/evd.json` | 执行证据索引（去重键 `(tst_id, seed, cfg, checker_type, checker_id)`） |
| `coverage/cell_matrix.json` | CELL = CG × P，green / yellow / red / na（NA ≠ pass） |
| `coverage/case_view.{json,md,html}` | 人读视图：视图1 **按逻辑 CASE 聚合**（批次按测试名，执行次数单列）、视图2 功能契约、视图3 路径矩阵、视图4 缺口（与 CELL 颜色一一对应）+ 覆盖率组总览 / **四集合（含约束 id 与 backed）** / Case×CELL / EVD。绿黄红**只映射** `case_cov` 的 derive 判定（`status_source=derive`）；无契约的批次/旧目录才走 `legacy` |
| `coverage/gates.json` | Case Gate（blocker / warning / info；规则表 + 声明式规则） |
| `coverage/coverage_holes.json` | **CDV 闭环建议**：缺口 → 动作（`stimulus_gap` / `model_drift` / `signoff_gap` / `backend_pending`）+ owner_test + seeds。只读 `tp_matrix` / `testpoints`，不改判定 |
| `coverage/evidence_manifest.json` | 每步产物 sha + 耗时（"这份视图是哪个版本出的"） |
| `coverage/{attribution,seed_diversity,association_report,plan_consistency}.json` | 归因 / 种子 / 关联 / 一致性 |
| `evidence/ledger.jsonl` | **事实账本**：只追加 + 哈希链（`prev_hash`），按 FactBundle 幂等写入，跨进程写用 `evidence/ledger.lock`（超时 + stale 兜底）。首条记录是 `contract_anchor`（`contract_hash` + `case_ir_sha256`）；锚点冻结后，**另一版契约的事实会被 `append_bundle` 直接拒绝**（`ContractAnchorMismatch`，deny-first） |
| `status/shadow_report.json` | M0 case 级影子对账（契约推导 vs 旧结论） |
| `status/tp_shadow.json` | M2 TP 级对账 + run 级 `bin_hit` / `tp_attr` 事实（读取**当场**的覆盖率 payload，不读上一轮 `coverage_result.json`） |
| `status/authority_diff.json` | **状态权威对账**：`case_view` 展示色 vs `case_cov` 的 derive 判定 + 当轮 TP 阴影。**audit 会读它**：非 0 差异 → `AUTHORITY_DIFF` 硬失败（不是仪表盘读数）；缺文件 → caveat |
| `status/seed_index.json` | P6 种子索引：哪颗 seed 清偿了哪些义务（可复现） |
| `status/worklist.json` | 未清偿义务 → 该重跑哪些 test（ops 默认按它过滤；全新 run 回落全量）。**同时合并 `coverage_holes`**：`stimulus_gap` / `signoff_gap` 直接变成建议的 `test@seed`，与义务清单一并进 `items` / `regex`；`model_drift` 与 `backend_pending` 不产生重跑建议。**`impact`** 读 `incremental/plan.json`：非保守结论时给每条建议标 `in_impact`，`impact_suggested` 就是"变更相关的最小重跑集" |

### ⑦ audit（签核）

- **读**：`tp_matrix`、`case_tp`、`gates.json`、`waves/manifest.json`、覆盖率、`docs/verification_quality.json`、`docs/engineering_metrics.json`、`docs/ir_shadow_diff.json`、**`status/authority_diff.json`**（视图 vs derive 分叉 → 硬失败）
- **写**：
  - `<run>/report.json` —— verdict / score / gates / summary
  - `<run>/caveats.json` —— 未签收事项（`TP_NOT_SIGNED_OFF` / `CASE_GATE_BLOCKED` / `MODEL_UNAVAILABLE` / `QUALITY_GATE_BLOCKED` …）
  - `<run>/docs/verification_quality.json` —— 五维质量门（functional / coverage / model / structural / evidence）
  - `<run>/docs/engineering_metrics.json` —— 回归耗时 / 增量节省 / 归因完整率 / 决策有效率 + **`red_lights`**（blocker 分类、归因完整率、未归类规则、覆盖缺口动作、误报率；误报率只在 `docs/triage.json` 有裁决时计算）
  - `<run>/docs/run_config.json` —— 本次运行的生效配置（来源 cli/gui/service + `SIGNOFFAI_*` 环境）
  - `<run>/signoff_evidence.json` + `signoff_evidence/` —— 证据包 v2：
    `inputs/ execution/ verdict/ case_view/ replay/` + `manifest.json`
  - `<run>/effective_policy.yaml` —— 本次生效的签核策略快照

**签核三态**（唯一实现 `evidence/verdict.py`，audit 与离线 replay 共用）：

```text
hard_ok=False                     → NEEDS_FIX（REJECTED）
hard_ok=True + 有效 caveat         → PASS_WITH_CAVEAT（CONDITIONAL）
hard_ok=True + 无有效 caveat       → READY（APPROVED）
```

质量门 `SIGNOFFAI_QUALITY_GATE=block` 时按维度灰度接三态：`evidence` / `functional` 维 `fail` → 硬失败（`QUALITY_GATE_BLOCKED`），其余非 pass → 软 caveat（`QUALITY_GATE_WARN`）；`report` / `warn` 只报告。

### 贯穿全程（run 仓库）

`docs/{events.jsonl, provenance.jsonl, provenance_summary.json, manifest.json, evidence_chain.json, file_change_chain.json, progress.json, checkpoints.sqlite}`、`artifacts/artifacts.json` —— 事件、血缘、文件变更链，每一步追加。

跨 run 的**可重建元数据**：`database/ic_verification.db#case_registry`（CASE 首末 run / EVD 数，`vagent coverage case-registry` 可查）。

---

## 3. 产物分四类（决定"能不能重建"）

| 类别 | 例子 | 能否重建 |
|---|---|---|
| **输入副本** | `rtl/`、`inputs/casemodel.yaml`、`inputs/source_map.json` | 不能（原件在工程里） |
| **生成物** | `agents/`、`env/`、`bench/`、`inputs/yaml/uvm/`、`contract/`、`coverage/case_ir.json`、`docs/ir_shadow_diff.json` | 能（模型 + 模板） |
| **度量** | `sim/coverage/*.ucdb`、`coverage_result.json`、`regression_run/**` | 不能，只能重跑仿真 |
| **派生结论** | `case_cov/`、`tp_matrix`、`cell_matrix`、`evd`、`case_view`、`gates`、`status/*`、`docs/run_config.json`、`report/caveats` | 能（`evidence_pipeline --only <step>` 单步重跑，不必重跑仿真；账本按 bundle 摘要幂等） |
| **可回收** | `regression_run/**/waves|cov/*.db`、`sim/**/*.ucdb|vdb`（**不含** `sim/coverage/` 的合并度量） | 能，但只能重跑仿真；`vagent gc` 默认 dry-run，`coverage/ status/ docs/ contract/ evidence/` 永不删 |

---

## 4. 一次真实 run 的目录（npu_sched，273/273 过）

```text
<run>/
├── spec.json                     front 解析出的设计身份
├── rtl/npu_sched.sv              外部 RTL 拷贝
├── inputs/                       casemodel 副本 + filelist + yaml/uvm 契约
├── agents/  env/  bench/         生成的 UVM（分目录 + 模块前缀）
├── contract/                     契约：contract.yaml / obligations.json / manifest
├── regression_run/               loopback|p0..p3 / build_* / test_*
│                                 （cov + waves + task_meta + sim 日志）
├── regression_stages.json        每级 passed/failed/total + blocked_at
├── waves/manifest.json           用例 ↔ 波形 ↔ TP
├── sim/coverage/                 merged/plan ucdb + reports + coverage_result.json
├── coverage/                     TP IR / Case IR / 矩阵 / 证据 / 视图 / 门禁
├── evidence/ledger.jsonl         事实账本（只追加 + 哈希链）
├── status/                       worklist / shadow / tp_shadow / authority_diff /
│                                 seed_index
├── docs/                         events / provenance / quality / metrics /
│                                 ir_shadow_diff / run_config / checkpoints
├── model/  golden/  artifacts/   参考模型、黄金基线、产物索引
├── report.json  caveats.json  signoff_evidence.json  effective_policy.yaml
└── signoff_evidence/             证据包 v2（319 份文件；case_view 段 278 份，
                                  execution 段含 run_config / authority / tp_shadow / seed_index / worklist）
```

本次读数：13 个契约组 / 267 次执行实例（HTML 视图1 聚合为 **23 个逻辑用例**）/
364 条 EVD / 13 个 CELL（黄 11 · 红 2）/ **47 条 SCB 证据为 `per_scb`** /
47 条 CASE 带约束 id / **状态权威对账 0 差异 · TP 影子 0 差异** /
Case Gate PASS（blocker 0）。

`docs/ir_shadow_diff.json`（IR 双写比对）与 `docs/run_config.json`（生效配置）
都在本 run 里生成并进了证据包。

---

## 5. 五条链（整条路径的价值所在）

1. **身份链**
   `spec → 手写 casemodel（+ xlsx / case_bindings）→ testpoints.yaml（tp_id + case_id 主身份 + case_ids[] 全量）→ task_meta.json（tst_id + 四集合指纹）→ case_cov（evd_id、cell_ids）→ evd.json → cell_matrix` —— 回答"这条波形在证明哪个功能点、受哪条约束驱动"。身份在**生成期注入**，不从测试名反推。

   **多对多**：一条 TP 可以被多条业务 CASE 共享（多个用例绑同一维度）。
   契约按 `case_ids[]` 逐身份归并 —— 只看主 `case_id` 会让后绑的 CASE 永远空。

   **CASE = groups[] + sva[] + scb[] + constraints[]**：约束 id 进契约哈希 ——
   约束换版后，旧证据不再对得上这一版契约。

2. **哈希链**
   `testpoints.yaml` 的 sha ↔ `methodology.json` 登记；`source_map.json` 的 xlsx/axes/casemodel 三方哈希（防导入后手改）；`contract_hash` 写进 task_meta 与事实；**约束内容指纹**（`constraint_fingerprints`：id → 策略定义哈希）也进契约哈希 —— 约束逻辑改了、id 没改也能被发现；`evidence_manifest.json` 记录每个派生物 sha；证据包 `manifest.json` 逐文件 sha256 + `package_hash`。

3. **事实链（Verification OS）**
   `contract/` → **`contract_anchor`（冻结版本）** → `compile_obligations` →
   `evidence/ledger.jsonl`（FactBundle + `prev_hash`）→ `derive()`（唯一判定实现）→
   `status/{shadow,tp_shadow,seed_index}` → `vagent contract why/status/worklist/seeds`。
   **无契约不执行、契约先冻结、事实只追加、状态只推导、视图只渲染。**
   视图层只做展示映射（`status_vocab`）；`status/authority_diff.json` 把
   "视图 vs 推导"的差异数成数字（本 run 47 条 / 0 差异）。

   **裁决代数是 deny-first**：`worst()` 取最严格结果（`MISSING` > `NOT_EXECUTED`
   > `PARTIAL` > `PROVEN`，`NOT_APPLICABLE` 不参与），下游许可不能覆盖上游缺失 ——
   不是加权求和。

   **闭合分母**：`required − waived − ignored`。`waived` 必须来自带审批人的
   waiver；`ignored` 是工具级排除仓；两者都不参与分母，但原因不同、可分开审计。

   **缺口闭环**：`coverage_holes.json` 把 `MISS/UNOBSERVED/UNMAPPED/UNSIGNED`
   翻译成 `stimulus_gap / model_drift / signoff_gap / backend_pending`，
   并带上 owner test 与 seeds。`stimulus_gap` / `signoff_gap` 会并进
   `status/worklist.json` 的 `items` 与 `regex` —— **下一轮该跑哪条
   `test@seed` 直接可执行**，不是一张需要人再翻译的清单。

   **输入也要被裁决拒绝**：`case_cov` 采集时比较 `task_meta.contract_hash` 与
   `contract/contract_manifest.json`，不一致 → `stale_contract`（证据清空）；
   `judge_case()` 入口再查一次事实携带的契约哈希，外来契约的事实直接
   `ValueError` 拒绝。旧证据不能清偿新义务。

4. **复现链**
   `status/seed_index.json`：`signed_off_by = task@seed` 回答"这条 TP 由哪次执行证明"；反过来"这颗 seed 清偿了哪些义务"也在表里。证据包自带 `replay/replay.py`（不依赖本工具）重算哈希与三态。

5. **签核链**
   `cell_matrix`（四层证据）→ `gates.json`（blocker/warning/info）→ `verification_quality.json`（五维；block 模式按维度接三态）→ `caveats.json` → `report.json` / `signoff_evidence/`。**缺证据不下绿；NA ≠ pass；有 X 不算验过。**

### 确定性的边界（必须诚实标注）

确定性裁决是**必要条件，不是充分条件**：`derive()` 与门禁本身也会错。

- 误拦截必须可归因：区分「证据真的缺失」与「validator / 探针 / 编译缺陷」；
  一次红灯的 `reason` 要指向可复核的环节，而不是只说"义务未满足"。
- 质量指标不能只报"拦住了多少"，还要报**误报率**与**归因正确率** ——
  否则"更严格"会退化成"更爱亮红灯"。
- 这套系统的适用范围是**可被编码为契约违反的缺陷**；契约表达不了的问题
  （规格本身错、参考模型错）不在它的证明范围里，不能冒充已覆盖。

---

## 6. 常用入口

```bash
# 主链
python -m src.cli.commands verify --rtl specs/npu_sched -o output_xxx \
    --target 95 --max-rounds 1 --no-manual-gate --approval auto

# casemodel 结构 lint（v2 分节 / manifest / 必填字段）
python -m src.cli.commands case-model lint specs/npu_sched/casemodel.yaml

# 契约 / 义务 / 事实
python -m src.cli.commands contract build|check|show   -o <run>
python -m src.cli.commands contract why <OBL-ID>       -o <run>
python -m src.cli.commands contract worklist|seeds|status -o <run>

# 证据视图 / 门禁 / 跨 run 索引
python -m src.cli.commands coverage case-evidence -o <run> -f html --out case_view
python -m src.cli.commands coverage case-gate     -o <run> [--strict]
python -m src.cli.commands coverage case-registry -m npu_sched

# 存储回收：只删可重建的波形/覆盖库，保留证据链（默认 dry-run）
python -m src.cli.commands gc --runs-root . --keep-last 5 --keep-days 30
python -m src.cli.commands gc --runs-root . --apply

# 覆盖率 delta 门禁（显式给基线时，功能覆盖率不得回退）
export SIGNOFFAI_COVERAGE_BASELINE=output_e2e_final4_...

# 工程指标与趋势
python -m src.cli.commands metrics show  -o <run> [--baseline <run>]
python -m src.cli.commands metrics trend -o <run> --last 10

# 增量 / 对比 / 证据包
python -m src.cli.commands incremental plan --baseline <a> --current <b>
python -m src.cli.commands diff runs --baseline <a> --current <b>
python -m src.cli.commands evidence verify <run>/signoff_evidence
python -m src.cli.commands evidence replay <run>/signoff_evidence
```

---

**一句话概括**：spec/RTL 只决定"测什么、被测的是谁"；casemodel 决定"怎么测"；回归产出度量；其余全是派生与取证。派生可以单步重建，度量只能重跑仿真 —— 这条边界决定了每一次"改模型后要不要重跑"。
