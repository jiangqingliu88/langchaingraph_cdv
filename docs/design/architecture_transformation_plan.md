# 架构转型方案：以 Case View 为骨架的验证证据架构

> 状态：**P0 + P1 + 三集合契约已落地（2026-11-04）**，P2 起的治理项待做。
> 落地清单见文末 §12；**可执行的签核标准**已收进
> `ARCHITECTURE.md` §9.11–§9.12（身份脊梁 / 七个主要性创意 / 判据 / 当前边界），
> 本文保留"为什么这么设计"的推导过程。
> 依据方法学：`docs/design/case_view_methodology_plan.md`（下称**方法学计划**）。
> 关联：`ARCHITECTURE.md` §3（五层）、§9（覆盖率与闭环）、§17（2.0 路线图）、
> `docs/design/case_coverage_and_wave_traceability.md`（逐用例签核）、
> `src/tools/humanview/{covg_ir,sva_ir,scb_ir}/arch.md`。
> 目标：**签核的骨架从"覆盖率数字"换成"CELL 四层证据"**，并把这条链上的
> 身份、产物、门禁、视图一次性理顺。

---

## 0. 一句话

现在的架构能跑出 **证据**，但组织不起 **结论**：

```text
能回答：这条 bin 被打到过几次        （tp_matrix）
能回答：这条用例证明了哪几个 TP      （case_tp / case_cov）
不能回答：哪个功能组的哪条通路，四层证据齐了没有（CELL / EVD / GATE）
```

转型把 **CASE（逻辑用例）→ TST（可执行实例）→ EVD（一次执行证据）→ CELL
（CG × 通路）** 四张身份表补齐，让 `tp_matrix` 从"结论"降为"输入证据"，
让 **CELL 状态**成为唯一的签核读数。

**改革范围**：6 刀、3 个新包、2 类新产物（`cell_matrix` / `evd`）、1 个门禁引擎。
**不动**：UVM 生成链、回归框架、EDA 适配、TP 主键、五层分层与 Workbench 冻结契约。

---

## 1. 现状（代码事实，不是文档说法）

### 1.1 已经能跑通的那一段

| 环节 | 真实落点 | 事实 |
|---|---|---|
| 逐用例证据 | `src/tools/checking/coverage_tools/case_cov.py`（603 行） | 写 `coverage/case_cov/<stage>/<task>.json`（`case_cov_v1`）+ `case_tp.json`（`case_tp_v1`） |
| TP 矩阵 | `collect_real_coverage._tp_matrix` | 已有 `SIGNED_OFF/UNSIGNED`、`signed_off_by="<task>@<seed>"` |
| 四层证据 | `coverage_tools/tp_evidence.py`（504 行） | 写 `tp_cov_evidence.json`（`tp_cov_evidence_v1`），四层状态齐 |
| 用例身份 | `src/tools/common/lib/case_meta.py`（400 行） | `task_meta.json`（`regression_task_v1`）+ `waves/manifest.json` |
| 三份 IR | `humanview/{covg,sva,scb}_ir` | 结构校验 + 矩阵视图，**只读文本，不写 run** |
| 视图 | `humanview/case_associate_view`（271+150 行） | 四张表，`case_associate_view_v1` |
| 入口 | CLI `coverage tp-evidence / case-evidence`；Workbench `flow.fcov` | 与 builder 共用同一份数据 |

**这条链在代码上是通的**：`case_cov.py` / `tp_evidence.py` / `case_associate_view`
均已实现并有单测（`tests/test_case_coverage.py`、`test_tp_evidence.py`、
`test_case_traceability_p1p2.py`），签核门禁也认了 `TP_NOT_SIGNED_OFF /
TP_WAVE_MISSING / TP_TIMING_WARN`。注意：本方案写作时的存量 run 早于这批代码，
所以下文所有"现状"都以**代码路径与 schema** 为准，不拿旧 run 的目录当证据。

### 1.2 缺的那一段（方法学计划 §1.2 的现实版本）

