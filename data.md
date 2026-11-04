# spec/RTL → 产物：一条数据路径

> 基线：2026-11-04 · 对应实现 `refactor/langgraph-migration`
> 实测 run：`output_e2e_final4_jiang_20261104_044624`（npu_sched，273/273 PASS，功能计划覆盖率 95.23%，签核 PASS_WITH_CAVEAT / CONDITIONAL；状态权威对账 0 差异、TP 影子 0 差异）

---

## 0. 输入（人给的东西）

| 输入 | 位置 | 说明 |
|---|---|---|
| **spec** | `specs/<模块>/<模块>_spec.md` | 人写。`---` 头里有 module / level / requirements，正文是功能描述 |
| **RTL** | `--rtl specs/<模块>` | 给了就跳过 design，原样拷进 `<run>/rtl/`；不给则由 design agent 生成 |
| **casemodel** | `specs/<模块>/casemodel.yaml`（人写，优先）<br>`config/casemodel/<m>.yaml` → `<run>/inputs/casemodel.yaml`（front 草稿） | 决定"每个维度有哪些取值、覆盖仓、交叉、断言、scoreboard、批次" |
| **可选** | `signoff_policy.yaml` / `axes.yaml` / `*.testpoint.xlsx` | 签核策略 / 轴声明 / 方案 B 的表导入入口 |

**契约不是输入，是构建物**：`contract/` 由 casemodel + TP IR 编译得到（见 ④）。

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

关键约束：`find_spec_yaml` 会清空 `inputs/yaml/uvm/*.yaml`，一切要进渲染的文件必须晚于它；`env_cov_bins` 必须在渲染前落盘，否则 `env_cov` 静默退回自动分箱。

| 路径 | 内容 |
|---|---|
| `agents/<iface>_agent/*` | 生成的 UVM 类 + `filelist.f` |
| `env/<m>_env*.sv`、`env/tests/`、`env/cons/` | 环境、测试类、约束 |
| `bench/<m>_bench_tb_top.sv` | tb_top（挂覆盖率接口） |
| `inputs/yaml/uvm/*.yaml` | 生成器契约（含 `dut_if` 身份、`dut_checker` 规则与逐条 SB 归属） |
| `coverage/testpoints.yaml` + `.json` | 测试点 IR（tp_id / 覆盖仓 / test / 种子 / 判据） |
| `coverage/case_ir.json` + `case_group_map.json` + `case_checker_map.json` | CCAT 分类树 + CASE 逻辑用例 + **四集合（groups / sva / scb / constraints）**；`constraints` 是约束 id（`p_*` 策略名），按 coverage plan 的维度交集归属，附 `constraint_backing`（backed / dimensions / reason） |
| `contract/contract.yaml` + `obligations.json` + `contract_manifest.json` | **契约构建物**：义务与规范哈希（M1） |
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
    sim.sh / status.env / sim_vsim.log   ← 命令、结论、UVM 日志（含 [SCB_DUT] / [SCB <id>] / [TP_HIT]）
    task_meta.json                       ← 用例身份 v2（task/test/seed/stage/tp_ids/case_id/case_ir_sha/contract_hash/constraint_ids）
    cov/<test>/questa.db                 ← 这一条用例自己的覆盖库（267 份）
    waves/<test>.db                      ← 这一条用例自己的波形（qwave.db）
regression_stages.json                   ← 每级 passed/failed/total + blocked_at
waves/manifest.json                      ← 用例 ↔ 波形 ↔ TP（唯一反查表）
status/worklist.json                     ← 未清偿义务 → 该重跑哪些 test（M4）
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
| `coverage/case_cov/<stage>/<task>.json` | 单用例证据：仓命中 / illegal / SCB（`evidence_level`）/ 断言 / timing / 波形 |
| `coverage/case_tp.json` | 用例 ↔ TP 证据表（`signed_off_by = task@seed`） |
| `coverage/tp_matrix.json` | TP × 覆盖仓矩阵（HIT / BACKDOOR_HIT / OBSERVED / UNSIGNED …） |
| `coverage/tp_cov_evidence.json` | 四层证据（functional / timing / data / path） |
| `coverage/evd.json` | 执行证据索引（去重键 `(tst_id, seed, cfg, checker_type, checker_id)`） |
| `coverage/cell_matrix.json` | CELL = CG × P，green / yellow / red / na（NA ≠ pass） |
| `coverage/case_view.{json,md,html}` | 人读视图：视图1 **按逻辑 CASE 聚合**（批次按测试名，执行次数单列）、视图2 功能契约、视图3 路径矩阵、视图4 缺口（与 CELL 颜色一一对应）+ 覆盖率组总览 / **四集合（含约束 id 与 backed）** / Case×CELL / EVD。绿黄红**只映射** `case_cov` 的 derive 判定（`status_source=derive`）；无契约的批次/旧目录才走 `legacy` |
| `coverage/gates.json` | Case Gate（blocker / warning / info；规则表 + 声明式规则） |
| `coverage/evidence_manifest.json` | 每步产物 sha + 耗时（"这份视图是哪个版本出的"） |
| `coverage/{attribution,seed_diversity,association_report,plan_consistency}.json` | 归因 / 种子 / 关联 / 一致性 |
| `evidence/ledger.jsonl` | **事实账本**：只追加 + 哈希链（`prev_hash`），按 FactBundle 幂等写入 |
| `status/shadow_report.json` | M0 case 级影子对账（契约推导 vs 旧结论） |
| `status/tp_shadow.json` | M2 TP 级对账 + run 级 `bin_hit` / `tp_attr` 事实（读取**当场**的覆盖率 payload，不读上一轮 `coverage_result.json`） |
| `status/authority_diff.json` | **状态权威对账**：`case_view` 展示色 vs `case_cov` 的 derive 判定 + 当轮 TP 阴影（差异应为 0） |
| `status/seed_index.json` | P6 种子索引：哪颗 seed 清偿了哪些义务（可复现） |
| `status/worklist.json` | 未清偿义务 → 该重跑哪些 test（ops 默认按它过滤；全新 run 回落全量） |

