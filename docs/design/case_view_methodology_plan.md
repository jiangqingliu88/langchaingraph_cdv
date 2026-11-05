# Case View 方法学落地计划

> 状态：**计划稿（未实现）**。
> 关联：`src/tools/humanview/method.md`（方法学定位）、
> `src/tools/humanview/case_associate_view/arch.md`（四张人读视图）、
> `src/tools/humanview/covg_ir/arch.md`、`sva_ir/arch.md`、`scb_ir/arch.md`、
> `docs/design/case_coverage_and_wave_traceability.md`（逐用例签核 / PATH / 四层证据）。
> 目标：把"用例证据"从**四张静态表**升级为**可登记、可追溯、可门禁的 Case View 方法学**，
> 同时不推翻当前已经跑通的 TP 主键与逐用例证据链。

---

## 0. 一句话

以 **YAML+Git 为 SSOT、TP 为度量主键、CELL 为派生签核视图、Case 为登记一等公民**，
把 `case_cov → tp_matrix → case_view` 这条链补成：

```text
FEAT/CONTRACT → CG/CP/BIN/P/SVA/SB
        │
        ▼
CCAT 分类 → CASE 逻辑用例 → TST 可执行实例（test+seed+cfg）
        │                         │
        │                         ▼
        │                    RUN / EVD（一次执行证据）
        │                         │
        ▼                         ▼
      CELL = CG × P  ←──── 四层证据聚合
        │
        ▼
  Case View（用例 / 契约 / 矩阵 / 缺口 / 追溯 / 复用）
        │
        ▼
  CI Gate（blocker / warning / info）
```

**SQL 不在 P0~P3 的路径上**。YAML+Python 生成器先跑通；只有达到规模/查询阈值时，
才引入 SQLite/DuckDB 做派生查询与门禁。

---

## 1. 现状盘点

### 1.1 已经落地

| 能力 | 落点 | 状态 |
|---|---|---|
| TP IR（测试点身份/实现/覆盖仓/执行计划） | `coverage/testpoints.yaml`、`.json` | ✅ |
| 逐用例覆盖切片（bin/illegal/SCB/断言/时序/波形） | `coverage/case_cov/**/*.json` | ✅ |
| 用例 ↔ TP 证据表（`signed_off_by` / 逐用例原因） | `coverage/case_tp.json` | ✅ |
| TP × 覆盖仓矩阵（含 `signed_off`） | `coverage/tp_matrix.json` | ✅ |
| 测试点位图 / `[TP_HIT]` / `tp_seen` | `coverage/tp_bitmap.json` + env_cov | ✅ |
| 波形 ↔ 用例 ↔ TP | `waves/manifest.json` | ✅ |
| 四层证据（功能/时序/数据/路径）按 TP 汇聚 | `coverage/tp_cov_evidence.json` | ✅ |
| Case 四张人读视图（用例/契约/矩阵/缺口） | `coverage/case_view.{json,md,html}` | ✅ |
| Workbench「Case 证据」页 | `src/workbench/modules/flow/fcov/module.py` | ✅ |
| CLI `coverage case-evidence` / `tp-evidence` | `src/cli/cmd_coverage.py` | ✅ |
| PATH 组（一条 bin = 一条 TP） | `path_groups:` + `framework/paths.py` | ✅（后端 P1b） |
| 功能覆盖率 / SVA / SCB 三份 IR | `src/tools/humanview/{covg_ir,sva_ir,scb_ir}` | ✅（结构校验） |
| 跨组 cross（N 元、同采样域、去重） | `coverage_model._attach_group_crosses` | ✅ |

### 1.2 关键缺口