| 缺口 | 代码事实 | 后果 |
|---|---|---|
| **没有 CASE 身份** | 全仓 grep：`case_id` 只出现在 casemodel 生成器与 SoC C-case（无关语义）；`tst_id`/`evd_id` 零命中 | 用例的"逻辑身份"就是目录名 `test_<task>_seed_<n>`，跨模块不可复用、不可分类 |
| **没有 CELL 身份** | `cell_id` 只出现在 AIVM xlsx（`"<tp_id>#r<row>"`，与覆盖无关） | 无法回答"CG_NPU_DEP × P_STORED_ISSUED 绿了吗" |
| **没有 RUN/EVD 身份** | `case_cov_v1` 有 `task/test/seed/stage`，无 `run_id/evd_id` | 跨 run 去重、过期判定、失败分类都靠目录名 |
| **没有门禁引擎** | 规则长在 `audit/main.py`（1155 行）的 16 个 `_caveat(...)` 里 | blocker 与 warning 同级，CI 只能读结论不能复用规则 |
| **没有 SSOT 分层** | `specs/<module>/casemodel.yaml` 是唯一可编辑源；`cases:` 段不存在 | CASE 分类树无处登记 |
| **流水线过载** | `collect_real_coverage.py` **1643 行**，`run()` 里串了 8 个写入器 | 想改一处要读完一整条编排；复杂度顶着 guard 上限 |

### 1.3 方法学计划里"尚未实现"的清单，逐条核对

| 计划条目 | 现实 |
|---|---|
| P0 `L5_cases.yaml` + `case_ir` | ❌ 仓库里不存在（grep 只命中计划文档） |
| P0 `coverage/cell_matrix.json` | ❌ 不存在 |
| P0 `case_cov/tp_matrix` 行加 `cell_id` | ❌ 不存在 |
| P1 `evd.json` + `run_id` | ❌ 不存在 |
| P2 `gates.py` | ❌ 不存在（规则在 audit 里） |
| P2 CONTRACT/AC、GAP/WVR、APPROVAL | ❌ 不存在 |
| P3 Case 分类树 / 复用 / 执行证据视图 | ❌ 不存在 |

结论：**方法学的地基（逐用例证据）已经打好，但身份层与签核视图层是空的。**

---

## 2. 目标架构

### 2.1 一张图

```text
                 ┌───────────────────────── 可编辑（SSOT）─────────────────────────┐
                 │ casemodel.yaml（L0 feats / L1 coverage / L2 paths / L4 checkers / │
                 │                 L5 cases）  +  gates.yaml                         │
                 └──────────────┬───────────────────────────────────────────────────┘
                                │  生成期（verify）
                                ▼
        TP IR (testpoints.yaml)  ← 每个 tp 带 tp_id / case_id / tst_id / cell_id
                                │  执行期（ops → 回归目录）
                                ▼
        task_meta.json (regression_task_v2: case_id/tst_id/tp_ids/cell_ids)
                                │  采集期（coverage）
                                ▼
        case_cov/<stage>/<task>.json (EVD)  ──┬─→ tp_matrix.json      （度量，输入证据）
        waves/manifest.json                   ├─→ tp_cov_evidence.json（四层证据）
                                              ├─→ evd.json            （运行身份，去重）
                                              └─→ cell_matrix.json    （签核读数）
                                                        │
                                                        ▼
                                                 gates.json（blocker/warning/info）
                                                        │
                                    ┌───────────────────┴───────────────────┐
                                    ▼                                       ▼
                            case_view.{json,md,html} v2            audit → report.json
                            （用例/契约/矩阵/缺口/分类/追溯）        （门禁结论 → 签核状态）
```

### 2.2 六条不变量（转型的验收线）

1. **单一可编辑源**：只有 `casemodel.yaml` + `gates.yaml` 能改；`cells/evd/gates/views` 全部生成，带 `readonly: true` 与 `ssot_sha256`。
2. **TP 仍是度量主键**：`tp_id` 不变、`signed_off` 语义不变；CELL 只聚合，不重算。
3. **CASE 身份在生成期注入**：`casemodel → TP IR → task_meta → EVD`，**禁止**事后从目录名/测试名正则反推 CASE。
4. **一条执行一条 EVD**：去重键 `(run_id, tst_id, seed, cfg)`；重复执行覆盖同一 EVD 的 `last_seen`，不新增。
5. **缺证据 = 黄，不 = 绿**：CELL 变绿必须四层（路径型 +path）逐层有明确 `passed`；`na` 必须写理由。
6. **视图与门禁不含业务逻辑**：只读生成物；任何"算"都在生成器里，且只算一次。

---

## 3. 七个架构决策（含被否的选项）

### D1. SSOT 形态：**先扩展 `casemodel.yaml` 分节，P2 才物理拆分**

方法学计划 §D5 提议 `coverage_model/L0_feats.yaml … L5_cases.yaml` 六个文件。
本期**不**一次拆完，理由：