### ⑦ audit（签核）

- **读**：`tp_matrix`、`case_tp`、`gates.json`、`waves/manifest.json`、覆盖率、`docs/verification_quality.json`、`docs/engineering_metrics.json`、`docs/ir_shadow_diff.json`
- **写**：
  - `<run>/report.json` —— verdict / score / gates / summary
  - `<run>/caveats.json` —— 未签收事项（`TP_NOT_SIGNED_OFF` / `CASE_GATE_BLOCKED` / `MODEL_UNAVAILABLE` / `QUALITY_GATE_BLOCKED` …）
  - `<run>/docs/verification_quality.json` —— 五维质量门（functional / coverage / model / structural / evidence）
  - `<run>/docs/engineering_metrics.json` —— 回归耗时 / 增量节省 / 归因完整率 / 决策有效率
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
   `spec → 手写 casemodel → testpoints.yaml（tp_id + case_id）→ task_meta.json（tst_id + 四集合指纹）→ case_cov（evd_id、cell_ids）→ evd.json → cell_matrix` —— 回答"这条波形在证明哪个功能点、受哪条约束驱动"。身份在**生成期注入**，不从测试名反推。

   **CASE = groups[] + sva[] + scb[] + constraints[]**：约束 id 进契约哈希 ——
   约束换版后，旧证据不再对得上这一版契约。

2. **哈希链**
   `testpoints.yaml` 的 sha ↔ `methodology.json` 登记；`source_map.json` 的 xlsx/axes/casemodel 三方哈希（防导入后手改）；`contract_hash` 写进 task_meta 与事实；`evidence_manifest.json` 记录每个派生物 sha；证据包 `manifest.json` 逐文件 sha256 + `package_hash`。

3. **事实链（Verification OS）**
   `contract/` → `compile_obligations` → `evidence/ledger.jsonl`（FactBundle + `prev_hash`）→ `derive()`（唯一判定实现）→ `status/{shadow,tp_shadow,seed_index}` → `vagent contract why/status/worklist/seeds`。**无契约不执行、事实只追加、状态只推导、视图只渲染。**
   视图层只做展示映射（`status_vocab`）；`status/authority_diff.json` 把
   "视图 vs 推导"的差异数成数字（本 run 47 条 / 0 差异）。

4. **复现链**
   `status/seed_index.json`：`signed_off_by = task@seed` 回答"这条 TP 由哪次执行证明"；反过来"这颗 seed 清偿了哪些义务"也在表里。证据包自带 `replay/replay.py`（不依赖本工具）重算哈希与三态。

5. **签核链**
   `cell_matrix`（四层证据）→ `gates.json`（blocker/warning/info）→ `verification_quality.json`（五维；block 模式按维度接三态）→ `caveats.json` → `report.json` / `signoff_evidence/`。**缺证据不下绿；NA ≠ pass；有 X 不算验过。**

---

## 6. 常用入口

```bash
# 主链
python -m src.cli.commands verify --rtl specs/npu_sched -o output_xxx \
    --target 95 --max-rounds 1 --no-manual-gate --approval auto

# 契约 / 义务 / 事实
python -m src.cli.commands contract build|check|show   -o <run>
python -m src.cli.commands contract why <OBL-ID>       -o <run>
python -m src.cli.commands contract worklist|seeds|status -o <run>

# 证据视图 / 门禁 / 跨 run 索引
python -m src.cli.commands coverage case-evidence -o <run> -f html --out case_view
python -m src.cli.commands coverage case-gate     -o <run> [--strict]
python -m src.cli.commands coverage case-registry -m npu_sched

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