| 缺口 | 后果 | 优先级 |
|---|---|---|
| **没有 CASE 身份** | 回归任务只有 `test + seed`，`case_cov.task` 是执行实例，不是逻辑用例；无法做 Case×CELL / 分类 / 复用视图 | P0 |
| **没有 CELL 身份** | `tp_matrix` 行没有 `cell_id`；TP 到 CELL 的 rollup 靠临时推断，不可审计 | P0 |
| **没有 EVD/RUN 身份** | `case_cov` 有 task/seed 但无 `evd_id / run_id`；跨 run 去重、版本过期、失败分类没有统一键 | P1 |
| **没有统一边表** | 需求/覆盖点/路径/checker/case 的关系散落各文件，追溯靠脚本各自拼 | P1 |
| **没有 CONTRACT/AC/APPROVAL** | 契约与验收条件未登记，豁免无审批链 | P2 |
| **没有 GAP/WVR 状态机** | 缺口与豁免只有列表，没有生命周期、负责人、到期 | P2 |
| **没有 VER/BASELINE** | 版本只靠 Git，视图无法回答"这是哪个模型版本出的结论" | P2 |
| **门禁不完整** | 现有 audit 偏覆盖率；Case/Cell/checker 的 blocker 门禁没有统一入口 | P2 |
| **视图不全** | 已有 4 张；缺 Case 分类树、复用、Case×CELL、执行证据、豁免看板 | P3 |

---

## 1.3 业务表（xlsx）vs 覆盖模型（casemodel）—— 两个真源的区别

以 `NPU_V2.CMDSCHED.testpoint.xlsx` 与 `specs/npu_sched/casemodel.yaml` 实测：

| 维度 | xlsx（业务测试点表） | casemodel（覆盖/激励模型） |
|---|---|---|
| 回答 | **该测什么**（Feature → Sub_Feature → 用例意图） | **怎么测/怎么量**（维度 / bin / cross / 批次） |
| 结构 | 470 行、64 个 TP 锚点、C/D/E 三层子特性（56/153/307 行） | 12 个维度、11 个批次、7 条 cross、4 条断言 |
| 分类 | CR/IF/C/F/BP/BO/R/E/P（F=25、IF=7、E=7、P=6…） | 维度名（D_queue/D_type/D_dep…），**不携带业务分类** |
| 测试 | TestName 多为 `func_cov监测` / 场景名，TestNum 有 0/1/8/11/1561/21854 | 11 个真实 UVM 批次 test（`npu_*_test`） |
| 追溯 | Doc Section / 章节（L5-HM057…） | `requirement` / `cover_id`（CP/REQ 编号） |
| 角色 | **CASE/CCAT 的真源** | **覆盖仓/checker/批次的实现模型** |

**结论**：两者不是同一条轴。当前 `case_ir` 按 casemodel 维度合成 CASE，只能得到
"12 个维度 CASE"，不是业务表里的 64 条用例；而 xlsx 的 64 条锚点、
C/D/E 子特性、TestName/TestNum/Doc Section 在 CASE 身份里全部丢失。

**大胆改法（已落地）**：

```text
xlsx（what） ──project_from_xlsx──► CaseDoc（CCAT/CASE，source=xlsx）
                                      │
                                      │ case_bindings.yaml
                                      │ （CASE → dimensions/cells/tests）
                                      ▼
                         casemodel（how）→ TP IR → CELL → EVD → Case View
```

- `case_ir.xlsx_projection` 把 xlsx 锚点 TP 投影成 CASE（64 条，重复 id 不合并），
  C/D 子特性投影成 CCAT 树，TestName/TestNum/Doc Section 保留在 CASE 上；
- **不自动猜维度**：CASE → dimensions/cells/tests 由 `case_bindings.yaml` 显式声明；
  没绑定的 CASE 由门禁报 `case_without_binding`，不编一个看起来对的；
- `casemodel.case_source` 声明业务来源：
  ```yaml
  case_source:
    xlsx: src/tools/humanview/aivm_ir/example/NPU_V2.CMDSCHED.testpoint.xlsx
    bindings: specs/npu_sched/case_bindings.yaml
    module: NPU_V2-CMDSCHED
  ```
  声明后 `project_from_casemodel` **优先用 xlsx**，不再按维度合成；
- 没声明 `case_source` 的模型保持旧行为（`cases:` 段 > 维度合成），兼容存量。

CLI：

```bash
# 生成绑定骨架（只填 dimensions/cells/tests，不重抄用例身份）
vagent humanview case-xlsx NPU.xlsx --emit-bindings specs/npu_sched/case_bindings.yaml
# 投影成 Case IR 并校验
vagent humanview case-xlsx NPU.xlsx --bindings specs/npu_sched/case_bindings.yaml \
       --out coverage/case_ir.json
```

## 2. 核心设计决策（先定边界，避免双真源）

### D0. 业务 xlsx 是 CASE/CCAT 的 SSOT，casemodel 是测量 IR