| 选项 | 代价 | 结论 |
|---|---|---|
| (a) 立刻拆 6 个文件 | 现有 **35 个文件**读 `casemodel.yaml`（bridge / verify / coverage / plan / workbench）全部要改；`aivm bridge` 还要同时写两份 | 否 |
| (b) `casemodel.yaml` 加 `feats:` / `cases:` 两个新段，其余不动 | schema 加两段（`additionalProperties:false` 需同步改），读者零改动 | **采用** |
| (c) 拆 + `casemodel.yaml` 变成生成物（兼容聚合） | 双写风险最大，且 bridge 入口要改造 | P2 视规模再定 |

**P2 的触发条件**（写死，避免无限拖延）：单个 `casemodel.yaml` 超过 1200 行，
**或** 评审改动冲突每周 > 2 次。不满足就继续聚合。

### D2. CELL = **派生签核视图**，不是实体

```text
CG    := tp.coverpoint 所属覆盖组（covg_ir.group_id，缺省用 coverpoint 前缀）
P     := tp.execution.stage（属性 TP）| path_groups 的 bin（路径 TP）
CELL  := f"CELL-{CG}-{P}"        # 唯一实现点：cell_matrix.py，只写一次
```

CELL **不入 YAML、不许手写**；`cell_matrix.json` 每次由 `tp_matrix + tp_cov_evidence`
重建，重建结果与上次逐字段一致（除 `generated_at`）。

### D3. CASE 身份在**生成期**注入

注入点只有两个：

1. `verify` 生成 TP IR 时，从 `casemodel.cases[]` 反查 `case_id` / `tst_id` 写进每个 TP；
2. `shell.py:_write_task_identity` 把 `case_id/tst_id/cell_ids` 透传进 `task_meta.json`。

**否决**：从 `test_<task>_seed_<n>` 目录名或 `+UVM_TESTNAME` 反推 CASE。回归任务名
由 `test_filter`/`test_name` 生成，改名即断链——这正是现在 `owner_basis` 要记录
"靠哪一层对上"的原因。兼容旧 run 时才允许回退推导，并标 `legacy: true`。

### D4. 证据流水线**单点化**：`collect_real_coverage` 减负

现状 `collect_real_coverage.py` 共 **1643 行**，`run()` 里串了 8 个写入器
（merge → seed diversity → case_cov → tp_matrix → tp_evidence → case_view →
semantic validation → coverage_result）。转型后：

```text
collect_real_coverage.run()     只做：编译 → 仿真 → 解析 → 合并   （≈ 700 行）
        │
        ▼  coverage/evidence_pipeline.py  (新)
run_evidence_pipeline(od, run_id)
   1 case_cov      → case_cov/**, case_tp.json
   2 tp_matrix     → tp_matrix.json
   3 tp_evidence   → tp_cov_evidence.json
   4 evd           → evd.json          （新）
   5 cell_matrix   → cell_matrix.json  （新）
   6 case_view     → case_view.*       （v2）
   7 gates         → gates.json        （新）
        │
        ▼
   coverage/evidence_manifest.json     （每步产物 + sha256 + 版本 + 耗时）
```

**为什么值得**：① 上表每一步都能单独重跑（`--only cell_matrix`），改模型后不必
重跑仿真；② `evidence_manifest.json` 让"这份视图是哪个模型版本出的"可回答；
③ 把 1643 行的编排拆开后，复杂度基线才有意义。

### D5. 门禁独立成 `gates.py`，audit 只做**消费**

```python
# src/tools/humanview/case_associate_view/gates.py
validate_case_view(view, cells, evd, rules) -> {
    "schema": "case_gates_v1",
    "blockers": [...], "warnings": [...], "infos": [...],
    "override": {"approval_id": "", "expires": ""},
}
```

- 规则表 `gates.yaml`（`RULE_VER` 随文件走），分 `blocker/warning/info`；
- audit 把 `blockers` 映射成现有 caveat 体系（新增 code 必须同步
  `tests/test_architecture_invariants.py::EXPECTED_CAVEATS`）；
- CI：`vagent coverage case-gate -o <run>` 退出码 1 = 有 blocker。

**否决**：继续把规则写在 `audit/main.py`。理由是 audit 已有 1155 行、16 个
caveat，再加"CELL 无 checker / vacuous SVA / 账本不平"会顶破复杂度基线，且
门禁规则无法被 CI 单独调用。