- **CASE 身份**（id / 分类 / 子特性 / 测试意图 / 文档出处）来自 xlsx；
- **覆盖仓 / checker / 批次**来自 casemodel；
- 两者通过 `case_bindings.yaml` 显式绑定（人不写第二份身份）；
- `case_source` 未声明时退回旧行为（声明 > 合成），且 `source` 字段如实标注来源。

### D1. TP 保留主键，CELL 是**派生签核视图**，不是第二 SSOT

当前工程的签核单位是 `tp_id`，不推翻：

```text
TP（一个取值/一个 bin）     = 度量单位，证据来自 case_cov
CELL（CG × P）              = 签核单位，由 TP 证据聚合
CASE（逻辑用例）             = 登记单位，关联多个 TST/EVD
```

映射规则（唯一实现点，生成器里只写一次）：

```text
CG   := group(tp.coverpoint)                  # 覆盖点属于哪个组
BIN  := tp.bin
P    := tp.execution.stage / PATH bin         # 路径型 TP 直接给 P
CELL := f"CELL-{CG}-{P}"
```

**CELL 不手写、不入 SSOT**；它是 `coverage/cell_matrix.json` 的生成物。
TP 的 `signed_off` 是 CELL 的输入证据，不是并列的第二签核结论。

### D2. Case 三件套先行

规范里的 `CCAT/CTPL/CASE/CPARAM/CRUN/TST` 六层对当前规模过重。先落：

```text
CCAT（分类树） → CASE（逻辑用例） → TST（可执行实例 = test + seed + cfg）
```

- `CTPL / CPARAM` 先作为 `CASE.template / CASE.params` 的字段，不单独建实体；
- `CRUN` 用现有 `task@seed` / EVD 代替；
- `CASE` ↔ `TST` 单向登记（`TST.case_id`），不双向写。

### D3. EVD = 逐用例记录 + 运行身份

现有 `case_cov/<task>.json` 就是一次执行的证据。补三个键即可：

```json
{
  "evd_id": "EVD-<run>-<task>-<seed>",
  "run_id": "<run 目录名>",
  "tst_id": "TST-<task>",
  "case_id": "CASE-<...>",
  "seed": 6001,
  "cfg": "",
  "cells": ["CELL-CG_DEP-P_STORED_ISSUED"]
}
```

去重键：`(run_id, tst_id, seed, cfg)`。旧 run 缺这些键 → 标 `legacy=true`，
不参与新版本聚合，但视图仍可读。

### D4. 四层证据驱动 CELL 状态

| 层 | 数据来源 | CELL 状态贡献 |
|---|---|---|
| functional | per-TP bin 命中 | 未全中 → yellow；0 命中 → red |
| timing | SVA / `[DUT_CHK]` / `[TP_TIMING]` | fail → red；未声明 → yellow |
| data | SCB matched/mismatched | mismatch/未执行 → red；未声明 → yellow |
| path | PATH bin + 绑定 checker | 未声明 → 该 CELL 不适用；PENDING_BACKEND → yellow |

```
CELL.green  = functional 全中 && timing 通过 && data 通过 &&（路径型）path 通过
CELL.yellow = 覆盖不足 / checker 未声明或未执行 / 证据不足
CELL.red    = 任一 fail、vacuous、账本不平、无 checker
CELL.na     = 该 CG 与该 P 无契约关系（必须记录理由）
```

### D5. YAML 按层聚合，不搞"一实体一文件"

当前 `casemodel.yaml` 是聚合文件，评审成本低。继续：

```
coverage_model/
  L0_feats.yaml          FEAT / CONTRACT / AC
  L1_coverage.yaml       CG / CP / BIN / X（对应 covg_ir）
  L2_paths.yaml          P / STG / BR（可复用 path_groups）
  L4_checkers.yaml       SVA / SB（对应 sva_ir / scb_ir）
  L5_cases.yaml          CCAT / CASE / TST
  gates.yaml             门禁规则与分级
```

- ID 全局唯一，由生成器校验；
- `generated/`（cells / edges / views）**不入库**，CI 生成并作为 artifact；
- 如果未来实体上万，再拆成一实体一文件——不要现在付这个成本。

### D6. SQL 后置

P0~P3 全部用 Python 生成器 + JSON/Markdown/HTML；达到以下任意 3 条再引入
SQLite/DuckDB：实体上万、边表几万、递归分类频繁、证据聚合复杂、门禁规则多、
需要 dashboard/历史对比。SQL 只做派生查询，不接 SSOT。