### D6. 视图只读：Workbench / CLI 只读生成物

- Workbench 经 `src/workbench/query/`（无 Qt）读 `case_view.json` / `gates.json`，
  不 import `src/tools/**`（现有冻结契约）；
- 写操作一律走 `src/app/services/`（新增 `case_view_service.py`）；
- CLI 与 Workbench 共用同一个服务函数——这是 ARCHITECTURE.md §1.3 已声明的
  边界，本期把它**用于新功能**，不再新增绕过路径。

### D7. SQL 门槛写死

满足**全部三条**才引入 SQLite/DuckDB：实体 > 5000、边 > 20000、`case_view` 生成
P95 > 2 s。SQL 只读派生 JSON，**永不成为 SSOT**。

---

## 4. 六刀（具体改动）

### 第一刀：身份脊梁（CASE / TST / EVD / CELL）

**新增**

| 文件 | 内容 |
|---|---|
| `src/tools/humanview/case_ir/__init__.py` | 导出 `load_case_ir / validate_case_ir / project_from_casemodel` |
| `src/tools/humanview/case_ir/ir_core.py` | `CCatIR / CaseIR / TstIR`，schema `case_ir_v1` |
| `src/tools/humanview/case_ir/loader.py` | 读 `casemodel.cases:` 段（P0）或 `L5_cases.yaml`（P2） |
| `src/tools/humanview/case_ir/validate.py` | ID 唯一、引用存在、CASE 至少一个 TST、TST 的 test 在 TP IR 中出现过 |

**改动**

| 文件 | 改动 |
|---|---|
| `casemodel_tools/schema/case_model.schema.json` | 新增 `cases:`（CCAT/CASE/TST 最小集合）；`feats:` 预留给 P3 |
| `src/tools/generation/casemodel_tools/domain/model.py` | 承载 `cases` 段（只存不解释，解释权在 case_ir） |
| `src/executors/verify/main.py` | 生成 TP IR 时写 `case_id` / `tst_id` |
| `regression_framework/generators/shell.py::_write_task_identity` | `task_meta` 增加 `case_id/tst_id/cell_ids`，schema 升 `regression_task_v2` |
| `coverage_tools/case_cov.py` | 写 `evd_id = EVD-<run>-<task>-<seed>`、`run_id`、`tst_id`、`case_id`；旧 run 无键 → `legacy: true` |
| `src/core/contracts/versions.py` | 注册 `case_ir_v1 / regression_task_v2 / evd_v1 / cell_matrix_v1 / case_gates_v1` |

**兼容窗口**：`regression_task_v1` 继续可读（缺键即 legacy）；`case_cov_v1` 不升版，
只**加键**（加键是向后兼容的）。

**验收**：任取一个 run，`case_cov/**/*.json` 100% 有 `case_id/tst_id/evd_id/cell_id`；
`tp_matrix.signed_off` 与转型前逐条一致（**不改签核结论**是硬要求）。

---

### 第二刀：证据流水线抽取

**新增** `src/tools/checking/coverage_tools/evidence_pipeline.py`：

```python
STEPS = ("case_cov", "tp_matrix", "tp_evidence", "evd", "cell_matrix", "case_view", "gates")

def run_evidence_pipeline(od, *, run_id="", only=None, force=False) -> dict:
    """按 STEPS 顺序跑派生物，写 coverage/evidence_manifest.json。"""

def rerun(od, step: str) -> dict:   # 只重跑一步（模型改了、仿真没重跑）
```

**改动**：`collect_real_coverage.run()` 删除 7 段编排，改调 `run_evidence_pipeline`。
拆完后预估 `collect_real_coverage.py` ≈ 900 行、`evidence_pipeline.py` ≈ 250 行。

**风险点**：`case_view` 与 `tp_evidence` 现在会被 `case_associate_view` 之外的
调用方直接触发（`flow_tools/coverage_api.py`）。流水线必须保证**幂等**：同一
`(odds, ssot_sha)` 重复跑不改变产物内容（除时间戳）。

---

### 第三刀：case_ir（L0/L5）与投影

P0 阶段 `case_ir` 不新增可编辑文件，而是**从 `casemodel.cases:` 投影**：

```python
project_from_casemodel(casemodel_dict) -> CaseIR
```

`aivm bridge`（xlsx → casemodel）同步支持写 `cases:` 段：PM 在表里给出的
分类/用例名直接落成 CCAT/CASE，不事后猜。