### D7. PATH 先轻量，后升级

当前 `path_groups` 是"路径 bin + 阶段序列 + 绑定 checks"；不要一步跳到
`P/STG/BR` 一等实体。等需要逐阶段证据/卡点定位时，再加 `stages[].branches[]`
字段，并保持旧 `path_groups` 可读。

---

## 3. 目标架构与数据流

```text
YAML（SSOT）
  │
  ├─ L0_feats / L1_coverage / L2_paths / L4_checkers / L5_cases
  │
  ▼
生成器（Python）
  ├─ ID/引用校验（schema + 关联规则）
  ├─ CELL 派生（CG × P）           → coverage/cell_matrix.json
  ├─ EDGE 派生（多对多关系）       → coverage/edges.json（可选）
  ├─ EVD 聚合（case_cov + run）    → coverage/evd.json
  ├─ Case View（四表 + 扩展表）    → coverage/case_view.{json,md,html}
  └─ Gate（blocker/warning/info）  → coverage/gates.json
  │
  ▼
Workbench / CLI / CI
```

**只读纪律**：`cells / edges / evd / case_view / gates` 都是生成物，
PR 禁止手改；SSOT 只有 YAML。

---

## 4. 最小 ID 子集（先落地这些）

| 层 | ID | 当前对应 | 本期是否新建 |
|---|---|---|---|
| L0 | `FEAT-` / `CONTRACT-` / `AC-` | 需求字符串 / `requirement` | FEAT ✅；CONTRACT/AC 先作为字段 |
| L1 | `CG-` / `CP-` / `BIN-` / `X-` | `covg_ir`、covergroup 名 | ✅（covg_ir 已有） |
| L2 | `P-` / `STG-` / `BR-` | `path_groups` / PATH TP | P ✅；STG/BR 可选 |
| L4 | `SVA-` / `SB-` | `sva_ir` / `scb_ir` | ✅ |
| L5 | `CCAT-` / `CASE-` / `TST-` | 无 / 无 / `task@seed` | **P0 新建** |
| L6 | `CELL-` / `EVD-` / `RUN-` / `BATCH-` | 无 / `case_cov` / run 目录 | **P0/P1 新建** |
| L7 | `GAP-` / `WVR-` / `APPROVAL-` / `VER-` / `BASELINE-` | 无 | P2 新建 |

命名：`<PREFIX>-<MODULE>-<CATEGORY>-<NNN>[-<SUFFIX>]`，全局唯一，废弃加
`deprecated: true` + `replaced_by`。

---

## 5. Case View 视图清单

### 5.1 已有（P0 保持）

1. **用例 × 证据层**：每个用例提供哪几层证据 → `case_view.cases`
2. **功能契约 × 证据层**：每个 Feat 的证据链完整度 → `case_view.features`
3. **功能组 × 生命周期路径**：CELL 状态 → `case_view.matrix`
4. **缺口与豁免**：缺口根因/动作/负责人/状态 → `case_view.gaps`

入口：
- Workbench `功能覆盖率 → Case 证据`
- CLI `vagent coverage case-evidence -o <run> --markdown`
- 产物 `coverage/case_view.{json,md,html}`

### 5.2 P0/P1 新增

5. **Case 分类树**：`CCAT` 节点 / 模板数 / CASE 数 / TST 数 / 缺口数
6. **Case 复用**：模板 × 模块/项目、实例数、参数覆盖
7. **Case × CELL 矩阵**：哪些 CELL 有 case、只有 checker 没 case、哪些 red
8. **Case 追溯**：`CASE → FEAT → P/STG → SCN → SVA/SB → EVD`
9. **Case 执行证据**：case × run × seed × cfg × pass/fail
10. **豁免/审批看板**：WVR/APPROVAL/到期提醒

### 5.3 视图元数据（每份生成物必须带）

```json
{
  "schema": "case_view_v2",
  "run": "...",
  "ver_id": "VER-...",
  "source_ssot": "coverage_model/*.yaml",
  "ssot_sha256": "...",
  "generated_at": "2026-11-03T...",
  "generator": "src.tools.humanview.case_associate_view",
  "confidence": "declared|measured",
  "readonly": true
}
```

---

## 6. 门禁设计