P2 若触发拆分条件，再加 `vagent case-model split`（`casemodel.yaml` → 
`coverage_model/L*.yaml`）与 `compose`（反向生成只读聚合视图）。

---

### 第四刀：`cell_matrix` + 四层状态

**新增** `src/tools/checking/coverage_tools/cell_matrix.py`（≤ 400 行）：

```python
def build_cell_matrix(od) -> dict:   # CELL = CG × P，输入 tp_matrix + tp_cov_evidence
def cell_status(layers: dict) -> tuple[str, list[str]]:  # green/yellow/red/na + reasons
```

状态判定（与方法学计划 §D4 对齐，缺证据不下绿）：

```text
green = functional 全中 && timing 通过 && data 通过 &&（路径型）path 通过
yellow = 覆盖不足 / checker 未声明或未执行 / timing 未声明
red    = 任一 fail、vacuous、账本不平、或"该 CELL 必须的 checker 不存在"
na     = 该 CG 与 P 无契约关系（必须写 reason）
```

**改动**：`tp_matrix` 行加 `cell_id`；`tp_cov_evidence` 增加 `cell_id` 索引；
`case_view.matrix` 改为读 `cell_matrix`（结构不变，值来源变了）。

---

### 第五刀：`gates` 引擎

**新增** `src/tools/humanview/case_associate_view/gates.py` + `gates.yaml`：

| 级别 | 规则（首版） |
|---|---|
| blocker | schema 失败；ID 重复；CASE 无 TST；CELL 无对应 checker；SVA vacuous（`hit_count=0` 且无 `cover_property`）；SCB `execute_count=0`；证据账本不平（`matched+missing+extra ≠ total`）；删除实体未标 `deprecated` |
| warning | CELL 无 case；CCAT 叶子无 case；CASE 无 EVD；WVR 将过期；owner 缺失；证据过期（`ssot_sha` 不匹配） |
| info | 新增缺口；覆盖率下降；checker 冗余；模型 diff |

**改动**：audit 消费 `gates.json`；新增 caveat code `CASE_GATE_BLOCKED`（blocker 聚合）
并同步 `EXPECTED_CAVEATS`；`vagent coverage case-gate` 与 Workbench fcov 页顶部状态条。

---

### 第六刀：视图 v2 + 入口

**改动** `case_associate_view`：

- schema 升 `case_associate_view_v2`，每份生成物带
  `{run, ver_id, source_ssot, ssot_sha256, generated_at, generator, confidence, readonly}`；
- 新增三张表：`case_tree`（CCAT 树）、`case_cell`（Case × CELL）、`case_runs`（执行证据）；
- 四张旧表字段不动（向后兼容读 v1）。

**入口**：CLI `coverage case-tree / case-matrix / case-trace`；Workbench fcov 页加
三个 Tab；`src/app/services/case_view_service.py` 作为唯一调用面。

---

## 5. 产物目录（转型后）

| 产物 | schema | 生产者 | 消费者 | 可编辑 |
|---|---|---|---|---|
| `coverage/testpoints.yaml` | `version: '1.0'`（无 `schema` 键） | verify | coverage / workbench | 否（模型生成） |
| `coverage/case_cov/**/<task>.json` | `case_cov_v1`（+键） | evidence_pipeline | tp_evidence / case_view | 否 |
| `coverage/case_tp.json` | `case_tp_v1` | evidence_pipeline | case_view / audit | 否 |
| `coverage/tp_matrix.json` | —（沿用） | evidence_pipeline | 闭环 / audit | 否 |
| `coverage/tp_cov_evidence.json` | `tp_cov_evidence_v1` | evidence_pipeline | cell_matrix / case_view | 否 |
| `coverage/evd.json` | **`evd_v1`** | evidence_pipeline | case_view / gates | 否 |
| `coverage/cell_matrix.json` | **`cell_matrix_v1`** | evidence_pipeline | case_view / gates / audit | 否 |
| `coverage/case_view.{json,md,html}` | **`case_associate_view_v2`** | evidence_pipeline | Workbench / CLI | 否 |
| `coverage/gates.json` | **`case_gates_v1`** | evidence_pipeline | audit / CI | 否 |
| `coverage/evidence_manifest.json` | **`evidence_manifest_v1`** | evidence_pipeline | 审计 / 复现 | 否 |
| `regression_run/**/task_meta.json` | **`regression_task_v2`** | shell generator | case_cov | 否 |
| `waves/manifest.json` | `wave_manifest_v1` | ops | case_view | 否 |

---

## 6. 分阶段迁移

| 阶段 | 工期 | 内容 | 退出条件 |
|---|---|---|---|
| **P0 身份** | 1–2 周 | 第一刀 + 第二刀的骨架（只抽 `case_cov/tp_matrix` 两步） | `case_cov` 100% 有 `case_id/tst_id/evd_id/cell_id`；`signed_off` 与转型前逐条一致 |
| **P1 读数** | 1–2 周 | 第四刀 + 第五刀（`cell_matrix` + 四层状态 + `gates` 报告态） | `cell_matrix.json` 可重建；`case_view.matrix` 与 `cell_matrix` 对得上；gate 只报告不阻断 |
| **P2 门禁** | 1 周 | 第五刀（blocker 生效）+ 第六刀 | blocker 全过才 READY；CI 有 `case-gate` 步骤 |
| **P3 治理** | 2 周 | CONTRACT/AC、GAP/WVR、APPROVAL、VER/BASELINE | 每条豁免有 reason/risk/expires/approval |
| **P4 视图/复用** | 1–2 周 | 分类树 / 复用 / 追溯 / 看板 | 六张视图可用；SQL 门槛评估 |
| **P5 SQL**（可选） | — | 达 D7 阈值才做 | — |

**回滚**：每阶段单独可回退——P0/P1 只**加键加文件**，不改旧字段；P2 的阻断可通过
`gates.yaml` 把规则降级为 warning 即时回退。

---

## 7. 本仓库特有的红线（做之前先看）

| 约束 | 出处 | 对本次转型的影响 |
|---|---|---|
| 行数预算：> 2000 error / > 1500 需登记 reason+plan | `config/architecture_guard.py` | `evidence_pipeline.py`、`cell_matrix.py` 从第一天就按 ≤ 400 行设计 |
| 复杂度基线：> 20 必须登记，改动后不得增长 | `config/complexity_baseline.json` | `run_evidence_pipeline` 用 STEP 表驱动，不写长 if/elif |
| caveat code 白名单 | `tests/test_architecture_invariants.py::EXPECTED_CAVEATS` | 新增 `CASE_GATE_BLOCKED` 必须同步，否则测试红 |
| 文档事实同步 | `test_architecture_doc_matches_code_facts`、`test_known_limitations_match_architecture_doc` | ARCHITECTURE.md §3/§9/§17 要随改动更新 |
| `core` 仅标准库 | `tests/core/test_core_is_stdlib_only.py` | schema 版本常量进 `core/contracts/versions.py`，别引 pydantic |
| 分层导入方向 | `tests/test_layer_direction.py` | `cell_matrix`/`gates` 放 tools 层；L1 不得引 L4 |
| Workbench 不 import `src.tools` | `src/workbench/ARCHITECTURE.md` | 新页面只经 `query/` + `app/services` |
| 工作台主体冻结 | ARCHITECTURE.md §12 | 只加模块/Tab，不改 ModuleBase/TaskRunner/EventBus |

---

## 8. 风险与对策

| 风险 | 触发条件 | 对策 |
|---|---|---|
| 身份漏注 | 某条路径（SoC C-case、`soc_adapter`、手工回归）没经过 `shell.py` | gate 出 `CASE_MISSING`：P0/P1 warning，P2 升 blocker；先跑一轮全量统计 |
| CELL 组合爆炸 | CG × P 数量随配置增长 | P 目前只有 stage/path 两类；`cell_matrix` 只对"有契约关系"的组合生成 |
| 双写回归 | 有人继续改 `casemodel.yaml` 的旧段又改 `case_ir` | 投影单向；P2 拆分前 `case_ir` 不提供写接口 |
| 视图与门禁漂移 | 生成器与视图各算一次 | 不变量 6：只有生成器算；视图只读 |
| 旧 run 不可读 | schema 升级 | N-1 兼容读 + `legacy: true`；视图里显式标注 |
| 门禁误杀 | 新 blocker 命中存量债务 | 上线首版一律 `warning`，统计一周后按规则逐个升级 |

---

## 9. 开放问题（建议答案）