### 6.1 分级

| 级别 | 示例规则 | 处置 |
|---|---|---|
| **blocker** | schema 失败；ID 重复；CASE 无 TST；CELL 无 checker；SVA vacuous；SCB execute_count=0；账本不平；删除未标 deprecated | 阻断 PR/签核 |
| **warning** | CELL 无 case；分类叶子无 case；模板无实例；CASE 无 EVD；WVR 将过期；owner 缺失；证据过期 | 记录/进 baseline |
| **info** | 新增缺口；覆盖率下降；checker 冗余；模型 diff | 通知 |

### 6.2 运营

- **增量优先**：PR 只查新增/修改实体；历史债进 baseline；
- **nightly 全量**：防止跨文件回归被增量漏掉；
- **绕过记录**：紧急绕过必须走 `APPROVAL-`，下个 sprint 补录；
- **规则版本化**：`RULE_VER` 随 gates.yaml 走。

### 6.3 落点

`src/tools/humanview/case_associate_view/gates.py`（或
`src/tools/checking/coverage_tools/gates.py`）：
- `validate_case_view(view, cells, evd) -> {blockers, warnings, infos}`
- CLI：`vagent coverage case-gate -o <run>`
- Workbench：Case 证据页顶部显示 gate 状态。

---

## 7. 实施阶段

### P0 —— Case 身份 + `cell_id` 派生（1~2 天）

**目标**：让每条用例、每个 CELL 都能被唯一识别，不改变现有签核结论。

1. `L5_cases.yaml` 最小 schema：
   ```yaml
   schema: case_ir_v1
   module: NPU_V2-CMDSCHED
   categories:
     - {id: CCAT-ROOT, name: 根, parent: null}
     - {id: CCAT-DEP, name: 数据依赖, parent: CCAT-ROOT}
   cases:
     - id: CASE-DEP-RAW
       category: [CCAT-DEP]
       template: CTPL-DEP-BASIC      # 可选，先不建实体
       feats: [Feat-19]
       cells: [CELL-CG_DEP-P_STORED_ISSUED]
       tsts: [TST-DEP-RAW]           # 单向
   ```
2. 回归任务 meta / `testpoints.yaml` 写 `case_id` / `tst_id`；
3. 生成器写 `coverage/cell_matrix.json`（`CELL = CG × P`），
   `tp_matrix` / `case_cov` 行加 `cell_id`；
4. `case_view` 四表消费 `cell_id`，行为不变；
5. 验收：
   - 100% `case_cov` 有 `case_id` / `tst_id` / `cell_id`；
   - `cell_matrix.json` 可完整重建，无手写 CELL；
   - 现有 `tp_matrix.signed_off` 不变。

**文件**：
- `src/tools/humanview/case_ir/`（新：ir_core / loader / validate）
- `src/tools/checking/coverage_tools/cell_matrix.py`（新）
- `src/executors/verify/main.py`（TP IR 加 case_id）
- `src/tools/execution/.../shell.py`（task meta 加 case_id/tst_id）
- `collect_real_coverage.py`（case_cov 加 cell_id/evd_id）

### P1 —— EVD/RUN + Case×CELL 视图（2~3 天）

1. `case_cov` 加 `evd_id / run_id / tst_id / cfg`；
2. `coverage/evd.json` 汇总（去重键 `(run,tst,seed,cfg)`）；
3. `case_view` 新增：Case 分类树、Case×CELL、Case 执行证据；
4. 视图元数据（schema/ssot_sha/ver/readonly）；
5. 验收：
   - 同一 `(run,tst,seed,cfg)` 只产生一条 EVD；
   - Case×CELL 矩阵能回答"哪些 CELL 无 case / 有 case 无证据"。

### P2 —— CONTRACT/AC + GAP/WVR + 门禁（2~3 天）

1. `L0_feats.yaml` 增加 `CONTRACT / AC / APPROVAL`；
2. `GAP / WVR` 状态机（open/assigned/fixed/verified/closed/reopened；
   draft/pending/approved/expired/revoked）；
3. `gates.py` 分级门禁 + CLI + Workbench 顶部状态；
4. 验收：
   - blocker 全过才能 READY；
   - 每条 WVR 有 reason/risk/expires/approval；
   - 无孤立 CASE / 无 Cell 无 checker / 无 vacuous SVA。