1. **CELL 是否成为正式签核单位？** 是"签核读数"，TP `signed_off` 仍是输入证据（同方法学计划）。
2. **Case 分类树谁维护？** PM/DV lead 在 `casemodel.cases`（P2 后 `L5_cases.yaml`）维护，CI 校验。
3. **CASEMODEL 与 case_ir 谁是真源？** P0 阶段 casemodel 是真源、case_ir 是投影；P2 若拆分则反转，`casemodel.yaml` 降为生成物。
4. **是否现在就建 CONTRACT/AC？** 否，P3；P0 只作为 `feats[].contract` 字段。
5. **VER/BASELINE 用 Git tag 还是 YAML？** Git tag 为准，YAML 只存 `ver_id` 引用。

---

## 10. 第一批任务（可开工）

| # | 任务 | 落点 | 验收 |
|---|---|---|---|
| 1 | `case_ir` 最小包（CCAT/CASE/TST + 校验） | `src/tools/humanview/case_ir/` | 单测：ID 唯一 / 引用存在 / CASE 无 TST 报错 |
| 2 | `casemodel.cases` schema 段 | `casemodel_tools/schema/case_model.schema.json` | `run_validate` 通过；旧模型不写该段仍合法 |
| 3 | TP IR 写 `case_id/tst_id` | `src/executors/verify/main.py` | 生成物含键；无 cases 段时为空且不报错 |
| 4 | `task_meta` v2 | `generators/shell.py` + `case_meta.py` | 旧 v1 可读；新目录含 `cell_ids` |
| 5 | `case_cov` 加 `evd_id/run_id/tst_id/case_id` | `coverage_tools/case_cov.py` | 100% 覆盖；`signed_off` 不变 |
| 6 | `evidence_pipeline` 骨架（先接 2 步） | `coverage_tools/evidence_pipeline.py` | `--only` 可单步重跑；manifest 落盘 |
| 7 | `cell_matrix` 派生 + 四层状态 | `coverage_tools/cell_matrix.py` | 与 `tp_cov_evidence` 逐 CELL 对齐 |
| 8 | `gates` 报告态 | `case_associate_view/gates.py` + `gates.yaml` | `case-gate` 输出三类且不阻断 |

**P0 的完成判据（可执行）**：

```bash
# 1) 身份齐
vagent coverage case-evidence -o <run> --markdown   # 每条用例带 case_id/tst_id/evd_id
# 2) 结论不变
diff <转型前的 tp_matrix.json> <转型后的 tp_matrix.json>   # signed_off 行逐条一致
# 3) 契约绿
python -m pytest tests -q && python -m config.architecture_guard.py
```

---

## 11. 明确不做

- 不推翻 TP 主键、不改 UVM 生成链、不动回归框架与 EDA 适配；
- 不做一实体一 YAML（聚合文件 + ID 校验），除非触发 D1 的拆分条件；
- 不把 CELL 变成手写实体；
- 不引入六层 Case 模型全套（CCAT/CTPL/CASE/CPARAM/CRUN/TST），先三件套；
- 不把 bin 命中率当签核结论；
- 不在 PATH 后端未接时宣称路径已验证；
- 不引入 SQL 作为 SSOT。

---

## 12. 落地状态（2026-11-03 本轮重构）

### 12.1 已落地

| 刀 | 落点 | 状态 |
|---|---|---|
| 第一刀 身份脊梁 | `humanview/case_ir/`（ir_core / loader / validate）；`casemodel.cases` schema 段；TP IR 写 `case_id/tst_id`（含行为/PATH 型兜底）；`task_meta` → `regression_task_v2`；`case_cov` 写 `evd_id/run_id/tst_id/case_id/cell_ids` | ✅ |
| 第二刀 证据流水线 | `coverage_tools/evidence_pipeline.py`（7 步 + `evidence_manifest.json`，`only=` 单步重跑）；`collect_real_coverage.run()` 只留度量 | ✅ |
| 第三刀 case_ir | 投影 + 合成（维度 / 行为域 / PATH 组），`source=declared\|synthesized` 如实标注；`coverage/case_ir.json` 由 verify 落盘 | ✅ |
| 第四刀 CELL | `coverage_tools/cell_matrix.py`（`CELL-<CG>-<P>`、四色状态机、缺证据不下绿） | ✅ |
| 第五刀 门禁 | `case_associate_view/gates.py` + `gates.yaml`；`vagent coverage case-gate [--strict]`；audit 消费 → `CASE_GATE_BLOCKED` | ✅ |
| 第六刀 视图 | `case_associate_view_v2`（四张旧表 + 分类树 / Case×CELL / 执行证据 + 元数据）；`evd.json` | ✅ |
| 接线 | `core/contracts/versions.py` 注册 8 个 schema；`app/services/case_view_service.py`；`workbench/query/case_view.py`；fcov 页 Gate 状态条 | ✅ |

**门禁上线策略**：`gates.yaml` 里只有 `duplicate_id` / `case_without_tst` 是
`stage: block`，其余 blocker 先 `report`（只记不阻断）——统计一周后逐条升级。

### 12.1b 四集合契约（arch.md 落地，2026-11-03；约束 id 2026-11-04 补）

`case = groups[] + sva[] + scb[] + constraints[]` 的显式容器已落到主链，**主链顺序不变**：

| 节点 | 落点 | 说明 |
|---|---|---|
| verify | `case_ir.json` 每条 case 带 `groups/sva/scb/constraints/not_applicable`；每项带 `cell` | 由 TP 反聚合（`case_ir/contract.py`），不手写 |
| verify | `testpoints.yaml` 每条 TP 带 `case_id/groups/sva/scb/constraints` | TP 是聚合源 |
| verify | `constraints[]` + `constraint_backing` | 按 `coverage_plan.constraint_backing.policies[].dimensions` 与 case 维度交集归属；没有交集不编 id |
| verify | `case_group_map.json` / `case_checker_map.json`（新） | 正反查索引 |
| verify | `methodology.json` 加 `case_ir_sha256` | 哈希链锚点 |
| ops | `task_meta.json` 加 `group_ids/sva_ids/scb_ids/constraint_ids/case_ir_sha` | **不动** `cov/*.db`、`waves/*.db` |
| coverage | `case_cov` 变四集合证据 + `scb_summary`（原 `scb` 汇总改名）+ `case_status` | |
| coverage | `case_tp` 加四集合反向索引；`tp_matrix` 行加 `case_id/groups/sva/scb/constraints/case_status` | |
| coverage | `cell_matrix` 由集合反向填充（`evidence{groups,sva,scb}` + `evidence_color`） | |
| coverage | `evd` 去重键扩到 `(case, seed, cfg, checker_type, checker_id)` | |
| coverage | `case_view` 加四节（Groups / SVA / SCB / Constraints） | 约束段标 `backed`（空骨架不冒充已生效） |
| coverage | `gates` 加 8 条集合完整性门禁 | |
| audit | 消费 `cell_matrix` + `gates`；新增 5 条 caveat | |

**`scb` 来源（已接入模型声明）**：`scoreboards:` 段（与 `assertions:` 并列）
→ `SB-*` → 按 `tp_bindings` 或 `checks` 交集绑到 TP → case 集合的 `scb[]`。
证据两种粒度，**明文标注**：

| `evidence` | 数据来源 | 写进 `evidence_level` |
|---|---|---|
| `per_sb`（`[SCB <id>]` 行） | 该 scoreboard 自己的收口行 | `per_scb` |
| `aggregate` | env 的 `[SCB_DUT]` 聚合行 | `aggregate` |
| `auto`（默认） | 有自己那行用它，否则退回聚合 | 如实写 |

模型不声明 `scoreboards:` 时，`scb` 仍是 `[]` + `not_applicable` 原因 ——
**不拿 `checks` 编假的 SB id**。`case_cov.scb_summary` 始终记录原始聚合。

**组/格命名**：`group = CG-<dimension>`（`CG-D_DEP`），`cell = CELL-<dimension>-<stage>`
（`CELL-D_DEP-P1`）。没有独立覆盖组实体时，`dimension` 是唯一稳定的功能分组；
`-stage` 取回归分级（path 型 TP 的 stage 为 `behavior`）。

### 12.2 本轮未做

- **未跑测试**（按要求）。落地后用 `pytest tests src/tools/checking/coverage_tools/src/tools/humanview`
  跑一遍，重点看 `test_architecture_invariants`（caveat 白名单已加
  `CASE_GATE_BLOCKED`）、`test_case_coverage`、`test_tp_evidence`、
  `test_humanview_ir`。
- P2 的 CONTRACT/AC、GAP/WVR、APPROVAL、VER/BASELINE 未建（按计划顺序）。
- `casemodel.yaml` 的物理拆分（`coverage_model/L*.yaml`）未做——仍走 D1 的
  聚合形态，触发条件写在 D1。
- Workbench 只加了 Gate 状态条；分类树 / Case×CELL / 执行证据三张表**数据已在
  `case_view.json` 里**（视图6/7），页面 Tab 待补。