### P3 —— 视图补全 + 复用（2 天）

1. Case 复用视图（模板 × 模块/项目 × 实例）；
2. Case 追溯视图（CASE→FEAT→P→SCN→SVA/SB→EVD）；
3. 豁免/审批看板（到期提醒）；
4. Workbench 子页/表格 + Markdown/HTML 导出。

### P4 —— SQL（可选，达阈值再做）

- SQLite/DuckDB，读 YAML 生成的 JSON；
- 提供 `cell_matrix / case_matrix / traceability / gates` 视图；
- **不把 SQL 变第二真源**。

---

## 8. 与现有工程的映射

| 现有 | 规范中的角色 | 处理 |
|---|---|---|
| `tp_id` | BIN/CP 的度量实例 | 保留，补 `cell_id` |
| `case_cov/<task>.json` | EVD | 补 `evd_id / run_id / tst_id / case_id` |
| `tp_matrix.json` | CELL 的输入证据 | 补 `cell_id`；CELL 状态由生成器算 |
| `case_tp.json` | Case ↔ TP 证据 | 保留，补 `case_id` |
| `waves/manifest.json` | EVD artifact | 保留 |
| `tp_cov_evidence.json` | 四层证据 | 保留，作为 CELL 聚合输入 |
| `case_view.*` | View | 升到 v2，补分类/复用/Case×CELL/执行证据 |
| `covg_ir / sva_ir / scb_ir` | L1/L4 IR | 保留，作为 CELL 的 checker 来源 |
| `path_groups` | P | 保留；STG/BR 可选升级 |
| `regression_run` | RUN/BATCH | 读 run 目录名作为 `run_id` |

---

## 9. 验收标准（可执行）

1. **身份**：`case_cov` 100% 有 `evd_id / run_id / tst_id / case_id / cell_id`；
2. **唯一性**：CELL 全部由 `CG × P` 生成，仓库里没有手写 CELL；
3. **Case View**：四张基础表 + 分类树/复用/Case×CELL/执行证据/豁免看板；
4. **四层证据**：CELL.green 必须 functional+timing+data（路径型 +path）全通过；
5. **门禁**：blocker/warning/info 可配置；blocker 阻断；绕过有 APPROVAL；
6. **可复现**：每份视图带 `ssot_sha256 / ver_id / generated_at`；
7. **不双写**：YAML 是唯一可编辑源；`generated/` 可重建、不入库；
8. **SQL 未引入也不缺功能**：P0~P3 纯 Python 可完成。

---

## 10. 明确不做（本期）

- 不把 CELL 变成手写实体（只生成）；
- 不引入六层 Case 模型（CCAT/CTPL/CASE/CPARAM/CRUN/TST）全套，先三件套；
- 不做一实体一 YAML（聚合文件 + ID 校验）；
- 不做 SQL 驱动（P4 达阈值再做）；
- 不把 bin 命中率当签核结论（四层证据才判）；
- 不在 PATH 后端未接时宣称路径已验证（标 PENDING_BACKEND）；
- 不做跨采样域的跨组 cross（同域约束，否则显式 bridge）。

---

## 11. 开放问题（需要拍板）

1. **CELL 是否成为正式签核单位？** 建议：是"签核视图"，TP `signed_off` 仍是输入证据；
2. **Case 分类树由谁维护？** 建议：PM/DV lead 在 `L5_cases.yaml` 维护，CI 校验；
3. **CONTRACT/AC 现在就建，还是先作为 Feat 字段？** 建议：P0 先字段，P2 再实体；
4. **是否引入 `SCN/CMB`？** 建议：等场景序列真正落地再建，先用 `PATH + CASE` 表达；
5. **VER/BASELINE 用 Git tag 还是 YAML？** 建议：Git tag 为准，YAML 只存 `ver_id` 引用。

---

## 12. 建议的第一刀

按 P0 先做三件事（不改现有签核逻辑）：

```text
① L5_cases.yaml（CCAT/CASE/TST 最小 schema）
② coverage/cell_matrix.json（CG × P 派生）
③ case_cov / tp_matrix 行补 case_id / tst_id / cell_id
```

跑通后，`case_view` 的"用例/契约/矩阵/缺口"四张表就能从"按 test 名猜"
升级为"按 CASE/CELL 身份聚合"。这就是 Case View 方法学真正的起点。
